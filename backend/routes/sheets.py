"""/api/sheets — Sheets: databases you design yourself (Mainframe-level).

A sheet is a table with typed columns, rows, formulas and saved views. The
point of it living in Neo4j rather than in a file is the `link` column type: a
cell can point at a real Task, Paper, Project or Idea, so a table you invented
this afternoon joins the same graph as everything else in the Mainframe.

Storage
    (:Sheet)-[:HAS_COLUMN]->(:SheetColumn)   ordered by `position`
    (:Sheet)-[:HAS_ROW]->(:SheetRow)         ordered by `position`
    (:Sheet)-[:HAS_VIEW]->(:SheetView)
    (:SheetRow)-[:LINKS_TO {col}]->(:Task|:Paper|:Project|:Idea)
    (:Sheet)-[:FOR]->(:Project)              the project this table belongs to

A sheet FOR a project is ONE node shown in two places: the project page renders
it inline, the Sheets tab lists it with its project, and "open in Sheets" walks
from one to the other. It is deliberately not a second, project-local table
type — a copy would drift, and a formula or a link column would work in one
place and not the other.

Cell values are stored as `c_<column key>` properties on the row. Column *keys*
are generated once and never change, so renaming a column can't orphan data.
Formula columns store no value at all — they're computed for display.
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse

import formula
from activity import record
from db import run_read, run_write
from models import (ColumnCreate, ColumnUpdate, ReorderRequest, SheetRowCreate,
                    RowsBulk, SheetRowUpdate, SheetCreate, SheetUpdate, SheetViewSave)

router = APIRouter(prefix="/api/sheets", tags=["sheets"])

CELL_PREFIX = "c_"
# Entity kinds a `link` column can point at: label + the property holding its
# display name. Adding a kind here is all it takes to make it linkable.
LINK_KINDS = {
    "task": ("Task", "title"),
    "paper": ("Paper", "title"),
    "project": ("Project", "name"),
    "idea": ("Idea", "title"),
    "document": ("Document", "title"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _attach_project(sheet_id: str, project_id: str | None) -> None:
    """Point a sheet at the project it belongs to. One project at a time.

    The edge is the truth and the `project_id` property is kept in step with
    it, the same pair a Project's own reference carries, so a client can read
    it back without walking the graph. The project's NAME is never stored —
    it is resolved live on read, so renaming a project can't leave a stale
    label sitting in a table listing.

    The new target is checked BEFORE the old edge is dropped. Doing it the
    other way round means a re-point at an id that turns out not to exist
    detaches the table and then reports a failure, which reads as "nothing
    happened" and is the one outcome that loses information.
    """
    if project_id:
        found = await run_read(
            "MATCH (p:Project {id: $pid}) RETURN p.id AS id", pid=project_id)
        if not found:
            raise HTTPException(404, "no project with that id")
    await run_write("MATCH (:Sheet {id: $id})-[r:FOR]->() DELETE r", id=sheet_id)
    if not project_id:
        await run_write(
            "MATCH (s:Sheet {id: $id}) SET s.project_id = ''", id=sheet_id)
        return
    await run_write(
        """
        MATCH (s:Sheet {id: $sid}), (p:Project {id: $pid})
        MERGE (s)-[:FOR]->(p)
        SET s.project_id = $pid
        """, sid=sheet_id, pid=project_id)


def _key(name: str, taken: set[str]) -> str:
    """A stable, Cypher-safe property key for a column.

    Only ever computed when a column is CREATED. Renames leave it alone — the
    key is the contract between the column and every cell already written.
    """
    base = unicodedata.normalize("NFKD", name or "")
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = re.sub(r"[^\w]+", "_", base).strip("_").lower()[:40] or "col"
    if base[0].isdigit():
        base = "c" + base
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    return out


def _coerce(value: Any, ctype: str) -> Any:
    """Normalise an incoming cell value for its column type.

    Neo4j can hold numbers and booleans natively, so a number column stores a
    number — that keeps sorting and Cypher filtering honest instead of
    comparing "10" < "9" as strings.
    """
    if value is None or value == "":
        return None
    if ctype == "number":
        try:
            f = float(str(value).replace(",", "").strip())
        except ValueError:
            return None
        return int(f) if f.is_integer() else f
    if ctype == "checkbox":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "x", "✓", "on"}
    if ctype == "multiselect":
        items = value if isinstance(value, list) else [
            s.strip() for s in str(value).split(",")]
        return json.dumps([s for s in items if s])
    if ctype == "formula":
        return None                      # computed for display, never stored
    return str(value)


async def _sheet(sheet_id: str) -> dict:
    rows = await run_read(
        """
        MATCH (s:Sheet {id: $id})
        OPTIONAL MATCH (s)-[:FOR]->(p:Project)
        RETURN s, p.id AS pid, p.name AS pname
        """, id=sheet_id)
    if not rows:
        raise HTTPException(404, "sheet not found")
    out = dict(rows[0]["s"])
    out["project_id"] = rows[0]["pid"] or ""
    out["project_name"] = rows[0]["pname"] or ""
    return out


async def _columns(sheet_id: str) -> list[dict]:
    rows = await run_read(
        """
        MATCH (:Sheet {id: $id})-[:HAS_COLUMN]->(c:SheetColumn)
        RETURN c ORDER BY c.position
        """, id=sheet_id)
    out = []
    for r in rows:
        c = dict(r["c"])
        c["options"] = json.loads(c.get("options") or "[]")
        out.append(c)
    return out


async def _rows(sheet_id: str) -> list[dict]:
    recs = await run_read(
        """
        MATCH (:Sheet {id: $id})-[:HAS_ROW]->(r:SheetRow)
        OPTIONAL MATCH (r)-[l:LINKS_TO]->(e)
        RETURN r, collect({col: l.col, id: e.id,
                           label: coalesce(e.title, e.name, e.id)}) AS links
        ORDER BY r.position
        """, id=sheet_id)
    out = []
    for rec in recs:
        node = dict(rec["r"])
        cells = {k[len(CELL_PREFIX):]: v for k, v in node.items()
                 if k.startswith(CELL_PREFIX)}
        # multiselect is stored as a JSON string; hand the client a real list.
        for k, v in list(cells.items()):
            if isinstance(v, str) and v.startswith("[") and v.endswith("]"):
                try:
                    cells[k] = json.loads(v)
                except ValueError:
                    pass
        links = {l["col"]: {"id": l["id"], "label": l["label"]}
                 for l in rec["links"] if l and l.get("col")}
        out.append({"id": node["id"], "position": node.get("position", 0),
                    "cells": cells, "links": links})
    return out


async def _views(sheet_id: str) -> list[dict]:
    rows = await run_read(
        "MATCH (:Sheet {id: $id})-[:HAS_VIEW]->(v:SheetView) RETURN v ORDER BY v.name",
        id=sheet_id)
    out = []
    for r in rows:
        v = dict(r["v"])
        for f in ("filters", "sorts", "hidden"):
            v[f] = json.loads(v.get(f) or "[]")
        out.append(v)
    return out


# --------------------------------------------------------------------------- #
# Sheets
# --------------------------------------------------------------------------- #
@router.get("")
async def list_sheets(project_id: str | None = None) -> list[dict]:
    """Every sheet, or every sheet belonging to one project.

    The project page asks with `project_id` and the Sheets tab asks without —
    one endpoint, so the two listings can't disagree about what a sheet is.
    """
    clause = "WHERE EXISTS { MATCH (s)-[:FOR]->(:Project {id: $pid}) }" if project_id else ""
    rows = await run_read(
        f"""
        MATCH (s:Sheet)
        {clause}
        OPTIONAL MATCH (s)-[:HAS_ROW]->(r:SheetRow)
        OPTIONAL MATCH (s)-[:HAS_COLUMN]->(c:SheetColumn)
        OPTIONAL MATCH (s)-[:FOR]->(p:Project)
        RETURN s, count(DISTINCT r) AS rows, count(DISTINCT c) AS cols,
               p.id AS pid, p.name AS pname
        ORDER BY s.updated_at DESC
        """, pid=project_id)
    return [{**dict(r["s"]), "rows": r["rows"], "cols": r["cols"],
             "project_id": r["pid"] or "", "project_name": r["pname"] or ""}
            for r in rows]


@router.post("", status_code=201)
async def create_sheet(body: SheetCreate) -> dict:
    sid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (s:Sheet {id: $id, name: $name, description: $desc,
                         created_at: $now, updated_at: $now})
        """, id=sid, name=body.name.strip() or "Untitled sheet",
        desc=body.description, now=_now())
    # A brand-new sheet with no columns is a dead end, so seed the shape of a
    # table. Given headings, those; otherwise something to name a row by and
    # somewhere to put a note.
    if body.columns:
        for name in body.columns:
            await add_column(sid, ColumnCreate(name=name, type="text", width=160))
    else:
        await add_column(sid, ColumnCreate(name="Name", type="text", width=220))
        await add_column(sid, ColumnCreate(name="Notes", type="longtext", width=280))
    await create_row(sid, SheetRowCreate())
    if body.project_id:
        await _attach_project(sid, body.project_id)
    await record("sheet", "created", detail=body.name[:70], entity_id=sid)
    return await get_sheet(sid)


@router.get("/link-targets")
async def link_targets(kind: str) -> list[dict]:
    """Candidates for a `link` cell. Kept small and sorted for a picker."""
    if kind not in LINK_KINDS:
        raise HTTPException(400, f"unknown link kind '{kind}'")
    label, prop = LINK_KINDS[kind]
    rows = await run_read(
        f"MATCH (e:{label}) RETURN e.id AS id, e.{prop} AS label "
        f"ORDER BY toLower(coalesce(e.{prop}, '')) LIMIT 500")
    return [{"id": r["id"], "label": r["label"] or r["id"]} for r in rows if r["id"]]


@router.get("/{sheet_id}")
async def get_sheet(sheet_id: str) -> dict:
    sheet = await _sheet(sheet_id)
    sheet["columns"] = await _columns(sheet_id)
    sheet["rows"] = await _rows(sheet_id)
    sheet["views"] = await _views(sheet_id)
    _attach_formulas(sheet["columns"], sheet["rows"])
    return sheet


def _attach_formulas(columns: list[dict], rows: list[dict]) -> None:
    """Fill each row's `computed` map. Aggregates mean one edit anywhere can
    change every formula cell, so this is always done for the whole sheet."""
    computed = formula.compute(columns, rows)
    for r in rows:
        r["computed"] = computed.get(r["id"], {})


@router.get("/{sheet_id}/compute")
async def compute_sheet(sheet_id: str) -> dict:
    """Recomputed formula cells, keyed by row id — what the grid asks for
    after an edit instead of refetching the whole sheet."""
    cols = await _columns(sheet_id)
    rows = await _rows(sheet_id)
    return formula.compute(cols, rows)


@router.patch("/{sheet_id}")
async def update_sheet(sheet_id: str, patch: SheetUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # The project is an edge, not a column, so it comes out of the generic SET
    # and is relinked as one move — the same shape a Project's own reference
    # uses. Sending "" detaches; not sending it leaves the edge alone.
    moved = "project_id" in fields
    project_id = fields.pop("project_id", None)
    if fields:
        fields["updated_at"] = _now()
        sets = ", ".join(f"s.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (s:Sheet {{id: $id}}) SET {sets} RETURN s", id=sheet_id, **fields)
        if not rows:
            raise HTTPException(404, "sheet not found")
    if moved:
        await _attach_project(sheet_id, project_id or "")
    await record("sheet", "updated",
                 detail=", ".join(list(fields) + (["project"] if moved else [])),
                 entity_id=sheet_id)
    return await _sheet(sheet_id)


@router.delete("/{sheet_id}", status_code=204, response_class=Response)
async def delete_sheet(sheet_id: str) -> Response:
    sheet = await _sheet(sheet_id)
    await run_write(
        """
        MATCH (s:Sheet {id: $id})
        OPTIONAL MATCH (s)-[:HAS_COLUMN|HAS_ROW|HAS_VIEW]->(child)
        DETACH DELETE s, child
        """, id=sheet_id)
    await record("sheet", "deleted", detail=sheet.get("name", "")[:70])
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Columns
# --------------------------------------------------------------------------- #
@router.post("/{sheet_id}/columns", status_code=201)
async def add_column(sheet_id: str, body: ColumnCreate) -> dict:
    existing = await _columns(sheet_id)
    cid = str(uuid.uuid4())
    key = _key(body.name, {c["key"] for c in existing})
    await run_write(
        """
        MATCH (s:Sheet {id: $sid})
        CREATE (s)-[:HAS_COLUMN]->(c:SheetColumn {
            id: $id, key: $key, name: $name, type: $type, options: $options,
            formula: $formula, link_kind: $link_kind, width: $width,
            summary: '', position: $pos
        })
        SET s.updated_at = $now
        RETURN c
        """,
        sid=sheet_id, id=cid, key=key, name=body.name.strip() or "Column",
        type=body.type, options=json.dumps(body.options), formula=body.formula,
        link_kind=body.link_kind, width=body.width,
        pos=float(len(existing)), now=_now())
    await record("sheet", "column added", detail=body.name[:70], entity_id=sheet_id)
    return {"id": cid, "key": key, "name": body.name, "type": body.type,
            "options": body.options, "formula": body.formula,
            "link_kind": body.link_kind, "width": body.width, "summary": "",
            "position": float(len(existing))}


@router.patch("/{sheet_id}/columns/{col_id}")
async def update_column(sheet_id: str, col_id: str, patch: ColumnUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "options" in fields:
        fields["options"] = json.dumps(fields["options"] or [])

    # Formulas refer to columns by their display name, so a rename would quietly
    # turn `=[Price] * [Qty]` into a reference to nothing. Rewrite the references
    # instead, the way a spreadsheet does.
    if "name" in fields:
        before = await _columns(sheet_id)
        old_name = next((c["name"] for c in before if c["id"] == col_id), None)
        new_name = (fields["name"] or "").strip() or "Column"
        fields["name"] = new_name
        if old_name and old_name != new_name:
            pattern = re.compile(r"\[\s*" + re.escape(old_name) + r"\s*\]", re.I)
            for col in before:
                if col["type"] != "formula" or not (col.get("formula") or "").strip():
                    continue
                rewritten = pattern.sub(f"[{new_name}]", col["formula"])
                if rewritten != col["formula"]:
                    await run_write(
                        "MATCH (c:SheetColumn {id: $cid}) SET c.formula = $f",
                        cid=col["id"], f=rewritten)
    # NOTE: `key` is deliberately absent from ColumnUpdate. Renaming a column
    # must not move its data.
    sets = ", ".join(f"c.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"""
        MATCH (:Sheet {{id: $sid}})-[:HAS_COLUMN]->(c:SheetColumn {{id: $cid}})
        SET {sets}
        RETURN c
        """, sid=sheet_id, cid=col_id, **fields)
    if not rows:
        raise HTTPException(404, "column not found")
    out = dict(rows[0]["c"])
    out["options"] = json.loads(out.get("options") or "[]")
    await record("sheet", "column updated", detail=out.get("name", "")[:70],
                 entity_id=sheet_id)
    return out


@router.delete("/{sheet_id}/columns/{col_id}", status_code=204, response_class=Response)
async def delete_column(sheet_id: str, col_id: str) -> Response:
    rows = await run_read(
        "MATCH (:Sheet {id: $sid})-[:HAS_COLUMN]->(c:SheetColumn {id: $cid}) RETURN c.key AS key",
        sid=sheet_id, cid=col_id)
    if not rows:
        raise HTTPException(404, "column not found")
    key = rows[0]["key"]
    # Drop the column, then the cells it owned — otherwise every row keeps a
    # property nothing can reach.
    await run_write(
        f"""
        MATCH (:Sheet {{id: $sid}})-[:HAS_COLUMN]->(c:SheetColumn {{id: $cid}}) DETACH DELETE c
        WITH 1 AS _
        MATCH (:Sheet {{id: $sid}})-[:HAS_ROW]->(r:SheetRow)
        REMOVE r.{CELL_PREFIX}{key}
        WITH r
        OPTIONAL MATCH (r)-[l:LINKS_TO {{col: $key}}]->() DELETE l
        """, sid=sheet_id, cid=col_id, key=key)
    await record("sheet", "column deleted", detail=key, entity_id=sheet_id)
    return Response(status_code=204)


@router.post("/{sheet_id}/columns/reorder")
async def reorder_columns(sheet_id: str, body: ReorderRequest) -> dict:
    await run_write(
        """
        UNWIND range(0, size($ids) - 1) AS i
        MATCH (:Sheet {id: $sid})-[:HAS_COLUMN]->(c:SheetColumn {id: $ids[i]})
        SET c.position = toFloat(i)
        """, sid=sheet_id, ids=body.ids)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Rows
# --------------------------------------------------------------------------- #
async def _write_cells(sheet_id: str, row_id: str, values: dict[str, Any]) -> None:
    """Apply a {column key: value} patch to one row, links included."""
    cols = {c["key"]: c for c in await _columns(sheet_id)}
    sets: dict[str, Any] = {}
    removes: list[str] = []
    links: list[tuple[str, str]] = []
    unlinks: list[str] = []
    for key, raw in values.items():
        col = cols.get(key)
        if not col:
            continue                       # ignore cells for columns that are gone
        if col["type"] == "link":
            if raw:
                links.append((key, str(raw)))
            else:
                unlinks.append(key)
            # The label is denormalised into the cell so the grid can paint a
            # row without a second query per link.
            continue
        v = _coerce(raw, col["type"])
        if v is None:
            removes.append(key)
        else:
            sets[key] = v

    if sets:
        assign = ", ".join(f"r.{CELL_PREFIX}{k} = ${k}" for k in sets)
        await run_write(f"MATCH (r:SheetRow {{id: $rid}}) SET {assign}",
                        rid=row_id, **sets)
    if removes:
        drop = ", ".join(f"r.{CELL_PREFIX}{k}" for k in removes)
        await run_write(f"MATCH (r:SheetRow {{id: $rid}}) REMOVE {drop}", rid=row_id)
    for key in unlinks:
        await run_write(
            "MATCH (r:SheetRow {id: $rid})-[l:LINKS_TO {col: $key}]->() DELETE l",
            rid=row_id, key=key)
    for key, target in links:
        kind = cols[key].get("link_kind") or "task"
        label, _prop = LINK_KINDS.get(kind, LINK_KINDS["task"])
        await run_write(
            f"""
            MATCH (r:SheetRow {{id: $rid}})
            OPTIONAL MATCH (r)-[old:LINKS_TO {{col: $key}}]->() DELETE old
            WITH r
            MATCH (e:{label} {{id: $target}})
            MERGE (r)-[:LINKS_TO {{col: $key}}]->(e)
            """, rid=row_id, key=key, target=target)


@router.post("/{sheet_id}/rows", status_code=201)
async def create_row(sheet_id: str, body: SheetRowCreate) -> dict:
    rid = str(uuid.uuid4())
    if body.after:
        # Slot the new row halfway between its neighbour and the one after it,
        # so inserting in the middle never has to renumber the whole sheet.
        rows = await run_read(
            """
            MATCH (:Sheet {id: $sid})-[:HAS_ROW]->(r:SheetRow)
            WITH r ORDER BY r.position
            WITH collect(r) AS rs
            WITH rs, [i IN range(0, size(rs) - 1) WHERE rs[i].id = $after | i][0] AS idx
            RETURN rs[idx].position AS here,
                   CASE WHEN idx + 1 < size(rs) THEN rs[idx + 1].position ELSE NULL END AS next
            """, sid=sheet_id, after=body.after)
        here = rows[0]["here"] if rows else 0.0
        nxt = rows[0]["next"] if rows else None
        pos = (here + nxt) / 2 if nxt is not None else (here or 0.0) + 1.0
    else:
        agg = await run_read(
            "MATCH (:Sheet {id: $sid})-[:HAS_ROW]->(r:SheetRow) RETURN max(r.position) AS m",
            sid=sheet_id)
        pos = ((agg[0]["m"] or 0.0) + 1.0) if agg else 0.0

    await run_write(
        """
        MATCH (s:Sheet {id: $sid})
        CREATE (s)-[:HAS_ROW]->(r:SheetRow {id: $rid, position: $pos, created_at: $now})
        SET s.updated_at = $now
        """, sid=sheet_id, rid=rid, pos=float(pos), now=_now())
    if body.values:
        await _write_cells(sheet_id, rid, body.values)
    return {"id": rid, "position": pos, "cells": {}, "links": {}}


@router.patch("/{sheet_id}/rows/{row_id}")
async def update_row(sheet_id: str, row_id: str, patch: SheetRowUpdate) -> dict:
    await _write_cells(sheet_id, row_id, patch.values)
    await run_write("MATCH (s:Sheet {id: $sid}) SET s.updated_at = $now",
                    sid=sheet_id, now=_now())
    rows = await run_read(
        """
        MATCH (r:SheetRow {id: $rid})
        OPTIONAL MATCH (r)-[l:LINKS_TO]->(e)
        RETURN r, collect({col: l.col, id: e.id,
                           label: coalesce(e.title, e.name, e.id)}) AS links
        """, rid=row_id)
    if not rows:
        raise HTTPException(404, "row not found")
    node = dict(rows[0]["r"])
    cells = {k[len(CELL_PREFIX):]: v for k, v in node.items() if k.startswith(CELL_PREFIX)}
    for k, v in list(cells.items()):
        if isinstance(v, str) and v.startswith("["):
            try:
                cells[k] = json.loads(v)
            except ValueError:
                pass
    links = {l["col"]: {"id": l["id"], "label": l["label"]}
             for l in rows[0]["links"] if l and l.get("col")}
    return {"id": row_id, "cells": cells, "links": links}


@router.post("/{sheet_id}/rows/bulk", status_code=201)
async def bulk_rows(sheet_id: str, body: RowsBulk) -> dict:
    """Paste or programmatic insert. Rows carrying a `link` column still go the
    slow way (each needs its own MATCH on the target); everything else lands in
    a single UNWIND."""
    cols = {c["key"]: c for c in await _columns(sheet_id)}
    has_link = any(c["type"] == "link" for c in cols.values())
    if has_link and any(
            any(cols.get(k, {}).get("type") == "link" and v for k, v in values.items())
            for values in body.rows):
        for values in body.rows:
            await create_row(sheet_id, SheetRowCreate(values=values))
        await record("sheet", "rows added", detail=f"{len(body.rows)} rows",
                     entity_id=sheet_id)
        return {"created": len(body.rows)}

    agg = await run_read(
        "MATCH (:Sheet {id: $sid})-[:HAS_ROW]->(r:SheetRow) RETURN max(r.position) AS m",
        sid=sheet_id)
    start = (agg[0]["m"] or 0.0) + 1.0 if agg else 0.0
    payload = []
    for n, values in enumerate(body.rows):
        props: dict[str, Any] = {}
        for key, value in values.items():
            col = cols.get(key)
            if not col or col["type"] == "link":
                continue
            v = _coerce(value, col["type"])
            if v is not None:
                props[CELL_PREFIX + key] = v
        payload.append({"id": str(uuid.uuid4()), "pos": start + n, "props": props})
    await run_write(
        """
        MATCH (s:Sheet {id: $sid})
        UNWIND $rows AS row
        CREATE (s)-[:HAS_ROW]->(r:SheetRow {id: row.id, position: row.pos, created_at: $now})
        SET r += row.props
        SET s.updated_at = $now
        """, sid=sheet_id, rows=payload, now=_now())
    await record("sheet", "rows added", detail=f"{len(payload)} rows", entity_id=sheet_id)
    return {"created": len(payload)}


@router.delete("/{sheet_id}/rows/{row_id}", status_code=204, response_class=Response)
async def delete_row(sheet_id: str, row_id: str) -> Response:
    await run_write("MATCH (r:SheetRow {id: $rid}) DETACH DELETE r", rid=row_id)
    await run_write("MATCH (s:Sheet {id: $sid}) SET s.updated_at = $now",
                    sid=sheet_id, now=_now())
    return Response(status_code=204)


@router.post("/{sheet_id}/rows/reorder")
async def reorder_rows(sheet_id: str, body: ReorderRequest) -> dict:
    await run_write(
        """
        UNWIND range(0, size($ids) - 1) AS i
        MATCH (:Sheet {id: $sid})-[:HAS_ROW]->(r:SheetRow {id: $ids[i]})
        SET r.position = toFloat(i)
        """, sid=sheet_id, ids=body.ids)
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Saved views
# --------------------------------------------------------------------------- #
@router.post("/{sheet_id}/views", status_code=201)
async def save_view(sheet_id: str, body: SheetViewSave) -> dict:
    vid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (s:Sheet {id: $sid})
        MERGE (s)-[:HAS_VIEW]->(v:SheetView {name: $name})
        ON CREATE SET v.id = $vid
        SET v.filters = $filters, v.sorts = $sorts, v.hidden = $hidden
        RETURN v
        """, sid=sheet_id, vid=vid, name=body.name.strip() or "View",
        filters=json.dumps(body.filters), sorts=json.dumps(body.sorts),
        hidden=json.dumps(body.hidden))
    v = dict(rows[0]["v"])
    for f in ("filters", "sorts", "hidden"):
        v[f] = json.loads(v.get(f) or "[]")
    await record("sheet", "view saved", detail=body.name[:70], entity_id=sheet_id)
    return v


@router.delete("/{sheet_id}/views/{view_id}", status_code=204, response_class=Response)
async def delete_view(sheet_id: str, view_id: str) -> Response:
    await run_write(
        "MATCH (:Sheet {id: $sid})-[:HAS_VIEW]->(v:SheetView {id: $vid}) DETACH DELETE v",
        sid=sheet_id, vid=view_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Import / export
# --------------------------------------------------------------------------- #
def _sniff(values: list[str]) -> str:
    """Guess a column type from a sample of its values, conservatively —
    a wrong guess is worse than `text`, because it silently drops data."""
    vals = [v.strip() for v in values if v and v.strip()]
    if not vals:
        return "text"
    if all(re.fullmatch(r"-?[\d,]*\.?\d+%?", v) for v in vals):
        return "number"
    if all(re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ].*)?", v) for v in vals):
        return "date"
    if all(v.lower() in {"true", "false", "yes", "no", "y", "n", "1", "0"} for v in vals):
        return "checkbox"
    if all(v.lower().startswith(("http://", "https://")) for v in vals):
        return "url"
    if all(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) for v in vals):
        return "email"
    # Few distinct values across many rows reads as a category, not free text.
    # A status column of read/reading/unread over eight rows should land here,
    # so the bar is "at most a third of the rows are distinct", not a quarter.
    uniq = {v.lower() for v in vals}
    if len(vals) >= 6 and len(uniq) <= max(3, len(vals) // 3) and len(uniq) <= 12:
        return "select"
    return "longtext" if max(len(v) for v in vals) > 80 else "text"


@router.post("/import", status_code=201)
async def import_csv(file: UploadFile = File(...), name: str = "") -> dict:
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.reader(io.StringIO(text))
    table = [r for r in reader if any(c.strip() for c in r)]
    if not table:
        raise HTTPException(400, "that file has no rows")
    headers = [h.strip() or f"Column {i + 1}" for i, h in enumerate(table[0])]
    body_rows = table[1:]

    sid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (s:Sheet {id: $id, name: $name, description: $desc,
                         created_at: $now, updated_at: $now})
        """, id=sid,
        name=(name or (file.filename or "Imported").rsplit(".", 1)[0])[:80],
        desc=f"Imported from {file.filename}", now=_now())

    keys: list[str] = []
    taken: set[str] = set()
    for i, header in enumerate(headers):
        sample = [r[i] for r in body_rows[:60] if i < len(r)]
        ctype = _sniff(sample)
        col = await add_column(sid, ColumnCreate(
            name=header, type=ctype,
            options=sorted({r[i].strip() for r in body_rows if i < len(r) and r[i].strip()})
                    if ctype == "select" else [],
            width=220 if ctype == "longtext" else 160))
        keys.append(col["key"])
        taken.add(col["key"])

    # One UNWIND for the whole file. Creating rows one at a time is two round
    # trips each, which turned a trivial 8-row CSV into a 23-second import and
    # would make a real one unusable.
    types = {c["key"]: c["type"] for c in await _columns(sid)}
    payload = []
    for n, r in enumerate(body_rows):
        props: dict[str, Any] = {}
        for i in range(min(len(keys), len(r))):
            value = _coerce(r[i], types.get(keys[i], "text"))
            if value is not None:
                props[CELL_PREFIX + keys[i]] = value
        payload.append({"id": str(uuid.uuid4()), "pos": float(n), "props": props})

    await run_write(
        """
        MATCH (s:Sheet {id: $sid})
        UNWIND $rows AS row
        CREATE (s)-[:HAS_ROW]->(r:SheetRow {id: row.id, position: row.pos, created_at: $now})
        SET r += row.props
        """, sid=sid, rows=payload, now=_now())

    await record("sheet", "imported", detail=f"{file.filename} · {len(body_rows)} rows",
                 entity_id=sid)
    return await get_sheet(sid)


@router.get("/{sheet_id}/export")
async def export_sheet(sheet_id: str, format: str = "csv"):
    sheet = await _sheet(sheet_id)
    cols = await _columns(sheet_id)
    rows = await _rows(sheet_id)
    stem = re.sub(r"[^\w-]+", "-", sheet.get("name", "sheet")).strip("-").lower() or "sheet"

    _attach_formulas(cols, rows)

    def cell(row: dict, col: dict) -> Any:
        if col["type"] == "link":
            return (row["links"].get(col["key"]) or {}).get("label", "")
        if col["type"] == "formula":
            # An export that dropped the computed columns would be a different
            # table from the one on screen.
            v = row.get("computed", {}).get(col["key"])
            return "" if v is None else v
        v = row["cells"].get(col["key"])
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if isinstance(v, bool):
            return "true" if v else "false"
        return "" if v is None else v

    if format == "json":
        payload = {
            "name": sheet.get("name"),
            "columns": [{"name": c["name"], "key": c["key"], "type": c["type"]} for c in cols],
            "rows": [{c["key"]: cell(r, c) for c in cols} for r in rows],
        }
        await record("sheet", "exported", detail=f"{sheet.get('name','')[:40]} → json",
                     entity_id=sheet_id)
        return Response(
            json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{stem}.json"'})

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([c["name"] for c in cols])
    for r in rows:
        writer.writerow([cell(r, c) for c in cols])
    buf.seek(0)
    await record("sheet", "exported", detail=f"{sheet.get('name','')[:40]} → csv",
                 entity_id=sheet_id)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})

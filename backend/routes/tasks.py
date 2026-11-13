"""/api/tasks — the Mainframe-level task system (per TASKS_SPEC).

A task is a living journal: a chain of :TaskEntry nodes that grows as you work.
Tasks nest (child -[:CHILD_OF]-> parent) and are owned by a module
(task -[:OWNED_BY]-> :Module). Every task header shows accumulated time (the
sum of all entry time_spent_mins). Tasks are NOT Synapse-specific, so this
router stays at /api/tasks, not /api/synapse/tasks.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import TaskCreate, TaskEntryCreate, TaskEntryUpdate, TaskUpdate

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# List — every task with its full entry journal + aggregates
# --------------------------------------------------------------------------- #
@router.get("")
async def list_tasks() -> list[dict]:
    rows = await run_read(
        """
        MATCH (t:Task)
        OPTIONAL MATCH (t)-[:HAS_ENTRY]->(e:TaskEntry)
        WITH t, e ORDER BY coalesce(e.date, '')
        WITH t, collect(e{.*}) AS entries
        OPTIONAL MATCH (c:Task {parent_id: t.id})
        WITH t, entries, count(c) AS subtask_count
        RETURN t{
            .*,
            entries: entries,
            subtask_count: subtask_count,
            total_mins: reduce(s = 0, x IN entries | s + coalesce(x.time_spent_mins, 0))
        } AS task
        ORDER BY coalesce(t.created_at, '')
        """
    )
    return [r["task"] for r in rows]


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
@router.post("", status_code=201)
async def create_task(body: TaskCreate) -> dict:
    tid = str(uuid.uuid4())
    now = _now()
    due = body.due_date.isoformat() if body.due_date else None
    await run_write(
        """
        CREATE (t:Task {
            id: $id, title: $title, horizon: $horizon, module: $module,
            est_time: $est_time, due_date: $due, parent_id: $parent_id,
            priority: $priority, status: 'active', done: false, done_at: null,
            created_at: $now, opened_at: $opened_at
        })
        WITH t
        MERGE (m:Module {name: $module})
        MERGE (t)-[:OWNED_BY]->(m)
        """,
        id=tid, title=body.title, horizon=body.horizon, module=body.module,
        est_time=body.est_time, due=due, parent_id=body.parent_id,
        priority=body.priority, now=now,
        # `created_at` records when the row was made and never moves; `opened_at`
        # is when the work started and is yours to correct.
        opened_at=body.opened_at or now,
    )
    if body.parent_id:
        await run_write(
            "MATCH (t:Task {id: $tid}), (p:Task {id: $pid}) MERGE (t)-[:CHILD_OF]->(p)",
            tid=tid, pid=body.parent_id,
        )
    if body.notes:
        await run_write(
            """
            MATCH (t:Task {id: $tid})
            CREATE (t)-[:HAS_ENTRY]->(:TaskEntry {
                id: $eid, type: 'initial_idea', date: $now, time_of_day: null,
                time_spent_mins: 0, time_spent_label: null, notes: $notes,
                learned: null, next_step: null, created_at: $now
            })
            """,
            tid=tid, eid=str(uuid.uuid4()), now=now, notes=body.notes,
        )
    await record(
        "task", "created",
        detail=f"{body.title[:70]} ({body.horizon}/{body.module})",
        module=body.module, entity_id=tid,
    )
    return await _get_one(tid)


# --------------------------------------------------------------------------- #
# Update — fields, done toggle, hide/park
# --------------------------------------------------------------------------- #
@router.patch("/{task_id}")
async def update_task(task_id: str, patch: TaskUpdate) -> dict:
    data = patch.model_dump(exclude_unset=True)
    fields: dict = {}

    for k in ("title", "horizon", "module", "est_time", "priority", "status"):
        if k in data and data[k] is not None:
            fields[k] = data[k]
    if "due_date" in data:
        fields["due_date"] = data["due_date"].isoformat() if data["due_date"] else None
    if "done" in data and data["done"] is not None:
        fields["done"] = data["done"]
        fields["done_at"] = _now() if data["done"] else None
        fields["status"] = "done" if data["done"] else "active"
    if "hidden" in data and data["hidden"] is not None:
        fields["status"] = "hidden" if data["hidden"] else "active"
    # Both ends of the task's life are explicitly settable — and settable to
    # nothing. `in data` rather than a truthiness test, so sending null clears
    # the value instead of being silently ignored (which is what made a wrong
    # completion time unfixable before). A `done_at` sent alongside `done: true`
    # wins over the automatic stamp above.
    if "opened_at" in data:
        fields["opened_at"] = data["opened_at"]
    if "done_at" in data:
        fields["done_at"] = data["done_at"]

    if not fields and "parent_id" not in data:
        raise HTTPException(400, "no fields to update")

    if fields:
        sets = ", ".join(f"t.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (t:Task {{id: $id}}) SET {sets} RETURN t", id=task_id, **fields
        )
        if not rows:
            raise HTTPException(404, "task not found")

    if "parent_id" in data:
        new_parent = data["parent_id"]
        await run_write(
            "MATCH (t:Task {id: $id})-[r:CHILD_OF]->() DELETE r", id=task_id
        )
        await run_write(
            "MATCH (t:Task {id: $id}) SET t.parent_id = $pid", id=task_id, pid=new_parent
        )
        if new_parent:
            await run_write(
                "MATCH (t:Task {id: $id}),(p:Task {id: $pid}) MERGE (t)-[:CHILD_OF]->(p)",
                id=task_id, pid=new_parent,
            )

    verb = (
        "completed" if fields.get("done")
        else "reopened" if fields.get("done") is False
        else "hidden" if fields.get("status") == "hidden"
        else "parked" if fields.get("status") == "parked"
        else "updated"
    )
    await record(
        "task", verb, detail=", ".join(fields) or "reparented",
        module=fields.get("module"), entity_id=task_id,
    )
    return await _get_one(task_id)


# --------------------------------------------------------------------------- #
# Delete — cascade=false reparents children to top level; cascade=true removes them
# --------------------------------------------------------------------------- #
@router.delete("/{task_id}", status_code=204, response_class=Response)
async def delete_task(task_id: str, cascade: bool = False) -> Response:
    if cascade:
        await run_write(
            """
            MATCH (t:Task {id: $id})
            OPTIONAL MATCH (d:Task)-[:CHILD_OF*1..]->(t)
            WITH t, collect(DISTINCT d) AS ds
            WITH ds + t AS nodes
            UNWIND nodes AS n
            OPTIONAL MATCH (n)-[:HAS_ENTRY]->(e:TaskEntry)
            DETACH DELETE e, n
            """,
            id=task_id,
        )
    else:
        # promote children to top level, then delete this task + its entries
        await run_write(
            """
            MATCH (c:Task)-[r:CHILD_OF]->(:Task {id: $id})
            SET c.parent_id = null DELETE r
            """,
            id=task_id,
        )
        await run_write(
            """
            MATCH (t:Task {id: $id})
            OPTIONAL MATCH (t)-[:HAS_ENTRY]->(e:TaskEntry)
            DETACH DELETE e, t
            """,
            id=task_id,
        )
    await record("task", "deleted", detail=f"{task_id}{' + subtasks' if cascade else ''}")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Entries — the journal
# --------------------------------------------------------------------------- #
@router.post("/{task_id}/entries", status_code=201)
async def add_entry(task_id: str, body: TaskEntryCreate) -> dict:
    eid = str(uuid.uuid4())
    now = _now()
    rows = await run_write(
        """
        MATCH (t:Task {id: $tid})
        CREATE (t)-[:HAS_ENTRY]->(e:TaskEntry {
            id: $id, type: $type, date: $date, time_of_day: $tod,
            time_spent_mins: $mins, time_spent_label: $label, notes: $notes,
            learned: $learned, next_step: $next, created_at: $now
        })
        RETURN e{.*} AS entry
        """,
        tid=task_id, id=eid, type=body.type, date=body.date or now,
        tod=body.time_of_day, mins=body.time_spent_mins, label=body.time_spent_label,
        notes=body.notes, learned=body.learned, next=body.next_step, now=now,
    )
    if not rows:
        raise HTTPException(404, "task not found")
    await record(
        "task", "entry added", detail=f"{body.type} · {body.time_spent_mins}min",
        entity_id=task_id,
    )
    return rows[0]["entry"]


@router.patch("/{task_id}/entries/{entry_id}")
async def update_entry(task_id: str, entry_id: str, patch: TaskEntryUpdate) -> dict:
    """Edit an existing journal entry (used by the timeline to fix a date)."""
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"e.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"""
        MATCH (:Task {{id: $tid}})-[:HAS_ENTRY]->(e:TaskEntry {{id: $eid}})
        SET {sets}
        RETURN e{{.*}} AS entry
        """,
        tid=task_id, eid=entry_id, **fields,
    )
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("task", "entry edited", detail=", ".join(fields), entity_id=task_id)
    return rows[0]["entry"]


@router.delete("/{task_id}/entries/{entry_id}", status_code=204, response_class=Response)
async def delete_entry(task_id: str, entry_id: str) -> Response:
    await run_write(
        "MATCH (:Task {id: $tid})-[:HAS_ENTRY]->(e:TaskEntry {id: $eid}) DETACH DELETE e",
        tid=task_id, eid=entry_id,
    )
    await record("task", "entry removed", detail=entry_id)
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
async def _get_one(task_id: str) -> dict:
    rows = await run_read(
        """
        MATCH (t:Task {id: $id})
        OPTIONAL MATCH (t)-[:HAS_ENTRY]->(e:TaskEntry)
        WITH t, e ORDER BY coalesce(e.date, '')
        WITH t, collect(e{.*}) AS entries
        OPTIONAL MATCH (c:Task {parent_id: t.id})
        WITH t, entries, count(c) AS subtask_count
        RETURN t{
            .*, entries: entries, subtask_count: subtask_count,
            total_mins: reduce(s = 0, x IN entries | s + coalesce(x.time_spent_mins, 0))
        } AS task
        """,
        id=task_id,
    )
    if not rows:
        raise HTTPException(404, "task not found")
    return rows[0]["task"]

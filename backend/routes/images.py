"""/api/images — the Mainframe-level image service (VISION_SPEC).

Deliberately generic: an image knows only which `module` it belongs to and the
`context_id` of whatever entity it hangs off. The HAS_IMAGE edge is drawn by
matching *any* node carrying that id — the same unlabelled id-match trick
activity.record() uses — so a paper, a habit, a workout, a task or a mind-dump
can all take images without this module knowing anything about them.

Every save requires a user-supplied name (the spec is emphatic: no auto-names,
no defaults). The name is sanitised into the filename; the original is kept on
the node for display.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from activity import record
from config import settings
from db import run_read, run_write
from models import ReorderRequest
from routes.mind import reorder_nodes
from models import ImageUpdate

router = APIRouter(prefix="/api/images", tags=["images"])

# Images only — PDFs and other documents keep their existing per-module
# uploaders (medical files, project files, paper PDFs).
MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}
# Any module may own images; unknown values are slugged rather than rejected so
# a new module needs no change here.
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str, fallback: str) -> str:
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return s[:60] or fallback


def _module_dir(module: str) -> Path:
    return settings.images_dir / _slug(module, "misc")


@router.get("")
async def list_images(module: str | None = None, context_id: str | None = None) -> list[dict]:
    clauses, params = [], {}
    if module:
        clauses.append("i.module = $module")
        params["module"] = module
    if context_id:
        clauses.append("i.context_id = $context_id")
        params["context_id"] = context_id
    cypher = "MATCH (i:Image)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN i ORDER BY coalesce(i.position, 1e15) ASC, i.created_at DESC"
    rows = await run_read(cypher, **params)
    return [dict(r["i"]) for r in rows]


@router.post("", status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    name: str = Form(...),
    module: str = Form("mainframe"),
    context_id: str | None = Form(None),
) -> dict:
    if not name.strip():
        raise HTTPException(400, "every image needs a name")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MIME_BY_EXT:
        raise HTTPException(400, f"unsupported image type '{ext or '?'}' — use "
                                 + ", ".join(sorted(MIME_BY_EXT)))
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")

    dest_dir = _module_dir(module)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{_slug(name, 'image')}_{stamp}{ext}"
    (dest_dir / filename).write_bytes(data)

    iid = str(uuid.uuid4())
    # new images land at the end of the manual order for their context
    tail = await run_read(
        "MATCH (i:Image) WHERE i.module = $module AND i.context_id = $context_id "
        "RETURN coalesce(max(i.position), -1.0) AS last",
        module=module, context_id=context_id,
    )
    next_pos = float((tail[0]["last"] if tail else -1.0) or -1.0) + 1.0
    rows = await run_write(
        """
        CREATE (i:Image {
            id: $id, name: $name, filename: $filename, path: $path,
            module: $module, context_id: $context_id, mime_type: $mime,
            bytes: $bytes, created_at: $now, position: $position
        })
        WITH i
        OPTIONAL MATCH (e) WHERE e.id = $context_id
        FOREACH (_ IN CASE WHEN e IS NULL THEN [] ELSE [1] END |
            MERGE (e)-[:HAS_IMAGE]->(i))
        RETURN i
        """,
        id=iid, name=name.strip(), filename=filename,
        path=str(dest_dir / filename), module=module, context_id=context_id,
        mime=MIME_BY_EXT[ext], bytes=len(data), position=next_pos,
        now=datetime.now(timezone.utc).isoformat(),
    )
    await record("image", "uploaded", detail=f"{name.strip()[:50]} · {module}",
                 module=module, entity_id=context_id)
    return dict(rows[0]["i"])


@router.post("/reorder")
async def reorder_images(body: ReorderRequest) -> dict:
    """Manual image order. Mainframe-level: works for any module's images,
    since every :Image carries a position regardless of where it's mounted."""
    pairs = await reorder_nodes("Image", body.ids)
    await record("image", "reordered", detail=f"{len(pairs)} images")
    return {"ok": True, "positions": pairs}


@router.get("/{image_id}")
async def get_image(image_id: str) -> dict:
    rows = await run_read("MATCH (i:Image {id: $id}) RETURN i", id=image_id)
    if not rows:
        raise HTTPException(404, "image not found")
    return dict(rows[0]["i"])


@router.get("/{image_id}/file")
async def serve_image(image_id: str) -> FileResponse:
    rows = await run_read("MATCH (i:Image {id: $id}) RETURN i", id=image_id)
    if not rows:
        raise HTTPException(404, "image not found")
    img = dict(rows[0]["i"])
    path = Path(img["path"])
    if not path.is_file():
        raise HTTPException(404, "image file missing on disk")
    return FileResponse(path, media_type=img.get("mime_type") or "application/octet-stream",
                        filename=img.get("filename"))


@router.put("/{image_id}")
async def rename_image(image_id: str, patch: ImageUpdate) -> dict:
    if not (patch.name or "").strip():
        raise HTTPException(400, "name cannot be empty")
    rows = await run_write(
        "MATCH (i:Image {id: $id}) SET i.name = $name RETURN i",
        id=image_id, name=patch.name.strip(),
    )
    if not rows:
        raise HTTPException(404, "image not found")
    img = dict(rows[0]["i"])
    await record("image", "renamed", detail=img["name"][:50], module=img.get("module"))
    return img


@router.delete("/{image_id}", status_code=204, response_class=Response)
async def delete_image(image_id: str) -> Response:
    rows = await run_read("MATCH (i:Image {id: $id}) RETURN i", id=image_id)
    if rows:
        img = dict(rows[0]["i"])
        try:
            Path(img["path"]).unlink(missing_ok=True)
        except OSError:
            pass  # node still goes; a stale file is better than a stuck record
        await run_write("MATCH (i:Image {id: $id}) DETACH DELETE i", id=image_id)
        await record("image", "deleted", detail=img.get("name", "")[:50],
                     module=img.get("module"))
    return Response(status_code=204)

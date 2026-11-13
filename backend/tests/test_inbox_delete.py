"""Inbox delete removes only the Inbox row (2026-11-08).

DELETE /api/synapse/inbox/{id} must take the :Task and nothing it points at:
the node it CAME_FROM stays, and its :TaskEntry journal is detached and stamped
orphaned_from / orphaned_at rather than deleted.

Runs against the live API (localhost:8000) and Neo4j, on scratch nodes it makes
and removes itself; skipped when either is not up.
Run with: env -u PYTHONPATH .venv/bin/pytest tests/test_inbox_delete.py
"""
import json
import os
import urllib.request
import uuid

import pytest

API = os.environ.get("MAINFRAME_API", "http://localhost:8000")
neo4j = pytest.importorskip("neo4j")


def _call(method, path, body=None):
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


@pytest.fixture
def db():
    try:
        _call("GET", "/api/synapse/inbox/log")
        d = neo4j.GraphDatabase.driver(
            "bolt://localhost:7687",
            auth=("neo4j", os.environ.get("NEO4J_PASSWORD", "mainframe")))
        d.verify_connectivity()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"live API / Neo4j not up: {e}")
    yield d
    d.close()


def _one(db, q, **p):
    with db.session() as s:
        return [dict(r) for r in s.run(q, **p)]


def test_delete_keeps_source_and_orphans_entries(db):
    tag = "pytest-del-" + uuid.uuid4().hex[:8]
    src_id = tag + "-src"
    title = tag + " row"
    _one(db, "CREATE (:Question {id: $id, text: $t, answered: false})", id=src_id, t=tag)
    row = _call("POST", "/api/synapse/inbox", {"title": title, "kind": "idea"})
    tid = row["id"]
    entry_id = None
    try:
        _one(db, "MATCH (t:Task {id: $tid}), (q:Question {id: $sid}) "
                 "MERGE (t)-[:CAME_FROM]->(q)", tid=tid, sid=src_id)
        e = _call("POST", f"/api/tasks/{tid}/entries", {"type": "note", "notes": tag})
        entry_id = e["id"]

        _call("DELETE", f"/api/synapse/inbox/{tid}")

        assert not _one(db, "MATCH (t:Task {id: $id}) RETURN t", id=tid), "row should be gone"
        assert _one(db, "MATCH (q:Question {id: $id}) RETURN q", id=src_id), \
            "the source node must survive the row's delete"
        left = _one(db, "MATCH (e:TaskEntry {id: $id}) RETURN e.orphaned_from AS f, "
                        "e.orphaned_at AS at, EXISTS { (e)--() } AS linked", id=entry_id)
        assert left, "the journal entry must survive the row's delete"
        assert left[0]["f"] == title and left[0]["at"]
        assert not left[0]["linked"], "the entry should be detached from the row"
        log = _call("GET", "/api/synapse/inbox/log")
        assert any(m.get("edge") == "DELETED" and title in (m.get("from") or m.get("frm") or json.dumps(m))
                   for m in log), "a DELETED line should be in What changed"
    finally:
        _one(db, "MATCH (n) WHERE n.id IN [$s, $t, $e] DETACH DELETE n",
             s=src_id, t=tid, e=entry_id or "")
        _one(db, "MATCH (m:Move) WHERE m.frm CONTAINS $tag OR m.from CONTAINS $tag "
                 "DETACH DELETE m", tag=tag)

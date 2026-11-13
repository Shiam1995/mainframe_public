"""Activity log — the spine of everything.

Every mutation in the system (create/update/delete of any entity) calls
`record(...)`, which writes a :ChangeEvent node to Neo4j. Nodes carry BOTH the
`:ChangeEvent` (spec name) and `:LogEntry` (legacy) labels so old read queries
keep working. Where an owning entity id is known, the event is linked with
`(:Entity)-[:HAS_CHANGE]->(:ChangeEvent)`. The /api/log route reads these back.

Keeping this in one helper guarantees the log stays comprehensive — which is
also why the IN_PHASE hook hangs off the end of it: see phasehook.py.
"""
from __future__ import annotations

import logging
import re
import uuid
from functools import lru_cache
from datetime import datetime, timezone

import phasehook
from db import run_write

log = logging.getLogger("synapse.activity")

# Categories the spec enumerates. Not enforced, but documented here.
CATEGORIES = {
    "paper", "highlight", "term", "task", "ref",
    "kg", "status", "deepdive", "idea", "header", "instance", "question",
    "dictionary", "mind", "project", "document", "sheet", "reminder", "focus", "framework",
    "goal", "note", "lesson", "assumption",
    # Pulse module
    "habit", "experiment", "routine", "medical", "medication", "fitness", "nutrition",
    "recovery",
}

# Which Mainframe module a category belongs to. Everything paper-domain is
# Synapse; tasks are Mainframe-level and pass their own module explicitly.
CATEGORY_MODULE = {
    "paper": "synapse", "highlight": "synapse", "term": "synapse",
    "ref": "synapse", "kg": "synapse", "status": "synapse",
    "deepdive": "synapse", "idea": "synapse", "header": "synapse",
    "instance": "synapse", "question": "synapse", "dictionary": "synapse",
    "task": "synapse",  # default; task routes override with the task's own module
    "mind": "synapse",  # mind-dump is Mainframe-level but tagged synapse for now
    "project": "synapse",
    # Documents are Mainframe-level: you write them from anywhere.
    "document": "synapse",
    "sheet": "synapse",
    # Reminders are Mainframe-level — they can be about anything.
    "reminder": "synapse",
    "focus": "synapse",
    "framework": "synapse",
    # Goals view is Mainframe-level — same fallback as the other shared tabs.
    "goal": "synapse",
    # Notes hang off anything in any module; the caller passes the owning
    # module when it knows one.
    "note": "synapse",
    # Lessons are Mainframe-level: a mistake is rarely confined to one module.
    "lesson": "synapse",
    # Assumptions, like questions, are made anywhere; same fallback.
    "assumption": "synapse",
    # Gratitude is Mainframe-level; routes pass module="mainframe".
    "gratitude": "synapse",
    "habit": "pulse", "experiment": "pulse", "routine": "pulse",
    "medical": "pulse", "medication": "pulse", "fitness": "pulse", "nutrition": "pulse",
    "recovery": "pulse", "tracking": "pulse",
    # Images are Mainframe-level: the caller always passes the owning module,
    # this is only the fallback when it doesn't.
    "image": "synapse",
    # Vision — content creation
    "pipeline": "vision", "video": "vision", "writing": "vision",
    "portfolio": "vision", "contact": "vision", "sandbox": "vision",
    # Vault — finance / inventory / assets
    "account": "vault", "transaction": "vault", "budget": "vault",
    "investment": "vault", "inventory": "vault", "findiary": "vault",
}

VALID_TRIGGERS = {"manual", "llm", "system"}


def match_by_id(param: str, var: str) -> str:
    """A Cypher fragment binding `var` to the node whose id is `$param`, by
    index seek across every constrained label — the fast form of
    `MATCH (var) WHERE var.id = $param` (see _entity_lookup for why that one
    takes seconds). Follow it with WITH/MERGE; `var` is unbound on no match."""
    return (f"WITH *, ${param} AS lid CALL (lid) {{ {_entity_lookup()} }} "
            f"WITH *, e AS {var}")


@lru_cache(maxsize=1)
def _entity_lookup() -> str:
    """The UNION subquery that finds an event's owning entity by id.

    This used to be `OPTIONAL MATCH (e) WHERE e.id = lid`. An *unlabelled*
    match can't use an index, so it scanned every node in the database — which
    since the 4-million-row food catalogue landed meant roughly three seconds
    of scanning per logged mutation, on every create/update/delete in the app.

    Every entity worth linking already has a `REQUIRE x.id IS UNIQUE`
    constraint (and therefore an index), so the labels are read straight out of
    db.py's schema list and turned into index seeks. Declaring a new
    constrained label is all it takes to make it linkable — nothing to keep in
    sync by hand.
    """
    from db import _SCHEMA_STATEMENTS

    labels: list[str] = []
    for stmt in _SCHEMA_STATEMENTS:
        m = re.search(r"FOR\s*\(\s*\w+\s*:\s*(\w+)\s*\)\s*REQUIRE\s+\w+\.id\s+IS\s+UNIQUE",
                      stmt, re.I)
        if m and m.group(1) not in labels:
            labels.append(m.group(1))
    # ChangeEvent itself is never the owner of a change.
    labels = [l for l in labels if l not in {"ChangeEvent", "LogEntry"}]
    if not labels:                       # defensive: never emit an empty CALL {}
        return "MATCH (e) WHERE e.id = lid RETURN e"
    # `CALL (lid) { ... }` scopes the variable once, so the branches don't
    # re-import it — the un-scoped form is deprecated in Neo4j 5.
    return " UNION ".join(f"MATCH (e:{l} {{id: lid}}) RETURN e" for l in labels)


async def record(
    category: str,
    action: str,
    detail: str = "",
    paper_id: str | None = None,
    paper_title: str | None = None,
    module: str | None = None,
    trigger: str = "manual",
    entity_id: str | None = None,
) -> None:
    """Append one timestamped :ChangeEvent to the activity log.

    - `module`: which Mainframe module owns this change. Defaults from category.
    - `trigger`: "manual" | "llm" | "system" — who caused the mutation.
    - `entity_id`: id of the owning entity, if not a paper. When set (or when
      `paper_id` is set), a (:Entity)-[:HAS_CHANGE]->(:ChangeEvent) edge is drawn.

    Never raises — logging must not break the operation it's recording.
    """
    resolved_module = module or CATEGORY_MODULE.get(category, "synapse")
    resolved_trigger = trigger if trigger in VALID_TRIGGERS else "manual"
    # Ids to link the event back to its owning entity/entities (nulls dropped).
    link_ids = [lid for lid in (paper_id, entity_id) if lid]
    try:
        await run_write(
            f"""
            CREATE (l:ChangeEvent:LogEntry {{
                id: $id, ts: $ts, timestamp: $ts,
                category: $category, action: $action, detail: $detail,
                paper_id: $paper_id, paper_title: $paper_title,
                module: $module, trigger: $trigger
            }})
            WITH l
            UNWIND $link_ids AS lid
              CALL (lid) {{ {_entity_lookup()} }}
              MERGE (e)-[:HAS_CHANGE]->(l)
            """,
            id=str(uuid.uuid4()),
            ts=datetime.now(timezone.utc).isoformat(),
            category=category,
            action=action,
            detail=detail,
            paper_id=paper_id,
            paper_title=paper_title,
            module=resolved_module,
            trigger=resolved_trigger,
            link_ids=link_ids,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("failed to write change event (%s/%s): %s", category, action, exc)

    # The IN_PHASE hook rides along here for the same reason the log does: this
    # is the one function every mutation in the app already passes through, so
    # filing work under the phase it was done in needs no line in any route.
    # It never raises; see phasehook's docstring for what it will and won't tag.
    await phasehook.after_write(entity_id or paper_id)

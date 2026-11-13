"""IN_PHASE — the one hook that files what you make under the phase you made it in.

A phase exists to answer "what did those fourteen weeks come to". That answer
cannot depend on remembering to tag anything, so membership is not something you
opt into: a Session, Task, Project, CalEvent, Goal, Mistake, Lesson, Document,
Change or Note created while a phase is running gets `-[:IN_PHASE]->` that phase, and
that is the only way it ever gets one.

WHERE IT HOOKS
    activity.record(). Every mutation in the app already calls it — that is the
    promise its own docstring makes and the reason the log is comprehensive — so
    it is the single place that sees every write without a line in any route.

TWO PATHS, because record() only sometimes knows the id of what it recorded:

    tag(entity_id)   the precise one. An indexed seek per label, the same trick
                     activity._entity_lookup() uses to avoid scanning the
                     four-million-row food catalogue. Runs on the write itself.
    sweep()          the catch-all, for the writes that pass no entity_id
                     (calendar events are the live example). One label scan each
                     over nodes that have no IN_PHASE edge yet, debounced to at
                     most once every SWEEP_EVERY seconds, so a burst of writes
                     costs one sweep rather than one per write.

BOTH ARE IDEMPOTENT AND BOTH CHECK THE CLOCK. A node already sitting in a phase
is left alone, and a node only joins if its own creation stamp falls inside the
window. Together those two rules stop the obvious wrong answer: editing a task
you wrote in phase 0 while phase 1 is running must not drag it into phase 1.

A node with no creation stamp at all is NOT tagged. Being unable to date
something is not evidence it happened now, and the first sweep would otherwise
swallow the entire back catalogue.

Never raises. Filing is bookkeeping; it must not break the write it is filing.
"""
from __future__ import annotations

import asyncio
import logging
import time

from db import run_write

log = logging.getLogger("synapse.phasehook")

# The kinds the phase dashboard reads back, under the label each actually
# carries in this database:
#   Session      planner sessions (:Session) and the work log (:WorkSession)
#   Event        the calendar's (:CalEvent)
#   Doc          (:Document)
#   Note         every note and every why, so the Reasoning tab can filter
#                by phase without a second way of knowing which phase
#   Mistake / Lesson / Change   written by the phase log — see step 5. Listing
#                them before they exist costs nothing (an unknown label matches
#                no rows) and means they are filed from the first one written.
LABELS = (
    "Session", "WorkSession", "Task", "Project", "CalEvent",
    "Goal", "Mistake", "Lesson", "Document", "Change", "Note",
)

# Sweep at most this often, in seconds. Long enough that a save-heavy minute is
# one sweep; short enough that nothing sits unfiled long enough to notice.
SWEEP_EVERY = 20.0

# Whichever stamp the label happens to keep its creation time in. `created_at`
# covers everything except planner sessions, which are timestamped by `start`;
# `date` is the last resort for the older work-log rows. left(...,10) trims an
# ISO datetime down to the date the phase window is expressed in.
_STAMP = "left(coalesce(n.created_at, n.start, n.date), 10)"

# The active phase, and only one: two would make "hours in phase" meaningless,
# and phases.py already refuses to start a second. ORDER BY .. LIMIT 1 is here
# so a database that somehow holds two still behaves deterministically.
_ACTIVE = """
MATCH (p:Phase) WHERE coalesce(p.status, 'active') = 'active'
WITH p ORDER BY p.start DESC LIMIT 1
"""

_IN_WINDOW = f"""
WHERE NOT (n)-[:IN_PHASE]->(:Phase)
  AND {_STAMP} >= p.start
  AND {_STAMP} <= p.end
"""

# One indexed seek per label. Every label here that exists today has a
# `REQUIRE x.id IS UNIQUE` constraint, so these are seeks, not scans.
_BY_ID = " UNION ".join(f"MATCH (n:{lbl} {{id: $id}}) RETURN n" for lbl in LABELS)

_TAG_ONE = f"""
{_ACTIVE}
CALL () {{ {_BY_ID} }}
WITH p, n
{_IN_WINDOW}
MERGE (n)-[:IN_PHASE]->(p)
RETURN count(*) AS n
"""

_SWEEP_ONE = """
%s
MATCH (n:%%s)
%s
MERGE (n)-[:IN_PHASE]->(p)
RETURN count(*) AS n
""" % (_ACTIVE, _IN_WINDOW)

_last_sweep = 0.0
_sweep_lock = asyncio.Lock()


async def tag(entity_id: str | None) -> None:
    """File one node under the active phase, if it belongs there.

    Cheap enough to run on every write that knows what it wrote: an id seek per
    label, then a MERGE that does nothing when the edge is already drawn.
    """
    if not entity_id:
        return
    try:
        await run_write(_TAG_ONE, id=entity_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not file %s under the active phase: %s", entity_id, exc)


async def sweep(force: bool = False) -> int:
    """File everything the precise path missed. Returns how many edges it drew.

    Debounced: a call inside SWEEP_EVERY seconds of the last one is a no-op, so
    this is safe to call from the write path. `force=True` skips the debounce —
    the dashboard read uses it so what you are looking at is never stale.
    """
    global _last_sweep
    now = time.monotonic()
    if not force and now - _last_sweep < SWEEP_EVERY:
        return 0
    async with _sweep_lock:
        # Re-check under the lock: several writes landing together should
        # produce one sweep between them, not one each.
        if not force and time.monotonic() - _last_sweep < SWEEP_EVERY:
            return 0
        _last_sweep = time.monotonic()
        drawn = 0
        for lbl in LABELS:
            try:
                rows = await run_write(_SWEEP_ONE % lbl)
                drawn += int(rows[0]["n"]) if rows else 0
            except Exception as exc:  # noqa: BLE001
                log.warning("phase sweep failed for :%s — %s", lbl, exc)
        if drawn:
            log.debug("filed %d node(s) under the active phase", drawn)
        return drawn


async def refile(pid: str) -> int:
    """Re-file a phase after its window moved. Returns how many edges it dropped.

    Moving a phase's start or length changes what "inside it" means, so the
    edges drawn under the old window have to be reconsidered — otherwise a
    phase you shortened keeps counting the fortnight you just cut off it.

    Only ever drops; the sweep that follows redraws whatever now belongs. And
    it leaves :Project alone: a project's membership is the lineup you ticked at
    the start plus anything you worked on, not the date it was created, so it is
    the one label here that a date change must not silently evict.
    """
    try:
        rows = await run_write(
            f"""
            MATCH (n)-[r:IN_PHASE]->(p:Phase {{id: $id}})
            WHERE NOT n:Project
              AND ({_STAMP} IS NULL OR {_STAMP} < p.start OR {_STAMP} > p.end)
            DELETE r
            RETURN count(*) AS n
            """, id=pid)
        return int(rows[0]["n"]) if rows else 0
    except Exception as exc:  # noqa: BLE001
        log.warning("could not re-file phase %s: %s", pid, exc)
        return 0


async def after_write(entity_id: str | None = None) -> None:
    """What activity.record() calls. The precise path first, then the debounced
    catch-all for whatever the caller could not name."""
    await tag(entity_id)
    await sweep()

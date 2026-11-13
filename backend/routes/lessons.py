"""/api/lessons — what went wrong, and what you would do instead.

    (:Lesson {id, date, wrong, instead, repeated, group, created_at})

Two sentences per row and one flag, because that is the whole useful content of
a lesson. "What went wrong" dated and attached to the thing it happened to, and
"what I would do instead" — which is the half people skip, and the half that
makes it a lesson rather than a complaint.

REPEATED IS NOT TYPED. You mark a later lesson as being the same as an earlier
one, which writes (:Lesson)-[:SAME_AS]->(:Lesson) and sets `repeated` on the
LATER one. Setting a tick called "repeated" by hand would let you record that
something recurred without saying what it recurred from, and the phase score
reads this: the mistakes part of the week is "no lesson this week marked
repeated". A number that can be typed is a number that can be wrong.

GROUPS are yours to define, with a colour each, exactly like idea kinds. There
is no fixed taxonomy of mistakes because the useful groupings are the ones you
notice yourself making, and they change.

ATTACHED TO THE THING: (:Lesson)-[:ABOUT]->(anything). A lesson about a project
turns up on that project; a lesson about nothing in particular is still a
lesson and is allowed to have no edge at all.

LESSONS v2 (2026-10-04, from the Lessons v2 spec): one row per
MISTAKE, every time it happens is an INSTANCE under it. That is the SAME_AS
model read the other way up: the root is the first time, each later lesson
pointing at it is an instance, and `repeated` still lands on those later rows,
so the phase score reads exactly what it read before. `GET /board` returns that
shape whole. Distractions logged from reading sessions carry a `pattern` and
stay in a tally, not the lesson list, until you promote a pattern into a lesson;
after that, new distractions with that pattern file themselves as instances.
Solutions are LessonEntry rows of kind "suggestion" with a status
(''/worked/mixed/failed) and an outcome line.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import _entity_lookup, record
from db import run_read, run_write
from models import (LessonCreate, LessonEntryCreate, LessonEntryUpdate,
                    LessonGroupUpsert, LessonInstanceCreate, LessonMerge,
                    LessonPromote, LessonUpdate)

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_TITLE = "coalesce(x.title, x.name, x.text, x.label, '(untitled)')"


def _shape(r: dict) -> dict:
    l = dict(r["lesson"])
    l["repeated"] = bool(l.get("repeated"))
    l["group"] = l.get("group") or ""
    l["about"] = ({"id": r["about_id"], "title": r["about_title"],
                   "label": r["about_label"]} if r.get("about_id") else None)
    l["same_as"] = ({"id": r["same_id"], "wrong": r["same_wrong"],
                     "date": r["same_date"]} if r.get("same_id") else None)
    # How many later lessons point back at this one. A lesson that has happened
    # four times is the one worth reading first.
    l["repeats"] = r.get("repeats") or 0
    for k in ("detail", "pattern", "source", "status"):
        l[k] = l.get(k) or ""
    return l


_ROWS = """
MATCH (l:Lesson)
WHERE $$WHERE$$
OPTIONAL MATCH (l)-[:ABOUT]->(x)
OPTIONAL MATCH (l)-[:SAME_AS]->(s:Lesson)
OPTIONAL MATCH (later:Lesson)-[:SAME_AS]->(l)
WITH l, x, s, count(later) AS repeats
RETURN l{.*} AS lesson, x.id AS about_id, head(labels(x)) AS about_label,
       CASE WHEN x IS NULL THEN '' ELSE %s END AS about_title,
       s.id AS same_id, s.wrong AS same_wrong, s.date AS same_date, repeats
ORDER BY l.date DESC, l.created_at DESC
""" % _TITLE


@router.get("/groups")
async def list_groups() -> list[dict]:
    rows = await run_read(
        "MATCH (g:LessonGroup) RETURN g.name AS name, g.color AS color, "
        "g.note AS note ORDER BY coalesce(g.order, 99), toLower(g.name)")
    return [{"name": r["name"], "color": r["color"] or "#7FA8C8",
             "note": r["note"] or ""}
            for r in rows if r["name"]]


@router.put("/groups")
async def upsert_group(body: LessonGroupUpsert) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "give the group a name")
    await run_write("MERGE (g:LessonGroup {name: $name}) SET g.color = $color "
                    "SET g.note = coalesce($note, g.note)",
                    name=name, color=body.color, note=body.note)
    await record("lesson", "group saved", detail=f"{name} {body.color}")
    return {"name": name, "color": body.color}


@router.delete("/groups/{name}", status_code=204, response_class=Response)
async def delete_group(name: str) -> Response:
    """Removes the group. Lessons in it keep the text and fall back to the
    neutral colour, the same way idea kinds behave."""
    await run_write("MATCH (g:LessonGroup {name: $name}) DELETE g", name=name)
    await record("lesson", "group deleted", detail=name)
    return Response(status_code=204)


@router.get("")
async def list_lessons(group: str | None = None, repeated: bool | None = None,
                       since: str | None = None) -> list[dict]:
    where, params = ["true"], {}
    if group:
        where.append("coalesce(l.group, '') = $group")
        params["group"] = group
    if repeated is not None:
        where.append("coalesce(l.repeated, false) = $repeated")
        params["repeated"] = repeated
    if since:
        where.append("l.date >= $since")
        params["since"] = since
    rows = await run_read(_ROWS.replace("$$WHERE$$", " AND ".join(where)), **params)
    return [_shape(r) for r in rows]


@router.post("", status_code=201)
async def create_lesson(body: LessonCreate) -> dict:
    """Write one down. `wrong` is required; `instead` is not, but a lesson with
    no "instead" is a note, and the client says so rather than refusing it."""
    if not body.wrong.strip():
        raise HTTPException(400, "say what went wrong")
    lid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (l:Lesson {id: $id, date: $date, wrong: $wrong, instead: $instead,
                          group: $group, repeated: false, created_at: $now,
                          detail: $detail, pattern: $pattern, source: $source})
        """, id=lid, date=body.date or date.today().isoformat(),
        wrong=body.wrong.strip(), instead=body.instead.strip(),
        group=body.group, now=_now(), detail=body.detail.strip(),
        pattern=body.pattern.strip(), source=body.source.strip())
    if body.about_id:
        await _link_about(lid, body.about_id)
    if body.same_as:
        await _mark_same(lid, body.same_as)
    elif body.source == "distraction" and body.pattern.strip():
        await _attach_to_pattern_root(lid, body.pattern.strip())
    await record("lesson", "written down", detail=body.wrong.strip()[:70], entity_id=lid)
    return await _one(lid)


@router.patch("/{lid}")
async def update_lesson(lid: str, body: LessonUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    about_id = fields.pop("about_id", "__unset__")
    same_as = fields.pop("same_as", "__unset__")
    # `repeated` is derived from SAME_AS and is not settable directly. See the
    # module docstring: the phase score reads it.
    fields.pop("repeated", None)
    if fields:
        sets = ", ".join(f"l.{k} = ${k}" for k in fields)
        rows = await run_write(
            f"MATCH (l:Lesson {{id: $id}}) SET {sets} RETURN l.id AS id",
            id=lid, **fields)
        if not rows:
            raise HTTPException(404, "no such lesson")
    if about_id != "__unset__":
        await _link_about(lid, about_id or "")
    if same_as != "__unset__":
        await _mark_same(lid, same_as or "")
    await record("lesson", "updated", detail=", ".join(fields) or "links", entity_id=lid)
    return await _one(lid)


@router.delete("/{lid}", status_code=204, response_class=Response)
async def delete_lesson(lid: str) -> Response:
    # The entries go with it. They only mean anything next to their lesson, so
    # leaving them behind would just accumulate rows nothing can reach.
    # Its instances: ones typed here go too; ones logged from a reading session
    # are that session's record, so they drop back into the distractions tally.
    await run_write(
        "MATCH (later:Lesson)-[r:SAME_AS]->(:Lesson {id: $id}) "
        "WHERE later.source = 'distraction' DELETE r SET later.repeated = false",
        id=lid)
    await run_write(
        "MATCH (later:Lesson)-[:SAME_AS]->(:Lesson {id: $id}) "
        "OPTIONAL MATCH (later)-[:HAS_ENTRY]->(e:LessonEntry) "
        "DETACH DELETE e, later", id=lid)
    await run_write(
        "MATCH (l:Lesson {id: $id}) "
        "OPTIONAL MATCH (l)-[:HAS_ENTRY]->(e:LessonEntry) "
        "DETACH DELETE e, l", id=lid)
    await record("lesson", "deleted", detail=lid)
    return Response(status_code=204)


@router.get("/repeated-since/{since}")
async def repeated_since(since: str) -> dict:
    """Lessons marked repeated on or after a date. What the phase score's
    mistakes part reads: 25 if this is empty for the week, 0 if it is not."""
    rows = await run_read(
        """
        MATCH (l:Lesson) WHERE coalesce(l.repeated, false) AND l.date >= $since
        OPTIONAL MATCH (l)-[:SAME_AS]->(s:Lesson)
        RETURN l{.id, .date, .wrong, .group} AS lesson, s.date AS first_time
        ORDER BY l.date DESC
        """, since=since)
    out = [{**dict(r["lesson"]), "first_time": r["first_time"] or ""} for r in rows]
    return {"since": since, "count": len(out), "clean": not out, "lessons": out}


async def _link_about(lid: str, about_id: str) -> None:
    """Attach a lesson to the thing it happened to, or to nothing.

    The id is looked up through the shared indexed lookup rather than an
    unlabelled match, which would scan the whole database.
    """
    await run_write("MATCH (l:Lesson {id: $id})-[r:ABOUT]->() DELETE r", id=lid)
    if not about_id:
        return
    await run_write(
        f"""
        MATCH (l:Lesson {{id: $id}})
        UNWIND [$about] AS lid
        CALL (lid) {{ {_entity_lookup()} }}
        MERGE (l)-[:ABOUT]->(e)
        """, id=lid, about=about_id)


async def _mark_same(lid: str, earlier_id: str) -> None:
    """Say this lesson is the same mistake as an earlier one.

    This is the only thing that sets `repeated`, and it sets it on the LATER
    lesson: the first time was not a repeat, and marking it as one would make
    the score punish you for the mistake you learned from.
    """
    await run_write(
        "MATCH (l:Lesson {id: $id})-[r:SAME_AS]->() DELETE r "
        "SET l.repeated = false", id=lid)
    if not earlier_id or earlier_id == lid:
        return
    rows = await run_write(
        "MATCH (l:Lesson {id: $id}), (s:Lesson {id: $sid}) "
        "MERGE (l)-[:SAME_AS]->(s) SET l.repeated = true RETURN l.id AS id",
        id=lid, sid=earlier_id)
    if not rows:
        raise HTTPException(404, "no such earlier lesson")


async def _one(lid: str) -> dict:
    rows = await run_read(_ROWS.replace("$$WHERE$$", "l.id = $lid"), lid=lid)
    if not rows:
        raise HTTPException(404, "no such lesson")
    return _shape(rows[0])


# --------------------------------------------------------------------------- #
# Entries — the suggestions and notes hanging off one lesson
# --------------------------------------------------------------------------- #
#
#     (:Lesson)-[:HAS_ENTRY]->(:LessonEntry {id, kind, text, created_at})
#
# WHY NOT :Note. The generic note store is append-only on purpose: a reason you
# gave in September and revised in November is two facts, not one overwritten
# one. These are not that. A suggestion is a working list you add to, reword and
# throw away while you are still deciding, and forcing every reword into a
# SUPERSEDES chain would bury the four ideas you are choosing between under
# twenty superseded drafts of them.
#
# ONE SHAPE, TWO BOXES. `kind` is the label of the box it was typed into, so
# "suggestion" and "note" are the same node with a different word on it. That is
# what lets one component on the client drive both, and a third later without
# any new table.
#
# THE API MIRRORS /api/questions deliberately — same verbs, same parent_id and
# kind parameters — because the same list box on the client talks to both.


def _entry_shape(r: dict) -> dict:
    e = dict(r["e"])
    e["kind"] = e.get("kind") or "note"
    return e


@router.get("/entries")
async def list_entries(parent_id: str, kind: str | None = None) -> list[dict]:
    """The entries on one lesson. `parent_id` is required: an entry only ever
    means something next to the lesson it belongs to."""
    where = ["true"]
    params: dict = {"pid": parent_id}
    if kind:
        where.append("coalesce(e.kind, 'note') = $kind")
        params["kind"] = kind
    rows = await run_read(
        "MATCH (:Lesson {id: $pid})-[:HAS_ENTRY]->(e:LessonEntry) "
        "WHERE " + " AND ".join(where) + " "
        "RETURN e{.*} AS e ORDER BY e.created_at ASC", **params)
    return [_entry_shape(r) for r in rows]


@router.post("/entries", status_code=201)
async def add_entry(body: LessonEntryCreate) -> dict:
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "an entry with no words in it is not an entry")
    if not body.parent_id:
        raise HTTPException(400, "say which lesson this is on")
    eid = str(uuid.uuid4())
    rows = await run_write(
        """
        MATCH (l:Lesson {id: $pid})
        CREATE (e:LessonEntry {id: $id, kind: $kind, text: $text, created_at: $now})
        CREATE (l)-[:HAS_ENTRY]->(e)
        RETURN e{.*} AS e
        """, pid=body.parent_id, id=eid,
        kind=(body.kind or "note").strip() or "note", text=text, now=_now())
    if not rows:
        raise HTTPException(404, "no such lesson")
    await record("lesson", (body.kind or "note") + " added", detail=text[:70],
                 entity_id=body.parent_id)
    return _entry_shape(rows[0])


@router.patch("/entries/{eid}")
async def update_entry(eid: str, body: LessonEntryUpdate) -> dict:
    fields = body.model_dump(exclude_unset=True)
    if "text" in fields:
        fields["text"] = (fields["text"] or "").strip()
        if not fields["text"]:
            raise HTTPException(400, "an entry with no words in it is not an entry")
    if "outcome" in fields:
        fields["outcome"] = (fields["outcome"] or "").strip()
    if not fields:
        raise HTTPException(400, "nothing to change")
    # When a solution was tried is the date its status last changed.
    if "status" in fields:
        fields["tried_at"] = date.today().isoformat() if fields["status"] else ""
    sets = ", ".join(f"e.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (e:LessonEntry {{id: $id}}) SET {sets} RETURN e{{.*}} AS e",
        id=eid, **fields)
    if not rows:
        raise HTTPException(404, "no such entry")
    return _entry_shape(rows[0])


@router.delete("/entries/{eid}", status_code=204, response_class=Response)
async def delete_entry(eid: str) -> Response:
    await run_write("MATCH (e:LessonEntry {id: $id}) DETACH DELETE e", id=eid)
    return Response(status_code=204)



async def log_distraction_as_lesson(text: str, instance_id: str = "",
                                    where: str = "", skip: set[str] | None = None,
                                    when: str | None = None) -> str:
    """File one interruption from a reading pass as a lesson. Returns the group
    it went under, or "" when this pass has already filed that group.

    THIS REPLACED THE WRITE INTO LEARNING. A distraction is a small instance of
    exactly what a lesson records: something that went wrong, and something you
    would do instead. Splitting them across two stores meant the mistakes you
    noticed while reading never sat next to the ones you noticed anywhere else.

    ATTACHED TO THE PASS. (:Lesson)-[:ABOUT]->(:Instance) rather than a sentence
    naming it, so the pass can show what interrupted it and a lesson can say
    which read it came out of. `where` stays in the text for readability.

    GROUPING still borrows Learning's kind matcher, which is the part worth
    keeping: it folds "phone", "my phone" and "phone kept buzzing" into one
    group instead of three that never repeat.
    """
    from routes.learning import match_kind

    text = (text or "").strip()
    if not text:
        return ""
    group = await match_kind(text)
    if not group or (skip and group in skip):
        return ""

    lid = str(uuid.uuid4())
    wrong = f"distracted by {text}"
    if where:
        wrong = f"{wrong} {where}"
    await run_write(
        """
        CREATE (l:Lesson {id: $id, date: $date, wrong: $wrong, instead: '',
                          group: '', repeated: false, created_at: $now,
                          source: 'distraction', pattern: $pattern})
        """, id=lid, date=(when or date.today().isoformat())[:10],
        wrong=wrong[:200], pattern=group, now=_now())
    await run_write("MERGE (:LearningKind {name: $n})", n=group)
    if instance_id:
        await run_write(
            "MATCH (l:Lesson {id: $id}), (i) WHERE i.id = $iid "
            "MERGE (l)-[:ABOUT]->(i)", id=lid, iid=instance_id)
    await _attach_to_pattern_root(lid, group)
    await record("lesson", "distraction logged", detail=group[:70],
                 module="synapse", trigger="system", entity_id=lid)
    return group


# --------------------------------------------------------------------------- #
# v2 — the board, instances, promoting a pattern, merging
# --------------------------------------------------------------------------- #

async def _attach_to_pattern_root(lid: str, pattern: str) -> None:
    """A distraction whose pattern has already been made into a lesson is an
    instance of that lesson. The pattern matcher already decided it is the
    same interruption; asking you to say so again would just leave gaps."""
    rows = await run_read(
        """
        MATCH (r:Lesson {pattern: $p})
        WHERE coalesce(r.source, '') <> 'distraction' AND r.id <> $id
          AND NOT (r)-[:SAME_AS]->(:Lesson)
        RETURN r.id AS id ORDER BY r.date ASC LIMIT 1
        """, p=pattern, id=lid)
    if rows:
        await _mark_same(lid, rows[0]["id"])


async def _phase_start() -> str:
    """Start of the active phase, or a fortnight ago when you are between
    phases, so "this phase" always means something."""
    from routes.phases import _active_id  # phases imports this module
    pid = await _active_id()
    if pid:
        rows = await run_read("MATCH (p:Phase {id: $id}) RETURN p.start AS s", id=pid)
        if rows and rows[0]["s"]:
            return str(rows[0]["s"])[:10]
    return (date.today() - timedelta(days=14)).isoformat()


@router.get("/board")
async def board() -> dict:
    """Everything the Lessons tab draws, in the shape it draws it: one row per
    mistake with its instances, solutions and notes; the categories with
    counts; and the distraction tally."""
    since = await _phase_start()
    rows = await run_read(
        f"""
        MATCH (l:Lesson)
        OPTIONAL MATCH (l)-[:SAME_AS]->(s:Lesson)
        OPTIONAL MATCH (l)-[:ABOUT]->(x)
        OPTIONAL MATCH (pp:Paper)-[:HAS_INSTANCE]->(x)
        RETURN l{{.*}} AS l, s.id AS same_id, x.id AS about_id,
               CASE WHEN x IS NULL THEN ''
                    // a reading pass has no title of its own: name the paper
                    WHEN pp IS NOT NULL THEN pp.title + ' v' + toString(x.version)
                    ELSE {_TITLE} END AS about_title
        """)
    ents = await run_read(
        "MATCH (l:Lesson)-[:HAS_ENTRY]->(e:LessonEntry) "
        "RETURN l.id AS lid, e{.*} AS e ORDER BY e.created_at ASC")
    groups = await list_groups()

    by_id: dict[str, dict] = {}
    for r in rows:
        l = dict(r["l"])
        for k in ("wrong", "instead", "group", "detail", "pattern", "source", "status", "date"):
            l[k] = l.get(k) or ""
        l["same_as"] = r["same_id"] or ""
        l["about"] = ({"id": r["about_id"], "title": r["about_title"]}
                      if r["about_id"] else None)
        by_id[l["id"]] = l

    def root_of(l: dict) -> dict:
        seen = set()
        while l["same_as"] and l["same_as"] in by_id and l["id"] not in seen:
            seen.add(l["id"])
            l = by_id[l["same_as"]]
        return l

    roots: dict[str, dict] = {}
    for l in by_id.values():
        if not l["same_as"] and l["source"] != "distraction":
            roots[l["id"]] = {**l, "instances": [], "solutions": [], "notes": []}
    for l in by_id.values():
        r = root_of(l)
        if r["id"] in roots:
            roots[r["id"]]["instances"].append({
                "id": l["id"], "date": l["date"], "first": l["id"] == r["id"],
                "text": l["detail"] or (l["wrong"] if l["id"] != r["id"] else ""),
                "source": l["source"], "about": l["about"],
                "created_at": l.get("created_at") or ""})
    for e in ents:
        r = roots.get(e["lid"])
        if not r:
            continue
        e = _entry_shape(e)
        e["status"] = e.get("status") or ""
        e["outcome"] = e.get("outcome") or ""
        e["tried_at"] = e.get("tried_at") or ""
        (r["solutions"] if e["kind"] == "suggestion" else r["notes"]).append(e)

    lessons = []
    for r in roots.values():
        inst = sorted(r["instances"], key=lambda i: (i["date"], i["created_at"]), reverse=True)
        r["instances"] = inst
        r["times"] = len(inst)
        r["last"] = inst[0]["date"] if inst else r["date"]
        r["repeats_this_phase"] = sum(1 for i in inst if not i["first"] and i["date"] >= since)
        # Solved is yours to say. "Trying" follows from having tried something.
        r["state"] = (r["status"] if r["status"] == "solved" else
                      "trying" if r["status"] == "trying" or any(s["status"] for s in r["solutions"])
                      else "")
        lessons.append(r)
    lessons.sort(key=lambda r: (r["date"], r.get("created_at") or ""), reverse=True)

    # Tally: every distraction row, by pattern, and which lesson (if any) it became.
    tally: dict[str, dict] = {}
    for l in by_id.values():
        if not l["pattern"]:
            continue
        t = tally.setdefault(l["pattern"], {"pattern": l["pattern"], "times": 0,
                                            "last": "", "while": [], "lesson_id": "",
                                            "loose": []})
        t["times"] += 1
        t["last"] = max(t["last"], l["date"])
        if l["about"] and l["about"]["title"] not in t["while"]:
            t["while"].append(l["about"]["title"])
        r = root_of(l)
        if r["id"] in roots:
            t["lesson_id"] = r["id"]
        else:
            t["loose"].append({"id": l["id"], "date": l["date"], "wrong": l["wrong"]})
    tally_rows = sorted(tally.values(), key=lambda t: (t["last"], t["times"]), reverse=True)

    names = {g["name"] for g in groups}
    cats = []
    for g in groups + ([{"name": "", "color": "#7FA8C8", "note": "no category"}]
                       if any(not r["group"] or r["group"] not in names for r in lessons) else []):
        mine = [r for r in lessons if (r["group"] == g["name"]) or
                (not g["name"] and (not r["group"] or r["group"] not in names))]
        cats.append({**g, "count": len(mine),
                     "repeated": sum(1 for r in mine if r["repeats_this_phase"])})

    return {"since": since, "lessons": lessons, "categories": cats, "tally": tally_rows}


@router.post("/{lid}/instances", status_code=201)
async def add_instance(lid: str, body: LessonInstanceCreate) -> dict:
    """It happened again. Writes a later :Lesson marked SAME_AS this one, which
    is what makes it a repeat for the phase score; or, with `from_id`, marks an
    existing distraction row as this mistake."""
    if body.from_id:
        await _mark_same(body.from_id, lid)
        await record("lesson", "instance marked same", detail=body.from_id, entity_id=lid)
        return {"id": body.from_id}
    if not body.detail.strip():
        raise HTTPException(400, "say what happened this time")
    rows = await run_read("MATCH (l:Lesson {id: $id}) RETURN l.wrong AS w, l.group AS g",
                          id=lid)
    if not rows:
        raise HTTPException(404, "no such lesson")
    iid = str(uuid.uuid4())
    await run_write(
        """
        CREATE (l:Lesson {id: $id, date: $date, wrong: $wrong, instead: '',
                          group: $group, repeated: false, created_at: $now,
                          detail: $detail, source: 'instance'})
        """, id=iid, date=body.date or date.today().isoformat(), wrong=rows[0]["w"],
        group=rows[0]["g"] or "", now=_now(), detail=body.detail.strip())
    await _mark_same(iid, lid)
    await record("lesson", "happened again", detail=body.detail.strip()[:70], entity_id=lid)
    return {"id": iid}


@router.post("/promote", status_code=201)
async def promote(body: LessonPromote) -> dict:
    """Make a distraction pattern into a lesson. The earliest loose row becomes
    the lesson (the first time is not a repeat) and every later one becomes an
    instance of it; distractions logged later with this pattern join it too."""
    pattern = body.pattern.strip()
    rows = await run_read(
        """
        MATCH (l:Lesson {pattern: $p, source: 'distraction'})
        WHERE NOT (l)-[:SAME_AS]->(:Lesson)
        RETURN l.id AS id, l.wrong AS wrong ORDER BY l.date ASC, l.created_at ASC
        """, p=pattern)
    if not rows:
        raise HTTPException(404, "no loose distractions with that pattern")
    root = rows[0]["id"]
    await run_write(
        """
        MATCH (l:Lesson {id: $id})
        SET l.source = '', l.detail = l.wrong, l.wrong = $wrong, l.group = $group
        """, id=root, wrong=(body.wrong.strip() or pattern), group=body.group)
    for r in rows[1:]:
        await _mark_same(r["id"], root)
    await record("lesson", "made from distractions", detail=pattern[:70], entity_id=root)
    return {"id": root, "instances": len(rows)}


@router.post("/{lid}/merge")
async def merge(lid: str, body: LessonMerge) -> dict:
    """Fold this lesson into another: it, its instances, solutions and notes all
    move under `into`. Every moved row becomes a repeat of that lesson."""
    if body.into == lid:
        raise HTTPException(400, "a lesson cannot merge into itself")
    ok = await run_read("MATCH (l:Lesson {id: $a}), (t:Lesson {id: $b}) RETURN t.id AS id",
                        a=lid, b=body.into)
    if not ok:
        raise HTTPException(404, "no such lesson")
    await run_write(
        """
        MATCH (later:Lesson)-[r:SAME_AS]->(:Lesson {id: $a}), (t:Lesson {id: $b})
        DELETE r MERGE (later)-[:SAME_AS]->(t) SET later.repeated = true
        """, a=lid, b=body.into)
    await run_write(
        """
        MATCH (:Lesson {id: $a})-[r:HAS_ENTRY]->(e:LessonEntry), (t:Lesson {id: $b})
        DELETE r CREATE (t)-[:HAS_ENTRY]->(e)
        """, a=lid, b=body.into)
    # The merged lesson's own wording survives as the instance's text.
    await run_write(
        "MATCH (l:Lesson {id: $a}) SET l.detail = CASE WHEN coalesce(l.detail, '') = '' "
        "THEN l.wrong ELSE l.detail END", a=lid)
    await _mark_same(lid, body.into)
    await record("lesson", "merged", detail=lid, entity_id=body.into)
    return {"id": body.into}

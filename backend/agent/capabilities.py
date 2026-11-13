"""The assistant's capability registry — a curated grip on the whole Mainframe.

Why not just expose the routes
------------------------------
The app has **421 routes**. Handing a 7B model 421 tools does not produce a
capable assistant, it produces a confused one: the tool list alone would fill
the context, and choosing between `PUT /vault/transactions/{id}` and
`PATCH /tasks/{id}` is not a decision worth asking a language model to make.

So this file is a deliberate, hand-written layer *over* the routes:

  * **Few, broad, verb-shaped tools.** "log time on a task", not six task
    endpoints. Each maps to whatever routes it needs.
  * **Every tool declares `kind`** — `read`, `write` or `delete`. That single
    field drives the safety model: reads run immediately, writes are proposed
    and wait for a human yes. A misheard command can never silently change data.
  * **Fuzzy references are resolved here, not by the model.** The user says "the
    website task"; the model passes that string through, and `_find_task`
    matches it against real rows. The model never invents an id.

Dates
-----
**The model is not allowed to compute dates.** Asked what's on tomorrow, the
local model confidently answered `2023-10-05` — it has no idea what day it is.
Every date parameter therefore accepts natural tokens ("today", "tomorrow",
"friday", "+3d") and is resolved by `resolve_date()` against the server's clock.
Today's date is also injected into the system prompt, but resolution is what
actually guarantees correctness.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from db import run_read, run_write

# --------------------------------------------------------------------------- #
# Dates — resolved here, never by the model
# --------------------------------------------------------------------------- #
_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}


def resolve_date(value: str | None, default_today: bool = True) -> str:
    """Turn whatever the model said into a real YYYY-MM-DD.

    Accepts ISO dates, 'today'/'tomorrow'/'yesterday', weekday names (meaning
    the NEXT one), and offsets like '+3d' / '-2d'. Anything unrecognised falls
    back to today rather than raising: a slightly wrong day is recoverable, a
    500 in the middle of a spoken sentence is not.
    """
    today = date.today()
    if not value:
        return today.isoformat() if default_today else ""
    v = str(value).strip().lower()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        return v
    if v in ("today", "now", "tonight", "this evening"):
        return today.isoformat()
    if v == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if v == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    m = re.fullmatch(r"([+-])\s*(\d+)\s*d(ays?)?", v)
    if m:
        n = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
        return (today + timedelta(days=n)).isoformat()
    for name, idx in _WEEKDAYS.items():
        if name in v:
            ahead = (idx - today.weekday()) % 7 or 7      # always the NEXT one
            if "last" in v:
                return (today - timedelta(days=(today.weekday() - idx) % 7 or 7)).isoformat()
            return (today + timedelta(days=ahead)).isoformat()
    if "next week" in v:
        return (today + timedelta(days=7)).isoformat()
    return today.isoformat() if default_today else ""


def _clock(value: str) -> str:
    """'6pm', '18:00', '6.30pm', '0900' -> 'HH:MM'. Empty if it isn't a time."""
    s = str(value or "").strip().lower().replace(".", ":")
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", s)
    if not m:
        m2 = re.fullmatch(r"(\d{2})(\d{2})", s)          # "0900"
        if not m2:
            return ""
        h, mi = int(m2.group(1)), int(m2.group(2))
        return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else ""
    h = int(m.group(1))
    mi = int(m.group(2) or 0)
    ampm = m.group(3)
    if ampm == "pm" and h < 12:
        h += 12
    if ampm == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else ""


def _normalise_times(start: str, end: str) -> tuple[str, str]:
    """Repair what a small model commonly gets wrong about times.

    Asked to put a gym session in "tomorrow at 6pm", qwen2.5 filled `end` and
    left `start` empty — which made an all-day event while the confirmation text
    still read "at 18:00". One stated time means a START. Also gives a lone
    start a one-hour default end, since a zero-length block is not a plan.
    """
    s, e = _clock(start), _clock(end)
    if not s and e:
        s, e = e, ""
    # A lone start, or an end that isn't after it, both mean "no duration was
    # given". The model has produced start==end ("from 6 PM to 6 PM") as well as
    # end-only, so both are repaired the same way rather than stored as a
    # zero-length block, which is not a plan.
    if s and (not e or e <= s):
        h, mi = int(s[:2]), int(s[3:])
        e = f"{(h + 1) % 24:02d}:{mi:02d}"
    return s, e


def _mins_from(value) -> int:
    """'45', '45 minutes', '1h30', '2 hours' -> minutes."""
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value or "").lower().strip()
    h = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hour)", s)
    m = re.search(r"(\d+)\s*(?:m|min)", s)
    total = 0
    if h:
        total += int(float(h.group(1)) * 60)
    if m:
        total += int(m.group(1))
    if total:
        return total
    digits = re.search(r"\d+", s)
    return int(digits.group()) if digits else 0


# --------------------------------------------------------------------------- #
# Fuzzy lookup — the model passes words, this finds the row
# --------------------------------------------------------------------------- #
# Words people add when referring to a thing, which are never part of its name.
# "the linkedin task" must find "Post on Linkedin".
_NOISE = {"task", "tasks", "the", "my", "a", "an", "on", "for", "about", "thing",
          "item", "one", "please", "that", "this", "it"}


def _keywords(query: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    keep = [w for w in words if w not in _NOISE and len(w) > 2]
    return keep or words          # if it was ALL noise, fall back to the raw words


async def _find_task(query: str) -> dict | None:
    """Find the task the user meant.

    A plain `CONTAINS` on the whole phrase fails constantly in practice: the
    model passes "the linkedIn task" and the row is called "Post on Linkedin".
    So the phrase is reduced to keywords and rows are ranked by how many of
    them they match — the same trick a search box uses.
    """
    if not query:
        return None
    words = _keywords(query)
    if not words:
        return None
    rows = await run_read(
        """
        MATCH (t:Task)
        WITH t, [w IN $words WHERE toLower(t.title) CONTAINS w] AS hits
        WHERE size(hits) > 0
        RETURN t{.id, .title, .status, .due_date, .module} AS t, size(hits) AS score
        ORDER BY score DESC,
                 CASE WHEN coalesce(t.status,'') = 'done' THEN 1 ELSE 0 END,
                 t.created_at DESC
        LIMIT 1
        """,
        words=words,
    )
    return rows[0]["t"] if rows else None


async def _find_food(query: str) -> dict | None:
    words = _keywords(query)
    if not words:
        return None
    rows = await run_read(
        """
        MATCH (f:Food)
        WITH f, [w IN $words WHERE toLower(f.name) CONTAINS w] AS hits
        WHERE size(hits) > 0
        RETURN f{.*} AS f, size(hits) AS score
        ORDER BY score DESC, coalesce(f.use_count,0) DESC LIMIT 1
        """,
        words=words,
    )
    return rows[0]["f"] if rows else None


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
CAPS: list[dict] = []


def cap(name: str, kind: str, description: str, params: dict, required: list[str] | None = None):
    """Register one capability. `kind` drives the safety model, so it is required."""
    assert kind in ("read", "write", "delete")

    def deco(fn):
        CAPS.append({
            "name": name, "kind": kind, "description": description,
            "params": params, "required": required or [], "fn": fn,
        })
        return fn
    return deco


def tool_schemas() -> list[dict]:
    """The registry in the shape Ollama's tool-calling API expects."""
    return [{
        "type": "function",
        "function": {
            "name": c["name"],
            # The kind is stated in the description too, so the model knows a
            # write will be shown to a human before it happens.
            "description": c["description"] + (
                "" if c["kind"] == "read" else "  (CHANGES DATA — will be confirmed by the user)"),
            "parameters": {"type": "object", "properties": c["params"],
                           "required": c["required"]},
        },
    } for c in CAPS]


def find(name: str) -> dict | None:
    return next((c for c in CAPS if c["name"] == name), None)


DATE_P = {"type": "string", "description": "A date: YYYY-MM-DD, or 'today' / 'tomorrow' / "
                                           "'friday' / '+3d'. Never guess — pass the user's words."}

# ============================== CALENDAR ==================================== #
@cap("calendar_day", "read", "What is scheduled on a given day: events, tasks due, and what was logged.",
     {"date": DATE_P})
async def _calendar_day(date: str = "today", **_):
    from routes.calendar import range_feed
    d = resolve_date(date)
    feed = await range_feed(from_=d, to=d)
    return {
        "date": d,
        "events": [{"title": e["title"], "start": e.get("start") or "all day",
                    "end": e.get("end", ""), "source": e.get("source")} for e in feed["events"]],
        "tasks_due": [t["title"] for t in feed["due"]],
        "logged": [f'{l["kind"]}: {l.get("label","")}' for l in feed["logged"]],
        "work_sessions": len(feed["work"]),
    }


@cap("calendar_week", "read", "An overview of the next N days — what's on and what's due.",
     {"start": DATE_P, "days": {"type": "integer", "description": "How many days, default 7"}})
async def _calendar_week(start: str = "today", days: int = 7, **_):
    from routes.calendar import range_feed
    s = resolve_date(start)
    e = (date.fromisoformat(s) + timedelta(days=max(1, min(int(days or 7), 31)) - 1)).isoformat()
    feed = await range_feed(from_=s, to=e)
    by_day: dict[str, list[str]] = {}
    for ev in feed["events"]:
        by_day.setdefault(ev["date"], []).append(f'{ev.get("start") or "all day"} {ev["title"]}')
    for t in feed["due"]:
        by_day.setdefault(t["due_date"], []).append(f'DUE: {t["title"]}')
    return {"from": s, "to": e, "days": by_day or "nothing scheduled"}


@cap("calendar_free_time", "read", "Find free gaps in a day, and how much time is already booked.",
     {"date": DATE_P})
async def _calendar_free(date: str = "today", **_):
    from routes.calendar import freebusy
    return await freebusy(date_=resolve_date(date))


@cap("calendar_suggestions", "read",
     "The assistant's own analysis: clashes, overdue work, things due with no time set aside, free blocks.",
     {})
async def _calendar_sug(**_):
    from routes.calendar import suggestions
    out = await suggestions()
    return [{"severity": s["severity"], "what": s["title"], "why": s["why"]} for s in out]


@cap("calendar_create_event", "write",
     "Put something in the calendar. Can be tied to a task, which turns it into planned work.",
     {"title": {"type": "string"}, "date": DATE_P,
      "start": {"type": "string", "description": "HH:MM 24-hour, e.g. 14:30. Omit for all-day."},
      "end": {"type": "string", "description": "HH:MM 24-hour"},
      "task_query": {"type": "string", "description": "Words matching a task this block is for"},
      "location": {"type": "string"}, "notes": {"type": "string"}},
     ["title"])
async def _cal_create(title: str, date: str = "today", start: str = "", end: str = "",
                      task_query: str = "", location: str = "", notes: str = "", **_):
    from models import CalEventCreate
    from routes.calendar import create_event
    start, end = _normalise_times(start, end)
    task = await _find_task(task_query) if task_query else None
    ev = await create_event(CalEventCreate(
        title=title, date=resolve_date(date), start=start, end=end,
        all_day=not start, location=location or "", notes=notes or "",
        kind="block" if task else "event", task_id=task["id"] if task else None))
    return {"created": ev["title"], "date": ev["date"],
            "time": f'{ev.get("start","")}–{ev.get("end","")}'.strip("–") or "all day",
            "linked_task": task["title"] if task else None}


# ================================ TASKS ===================================== #
@cap("tasks_list", "read", "List tasks — open ones by default, optionally only those due soon.",
     {"status": {"type": "string", "description": "'open' (default) or 'done'"},
      "due_within_days": {"type": "integer", "description": "Only tasks due within N days"}})
async def _tasks_list(status: str = "open", due_within_days: int = 0, **_):
    clauses = ["coalesce(t.status,'') <> 'hidden'"]
    params: dict = {}
    if status == "done":
        clauses.append("(t.status = 'done' OR t.done_at IS NOT NULL)")
    else:
        clauses.append("coalesce(t.status,'') <> 'done' AND t.done_at IS NULL")
    if due_within_days:
        params["cut"] = (date.today() + timedelta(days=int(due_within_days))).isoformat()
        clauses.append("t.due_date IS NOT NULL AND t.due_date <= $cut")
    rows = await run_read(
        f"MATCH (t:Task) WHERE {' AND '.join(clauses)} "
        "RETURN t{.title, .due_date, .priority, .horizon, .module, .status} AS t "
        "ORDER BY coalesce(t.due_date,'9999'), t.created_at DESC LIMIT 40", **params)
    return [r["t"] for r in rows] or "no matching tasks"


@cap("task_create", "write", "Create a new task.",
     {"title": {"type": "string"}, "due": DATE_P,
      "horizon": {"type": "string", "description": "short, medium or long"},
      "module": {"type": "string", "description": "synapse, pulse, vision or vault"},
      "priority": {"type": "string", "description": "low, medium or high"},
      "notes": {"type": "string"}},
     ["title"])
async def _task_create(title: str, due: str = "", horizon: str = "short",
                       module: str = "synapse", priority: str = "medium", notes: str = "", **_):
    from models import TaskCreate
    from routes.tasks import create_task
    d = resolve_date(due, default_today=False) if due else None
    t = await create_task(TaskCreate(
        title=title, horizon=horizon if horizon in ("short", "medium", "long") else "short",
        module=module if module in ("synapse", "pulse", "vision", "vault") else "synapse",
        priority=priority if priority in ("low", "medium", "high") else "medium",
        due_date=d or None, notes=notes or None))
    return {"created_task": t.get("title"), "due": t.get("due_date")}


@cap("task_log_time", "write", "Record time spent working on a task.",
     {"task_query": {"type": "string", "description": "Words from the task's title"},
      "minutes": {"type": "integer"}, "date": DATE_P,
      "notes": {"type": "string", "description": "What was actually done"}},
     ["task_query", "minutes"])
async def _task_log(task_query: str, minutes, date: str = "today", notes: str = "", **_):
    from models import TaskEntryCreate
    from routes.tasks import add_entry
    t = await _find_task(task_query)
    if not t:
        return {"error": f"No task matches “{task_query}”. Nothing was logged."}
    mins = _mins_from(minutes)
    # "progress" is the journal entry type for time spent — TaskEntryCreate's
    # `type` is a closed Literal, and "work" is not one of its values.
    await add_entry(t["id"], TaskEntryCreate(
        type="progress", date=resolve_date(date), time_spent_mins=mins, notes=notes or ""))
    return {"logged_to": t["title"], "minutes": mins, "date": resolve_date(date)}


@cap("task_complete", "write", "Mark a task as done.",
     {"task_query": {"type": "string"}}, ["task_query"])
async def _task_done(task_query: str, **_):
    t = await _find_task(task_query)
    if not t:
        return {"error": f"No task matches “{task_query}”."}
    await run_write("MATCH (t:Task {id:$id}) SET t.status='done', t.done_at=$ts",
                    id=t["id"], ts=datetime.now().isoformat(timespec="seconds"))
    return {"completed": t["title"]}


# ================================= WORK ===================================== #
@cap("work_log", "write", "Log a block of work in the work database (not tied to a specific task).",
     {"what": {"type": "string", "description": "What you did"},
      "minutes": {"type": "integer"}, "date": DATE_P,
      "module": {"type": "string", "description": "synapse, pulse, vision or vault"}},
     ["what"])
async def _work_log(what: str, minutes=0, date: str = "today", module: str = "synapse", **_):
    from models import WorkSessionCreate
    from routes.work import create_session
    s = await create_session(WorkSessionCreate(
        date=resolve_date(date), mins=_mins_from(minutes), what=what,
        module=module if module in ("synapse", "pulse", "vision", "vault") else "synapse"))
    return {"logged": what, "minutes": s.get("mins"), "date": s.get("date")}


# ============================== NUTRITION =================================== #
@cap("food_search", "read",
     "Search the 4-million-food catalogue (USDA, Open Food Facts, UK CoFID) for nutrition figures.",
     {"query": {"type": "string"}}, ["query"])
async def _food_search(query: str, **_):
    from routes.nutrition import search_catalog
    rows = await search_catalog(q=query, limit=5)
    return [{"name": f["name"], "brand": f.get("brand", ""), "per_100g": {
        "calories": f.get("calories"), "protein": f.get("protein"),
        "carbs": f.get("carbs"), "fat": f.get("fat")}, "source": f.get("source_label")}
        for f in rows] or "nothing found"


@cap("food_log", "write", "Log something eaten, from your own food library.",
     {"food_query": {"type": "string"}, "servings": {"type": "number"},
      "meal": {"type": "string", "description": "breakfast, lunch, dinner or snacks"},
      "date": DATE_P},
     ["food_query"])
async def _food_log(food_query: str, servings: float = 1, meal: str = "snacks",
                    date: str = "today", **_):
    from models import FoodEntryCreate
    from routes.nutrition import add_entry as add_food_entry
    f = await _find_food(food_query)
    if not f:
        return {"error": f"“{food_query}” isn't in your food library yet. "
                         "Search the food database and add it first."}
    n = float(servings or 1)
    e = await add_food_entry(FoodEntryCreate(
        food_id=f["id"], food_name=f["name"], date=resolve_date(date),
        meal_slot=meal if meal in ("breakfast", "lunch", "dinner", "snacks") else "snacks",
        serving_size=n, calories=(f.get("calories") or 0) * n,
        protein=(f.get("protein") or 0) * n, carbs=(f.get("carbs") or 0) * n,
        fat=(f.get("fat") or 0) * n))
    return {"logged": f["name"], "servings": n, "calories": e.get("calories")}


@cap("nutrition_today", "read", "Today's calories and macros against target, water and weight.",
     {"date": DATE_P})
async def _nutrition_today(date: str = "today", **_):
    from routes.nutrition import dashboard
    d = await dashboard(date_=resolve_date(date))
    return {"date": d["date"], "calories": d["totals"].get("calories"),
            "target": d["goals"].get("daily_calories"), "remaining": d["remaining"].get("calories"),
            "protein": d["totals"].get("protein"), "water_ml": d["water"]["total_ml"],
            "entries": d["entry_count"], "streak_days": d["streak_days"]}


@cap("water_add", "write", "Record drinking water.",
     {"ml": {"type": "integer", "description": "Millilitres"}, "date": DATE_P}, ["ml"])
async def _water(ml: int, date: str = "today", **_):
    from models import WaterCreate
    from routes.nutrition import add_water
    r = await add_water(WaterCreate(date=resolve_date(date), amount=float(ml)))
    return {"added_ml": int(ml), "total_today": r.get("total_ml") if isinstance(r, dict) else None}


@cap("weight_log", "write", "Record a body-weight reading.",
     {"kg": {"type": "number"}, "date": DATE_P}, ["kg"])
async def _weight(kg: float, date: str = "today", **_):
    from models import WeightCreate
    from routes.nutrition import add_weight
    await add_weight(WeightCreate(date=resolve_date(date), weight=float(kg)))
    return {"logged_kg": float(kg), "date": resolve_date(date)}


# ================================ PULSE ===================================== #
@cap("habits_today", "read", "Which habits are done today and which are still outstanding.", {})
async def _habits_today(**_):
    today = date.today().isoformat()
    rows = await run_read(
        """
        MATCH (h:Habit) WHERE coalesce(h.archived,false) = false
        OPTIONAL MATCH (h)-[:HAS_LOG]->(l:HabitLog {date:$d})
        RETURN h.name AS habit, count(l) > 0 AS done ORDER BY habit
        """, d=today)
    return {"date": today, "habits": [{"habit": r["habit"], "done": r["done"]} for r in rows]
            or "no habits set up"}


@cap("habit_log", "write", "Tick off a habit for a day.",
     {"habit_query": {"type": "string"}, "date": DATE_P, "notes": {"type": "string"}},
     ["habit_query"])
async def _habit_log(habit_query: str, date: str = "today", notes: str = "", **_):
    import uuid
    rows = await run_read("MATCH (h:Habit) WHERE toLower(h.name) CONTAINS toLower($q) "
                          "RETURN h{.id,.name} AS h LIMIT 1", q=habit_query)
    if not rows:
        return {"error": f"No habit matches “{habit_query}”."}
    h = rows[0]["h"]
    d = resolve_date(date)
    await run_write(
        "MATCH (h:Habit {id:$hid}) MERGE (l:HabitLog {id:$lid}) "
        # The app's own direction is (Habit)-[:HAS_LOG]->(HabitLog).
        "SET l.date=$d, l.notes=$n, l.level=1 MERGE (h)-[:HAS_LOG]->(l)",
        hid=h["id"], lid=str(uuid.uuid4()), d=d, n=notes or "")
    return {"habit": h["name"], "logged_for": d}


# ================================ VAULT ===================================== #
@cap("vault_balance", "read", "Account balances and the current month's spending against budget.", {})
async def _vault_balance(**_):
    accounts = await run_read("MATCH (a:Account) RETURN a{.name, .balance, .type} AS a ORDER BY a.name")
    return {"accounts": [r["a"] for r in accounts] or "no accounts set up"}


@cap("vault_add_transaction", "write", "Record money spent or received.",
     {"amount": {"type": "number"}, "description": {"type": "string"},
      "category": {"type": "string"}, "type": {"type": "string",
       "description": "'expense' or 'income'"}, "date": DATE_P},
     ["amount", "description"])
async def _vault_tx(amount: float, description: str, category: str = "",
                    type: str = "expense", date: str = "today", **_):
    import uuid
    signed = -abs(float(amount)) if type != "income" else abs(float(amount))
    await run_write(
        "CREATE (t:Transaction {id:$id, date:$d, amount:$a, description:$desc, "
        "category:$cat, type:$ty, created_at:$ts})",
        id=str(uuid.uuid4()), d=resolve_date(date), a=signed, desc=description,
        cat=category or "uncategorised", ty=type,
        ts=datetime.now().isoformat(timespec="seconds"))
    return {"recorded": description, "amount": signed, "date": resolve_date(date)}


# =============================== SYNAPSE ==================================== #
@cap("papers_list", "read", "Papers and sources in the repository, newest first.",
     {"query": {"type": "string", "description": "Optional words to filter by title"}})
async def _papers(query: str = "", **_):
    where = "WHERE toLower(p.title) CONTAINS toLower($q)" if query else ""
    rows = await run_read(
        f"MATCH (p:Paper) {where} RETURN p{{.title, .year, .status, .kind}} AS p "
        "ORDER BY coalesce(p.added_at,'') DESC LIMIT 15", q=query or "")
    return [r["p"] for r in rows] or "nothing found"


@cap("mind_dump", "write", "Capture a thought, idea or thing to look at later into the Mind Dump inbox.",
     {"text": {"type": "string"}, "kind": {"type": "string",
      "description": "'idea', 'look-at' or 'note'"}},
     ["text"])
async def _mind(text: str, kind: str = "note", **_):
    from models import MindDumpCreate
    from routes.mind import create_dump
    d = await create_dump(MindDumpCreate(
        text=text, kind=kind if kind in ("idea", "look-at", "note") else "note"))
    return {"captured": d.get("text", text)[:80], "kind": d.get("kind")}


# ============================== CROSS-APP =================================== #
@cap("recent_activity", "read", "What has happened in the Mainframe recently, across every module.",
     {"limit": {"type": "integer", "description": "How many entries, default 15"}})
async def _recent(limit: int = 15, **_):
    rows = await run_read(
        "MATCH (c:ChangeEvent) RETURN c{.category, .action, .detail, .module, .timestamp} AS c "
        "ORDER BY c.timestamp DESC LIMIT $n", n=max(1, min(int(limit or 15), 50)))
    return [r["c"] for r in rows]


@cap("whats_next", "read",
     "The single best overview: what's on today, what's due, what's outstanding. Use this when asked "
     "an open question like 'what should I do' or 'how am I doing'.", {})
async def _whats_next(**_):
    from routes.calendar import range_feed, suggestions as cal_sug
    today = date.today().isoformat()
    feed = await range_feed(from_=today, to=today)
    sug = await cal_sug()
    return {
        "today": today,
        "events": [f'{e.get("start") or "all day"} {e["title"]}' for e in feed["events"]],
        "due_today": [t["title"] for t in feed["due"]],
        "flagged": [s["title"] for s in sug[:5]],
    }

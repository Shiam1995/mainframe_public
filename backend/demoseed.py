"""Fill a fresh, empty Mainframe with a believable set of invented demo data.

    cd backend
    .venv/bin/python demoseed.py            # seed
    .venv/bin/python demoseed.py --undo     # remove exactly what the seed made

HOW IT WRITES
-------------
Through the app's own routes, in-process (FastAPI's TestClient), not through
hand-written Cypher. A route is the definition of what a tab can read: every id,
default, timestamp, :ChangeEvent and relationship it sets is what the UI
expects, so posting through it is the only way to be sure the shapes are right.
No server needs to be running, and there is exactly one database in play: the
one `NEO4J_URI` names (via config.settings), for both the writes and the
tagging. A handful of things have no write route at all (a phase claim's
per-week plan, a phase's weekly capacity, paper-to-paper :CITES) and those few
are set with direct Cypher, noted where they happen.

WHY EVERYTHING IS TAGGED
------------------------
Before seeding, the script notes the elementId of every node already in the
graph. Afterwards, every node that was not there gets `demo_seed = DEMO_TAG` —
including the side-effect nodes the routes make on their own (:ChangeEvent log
rows, :Move rows, :Hop whys, the :Module and :HabitArea nodes some routes
MERGE). So `--undo` is one query and takes back everything the seed caused.
Nothing that existed before is deleted; properties a route may have touched on
a pre-existing node are not reverted (in practice none are, on a fresh graph).

SAFETY
------
This is meant for an empty install. It refuses to run against a graph with
more than MAX_NODES nodes unless `--force` is passed. Run twice without an
undo, the second run finds the tagged nodes, says so and writes nothing — a
second set would duplicate everything, and the phase route refuses a second
active phase anyway. The target URI is printed before anything runs.

Dates are relative to today, so the demo always looks current. The random
choices are seeded, so two runs on the same day produce the same data.
All content is invented: no real people, papers or accounts.
"""
from __future__ import annotations

import argparse
import random
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

DEMO_TAG = "2026-07-30"
MAX_NODES = 10_000          # a fresh install has a few dozen; real data has far more

R = random.Random(7)
TODAY = date.today()


def d(n: int) -> str:
    """n days ago, as YYYY-MM-DD (negative n = in the future)."""
    return (TODAY - timedelta(days=n)).isoformat()


def ahead(n: int) -> str:
    return d(-n)


def ts_days_ago(n: float, hour: int = 10) -> str:
    """An ISO timestamp n days ago, in the same UTC format the routes write."""
    base = datetime.combine(TODAY, datetime.min.time(), tzinfo=timezone.utc)
    return (base - timedelta(days=n) + timedelta(hours=hour)).isoformat()


class SeedError(RuntimeError):
    pass


# =========================================================================== #
# The client: the app in-process
# =========================================================================== #
class Api:
    """Thin wrapper over TestClient that fails loudly on any non-2xx."""

    def __init__(self, client):
        self.c = client
        self.calls = 0

    def _do(self, method: str, path: str, body=None, params=None):
        r = self.c.request(method, path, json=body, params=params)
        self.calls += 1
        if r.status_code >= 400:
            raise SeedError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        if not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            return r.text

    def get(self, path, **params):
        return self._do("GET", path, params=params or None)

    def post(self, path, body=None, **params):
        return self._do("POST", path, body if body is not None else {}, params or None)

    def put(self, path, body=None, **params):
        return self._do("PUT", path, body if body is not None else {}, params or None)

    def patch(self, path, body=None, **params):
        return self._do("PATCH", path, body if body is not None else {}, params or None)


def _app_client():
    """The FastAPI app with a lifespan that sets the schema up and nothing else
    (no Friday report scheduler running inside a one-shot script)."""
    from fastapi.testclient import TestClient

    import main
    from db import close_driver, init_schema, verify_connectivity

    @asynccontextmanager
    async def _lifespan(_app):
        if not await verify_connectivity():
            raise SeedError("cannot reach Neo4j — start it first")
        await init_schema()
        yield
        await close_driver()

    main.app.router.lifespan_context = _lifespan
    return TestClient(main.app, raise_server_exceptions=True)


# =========================================================================== #
# The data
# =========================================================================== #
def seed(api: Api, db) -> None:
    """Everything, in the brief's priority order. `db` is a sync neo4j session,
    used only for the few fields no route writes."""

    # ------------------------------------------------------------ projects --
    # Two levels. (name, kind, color, priority, status, low_h, high_h, done_when)
    tree = [
        ("Home Lab", "build", "blue", 1, "active", 30, 50,
         "Every service runs on the rack and backs up nightly",
         [("Network Rack", "build", "", 1, "active", 10, 16, "Rack wired, labelled, documented"),
          ("Backup Server", "build", "", 2, "active", 8, 14, "Restore tested from a cold start")]),
        ("Learn Statistics", "study", "purple", 1, "active", 60, 90,
         "Can run and explain a regression on my own data",
         [("Probability Course", "study", "", 1, "active", 30, 40, "All twelve units and exercises done"),
          ("Regression Notes", "study", "", 2, "active", 12, 20, "Notes cover OLS to logistic")]),
        ("Garden Redesign", "admin", "green", 2, "active", 15, 25,
         "New beds planted and the path laid", []),
        ("Cooking Channel", "build", "yellow", 2, "active", 25, 45,
         "Three episodes published",
         [("Pilot Episode", "build", "", 1, "active", 8, 12, "Pilot edited and uploaded")]),
    ]
    projects: dict[str, str] = {}
    for name, kind, color, prio, status, lo, hi, done_when, kids in tree:
        pid = api.post("/api/synapse/projects", {"name": name, "why": ""})["id"]
        projects[name] = pid
        api.patch(f"/api/synapse/projects/{pid}", {
            "kind": kind, "color": color, "priority": prio, "status": status,
            "low_h": lo, "high_h": hi, "done_when": done_when})
        for kname, kkind, kcolor, kprio, kstatus, klo, khi, kdone in kids:
            kid = api.post("/api/synapse/projects", {
                "name": kname, "parent_id": pid,
                "why": "split out so it can be estimated on its own"})["id"]
            projects[kname] = kid
            api.patch(f"/api/synapse/projects/{kid}", {
                "kind": kkind, "priority": kprio, "status": kstatus,
                "low_h": klo, "high_h": khi, "done_when": kdone, "est_override": True})

    # whys and notes on projects — what the Reasoning tab reads
    whys = [
        ("Home Lab", "why", "Paying for three cloud services to store photos is silly when an old PC can do it."),
        ("Home Lab", "note", "The switch has 8 ports; the rack plan needs 10. Buy a second one or drop the printer."),
        ("Learn Statistics", "why", "Every spreadsheet argument at work ends with nobody knowing if the difference is real."),
        ("Garden Redesign", "why", "The lawn floods every winter; raised beds fix that and grow food."),
        ("Cooking Channel", "why", "Filming forces me to actually measure things and write the recipes down."),
        ("Cooking Channel", "note", "Natural light in the kitchen is gone by 4pm in winter — film at weekends."),
    ]
    for pname, kind, text in whys:
        api.post(f"/api/synapse/projects/{projects[pname]}/why", {"text": text, "kind": kind})

    # --------------------------------------------------------------- inbox --
    # (title, kind, project or None, state, starred tone or None, notes)
    rows = [
        ("Label every cable at both ends", "task", "Network Rack", "done", None, []),
        ("Flash the router with open firmware", "task", "Network Rack", "open", "priority",
         ["Back up the current config first.", "Check the model is on the supported list."]),
        ("Set up nightly snapshot job", "task", "Backup Server", "open", "soon", []),
        ("Test a full restore onto a spare disk", "task", "Backup Server", "open", None, []),
        ("Try a small UPS so the server survives power blips", "idea", "Home Lab", "open", "later", []),
        ("Finish unit 4: conditional probability", "task", "Probability Course", "done", None, []),
        ("Unit 5 exercises", "task", "Probability Course", "open", "priority",
         ["Questions 7 and 9 are the hard ones — leave time."]),
        ("Make flashcards for the common distributions", "idea", "Probability Course", "open", None, []),
        ("Find a dataset with a real question in it", "task", "Regression Notes", "open", "soon", []),
        ("Measure the garden and draw it to scale", "task", "Garden Redesign", "done", None, []),
        ("Order timber for two raised beds", "task", "Garden Redesign", "open", "priority",
         ["Quote from the yard: 2 x 1.8m kits, delivery Thursday."]),
        ("Plant garlic before the first frost", "task", "Garden Redesign", "open", None, []),
        ("A herb spiral by the back door", "idea", "Garden Redesign", "open", None, []),
        ("Write the pilot recipe card", "task", "Pilot Episode", "done", None, []),
        ("Shoot B-roll of the market", "task", "Pilot Episode", "open", "soon", []),
        ("Episode idea: one-pan dinners under 30 minutes", "idea", "Cooking Channel", "open", "priority", []),
        ("Episode idea: bread with four ingredients", "idea", "Cooking Channel", "open", None, []),
        # loose rows, not given anywhere yet
        ("Renew the car insurance", "task", None, "open", "priority", []),
        ("Book a dentist check-up", "task", None, "done", None, []),
        ("Call the bank about the old savings account", "task", None, "open", None, []),
        ("A reading list shared with friends", "idea", None, "open", None,
         ["Could just be a shared spreadsheet to start."]),
        ("Learn to sharpen kitchen knives properly", "idea", None, "open", None, []),
        ("Weekend walking route map", "idea", None, "open", "later", []),
        ("Swap the email newsletter for an RSS reader", "idea", None, "dropped", None, []),
    ]
    task_ids: dict[str, str] = {}
    for i, (title, kind, pname, state, star, notes) in enumerate(rows):
        tid = api.post("/api/synapse/inbox", {"title": title, "kind": kind})["id"]
        task_ids[title] = tid
        if pname:
            api.post(f"/api/synapse/inbox/{tid}/give",
                     {"project_id": projects[pname], "why": ""})
        if star:
            api.post(f"/api/synapse/inbox/{tid}/star", {"starred": True, "tone": star})
        for text in notes:
            api.post("/api/rows", {"text": text, "kind": "note", "parent_id": tid,
                                   "inbox": False})
        if kind == "task" and state == "open" and i % 3 == 0:
            api.patch(f"/api/synapse/inbox/{tid}", {
                "low_h": 1.0, "high_h": 3.0, "due": ahead(3 + i % 10),
                "do_on": ahead(1 + i % 6), "do_at": "10:00", "takes_min": 60})
        if state == "done":
            api.post(f"/api/synapse/inbox/{tid}/done", {"why": ""})
        elif state == "dropped":
            api.post(f"/api/synapse/inbox/{tid}/drop",
                     {"why": "the reader I already use does this"})

    # -------------------------------------------------------------- phases --
    # One active 14-week phase that began on a Monday a few weeks ago.
    start = TODAY - timedelta(days=TODAY.weekday()) - timedelta(weeks=4)
    claimed = {"Home Lab": 70.0, "Learn Statistics": 120.0, "Cooking Channel": 50.0}
    phase = api.post("/api/phases", {
        "name": "Autumn Sprint", "start": start.isoformat(), "weeks": 14,
        "goal": "Rack running, statistics course finished, pilot episode out.",
        "project_ids": [projects[n] for n in claimed]})
    phase_id = phase["id"]
    for pname, hours in claimed.items():
        api.post(f"/api/phases/{phase_id}/pull", {
            "kind": "project", "id": projects[pname], "hours": hours,
            "why": "one of the three things this phase is for"})
    # NO ROUTE writes these: the per-week plan on the claim (phases.py reads
    # r.planned, fourteen numbers) and the phase's weekly capacity. Set directly.
    weekly = {"Home Lab": [6, 6, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 4, 4],
              "Learn Statistics": [9, 9, 9, 9, 8, 8, 8, 8, 9, 9, 9, 9, 8, 8],
              "Cooking Channel": [3, 3, 3, 4, 4, 4, 4, 4, 4, 4, 4, 3, 3, 3]}
    for pname, plan in weekly.items():
        db.run("MATCH (:Project {id: $pid})-[r:CLAIMED_BY]->(:Phase {id: $ph}) "
               "SET r.planned = $plan",
               pid=projects[pname], ph=phase_id, plan=[float(x) for x in plan])
    db.run("MATCH (p:Phase {id: $id}) SET p.capacity_h_per_week = 20.0", id=phase_id)

    for text, horizon, pname, plan_w in [
        ("Finish probability units 5 and 6", "week", "Probability Course", 8.0),
        ("Rack wired and every port labelled", "month", "Network Rack", 10.0),
        ("Pilot episode rough cut", "month", "Pilot Episode", 6.0),
    ]:
        api.post("/api/phases/goals", {"text": text, "horizon": horizon,
                                       "project_id": projects[pname],
                                       "plan_h_week": plan_w, "due": ahead(10)})

    # ------------------------------------------------------- work sessions --
    # Hours are never stored: they are summed from these rows. Some land on
    # the claimed projects (so Phases/Pace have numbers), some on their tasks,
    # some on work the plan never accounted for.
    targets = [
        ("Network Rack", "project", "build", "pulse", ["wired the patch panel", "mounted the shelf", "labelled ports"]),
        ("Backup Server", "project", "build", "mainframe", ["installed the OS", "wrote the snapshot script"]),
        ("Probability Course", "project", "study", "synapse", ["unit 4 videos", "unit 5 exercises", "re-did the quiz"]),
        ("Regression Notes", "project", "study", "synapse", ["wrote up least squares"]),
        ("Pilot Episode", "project", "build", "vision", ["scripted the intro", "filmed the prep", "rough cut"]),
        ("Garden Redesign", "project", "admin", "mainframe", ["measured the beds", "priced timber"]),
    ]
    weights = [3, 1, 4, 1, 2, 1]
    for n in range(45, -1, -1):
        day = TODAY - timedelta(days=n)
        k = R.choice([0, 1, 1, 2, 2, 3]) if day.weekday() < 5 else R.choice([0, 1, 2])
        hour = 9
        for _ in range(k):
            pname, ref_kind, wkind, module, whats = R.choices(targets, weights)[0]
            mins = R.choice([30, 45, 60, 60, 90, 120])
            st = f"{hour:02d}:00"
            end_m = hour * 60 + mins
            en = f"{end_m // 60:02d}:{end_m % 60:02d}"
            hour = min(20, hour + mins // 60 + 1)
            api.post("/api/work", {
                "date": day.isoformat(), "start": st, "end": en, "mins": mins,
                "module": module, "ref_kind": ref_kind, "ref_id": projects[pname],
                "ref_title": pname, "kind": wkind, "what": R.choice(whats),
                "focus": R.choice(["active", "active", "passive"]),
                "completed": R.random() < 0.2})

    # Spread creation dates back over the last weeks so the Inbox and Projects
    # do not all read "created today". Same timestamp format the routes write.
    for i, tid in enumerate(task_ids.values()):
        db.run("MATCH (t:Task {id: $id}) SET t.created_at = $ts",
               id=tid, ts=ts_days_ago(40 - i * 1.5))
    for i, pid in enumerate(projects.values()):
        db.run("MATCH (p:Project {id: $id}) SET p.created_at = $ts",
               id=pid, ts=ts_days_ago(50 - i * 2))

    # -------------------------------------------------------------- habits --
    habits = [
        # name, category, area, frequency, source, source_types
        ("Morning stretch", "fitness", "fitness", "daily", None, None),
        ("Train", "fitness", "fitness", "3x-week", "workout", None),
        ("Read 20 pages", "learning", "learning", "daily", None, None),
        ("Study session", "learning", "learning", "weekdays", "study", None),
        ("Lights out by 23:00", "sleep", "sleep", "daily", None, None),
        ("Meditate", "mindfulness", "recovery", "daily", "recovery", ["Meditation"]),
        ("Log every meal", "nutrition", "diet", "daily", "food", None),
        ("No-spend day", "other", "finance", "3x-week", "no_spend", None),
        ("Inbox to zero", "productivity", "admin", "weekdays", None, None),
    ]
    tick_habits = []
    for name, cat, area, freq, source, stypes in habits:
        body = {"name": name, "category": cat, "frequency": freq, "area": area,
                "tier": "main"}
        if source:
            body["source"] = source
        if stypes:
            body["source_types"] = stypes
        h = api.post("/api/pulse/habits", body)
        if not source:
            tick_habits.append(h["id"])
    for hid in tick_habits:
        for n in range(60):
            keep = 0.3 if 26 <= n <= 36 else 0.78       # a bad fortnight, not a wall of green
            if R.random() < keep:
                api.post(f"/api/pulse/habits/{hid}/logs",
                         {"date": d(n), "level": R.choice([1, 2, 2, 3, 3])})

    # ------------------------------------------------------------- fitness --
    api.post("/api/pulse/fitness/cycles", {
        "name": "Autumn base", "weeks": 8, "start_date": d(35), "phase": "Hypertrophy",
        "goals": "Three lifts a week, one run", "notes": ""})
    lifts = {"Push": [("Bench press", 60), ("Overhead press", 37.5), ("Dips", 0)],
             "Pull": [("Deadlift", 100), ("Barbell row", 55), ("Pull-up", 0)],
             "Legs": [("Back squat", 80), ("Romanian deadlift", 70), ("Lunge", 20)]}
    order = ["Push", "Pull", "Legs"]
    w_i = 0
    for n in range(56, -1, -1):
        day = TODAY - timedelta(days=n)
        if day.weekday() in (0, 2, 4) and R.random() < 0.85:
            wtype = order[w_i % 3]
            w_i += 1
            blocks = []
            for ex, kg in lifts[wtype]:
                prog = kg + 2.5 * (56 - n) // 14 if kg else 0
                for _ in range(3):
                    blocks.append({"kind": "exercise", "exercise": ex,
                                   "reps": R.choice([6, 8, 8, 10]), "kg": float(prog),
                                   "rpe": R.choice([7, 8, 8, 9])})
            api.post("/api/pulse/fitness/workouts", {
                "date": day.isoformat(), "type": wtype,
                "duration": R.choice([45, 50, 60, 70]), "intensity": R.randint(5, 9),
                "notes": R.choice(["felt strong", "short on time", "good session", ""]),
                "blocks": blocks})
        elif day.weekday() == 5 and R.random() < 0.8:
            km = round(R.uniform(4.0, 8.0), 1)
            api.post("/api/pulse/fitness/cardio", {
                "date": day.isoformat(), "type": "run", "distance_km": km,
                "duration_mins": int(km * R.uniform(5.5, 6.5)),
                "perceived_effort": R.randint(4, 8), "route": "river loop"})
    for ex, kg, reps in [("Bench press", 70, 3), ("Back squat", 95, 3), ("Deadlift", 120, 1)]:
        api.post("/api/pulse/fitness/maxes", {"exercise": ex, "kg": kg, "reps": reps, "date": d(10)})
    # Fitness goals are left out: POST /api/pulse/fitness/goals 500s on any body,
    # because models.py defines GoalCreate twice and the focus-panel one (title,
    # note, horizon) shadows the fitness one (text, current, target) that
    # routes/fitness.py reads.

    # ------------------------------------------------------------ recovery --
    rtypes = {}
    for name, icon in [("Meditation", ""), ("Breathing", ""), ("Sauna", ""), ("Nature walk", "")]:
        rtypes[name] = api.post("/api/pulse/recovery/types", {"name": name, "icon": icon})["id"]
    for n in range(40, -1, -1):
        for name, p, dur in [("Meditation", 0.6, 10), ("Breathing", 0.25, 5),
                             ("Sauna", 0.1, 20), ("Nature walk", 0.15, 45)]:
            if R.random() < p:
                api.post("/api/pulse/recovery/sessions", {
                    "date": d(n), "type_id": rtypes[name], "duration": dur,
                    "feel": R.choice(["calmer", "better", "same", "much better"])})

    # ----------------------------------------------------------- nutrition --
    api.put("/api/pulse/nutrition/goals", {
        "daily_calories": 2300, "protein_g": 140, "carbs_g": 250, "fat_g": 75,
        "water_ml": 2500, "weight_target": 74.0, "height_cm": 178})
    # Generic foods with ordinary per-serving macros (invented, rounded).
    foods_spec = [
        ("Porridge oats", "grains", 40, "g", 150, 5, 24, 3),
        ("Banana", "fruit", 1, "medium", 105, 1.3, 27, 0.4),
        ("Chicken breast", "meat", 150, "g", 248, 46, 0, 5.4),
        ("Greek yogurt", "dairy", 150, "g", 146, 15, 6, 7),
        ("Wholemeal bread", "grains", 2, "slices", 180, 8, 32, 2.4),
        ("Salmon fillet", "fish", 120, "g", 250, 25, 0, 16),
        ("Brown rice", "grains", 180, "g cooked", 220, 5, 46, 1.8),
        ("Eggs", "dairy", 2, "large", 143, 12.6, 0.8, 9.5),
        ("Mixed nuts", "snacks", 30, "g", 180, 5, 6, 16),
        ("Lentil soup", "meals", 1, "bowl", 230, 13, 32, 5),
        ("Apple", "fruit", 1, "medium", 95, 0.5, 25, 0.3),
        ("Pasta with tomato sauce", "meals", 1, "plate", 480, 15, 85, 9),
    ]
    foods = []
    for name, cat, size, unit, cal, pro, carb, fat in foods_spec:
        f = api.post("/api/pulse/nutrition/foods", {
            "name": name, "category": cat, "serving_size": size, "serving_unit": unit,
            "calories": cal, "protein": pro, "carbs": carb, "fat": fat, "verified": True})
        foods.append(f)
    by_slot = {"breakfast": [0, 1, 3, 4, 7], "lunch": [9, 4, 3, 10], "dinner": [2, 5, 6, 11],
               "snacks": [8, 10, 1, 3]}
    for n in range(21, -1, -1):
        if n and R.random() < 0.12:            # some days simply are not logged
            continue
        for slot, idxs in by_slot.items():
            if slot == "snacks" and R.random() < 0.4:
                continue
            for fi in R.sample(idxs, R.choice([1, 2])):
                f = foods[fi]
                mult = R.choice([1.0, 1.0, 1.5, 0.5, 2.0])
                api.post("/api/pulse/nutrition/log", {
                    "date": d(n), "meal_slot": slot, "food_id": f["id"],
                    "food_name": f["name"], "serving_size": mult, "serving_unit": "serving",
                    "calories": round(f["calories"] * mult, 1),
                    "protein": round(f["protein"] * mult, 1),
                    "carbs": round(f["carbs"] * mult, 1),
                    "fat": round(f["fat"] * mult, 1)})
        for _ in range(R.randint(3, 6)):
            api.post("/api/pulse/nutrition/water", {"date": d(n), "amount": R.choice([250.0, 330.0, 500.0])})
    weight = 77.8
    for n in range(60, -1, -3):
        weight += R.uniform(-0.35, 0.2)
        api.post("/api/pulse/nutrition/weight", {"date": d(n), "weight": round(weight, 1)})

    # --------------------------------------------------- pulse extras -----
    api.post("/api/pulse/experiments", {
        "name": "No screens after 22:00", "days": 21, "unit": "days", "start_date": d(9),
        "hypothesis": "Falling asleep takes less than 15 minutes"})
    rt = api.post("/api/pulse/routines", {"name": "Morning routine", "unit": "ongoing",
                                          "category": "health", "time_of_day": "07:00",
                                          "duration_mins": 25})
    for step in ["Glass of water", "Ten minutes of stretching", "Plan the day"]:
        api.post(f"/api/pulse/routines/{rt['id']}/steps", {"name": step})

    # --------------------------------------------------------------- vault --
    acc = {}
    for name, kind, provider, bal in [("Everyday current", "current", "High Street Bank", 1840.25),
                                      ("Rainy-day savings", "savings", "High Street Bank", 6200.00),
                                      ("Travel card", "digital", "Online Bank", 310.40),
                                      ("Cash", "cash", "", 45.00)]:
        acc[kind] = api.post("/api/vault/accounts", {"name": name, "type": kind,
                                                     "provider": provider, "balance": bal,
                                                     "currency": "GBP"})["id"]
    spend = [("Supermarket", "Groceries", 18, 70, "needed"),
             ("Corner shop", "Groceries", 3, 12, "needed"),
             ("Coffee", "Eating out", 3, 5, "wanted"),
             ("Train ticket", "Transport", 4, 26, "needed"),
             ("Bus fare", "Transport", 2, 3, "needed"),
             ("Takeaway", "Eating out", 15, 32, "wasteful"),
             ("Hardware store", "Home", 8, 60, "needed"),
             ("Bookshop", "Learning", 9, 25, "wanted"),
             ("Garden centre", "Garden", 12, 45, "wanted"),
             ("Pharmacy", "Health", 4, 15, "needed")]
    for n in range(75, -1, -1):
        for _ in range(R.choice([0, 1, 1, 2, 3])):
            desc, cat, lo, hi, verdict = R.choice(spend)
            api.post("/api/vault/transactions", {
                "date": d(n), "description": desc, "amount": round(R.uniform(lo, hi), 2),
                "type": "expense", "category": cat, "account_id": acc["current"],
                "verdict": verdict})
        day = TODAY - timedelta(days=n)
        if day.day == 25:
            api.post("/api/vault/transactions", {
                "date": day.isoformat(), "description": "Salary", "amount": 2650.0,
                "type": "income", "category": "Income", "account_id": acc["current"]})
        if day.day == 1:
            for desc, cat, amt in [("Rent", "Housing", 950.0), ("Council tax", "Bills", 140.0),
                                   ("Electricity and gas", "Bills", 88.0)]:
                api.post("/api/vault/transactions", {
                    "date": day.isoformat(), "description": desc, "amount": amt,
                    "type": "expense", "category": cat, "account_id": acc["current"],
                    "verdict": "needed"})
            api.post("/api/vault/transactions", {
                "date": day.isoformat(), "description": "Monthly saving", "amount": 200.0,
                "type": "transfer", "category": "Savings", "account_id": acc["current"]})
    for name, icon, amt in [("Groceries", "🛒", 320), ("Eating out", "🍽", 90), ("Transport", "🚆", 120),
                            ("Home", "🏠", 60), ("Learning", "📚", 30), ("Garden", "🌱", 50)]:
        api.post("/api/vault/budget", {"name": name, "icon": icon, "amount": amt})
    api.put("/api/vault/budget/income", {"month": TODAY.strftime("%Y-%m"), "amount": 2650.0})
    for name, amt, cadence, cat, area, nxt in [
        ("Music streaming", 10.99, "monthly", "Subscriptions", "other", 6),
        ("Video streaming", 8.99, "monthly", "Subscriptions", "other", 12),
        ("Cloud storage", 2.49, "monthly", "Subscriptions", "other", 19),
        ("Gym membership", 29.0, "monthly", "Health", "other", 3),
        ("Phone contract", 16.0, "monthly", "Bills", "other", 9),
        ("Domain name", 12.0, "yearly", "Subscriptions", "other", 140),
    ]:
        api.post("/api/vault/recurring", {
            "name": name, "amount": amt, "cadence": cadence, "next_due": ahead(nxt),
            "category": cat, "account_id": acc["current"], "area": area,
            "start": d(200), "worth": "yes" if amt > 5 else "maybe"})
    for name, kind, platform, put_in, value in [
        ("Global index fund", "ETF", "Investment platform", 3600.0, 3925.0),
        ("Bond fund", "Fund", "Investment platform", 1200.0, 1188.0)]:
        api.post("/api/vault/investments", {"name": name, "type": kind, "platform": platform,
                                            "amount_invested": put_in, "current_value": value})
    for name, cat, loc, value in [("Road bike", "sport", "hall", 450.0),
                                  ("Stand mixer", "kitchen", "kitchen", 180.0),
                                  ("Old desktop PC (home server)", "electronics", "study", 120.0),
                                  ("Camera and tripod", "electronics", "study", 380.0)]:
        api.post("/api/vault/inventory", {"name": name, "category": cat, "location": loc,
                                          "value": value, "acquired": d(400)})
    api.post("/api/vault/diary", {"date": d(12), "title": "Takeaway habit",
                                  "text": "Three takeaways in one week again. Batch-cook on Sundays.",
                                  "tags": ["food"]})
    api.post("/api/vault/diary", {"date": d(3), "title": "Savings on track",
                                  "text": "Rainy-day pot passed six thousand. Keep the transfer automatic.",
                                  "tags": ["savings"]})

    # ------------------------------------------------------------ calendar --
    for title, offset, st, en, kind, loc in [
        ("Team stand-up", -1, "09:30", "09:45", "event", "Online"),
        ("Dentist check-up", -6, "11:30", "12:00", "event", "High Street"),
        ("Allotment open day", -3, "10:00", "12:00", "event", "Community garden"),
        ("Team stand-up", 1, "09:30", "09:45", "event", "Online"),
        ("Deep work — probability unit 5", 1, "10:00", "12:00", "block", ""),
        ("Film the pilot episode", 2, "14:00", "17:00", "block", "Kitchen"),
        ("Dinner with friends", 3, "19:00", "21:30", "event", "Local restaurant"),
        ("Timber delivery", 4, "08:00", "10:00", "event", "Home"),
        ("Pay the car insurance", 5, "", "", "reminder", ""),
        ("Statistics study group", 6, "18:00", "19:30", "event", "Library"),
        ("Rack wiring session", 8, "10:00", "13:00", "block", "Study"),
        ("Haircut", 11, "12:00", "12:30", "event", ""),
    ]:
        api.post("/api/calendar/events", {
            "title": title, "date": ahead(offset), "start": st, "end": en,
            "all_day": not st, "kind": kind, "location": loc})

    # --------------------------------------------- diary, gratitude, journal --
    for n, module, title, text in [
        (1, "mainframe", "Good Friday push", "Got the rack shelf up and two units of stats done. Tired but pleased."),
        (2, "pulse", "Legs day", "Squats felt heavy; slept badly. Kept the weight the same instead of pushing."),
        (4, "synapse", "Probability finally clicking", "Drawing the tree diagrams by hand helped more than the videos."),
        (6, "vault", "Budget check", "Eating out is over budget again. Groceries fine."),
        (9, "vision", "Pilot script", "Cut the intro from two minutes to forty seconds. Better."),
        (13, "mainframe", "Slow week", "Not much done. Garden plans only. That's fine."),
    ]:
        api.post("/api/diary", {"date": d(n), "text": text, "title": title, "module": module})
    for n, text in [(0, "A long walk at lunch in the sun"), (1, "A friend called just to chat"),
                    (2, "The first tomatoes from the windowsill"), (3, "A quiet evening with a book"),
                    (5, "Bread came out right on the first try"), (7, "Neighbour lent me a drill")]:
        api.post("/api/gratitude", {"period": "day", "text": text, "date": d(n), "time": "21:00"})
    api.post("/api/gratitude", {"period": "week", "text": "The stats course is finally making sense", "date": d(0)})
    api.post("/api/gratitude", {"period": "month", "text": "Healthy, and the garden plan is real", "date": d(0)})
    for text, kind in [("Film the pilot in two short sessions instead of one long one", "idea"),
                       ("Look at second-hand server racks", "look-at"),
                       ("Weekly review on Sunday evenings works better than Monday", "note")]:
        api.post("/api/mind", {"text": text, "kind": kind})

    # ------------------------------------------- questions, lessons, assumptions --
    for text in ["Is a 3-2-1 backup overkill for a home lab?",
                 "When is a median more honest than a mean?",
                 "Do raised beds need a liner?",
                 "How long should a cooking video be?"]:
        api.post("/api/questions", {"text": text})
    for wrong, instead, group, n in [
        ("Started filming before the recipe was tested", "Cook it once off-camera first", "Method", 8),
        ("Planned five study sessions in a week with two free evenings", "Plan from the calendar, not from hope", "Planning", 15),
        ("Checked email before the first deep-work block", "Email after the first block, not before", "Focus", 4),
    ]:
        api.post("/api/lessons", {"wrong": wrong, "instead": instead, "group": group, "date": d(n)})
    for text in ["The old PC is powerful enough to run every service",
                 "Two raised beds are enough for a family of two"]:
        api.post("/api/assumptions", {"text": text})

    # ------------------------------------------------------------ synapse --
    papers_spec = [
        ("A Gentle Introduction to Bayesian Updating", ["A. Author", "B. Writer"], 2019,
         "Journal of Everyday Statistics", "read"),
        ("Why Averages Mislead: Notes on Skewed Data", ["C. Scholar"], 2021,
         "Teaching Statistics Review", "reading"),
        ("Small-Sample Regression in Practice", ["A. Author", "D. Analyst"], 2020,
         "Applied Methods Quarterly", "unread"),
        ("Soil Drainage in Raised Garden Beds", ["E. Grower"], 2018,
         "Horticulture Notes", "read"),
        ("Backup Strategies for Small Networks", ["F. Admin", "G. Operator"], 2022,
         "Home Systems Letters", "revisit"),
        ("Heat, Time and Texture in Home Baking", ["H. Baker"], 2017,
         "Kitchen Science Digest", "unread"),
    ]
    paper_ids = []
    for title, authors, year, venue, status in papers_spec:
        p = api.post("/api/synapse/papers/manual", {
            "title": title, "kind": "paper", "authors": authors, "year": year,
            "venue": venue, "status": status,
            "abstract": "An invented paper used as demo content. It has no file attached."})
        paper_ids.append(p["id"])
    for i, pid in enumerate(paper_ids):
        db.run("MATCH (p:Paper {id: $id}) SET p.added_at = $ts", id=pid,
               ts=ts_days_ago(30 - i * 4))

    hl = {
        0: [("Intro", "A prior is just what you believed before you looked.", "Plain-language version of the whole idea.", "new"),
            ("Section 2", "Each new observation shifts the estimate, never replaces it.", "", "rethink"),
            ("Section 4", "Worked example with a coin of unknown bias.", "Redo this by hand.", "implement")],
        1: [("Section 1", "The mean of a skewed sample sits where few of the data are.", "", "new"),
            ("Section 3", "Report the median and the spread together.", "Use in the work report.", "implement")],
        3: [("Results", "Beds over clay need 30 cm of free-draining fill.", "Our garden is clay.", "new"),
            ("Discussion", "Liners are optional where moles are rare.", "", "knew")],
    }
    for pi, items in hl.items():
        inst = api.post("/api/synapse/instances", {
            "purpose": "first read", "read_date": d(20 - pi * 3), "mins": 45,
            "active_mins": 35, "passive_mins": 10, "notes": "",
            "main_question": "What is the one idea worth keeping?"}, paper_id=paper_ids[pi])
        for page, (section, excerpt, note, tag) in enumerate(items, start=1):
            api.post("/api/synapse/highlights", {
                "section": section, "excerpt": excerpt, "my_note": note, "tag": tag,
                "page": page}, instance_id=inst["id"])
    terms = {
        0: [("Prior", "What you believed before seeing the data", "statistics", 2),
            ("Posterior", "The belief after updating on the data", "statistics", 1)],
        1: [("Median", "The middle value of sorted data", "statistics", 3),
            ("Skewness", "How lopsided a distribution is", "statistics", 1)],
        2: [("Residual", "Observed minus predicted value", "statistics", 1)],
        3: [("Drainage", "How fast water leaves the soil", "horticulture", 2)],
        4: [("Snapshot", "A point-in-time copy of a file system", "computing", 2),
            ("3-2-1 rule", "Three copies, two media, one off-site", "computing", 1)],
        5: [("Maillard reaction", "Browning of proteins and sugars under heat", "cooking", 1)],
    }
    for pi, items in terms.items():
        for name, definition, domain, fam in items:
            api.post("/api/synapse/terms", {"name": name, "definition": definition,
                                            "domain": domain, "familiarity": fam},
                     paper_id=paper_ids[pi])
    for name, eli5, definition in [
        ("Variance", "How spread out the numbers are", "Mean of squared deviations from the mean"),
        ("Compost", "Rotted plant waste that feeds soil", "Decomposed organic matter used as fertiliser"),
        ("RAID", "Several disks acting as one", "Redundant array of independent disks")]:
        api.post("/api/synapse/dictionary/terms", {"name": name, "eli5": eli5,
                                                   "definition": definition, "familiarity": 2})
    # Repo-to-repo citations: (:Paper)-[:CITES]->(:Paper). No route draws these
    # (they come out of reference resolution, which needs a PDF), so set directly.
    for a, b in [(1, 0), (2, 0), (2, 1), (4, 3)]:
        db.run("MATCH (a:Paper {id: $a}), (b:Paper {id: $b}) MERGE (a)-[:CITES]->(b)",
               a=paper_ids[a], b=paper_ids[b])
    # and a couple of hand-drawn map links, through the route
    api.post("/api/synapse/refgraph/edges", {"source_id": paper_ids[5], "target_id": paper_ids[3],
                                             "label": "same garden-and-kitchen thread"})
    api.post("/api/synapse/refgraph/edges", {"source_id": paper_ids[2], "target_id": paper_ids[4],
                                             "label": "relates"})

    # -------------------------------------------------------------- vision --
    for title, vtype, desc, target in [
        ("One-pan dinners under 30 minutes", "educational",
         "Three weeknight dinners, one pan each, start to finish on camera.", 21),
        ("Bread with four ingredients", "tutorial",
         "Flour, water, salt, yeast — and why each one matters.", 45)]:
        api.post("/api/vision/videos", {"title": title, "type": vtype, "description": desc,
                                        "target_date": ahead(target), "tags": ["cooking"]})
    for title, wtype, platform in [("What a home lab taught me about backups", "Blog", "Blog"),
                                   ("Raised beds on clay: a first season", "Blog", "Blog")]:
        api.post("/api/vision/writing", {"title": title, "type": wtype, "platform": platform})
    api.post("/api/vision/portfolio", {"title": "Garden planner spreadsheet",
                                       "description": "A scale plan and planting calendar.",
                                       "type": "Design", "tags": ["garden"]})
    for name, role, platform in [("Sam Example", "Food video editor", "Email"),
                                 ("Alex Sample", "Allotment society", "In person")]:
        api.post("/api/vision/network", {"name": name, "role": role, "platform": platform,
                                         "known_from": "demo"})


# =========================================================================== #
# Runner
# =========================================================================== #
def _driver():
    from neo4j import GraphDatabase
    from config import settings
    return settings, GraphDatabase.driver(settings.neo4j_uri,
                                          auth=(settings.neo4j_user, settings.neo4j_password))


def undo(session) -> int:
    r = session.run("MATCH (n) WHERE n.demo_seed = $tag DETACH DELETE n RETURN count(n) AS n",
                    tag=DEMO_TAG).single()
    return r["n"] if r else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--undo", action="store_true", help="delete every node the seed made")
    ap.add_argument("--force", action="store_true",
                    help=f"run even though the graph has more than {MAX_NODES} nodes")
    args = ap.parse_args(argv)

    import logging
    import main as _main  # noqa: F401 — its import sets logging up; quieten it after
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("neo4j").setLevel(logging.ERROR)

    settings, drv = _driver()
    print(f"target: {settings.neo4j_uri}  (MAINFRAME_HOME data dir: {settings.projects_dir.parent})")
    try:
        with drv.session(database=settings.neo4j_database) as s:
            total = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            print(f"nodes in graph before: {total}")
            if total > MAX_NODES and not args.force:
                print(f"REFUSING: more than {MAX_NODES} nodes — this does not look like a fresh "
                      "install. Check NEO4J_URI, or pass --force if you really mean it.")
                return 2
            if args.undo:
                print(f"removed {undo(s)} demo nodes; "
                      f"nodes now: {s.run('MATCH (n) RETURN count(n) AS c').single()['c']}")
                return 0
            already = s.run("MATCH (n) WHERE n.demo_seed = $t RETURN count(n) AS c",
                            t=DEMO_TAG).single()["c"]
            if already:
                print(f"already seeded ({already} demo nodes). Nothing done; run --undo first "
                      "to seed afresh.")
                return 0
            before = [r["e"] for r in s.run("MATCH (n) RETURN elementId(n) AS e")]

            err: BaseException | None = None
            calls = 0
            try:
                with _app_client() as client:
                    api = Api(client)
                    try:
                        seed(api, s)
                    finally:
                        calls = api.calls
            except BaseException as e:      # noqa: BLE001 — tag what was made, then re-raise
                err = e
            finally:
                # Tag every node that was not there before, side effects included,
                # even if the seed stopped part-way — so --undo can always clean up.
                rows = s.run(
                    "MATCH (n) WHERE NOT elementId(n) IN $before "
                    "SET n.demo_seed = $tag "
                    "WITH labels(n) AS ls UNWIND ls AS l RETURN l, count(*) AS c ORDER BY c DESC",
                    before=before, tag=DEMO_TAG).data()
            print(f"{calls} API calls; nodes created, by label:")
            for r in rows:
                print(f"  {r['l']:<22} {r['c']:>6}")
            total_after = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            print(f"nodes in graph after: {total_after}")
            if err:
                print(f"SEED STOPPED EARLY: {err}\n(everything it made is tagged; --undo removes it)")
                return 1
    finally:
        drv.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

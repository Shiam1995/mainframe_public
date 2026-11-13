"""/api/pulse/benchmarks — periodic health/fitness assessments (Pulse Fitness).

Snapshot measurements (default quarterly) that form a health baseline over time:
fitness metrics + blood work in ONE timeline, with period-over-period deltas.
Plus a personal baseline (age/height/weight/…) + goals shown up front.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (
    AssessmentCreate, BaselineUpdate, CustomMetricCreate, MetricConfigUpdate, ScheduleUpdate,
    SnapshotQuick,
)

router = APIRouter(prefix="/api/pulse/benchmarks", tags=["benchmarks"])

FREQ_MONTHS = {"monthly": 1, "quarterly": 3, "6-monthly": 6, "yearly": 12}

# Baseline fields captured into every snapshot so the baseline itself has history.
BASELINE_FIELDS = ["age", "height", "weight", "body_fat", "resting_hr", "goals"]
# The numeric ones that get a trend line (value parsed from strings like "70kg").
BASELINE_NUMERIC = [
    ("weight", "Weight", "⚖️", False),
    ("body_fat", "Body Fat", "📉", False),
    ("resting_hr", "Resting HR", "❤️", False),
    ("age", "Age", "🧬", False),
]

# Default metric catalogue (config-driven; users toggle + add custom).
DEFAULT_METRICS = [
    ("vo2max", "VO2 Max", "ml/kg/min", "🫁", True, "fitness", True),
    ("strength", "Strength Score", "/10", "💪", True, "fitness", True),
    ("flexibility", "Flexibility", "/10", "🤸", True, "fitness", False),
    ("mobility", "Mobility", "/10", "🔄", True, "fitness", False),
    ("balance", "Balance", "/10", "⚖️", True, "fitness", False),
    ("grip", "Grip Strength", "kg", "🤜", True, "fitness", True),
    ("endurance", "Endurance", "/10", "🏃", True, "fitness", False),
    ("recovery", "Recovery Time", "mins", "⏱️", False, "fitness", False),
    ("bench_resting_hr", "Resting HR", "bpm", "❤️", False, "fitness", True),
    ("fitness_age", "Fitness Age", "years", "🧬", False, "fitness", False),
    ("haemoglobin", "Haemoglobin", "g/dL", "🩸", True, "blood", False),
    ("haematocrit", "Haematocrit", "%", "🩸", True, "blood", False),
    ("wbc", "White Blood Cells", "10³/µL", "🩸", True, "blood", False),
    ("platelets", "Platelets", "10³/µL", "🩸", True, "blood", False),
    ("glucose", "Blood Glucose (fasting)", "mmol/L", "🩸", False, "blood", True),
    ("hba1c", "HbA1c", "%", "🩸", False, "blood", True),
    ("cholesterol", "Total Cholesterol", "mmol/L", "🩸", False, "blood", True),
    ("hdl", "HDL", "mmol/L", "🩸", True, "blood", False),
    ("ldl", "LDL", "mmol/L", "🩸", False, "blood", False),
    ("triglycerides", "Triglycerides", "mmol/L", "🩸", False, "blood", True),
    ("iron", "Iron (serum)", "µmol/L", "🩸", True, "blood", True),
    ("ferritin", "Ferritin", "µg/L", "🩸", True, "blood", True),
    ("vitamin_d", "Vitamin D", "nmol/L", "🩸", True, "blood", True),
    ("vitamin_b12", "Vitamin B12", "pg/mL", "🩸", True, "blood", True),
    ("testosterone", "Testosterone", "nmol/L", "🩸", True, "blood", False),
    ("tsh", "Thyroid (TSH)", "mIU/L", "🩸", True, "blood", False),
    ("crp", "CRP (inflammation)", "mg/L", "🩸", False, "blood", True),
    ("creatinine", "Kidney — Creatinine", "µmol/L", "🩸", False, "blood", True),
    ("egfr", "Kidney — eGFR", "mL/min", "🩸", True, "blood", True),
    ("alt", "Liver — ALT", "U/L", "🩸", False, "blood", True),
    ("ast", "Liver — AST", "U/L", "🩸", False, "blood", True),
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(var: str) -> str:
    return f"MERGE (mod:Module {{name: 'pulse'}}) MERGE ({var})-[:OWNED_BY]->(mod)"


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
    dim = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, dim))


def _parse_num(s) -> float | None:
    """Pull the leading number out of a baseline string like '70kg' / '20.5%'."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    buf = ""
    for ch in str(s).strip():
        if ch.isdigit() or (ch == "-" and not buf) or (ch == "." and "." not in buf):
            buf += ch
        elif buf:
            break
    try:
        return float(buf)
    except ValueError:
        return None


async def _frequency() -> str:
    cfg = await run_read("MATCH (s:BenchmarkSchedule {id:'main'}) RETURN s.frequency AS f")
    return cfg[0]["f"] if cfg and cfg[0]["f"] else "quarterly"


async def _next_due_for(snap_date: str) -> str | None:
    try:
        freq = await _frequency()
        return _add_months(date.fromisoformat(snap_date[:10]), FREQ_MONTHS[freq]).isoformat()
    except Exception:  # noqa: BLE001
        return None


async def _seed_metrics() -> None:
    for key, name, unit, icon, hib, cat, tracked in DEFAULT_METRICS:
        await run_write(
            """
            MERGE (m:BenchmarkMetric {key: $key})
            ON CREATE SET m.name=$name, m.unit=$unit, m.icon=$icon,
                          m.higher_is_better=$hib, m.category=$cat, m.tracked=$tracked, m.custom=false
            """,
            key=key, name=name, unit=unit, icon=icon, hib=hib, cat=cat, tracked=tracked,
        )


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
@router.get("/baseline")
async def get_baseline() -> dict:
    rows = await run_read("MATCH (b:Baseline {id: 'me'}) RETURN b{.*} AS b")
    return rows[0]["b"] if rows else {"id": "me"}


@router.put("/baseline")
async def set_baseline(patch: BaselineUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    fields["updated_at"] = _now()
    sets = ", ".join(f"b.{k} = ${k}" for k in fields)
    rows = await run_write(f"MERGE (b:Baseline {{id: 'me'}}) SET {sets} WITH b {_own('b')} RETURN b{{.*}} AS b", **fields)
    await record("fitness", "baseline updated", detail=", ".join(k for k in fields if k != "updated_at"), module="pulse")
    return rows[0]["b"]


# --------------------------------------------------------------------------- #
# Metrics config
# --------------------------------------------------------------------------- #
@router.get("/metrics")
async def list_metrics() -> list[dict]:
    await _seed_metrics()
    rows = await run_read("MATCH (m:BenchmarkMetric) RETURN m{.*} AS m ORDER BY m.category, m.name")
    return [r["m"] for r in rows]


@router.put("/metrics/{key}")
async def update_metric(key: str, patch: MetricConfigUpdate) -> dict:
    fields = patch.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(400, "no fields")
    sets = ", ".join(f"m.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (m:BenchmarkMetric {{key: $key}}) SET {sets} RETURN m{{.*}} AS m", key=key, **fields)
    if not rows:
        raise HTTPException(404, "metric not found")
    return rows[0]["m"]


@router.post("/metrics", status_code=201)
async def add_custom_metric(body: CustomMetricCreate) -> dict:
    cat = body.category if body.category in ("fitness", "blood", "custom") else "custom"
    icon = "🩸" if cat == "blood" else "📊"
    key = ("bio_" if cat == "blood" else "custom_") + uuid.uuid4().hex[:8]
    rows = await run_write(
        """
        CREATE (m:BenchmarkMetric {key:$key, name:$name, unit:$unit, icon:$icon,
            higher_is_better:$hib, category:$cat, tracked:true, custom:true})
        RETURN m{.*} AS m
        """,
        key=key, name=body.name.strip(), unit=body.unit, hib=body.higher_is_better, cat=cat, icon=icon,
    )
    return rows[0]["m"]


# --------------------------------------------------------------------------- #
# Assessments
# --------------------------------------------------------------------------- #
async def _assessment(aid: str) -> dict:
    rows = await run_read(
        """
        MATCH (a:Assessment {id: $id})
        OPTIONAL MATCH (a)-[:HAS_VALUE]->(v:MetricValue)
        RETURN a{.*} AS a, collect(v{.*}) AS values
        """,
        id=aid,
    )
    if not rows:
        raise HTTPException(404, "assessment not found")
    a = rows[0]["a"]
    a["values"] = {v["metric_key"]: {"value": v.get("value"), "notes": v.get("notes", "")} for v in rows[0]["values"] if v.get("metric_key")}
    return a


@router.get("")
async def list_assessments() -> list[dict]:
    rows = await run_read(
        """
        MATCH (a:Assessment)
        OPTIONAL MATCH (a)-[:HAS_VALUE]->(v:MetricValue)
        RETURN a{.*} AS a, collect(v{.*}) AS values
        ORDER BY a.date DESC
        """
    )
    out = []
    for r in rows:
        a = r["a"]
        a["values"] = {v["metric_key"]: {"value": v.get("value"), "notes": v.get("notes", "")} for v in r["values"] if v.get("metric_key")}
        out.append(a)
    return out


async def _current_baseline() -> dict:
    rows = await run_read("MATCH (b:Baseline {id: 'me'}) RETURN b{.*} AS b")
    return rows[0]["b"] if rows else {}


async def _do_snapshot(dt: str, label: str, typ: str, notes: str, values: dict, baseline: dict | None) -> dict:
    """Create one snapshot: freeze the baseline fields + next-due date, then values."""
    aid = str(uuid.uuid4())
    current = await _current_baseline()
    src = baseline if baseline is not None else current
    bl = {f"bl_{k}": (str(src.get(k)) if src.get(k) not in (None, "") else "") for k in BASELINE_FIELDS}
    # Goals and notes are + rows on the baseline now (see routes/rows.py), not
    # strings on it, so it is their text that gets frozen into the snapshot.
    rrows = await run_read(
        "MATCH (r:Row)-[:ON]->(:Baseline {id: 'me'}) "
        "RETURN coalesce(r.kind, 'note') AS kind, r.text AS text ORDER BY r.created_at, r.id")
    bl["bl_goals"] = " · ".join(r["text"] for r in rrows if r["kind"] == "goal")
    bl["bl_notes"] = " · ".join(r["text"] for r in rrows if r["kind"] == "note")
    # No metric values supplied (e.g. quick snapshot) → freeze the baseline's
    # current readings (mv_<key> fields), so biomarkers flow into the timeline.
    if not values:
        values = {k[3:]: {"value": v} for k, v in current.items()
                  if k.startswith("mv_") and v not in (None, "")}
    next_due = await _next_due_for(dt)
    await run_write(
        f"""
        CREATE (a:Assessment {{id:$id, date:$date, label:$label, type:$type, notes:$notes,
            next_due:$next_due, created_at:$now}})
        SET a += $bl
        WITH a {_own('a')}
        """,
        id=aid, date=dt, label=label, type=typ, notes=notes, next_due=next_due, now=_now(), bl=bl,
    )
    for key, mv in (values or {}).items():
        if mv is None or mv.get("value") in (None, ""):
            continue
        try:
            val = float(mv.get("value"))
        except (TypeError, ValueError):
            continue
        await run_write(
            "MATCH (a:Assessment {id:$aid}) CREATE (a)-[:HAS_VALUE]->(:MetricValue {id:$vid, metric_key:$key, value:$val, notes:$notes})",
            aid=aid, vid=str(uuid.uuid4()), key=key, val=val, notes=(mv.get("notes") or ""),
        )
    await record("fitness", "snapshot saved", detail=label or dt, module="pulse")
    return await _assessment(aid)


@router.post("", status_code=201)
async def create_assessment(body: AssessmentCreate) -> dict:
    return await _do_snapshot(body.date, body.label, body.type, body.notes, body.values, body.baseline)


@router.post("/snapshot", status_code=201)
async def quick_snapshot(body: SnapshotQuick) -> dict:
    """Save the CURRENT baseline as a point-in-time snapshot in one click."""
    dt = (body.date or date.today().isoformat())[:10]
    label = body.label.strip() or f"Snapshot {dt}"
    return await _do_snapshot(dt, label, "combined", body.notes, {}, None)


@router.get("/compare")
async def compare() -> dict:
    """All assessments (columns) with their metric values — client computes deltas."""
    assessments = await list_assessments()
    metrics = await list_metrics()
    return {"assessments": assessments, "metrics": metrics}


@router.get("/trend/{key}")
async def trend(key: str) -> list[dict]:
    rows = await run_read(
        """
        MATCH (a:Assessment)-[:HAS_VALUE]->(v:MetricValue {metric_key: $key})
        RETURN a.date AS date, v.value AS value ORDER BY a.date
        """,
        key=key,
    )
    return rows


@router.get("/trends")
async def trends() -> dict:
    """Series across all snapshots for each tracked metric + baseline numerics."""
    assessments = await list_assessments()          # newest first
    ordered = list(reversed(assessments))            # oldest → newest for plotting
    metrics = [m for m in await list_metrics() if m.get("tracked")]

    metric_series = []
    for m in metrics:
        pts = [{"date": a["date"], "value": a["values"][m["key"]]["value"]}
               for a in ordered if a.get("values", {}).get(m["key"])]
        if len(pts) >= 1:
            metric_series.append({**{k: m[k] for k in ("key", "name", "unit", "icon", "higher_is_better")}, "points": pts})

    baseline_series = []
    for key, name, icon, hib in BASELINE_NUMERIC:
        pts = []
        for a in ordered:
            v = _parse_num(a.get(f"bl_{key}"))
            if v is not None:
                pts.append({"date": a["date"], "value": v})
        if len(pts) >= 1:
            baseline_series.append({"key": key, "name": name, "icon": icon, "unit": "", "higher_is_better": hib, "points": pts})

    return {"count": len(assessments), "metrics": metric_series, "baseline": baseline_series}


@router.get("/{aid}")
async def get_assessment(aid: str) -> dict:
    return await _assessment(aid)


@router.delete("/{aid}", status_code=204, response_class=Response)
async def delete_assessment(aid: str) -> Response:
    await run_write("MATCH (a:Assessment {id:$id}) OPTIONAL MATCH (a)-[:HAS_VALUE]->(v:MetricValue) DETACH DELETE v, a", id=aid)
    await record("fitness", "assessment deleted", detail=aid, module="pulse")
    return Response(status_code=204)


@router.post("/{aid}/import-blood")
async def import_blood(aid: str) -> dict:
    """Best-effort link the latest Medical→Blood entry to this assessment."""
    rows = await run_read("MATCH (m:MedicalEntry {section: 'blood'}) RETURN m{.*} AS m ORDER BY m.date DESC LIMIT 1")
    if not rows:
        return {"linked": None, "message": "no blood tests in Medical"}
    await run_write(
        "MATCH (a:Assessment {id:$aid}), (m:MedicalEntry {id:$mid}) MERGE (a)-[:INCLUDES_BLOOD_WORK]->(m)",
        aid=aid, mid=rows[0]["m"]["id"],
    )
    return {"linked": rows[0]["m"]}


# --------------------------------------------------------------------------- #
# Schedule
# --------------------------------------------------------------------------- #
@router.get("/schedule/info")
async def get_schedule() -> dict:
    cfg = await run_read("MATCH (s:BenchmarkSchedule {id:'main'}) RETURN s.frequency AS f")
    freq = cfg[0]["f"] if cfg and cfg[0]["f"] else "quarterly"
    last = await run_read("MATCH (a:Assessment) RETURN max(a.date) AS d")
    last_date = last[0]["d"] if last else None
    next_due, status, days = None, "none", None
    if last_date:
        try:
            nd = _add_months(date.fromisoformat(last_date[:10]), FREQ_MONTHS[freq])
            next_due = nd.isoformat()
            days = (nd - date.today()).days
            status = "overdue" if days < 0 else "due-soon" if days <= 14 else "ok"
        except Exception:  # noqa: BLE001
            pass
    return {"frequency": freq, "last_assessment": last_date, "next_due": next_due, "days": days, "status": status}


@router.put("/schedule/info")
async def set_schedule(body: ScheduleUpdate) -> dict:
    await run_write(f"MERGE (s:BenchmarkSchedule {{id:'main'}}) SET s.frequency=$f WITH s {_own('s')}", f=body.frequency)
    return await get_schedule()

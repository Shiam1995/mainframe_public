"""Read .ics files (Google Calendar exports) into `:CalEvent`.

Deliberately dependency-free
----------------------------
RFC 5545 is a large spec, but the slice a personal calendar actually uses is
small and well-defined, and a hand-rolled reader keeps the zero-dependency rule
that the rest of this app follows. What it handles:

  * **Line unfolding.** A long SUMMARY is split across lines with a leading
    space or tab. Parse line-by-line without rejoining and every long event
    title arrives truncated — which looks like working software until you read
    one.
  * **Parameters on properties** — `DTSTART;TZID=Europe/London:20260730T140000`.
    The value is after the FIRST colon, but a colon can also appear inside the
    value (a URL in DESCRIPTION), so splitting on the last colon, or on every
    colon, both corrupt data.
  * **Escaping.** `\\n`, `\\,`, `\\;` and `\\\\` are escape sequences in text
    values, so a description containing a comma arrives with a stray backslash
    unless they're decoded.
  * **Three DTSTART forms**: date-only (all-day), floating/zoned local time, and
    UTC with a trailing `Z` — which must be converted to local time or every
    imported event sits at the wrong hour for half the year.
  * **Recurrence** — the common `RRULE` cases, expanded into concrete days
    within a bounded window (see `expand`), plus `EXDATE` cancellations.

What it does NOT do, on purpose: VTODO, VALARM, attendees, free/busy
publishing, or full timezone-database maths. Zoned times are read as local time,
which is right whenever the calendar's zone is the machine's zone — true for a
single-user app on one laptop, and stated here so the limit is known rather
than discovered.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("synapse.ics")

# How far a repeating event is expanded. Unbounded expansion of "every weekday,
# forever" is an infinite loop, so a window is not optional.
EXPAND_BACK_DAYS = 120
EXPAND_FORWARD_DAYS = 400
MAX_OCCURRENCES = 400          # per rule, a backstop against a pathological RRULE

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def import_dir() -> Path:
    from config import settings
    return Path(settings.calendar_import_dir).expanduser()


# --------------------------------------------------------------------------- #
# Lexing
# --------------------------------------------------------------------------- #
def _unfold(text: str) -> list[str]:
    """Rejoin continuation lines. A line beginning with space or tab is a
    continuation of the previous one, with that first character dropped."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _split_line(line: str) -> tuple[str, dict[str, str], str]:
    """'DTSTART;TZID=Europe/London:20260730T140000' ->
       ('DTSTART', {'TZID': 'Europe/London'}, '20260730T140000')

    Splits on the FIRST colon only: a DESCRIPTION containing 'https://…' has
    colons inside its value, and they belong to the value.
    """
    idx = line.find(":")
    if idx < 0:
        return line.strip().upper(), {}, ""
    head, value = line[:idx], line[idx + 1:]
    parts = head.split(";")
    name = parts[0].strip().upper()
    params = {}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            params[k.strip().upper()] = v.strip().strip('"')
    return name, params, value


def _unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append({"n": "\n", "N": "\n", ",": ",", ";": ";", "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _parse_dt(value: str, params: dict) -> tuple[date | None, str, bool]:
    """Return (date, 'HH:MM' or '', all_day).

    A trailing 'Z' means UTC and is converted to local time — skip that and
    every imported event is an hour out for half the year.
    """
    value = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or (len(value) == 8 and "T" not in value):
        try:
            return date(int(value[0:4]), int(value[4:6]), int(value[6:8])), "", True
        except ValueError:
            return None, "", True
    m = re.match(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?$", value)
    if not m:
        return None, "", False
    y, mo, d, hh, mi, _ss, z = m.groups()
    try:
        dt = datetime(int(y), int(mo), int(d), int(hh), int(mi))
    except ValueError:
        return None, "", False
    if z:                       # UTC -> local, using this machine's offset
        dt = dt.replace(tzinfo=_utc()).astimezone()
        dt = dt.replace(tzinfo=None)
    return dt.date(), f"{dt.hour:02d}:{dt.minute:02d}", False


def _utc():
    from datetime import timezone
    return timezone.utc


# --------------------------------------------------------------------------- #
# Recurrence
# --------------------------------------------------------------------------- #
def _parse_rrule(value: str) -> dict:
    out: dict = {}
    for part in value.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().upper()] = v.strip()
    return out


def expand(start: date, rule: dict, window_from: date, window_to: date,
           exdates: set[date]) -> list[date]:
    """Expand an RRULE into concrete dates inside the window.

    Supports FREQ=DAILY/WEEKLY/MONTHLY/YEARLY with INTERVAL, COUNT, UNTIL and
    (for weekly) BYDAY. Anything more exotic falls back to the single start
    date rather than guessing — a wrong repeating event is far worse than a
    missing one, because it silently fills the calendar with fiction.
    """
    freq = (rule.get("FREQ") or "").upper()
    if freq not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        return [start] if window_from <= start <= window_to else []

    interval = max(1, int(rule.get("INTERVAL") or 1))
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    until = None
    if rule.get("UNTIL"):
        u, _t, _a = _parse_dt(rule["UNTIL"], {})
        until = u

    bydays = [WEEKDAYS[d[-2:].upper()] for d in rule.get("BYDAY", "").split(",")
              if d and d[-2:].upper() in WEEKDAYS]

    out: list[date] = []
    emitted = 0
    cursor = start
    guard = 0
    while cursor <= window_to and guard < 4000:
        guard += 1
        if until and cursor > until:
            break
        if count is not None and emitted >= count:
            break

        if freq == "WEEKLY" and bydays:
            week_start = cursor - timedelta(days=cursor.weekday())
            for wd in sorted(bydays):
                day = week_start + timedelta(days=wd)
                if day < start:
                    continue
                if until and day > until:
                    continue
                if count is not None and emitted >= count:
                    break
                emitted += 1
                if window_from <= day <= window_to and day not in exdates:
                    out.append(day)
            cursor += timedelta(weeks=interval)
            continue

        emitted += 1
        if window_from <= cursor <= window_to and cursor not in exdates:
            out.append(cursor)

        if freq == "DAILY":
            cursor += timedelta(days=interval)
        elif freq == "WEEKLY":
            cursor += timedelta(weeks=interval)
        elif freq == "MONTHLY":
            cursor = _add_months(cursor, interval)
        else:
            cursor = _add_months(cursor, 12 * interval)

        if len(out) >= MAX_OCCURRENCES:
            break
    return out


def _add_months(d: date, n: int) -> date:
    """Month arithmetic that survives the 31st. The 31st + 1 month has no
    correct answer; clamping to the last valid day is the least wrong one, and
    is what calendar apps do."""
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    m += 1
    for day in range(d.day, 27, -1):
        try:
            return date(y, m, day)
        except ValueError:
            continue
    return date(y, m, min(d.day, 28))


# --------------------------------------------------------------------------- #
# Parsing a whole file
# --------------------------------------------------------------------------- #
def parse_ics(text: str, calendar_name: str = "") -> list[dict]:
    """Turn .ics text into event dicts in this app's shape."""
    today = date.today()
    win_from = today - timedelta(days=EXPAND_BACK_DAYS)
    win_to = today + timedelta(days=EXPAND_FORWARD_DAYS)

    events: list[dict] = []
    cur: dict | None = None
    cal_name = calendar_name

    for line in _unfold(text):
        if not line.strip():
            continue
        name, params, value = _split_line(line)

        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            cur = {"exdates": set(), "rrule": None}
            continue
        if name == "END" and value.strip().upper() == "VEVENT":
            if cur:
                events.extend(_materialise(cur, cal_name, win_from, win_to))
            cur = None
            continue
        if cur is None:
            # X-WR-CALNAME is the calendar's own name — worth keeping so several
            # imported calendars stay distinguishable.
            if name == "X-WR-CALNAME" and not calendar_name:
                cal_name = _unescape(value).strip()
            continue

        if name == "SUMMARY":
            cur["title"] = _unescape(value).strip()
        elif name == "DESCRIPTION":
            cur["notes"] = _unescape(value).strip()
        elif name == "LOCATION":
            cur["location"] = _unescape(value).strip()
        elif name == "UID":
            cur["uid"] = value.strip()
        elif name == "DTSTART":
            d, hm, allday = _parse_dt(value, params)
            cur.update({"date": d, "start": hm, "all_day": allday})
        elif name == "DTEND":
            d, hm, allday = _parse_dt(value, params)
            cur.update({"end_date": d, "end": hm})
        elif name == "RRULE":
            cur["rrule"] = _parse_rrule(value)
        elif name == "EXDATE":
            for chunk in value.split(","):
                d, _hm, _a = _parse_dt(chunk, params)
                if d:
                    cur["exdates"].add(d)
        elif name == "STATUS":
            cur["status"] = value.strip().upper()

    return events


def _materialise(cur: dict, cal_name: str, win_from: date, win_to: date) -> list[dict]:
    """One VEVENT -> one or many concrete events."""
    start_d: date | None = cur.get("date")
    if not start_d or not cur.get("title"):
        return []
    if cur.get("status") == "CANCELLED":
        return []

    end_d: date | None = cur.get("end_date")
    # An all-day event's DTEND is EXCLUSIVE — a one-day event ends on the
    # following day. Stored as-is it would show as spanning two days, every time.
    if cur.get("all_day") and end_d and end_d > start_d:
        end_d = end_d - timedelta(days=1)
    span = (end_d - start_d).days if end_d and end_d > start_d else 0

    uid = cur.get("uid") or str(uuid.uuid4())
    rule = cur.get("rrule")
    days = (expand(start_d, rule, win_from, win_to, cur["exdates"]) if rule
            else ([start_d] if win_from <= start_d <= win_to else []))

    out = []
    for occurrence in days:
        out.append({
            "id": f"ics:{uid}:{occurrence.isoformat()}",
            "external_id": uid,
            "title": cur["title"],
            "date": occurrence.isoformat(),
            "start": cur.get("start", ""),
            "end": cur.get("end", ""),
            "end_date": (occurrence + timedelta(days=span)).isoformat() if span else "",
            "all_day": bool(cur.get("all_day")),
            "location": cur.get("location", ""),
            "notes": cur.get("notes", ""),
            "kind": "event",
            "source": "ics",
            "calendar_name": cal_name,
            "recurring": bool(rule),
        })
    return out


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
async def sync(force: bool = False) -> dict:
    """Read every .ics in the import folder and reconcile `:CalEvent`.

    Imported events are replaced wholesale per file, not merged: an event
    deleted in Google simply stops appearing in the next export, and the only
    way to notice that is to treat the file as the truth. Events you created in
    the Mainframe are never touched — they have `source: 'mainframe'`.
    """
    from db import run_read, run_write

    d = import_dir()
    d.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in d.glob("*.ics") if p.is_file())

    summary: dict = {"files": [], "imported": 0, "removed": 0, "dir": str(d)}
    if not files:
        return summary

    seen_ids: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            summary["files"].append({"file": path.name, "error": str(exc)})
            continue
        events = parse_ics(text, calendar_name=path.stem)
        for i in range(0, len(events), 500):
            await run_write(
                """
                UNWIND $rows AS row
                MERGE (e:CalEvent {id: row.id})
                SET e += row, e.updated_at = $ts
                """,
                rows=events[i:i + 500], ts=datetime.now().isoformat(timespec="seconds"),
            )
        seen_ids.extend(e["id"] for e in events)
        summary["files"].append({"file": path.name, "events": len(events)})
        summary["imported"] += len(events)

    # Sweep imported events that no longer appear in any file.
    gone = await run_write(
        """
        MATCH (e:CalEvent) WHERE e.source = 'ics' AND NOT e.id IN $ids
        DETACH DELETE e RETURN count(e) AS n
        """,
        ids=seen_ids,
    )
    summary["removed"] = gone[0]["n"] if gone else 0
    log.info("calendar: imported %d events from %d file(s), swept %d",
             summary["imported"], len(files), summary["removed"])
    return summary

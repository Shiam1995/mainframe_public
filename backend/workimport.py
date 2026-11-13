"""Paste-to-rows for the Database tab.

Turns a block of pasted text (a range copied out of a spreadsheet, a CSV, the
Database tab's own export) into WorkSession-shaped dicts. Pure: no database,
no I/O. The route resolves "On" titles to real things and saves; this only
reads text, so it can be tested on its own.

Each parsed row carries `errors` (the row can't be saved as it stands) and
`warnings` (it can, but check it). Nothing here guesses silently: a value that
didn't parse is reported, never dropped.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, timedelta
from typing import Optional

# header text (lowercased, non-letters squeezed out) → field.
_ALIASES = {
    "date": "date", "day": "date", "when": "date",
    "start": "start", "from": "start", "begin": "start", "started": "start",
    "end": "end", "to": "end", "finish": "end", "until": "end", "stop": "end",
    "mins": "mins", "min": "mins", "minutes": "mins", "time": "mins",
    "duration": "mins", "length": "mins",
    "hours": "hours", "hrs": "hours", "h": "hours",
    "module": "module",
    "refkind": "ref_kind", "on kind": "ref_kind", "kind": "ref_kind",
    "on": "ref_title", "reftitle": "ref_title", "project": "ref_title",
    "title": "ref_title", "subject": "ref_title", "target": "ref_title",
    "type": "kind", "worktype": "kind",
    "what": "what", "whatidid": "what", "description": "what", "task": "what",
    "activity": "what", "did": "what",
    "focus": "focus",
    "notes": "notes", "note": "notes", "comment": "notes", "comments": "notes",
    "completed": "completed", "done": "completed", "pushed": "completed",
}

# With no header, columns are read in the Database tab's own export order, so
# an exported CSV pastes straight back in.
POSITIONAL = ["date", "start", "end", "mins", "module", "ref_kind", "ref_title",
              "kind", "what", "focus", "notes", "completed"]

MODULES = ("synapse", "pulse", "vision", "vault", "mainframe")
WORK_TYPES = ("study", "build", "admin", "body")
FOCUS = ("active", "passive", "none")

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def _key(h: str) -> str:
    return re.sub(r"[^a-z]", "", h.lower())


def _field_of(h: str) -> Optional[str]:
    k = _key(h)
    if not k:
        return None
    # "What I did" → whatidid; "On kind" and friends collapse the same way.
    return _ALIASES.get(k) or {_key(a): f for a, f in _ALIASES.items()}.get(k)


def split_table(text: str) -> list[list[str]]:
    """Text → list of cell lists. Tabs win (a spreadsheet copy is always
    tab-separated), then whichever of , ; | the first line uses most."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        return []
    lines = text.split("\n")
    if any("\t" in ln for ln in lines):
        delim = "\t"
    else:
        first = lines[0]
        delim = max([",", ";", "|"], key=first.count)
        if first.count(delim) == 0:
            delim = ","          # one column: every line is a single cell
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]


def detect_header(first: list[str]) -> Optional[list[Optional[str]]]:
    """The first row's field mapping if it reads as a header, else None.
    Two recognised names — or one, for a one/two-column paste — make a header;
    a data row (a date, a number) never matches a name."""
    fields = [_field_of(c) for c in first]
    hits = sum(1 for f in fields if f)
    if hits >= 2 or (hits == 1 and len(first) <= 2):
        # The export has both `ref_kind` and `kind`: there, `kind` is the work
        # type, not what the work was on.
        keys = [_key(c) for c in first]
        if "refkind" in keys:
            fields = ["kind" if k == "kind" else f for k, f in zip(keys, fields)]
        return fields
    return None


def parse_date(s: str, today: date) -> Optional[str]:
    s = s.strip().lower()
    if not s:
        return None
    if s == "today":
        return today.isoformat()
    if s == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ t].*)?", s)
    if m:
        y, mo, d = map(int, m.groups())
        return _mk(y, mo, d)
    # Day first: 29/09/2026, 29.9.26, 29-9 (UK order — this is a UK box).
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})(?:[/.\-](\d{2,4}))?", s)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        y = int(m.group(3)) if m.group(3) else today.year
        if y < 100:
            y += 2000
        return _mk(y, mo, d)
    # 29 Sep, 29 September 2026, Sep 29 2026, Mon 29 Sep
    words = re.findall(r"[a-z]+|\d+", s)
    mon = next((_MONTHS[w[:3]] for w in words if w[:3] in _MONTHS and w.isalpha()), None)
    nums = [int(w) for w in words if w.isdigit()]
    if mon and nums:
        d = next((n for n in nums if n <= 31), None)
        y = next((n for n in nums if n > 31), today.year)
        if d:
            return _mk(y if y > 99 else y + 2000, mon, d)
    return None


def _mk(y: int, mo: int, d: int) -> Optional[str]:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def parse_time(s: str) -> Optional[str]:
    """'9:05', '09.05', '905', '9am', '2:30 pm' → 'HH:MM'. '' → ''."""
    s = s.strip().lower().replace(" ", "")
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,2})(?:[:.h](\d{2}))?(am|pm)?", s) or \
        re.fullmatch(r"(\d{1,2})(\d{2})(am|pm)?", s)
    if not m:
        return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_mins(s: str, hours: bool = False) -> Optional[int]:
    """Duration → minutes. '90' · '1h30' · '1h 30m' · '1:30' · '1.5h' · '45m'.
    A bare number is minutes, unless the column was headed hours."""
    s = s.strip().lower().replace(" ", "")
    if not s:
        return 0
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", s)
    if m:
        v = float(m.group(1))
        return round(v * 60) if hours else round(v)
    m = re.fullmatch(r"(\d+):(\d{2})", s)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    # 1h30 — minutes straight after an h need no unit
    m = re.fullmatch(r"(\d+(?:\.\d+)?)h(?:rs?|ours?)?(\d+)(?:m(?:ins?|inutes?)?)?", s)
    if m:
        return round(float(m.group(1)) * 60) + int(m.group(2))
    m = re.fullmatch(r"(?:(\d+(?:\.\d+)?)h(?:rs?|ours?)?)?(?:(\d+)m(?:ins?|inutes?)?)?", s)
    if m and (m.group(1) or m.group(2)):
        return round(float(m.group(1) or 0) * 60) + int(m.group(2) or 0)
    return None


_TRUE = {"1", "true", "yes", "y", "x", "✓", "✔", "done", "★", "completed"}


def parse_rows(text: str, today: date, defaults: dict) -> dict:
    """The whole paste → {header, columns, rows}. Each row is the WorkSession
    fields plus `line`, `errors`, `warnings`. `defaults` fills module /
    ref_kind / date where the paste leaves them out."""
    table = split_table(text)
    if not table:
        return {"header": False, "columns": [], "rows": []}
    header = detect_header(table[0])
    body = table[1:] if header else table
    fields = header or POSITIONAL[: max(len(r) for r in body)]
    first_line = 2 if header else 1

    out = []
    for i, cells in enumerate(body):
        raw = {}
        for f, c in zip(fields, cells):
            if f and c and f not in raw:
                raw[f] = c
        errors, warnings = [], []
        row = {
            "line": first_line + i,
            "date": defaults.get("date") or today.isoformat(),
            "start": "", "end": "", "mins": 0,
            "module": defaults.get("module") or "mainframe",
            "ref_kind": (defaults.get("ref_kind") or "").strip(),
            "ref_title": "", "kind": None, "what": "", "focus": "none",
            "notes": "", "completed": False,
        }
        if "date" in raw:
            d = parse_date(raw["date"], today)
            if d:
                row["date"] = d
            else:
                errors.append(f"date “{raw['date']}” not understood")
        for k in ("start", "end"):
            if k in raw:
                t = parse_time(raw[k])
                if t is None:
                    errors.append(f"{k} “{raw[k]}” isn't a time")
                else:
                    row[k] = t
        if "mins" in raw or "hours" in raw:
            src = raw.get("mins") or raw.get("hours")
            v = parse_mins(src, hours="mins" not in raw)
            if v is None:
                errors.append(f"time “{src}” isn't a duration")
            else:
                row["mins"] = v
        if "module" in raw:
            v = raw["module"].lower()
            if v in MODULES:
                row["module"] = v
            else:
                warnings.append(f"module “{raw['module']}” unknown → {row['module']}")
        if "ref_kind" in raw:
            row["ref_kind"] = raw["ref_kind"].strip().lower()
        if "kind" in raw:
            v = raw["kind"].lower()
            if v in WORK_TYPES:
                row["kind"] = v
            else:
                warnings.append(f"type “{raw['kind']}” unknown → taken from the project")
        if "focus" in raw:
            v = raw["focus"].lower()
            v = {"—": "none", "-": "none", "n/a": "none", "": "none"}.get(v, v)
            if v in FOCUS:
                row["focus"] = v
            else:
                warnings.append(f"focus “{raw['focus']}” unknown → none")
        for k in ("ref_title", "what", "notes"):
            row[k] = raw.get(k, "")
        if "completed" in raw:
            row["completed"] = raw["completed"].strip().lower() in _TRUE

        if not row["mins"] and not (row["start"] and row["end"]) and not errors:
            warnings.append("no duration — logs as 0 min")
        if not (row["ref_title"] or row["what"] or row["notes"]):
            warnings.append("nothing says what this was")
        row["errors"], row["warnings"] = errors, warnings
        out.append(row)
    return {"header": bool(header), "columns": fields, "rows": out}

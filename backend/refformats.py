"""Structured bibliography formats: BibTeX/BibLaTeX, RIS, and EndNote/Refer.

Everything else in this package guesses where one field ends and the next
begins. These three formats already say so, and people paste them constantly —
Zotero, Mendeley, JabRef and Google Scholar's "Cite" all hand out BibTeX or
RIS. Running that through prose heuristics throws away a perfect answer, so
these are parsed exactly and never reach the heuristic path.

Only the parts that decide a field's value are implemented. Rendering,
sorting, label generation and cross-reference inheritance are BibTeX's job,
not ours.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- #
# Sniffing
# --------------------------------------------------------------------------- #
_BIBTEX_ENTRY = re.compile(r"@\s*[A-Za-z]+\s*[{(]", re.MULTILINE)
_RIS_TY = re.compile(r"^TY\s{2}-\s", re.MULTILINE)
_RIS_TAG = re.compile(r"^[A-Z][A-Z0-9]\s{2}-(?:\s|$)", re.MULTILINE)
_ENW_TAG = re.compile(r"^%[A-Za-z0-9!$&*?@\[\]^~+<>()]\s", re.MULTILINE)


def sniff(text: str) -> str | None:
    """"bibtex" | "ris" | "enw" | None — None meaning "this is prose"."""
    if _RIS_TY.search(text) and len(_RIS_TAG.findall(text)) >= 3:
        return "ris"
    if len(_BIBTEX_ENTRY.findall(text)) >= 1 and "=" in text:
        return "bibtex"
    if len(_ENW_TAG.findall(text)) >= 3:
        return "enw"
    return None


# --------------------------------------------------------------------------- #
# BibTeX
# --------------------------------------------------------------------------- #
# A value is brace-balanced, and a literal quote can only appear inside braces,
# so both delimiters need a depth-counting scan rather than a regex.
def _read_value(src: str, i: int, macros: dict[str, str]) -> tuple[str, int]:
    parts: list[str] = []
    while i < len(src):
        while i < len(src) and src[i].isspace():
            i += 1
        if i >= len(src):
            break
        c = src[i]
        if c == "{":
            depth, j = 1, i + 1
            while j < len(src) and depth:
                if src[j] == "\\":
                    j += 2
                    continue
                depth += (src[j] == "{") - (src[j] == "}")
                j += 1
            parts.append(src[i + 1:j - 1])
            i = j
        elif c == '"':
            depth, j = 0, i + 1
            while j < len(src):
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "{":
                    depth += 1
                elif src[j] == "}":
                    depth -= 1
                elif src[j] == '"' and depth == 0:
                    break
                j += 1
            parts.append(src[i + 1:j])
            i = j + 1
        else:
            m = re.match(r"[^\s,#}\)]+", src[i:])
            if not m:
                break
            tok = m.group(0)
            # a bare token is a number, or an @string macro to look up
            parts.append(tok if tok.isdigit() else macros.get(tok.lower(), tok))
            i += len(tok)
        while i < len(src) and src[i].isspace():
            i += 1
        if i < len(src) and src[i] == "#":       # concatenation
            i += 1
            continue
        break
    return "".join(parts), i


# The 13 accents that survive purification, plus the ligatures. Enough to turn
# TeX escapes back into the text a person would search for.
_ACCENTS = {
    r"\\i": "i", r"\\j": "j", r"\\oe": "oe", r"\\OE": "OE", r"\\ae": "ae",
    r"\\AE": "AE", r"\\aa": "a", r"\\AA": "A", r"\\o": "o", r"\\O": "O",
    r"\\l": "l", r"\\L": "L", r"\\ss": "ss",
}
_ACCENT_CMD = re.compile(r"\\[`'^\"~=.uvHtcdbr]\s*\{?([A-Za-z])\}?")


def detex(v: str) -> str:
    """TeX source → the text a reader sees. Braces carry case protection, not
    meaning, so they are dropped once nothing else needs them."""
    v = _ACCENT_CMD.sub(r"\1", v)
    for cmd, rep in _ACCENTS.items():
        v = re.sub(cmd + r"(?![A-Za-z])", rep, v)
    v = re.sub(r"\\[A-Za-z]+\s*", "", v)
    v = v.replace("{", "").replace("}", "").replace("\\", "")
    v = v.replace("---", "\u2014").replace("--", "\u2013").replace("~", " ")
    return re.sub(r"\s+", " ", v).strip()


def split_names(field: str) -> list[str]:
    """Split an author/editor field on the keyword `and` at brace depth 0."""
    out, depth, cur = [], 0, []
    toks = re.split(r"(\s+)", field)
    for t in toks:
        depth += t.count("{") - t.count("}")
        if t.strip().lower() == "and" and depth == 0 and cur:
            out.append("".join(cur).strip())
            cur = []
            continue
        cur.append(t)
    if "".join(cur).strip():
        out.append("".join(cur).strip())
    return [n for n in out if n]


def _tokens(part: str) -> list[str]:
    """Split a name part on whitespace at brace depth 0 only.

    Two words inside one brace group always belong to the same part, which is
    how a corporate author survives as a single family name:
    "{Association for Computing Machinery}" is ONE token, not four.
    """
    out, depth, cur = [], 0, []
    for ch in part:
        depth += (ch == "{") - (ch == "}")
        if ch.isspace() and depth == 0:
            if cur:
                out.append("".join(cur))
                cur = []
            continue
        cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def name_parts(name: str) -> dict:
    """One BibTeX name → {given, von, family, suffix}.

    The three forms are chosen by counting commas at brace depth 0:
        0 commas  "First von Last"
        1 comma   "von Last, First"
        2 commas  "von Last, Jr, First"
    In the comma-less form the von part is the run from the first
    lowercase-initial token to the last — which is why "Jean de La Fontaine"
    parses correctly and "jean de la fontaine" does not have a First at all.
    """
    if name.strip().lower() == "others":
        return {"given": "", "von": "", "family": "others", "suffix": ""}
    chunks, depth, cur = [], 0, []
    for ch in name:
        depth += (ch == "{") - (ch == "}")
        if ch == "," and depth == 0:
            chunks.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    chunks.append("".join(cur))

    def lower(tok: str) -> bool:
        """Does this token start with a lowercase letter at brace depth 0?

        A braced token has NO depth-0 character, so it is not lowercase-initial
        whatever it contains — which is the whole point of writing
        "Jean {de} la fontaine" to keep "de" out of the von part.
        """
        t = tok.lstrip("\\")
        if t[:1] == "{":
            return False
        return t[:1].islower()

    def pack(given, von, family, suffix):
        strip = lambda x: re.sub(r"\s+", " ", x.replace("{", "").replace("}", "")).strip()
        return {"given": strip(given), "von": strip(von),
                "family": strip(family), "suffix": strip(suffix)}

    if len(chunks) == 1:
        toks = _tokens(chunks[0])
        if not toks:
            return pack("", "", "", "")
        # "First von Last": the von runs from the FIRST lowercase-initial token
        # to the LAST one; everything before is First and everything after Last.
        lows = [i for i, t in enumerate(toks[:-1]) if lower(t)]
        if lows:
            a, b = lows[0], lows[-1]
            return pack(" ".join(toks[:a]), " ".join(toks[a:b + 1]),
                        " ".join(toks[b + 1:]), "")
        return pack(" ".join(toks[:-1]), "", toks[-1], "")

    # "von Last, First" / "von Last, Jr, First": here the von is the longest
    # PREFIX ending on a lowercase-initial token, so "De la Fontaine" gives
    # von="De la" and not von="la".
    head = _tokens(chunks[0])
    given = chunks[-1].strip()
    suffix = chunks[1].strip() if len(chunks) > 2 else ""
    lows = [i for i, t in enumerate(head[:-1]) if lower(t)]
    if lows:
        b = lows[-1]
        return pack(given, " ".join(head[:b + 1]), " ".join(head[b + 1:]), suffix)
    return pack(given, "", " ".join(head), suffix)


# `journal` is BibTeX's name for what biblatex calls `journaltitle`; the
# aliases are resolved on read, exactly as biber does.
_ALIASES = {"journaltitle": "journal", "address": "location", "school": "institution",
            "annote": "annotation", "archiveprefix": "eprinttype"}
_VENUE_FIELDS = ("journal", "booktitle", "publisher", "institution", "series", "howpublished")


def parse_bibtex(text: str) -> list[dict]:
    """A .bib file → [{title, year, link, venue, authors, type, key, raw}]."""
    macros: dict[str, str] = {}
    out: list[dict] = []
    for m in re.finditer(r"@\s*([A-Za-z]+)\s*[{(]", text):
        kind = m.group(1).lower()
        i = m.end()
        if kind in ("comment",):
            continue
        if kind in ("string", "preamble"):
            if kind == "string":
                mm = re.match(r"\s*([A-Za-z][\w:.-]*)\s*=\s*", text[i:])
                if mm:
                    val, _ = _read_value(text, i + mm.end(), macros)
                    macros[mm.group(1).lower()] = val
            continue
        km = re.match(r"\s*([^\s,]*)\s*,", text[i:])
        key = km.group(1) if km else ""
        i += km.end() if km else 0
        fields: dict[str, str] = {}
        while i < len(text):
            fm = re.match(r"\s*([A-Za-z][\w:.-]*)\s*=\s*", text[i:])
            if not fm:
                break
            name = fm.group(1).lower()
            val, i = _read_value(text, i + fm.end(), macros)
            fields[_ALIASES.get(name, name)] = val
            mm = re.match(r"\s*,", text[i:])
            if not mm:
                break
            i += mm.end()
        if not fields:
            continue
        # detex AFTER dissection: "{de}" parses differently from "de", and
        # stripping the braces first silently changes the answer.
        authors = [{k: detex(v) for k, v in name_parts(n).items()}
                   for n in split_names(fields.get("author", ""))]
        doi = detex(fields.get("doi", ""))
        url = detex(fields.get("url", ""))
        eprint = detex(fields.get("eprint", ""))
        venue = next((detex(fields[f]) for f in _VENUE_FIELDS if fields.get(f)), None)
        year = fields.get("year") or ""
        if not year and fields.get("date"):
            ym = re.search(r"(?:19|20)\d{2}", fields["date"])
            year = ym.group(0) if ym else ""
        ym = re.search(r"\d{4}", year)
        out.append({
            "type": kind,
            "key": key,
            "title": detex(fields.get("title", "")) or None,
            "year": int(ym.group(0)) if ym else None,
            "venue": venue,
            "authors": ", ".join(
                " ".join(p for p in (a["given"], a["von"], a["family"], a["suffix"]) if p)
                for a in authors) or None,
            "link": (url or (f"https://doi.org/{doi}" if doi else "")
                     or (f"https://arxiv.org/abs/{eprint}" if eprint else "")) or None,
            "raw": text[m.start():i][:400],
        })
    return out


# --------------------------------------------------------------------------- #
# RIS
# --------------------------------------------------------------------------- #
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])\s{2}-\s?(.*)$")
# Producers disagree about which tag holds the title and which the container,
# so several are accepted for each and the first one present wins.
_RIS_TITLE = ("TI", "T1", "CT", "BT")
_RIS_VENUE = ("T2", "JF", "JO", "J2", "JA", "BT", "T3")
_RIS_AUTHOR = ("AU", "A1", "A2", "A3", "A4")


def parse_ris(text: str) -> list[dict]:
    """A .ris file → the same records. `TY` opens a record and `ER` closes it."""
    records: list[dict] = []
    cur: dict[str, list[str]] = {}
    last: str | None = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = _RIS_LINE.match(line)
        if m:
            tag, val = m.group(1), m.group(2).strip()
            if tag == "TY":
                cur, last = {"TY": [val]}, "TY"
                continue
            if tag == "ER":
                if cur:
                    records.append(_ris_record(cur))
                cur, last = {}, None
                continue
            cur.setdefault(tag, []).append(val)
            last = tag
        elif line.strip() and last and cur:
            # a continuation line carries no tag; it belongs to the tag above
            cur[last][-1] = (cur[last][-1] + " " + line.strip()).strip()
    if cur:
        records.append(_ris_record(cur))
    return records


def _ris_record(f: dict[str, list[str]]) -> dict:
    first = lambda tags: next((f[t][0] for t in tags if f.get(t)), None)
    title = first(_RIS_TITLE)
    venue = next((f[t][0] for t in _RIS_VENUE if f.get(t) and f[t][0] != title), None)
    year = None
    for t in ("PY", "Y1", "DA", "YR"):
        if f.get(t):
            ym = re.search(r"(?:19|20)\d{2}", f[t][0])
            if ym:
                year = int(ym.group(0))
                break
    doi = first(("DO", "DI", "DOI"))
    url = next((u for t in ("UR", "L2") for u in f.get(t, []) if u.startswith("http")), None)
    authors = [a for t in _RIS_AUTHOR for a in f.get(t, [])]
    return {
        "type": (f.get("TY") or [""])[0].lower(),
        "key": (f.get("ID") or [""])[0],
        "title": title,
        "year": year,
        "venue": venue,
        "authors": "; ".join(authors) or None,
        "link": url or (f"https://doi.org/{doi}" if doi else None),
        "raw": "; ".join(f"{k}: {v[0]}" for k, v in list(f.items())[:8])[:400],
    }


# --------------------------------------------------------------------------- #
# EndNote / Refer
# --------------------------------------------------------------------------- #
# EndNote reassigned several of refer's letters, and a parser that assumes
# refer puts a DOI into "report number" and an abstract into "annotation". The
# presence of "%0" is what says which dialect this is.
_ENW_LINE = re.compile(r"^%(.)\s(.*)$")


def parse_enw(text: str) -> list[dict]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    out: list[dict] = []
    for block in blocks:
        f: dict[str, list[str]] = {}
        last = None
        for line in block.split("\n"):
            m = _ENW_LINE.match(line)
            if m:
                f.setdefault(m.group(1), []).append(m.group(2).strip())
                last = m.group(1)
            elif line.strip() and last:
                f[last][-1] += " " + line.strip()
        if not f.get("T"):
            continue
        endnote = "0" in f
        year = None
        if f.get("D"):
            ym = re.search(r"(?:19|20)\d{2}", f["D"][0])
            year = int(ym.group(0)) if ym else None
        out.append({
            "type": (f.get("0") or [""])[0].lower(),
            "key": (f.get("F") or [""])[0],
            "title": f["T"][0],
            "year": year,
            "venue": (f.get("J") or f.get("B") or f.get("I") or [None])[0],
            "authors": "; ".join(f.get("A", [])) or None,
            # %R is a DOI in EndNote and a report number in plain refer
            "link": (f"https://doi.org/{f['R'][0]}"
                     if endnote and f.get("R") and f["R"][0].startswith("10.")
                     else (f.get("U") or [None])[0]),
            "raw": block.strip()[:400],
        })
    return out


def parse(text: str) -> list[dict] | None:
    """Structured records if the text is one of these formats, else None."""
    kind = sniff(text)
    if kind == "bibtex":
        return parse_bibtex(text) or None
    if kind == "ris":
        return parse_ris(text) or None
    if kind == "enw":
        return parse_enw(text) or None
    return None

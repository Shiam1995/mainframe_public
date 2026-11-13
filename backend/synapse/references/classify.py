"""Classify a reference on TWO orthogonal axes. Never collapse them.

  form    — what kind of document it is
  warrant — why it can be trusted

A Horizon 2020 annex is (policy-document, institutional-primary): not peer
reviewed, definitionally authoritative for what it defines. A vendor's
"readiness index primer" is (webpage, unwarranted). Both are "not peer
reviewed"; they are epistemically opposite — which is exactly why one field
can't hold both facts.

Form comes free from Crossref's `type` when resolution succeeded; otherwise
it's inferred from the entry text. Warrant is ALWAYS inferred (there is no
registry of trustworthiness), so every classification carries
warrant_source="inferred" until a human confirms it — then it's "manual".
"""
from __future__ import annotations

import re

FORMS = {"journal-article", "proceedings-article", "report", "policy-document",
         "book-chapter", "webpage", "event", "dataset"}
WARRANTS = {"peer-reviewed", "institutional-primary", "commissioned", "trade",
            "unwarranted"}

# Crossref `type` → our form. Anything unmapped falls back to the heuristics.
_CROSSREF_FORM = {
    "journal-article": "journal-article",
    "proceedings-article": "proceedings-article",
    "book-chapter": "book-chapter",
    "book-section": "book-chapter",
    "book-part": "book-chapter",
    "report": "report",
    "report-component": "report",
    "dataset": "dataset",
    "posted-content": "webpage",
    # OpenAlex types that differ from Crossref's
    "article": "journal-article",
}

_INSTITUTIONAL = re.compile(
    r"european commission|joint research centre|\bJRC\b|department of|ministry|"
    r"innovation fund|european union|\bOECD\b|united nations|\bNASA\b|"
    r"government|directorate|council of the eu|\bEIT\b|federal|agency",
    re.IGNORECASE,
)
_COMMISSIONED = re.compile(
    r"a study for|commissioned by|on behalf of|consult(?:ing)?\b|report to the",
    re.IGNORECASE,
)
_POLICY = re.compile(
    r"annex|declaration|work programme|directive|regulation|communication|"
    r"white paper|framework|action plan|brochure",
    re.IGNORECASE,
)
_EVENT = re.compile(r"workshop held|conference held|proceedings of the .* held|webinar",
                    re.IGNORECASE)
_JOURNAL_SIG = re.compile(
    r"(?:journal|transactions|acta|quarterly|review)\b.*\d+.*\(\d{4}\)|"
    r"\b\d+,\s*\d+\s*\(\d{4}\),\s*\d+[-–]\d+",
    re.IGNORECASE,
)
_PROCEEDINGS = re.compile(r"\bIn (?:Proceedings|.*Conference|.*Symposium)\b|\bICSGSC\b",
                          re.IGNORECASE)
_EDITED_VOLUME = re.compile(r"\(Eds?\.\)", re.IGNORECASE)


def _infer_form(parsed: dict) -> str:
    raw = parsed.get("raw_string", "")
    if _EVENT.search(raw):
        return "event"
    if _POLICY.search(raw) and _INSTITUTIONAL.search(raw):
        return "policy-document"
    if _PROCEEDINGS.search(raw):
        return "proceedings-article"
    if _EDITED_VOLUME.search(raw):
        return "book-chapter"
    if _JOURNAL_SIG.search(raw) or parsed.get("issn"):
        return "journal-article"
    if re.search(r"\breport\b|\bguide\b|\bstudy\b|\banalysis\b", raw, re.IGNORECASE) \
            and _INSTITUTIONAL.search(raw):
        return "report"
    if parsed.get("url"):
        return "webpage"
    return "report" if _INSTITUTIONAL.search(raw) else "webpage"


def _infer_warrant(parsed: dict, form: str, resolved: bool) -> str:
    raw = parsed.get("raw_string", "")
    # order matters: a commissioned study MENTIONS the institution it was done
    # for, so the commissioned test must run before the institutional one
    if _COMMISSIONED.search(raw):
        return "commissioned"
    if form in ("journal-article", "proceedings-article", "book-chapter"):
        if resolved or parsed.get("issn") or parsed.get("doi"):
            return "peer-reviewed"
    if _INSTITUTIONAL.search(raw) or any(a.get("is_org") for a in parsed.get("authors", [])):
        return "institutional-primary"
    if form == "webpage" and parsed.get("authors"):
        return "trade"          # a bylined piece on someone else's site
    return "unwarranted"


def classify(parsed: dict, resolution: dict) -> dict:
    """→ {form, warrant, warrant_source}. `resolution` is resolve.py's result."""
    resolved = resolution.get("resolved") or {}
    form = _CROSSREF_FORM.get(resolved.get("crossref_type") or "")
    if form is None:
        form = _infer_form(parsed)
    warrant = _infer_warrant(parsed, form, resolved=bool(resolved))
    return {"form": form, "warrant": warrant, "warrant_source": "inferred"}

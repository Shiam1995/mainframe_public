"""Markdown → HTML, hand-rolled, zero dependencies.

There is exactly ONE renderer in this app and it lives here. The editor's live
preview calls it over `POST /api/docs/render` rather than shipping a second
implementation in JavaScript — a preview that quietly disagrees with the
exported file is worse than a slow preview, and on localhost the round trip is
sub-millisecond.

Supported: headings, bold/italic/strike, inline code, fenced code, links,
images, ordered/unordered/task lists (nested), blockquotes, tables, horizontal
rules, hard line breaks, and raw paragraphs. Deliberately not a CommonMark
implementation — it covers what a person actually writes in a document.
"""
from __future__ import annotations

import html
import re

# --------------------------------------------------------------------------- #
# Inline
# --------------------------------------------------------------------------- #
_CODE_SPAN = re.compile(r"`([^`]+)`")
# One level of balanced parens is allowed inside the target so that links like
# en.wikipedia.org/wiki/Mainframe_(computing) survive intact.
_URL_PART = r"((?:[^()\s]|\([^()\s]*\))+)"
_IMAGE = re.compile(r"!\[([^\]]*)\]\(" + _URL_PART + r"(?:\s+\"([^\"]*)\")?\)")
_LINK = re.compile(r"\[([^\]]+)\]\(" + _URL_PART + r"(?:\s+\"([^\"]*)\")?\)")
_BOLD_ITALIC = re.compile(r"\*\*\*(?=\S)(.+?)(?<=\S)\*\*\*", re.S)
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", re.S)
_ITALIC = re.compile(r"(?<![*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![*\w])", re.S)
_UNDER_ITALIC = re.compile(r"(?<![_\w])_(?=\S)([^_]+?)(?<=\S)_(?![_\w])", re.S)
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S)
_AUTOLINK = re.compile(r"(?<![\"'=(\w])(https?://[^\s<>\")\]]+)")

# Safe subset for link/image targets. Blocks javascript: and data: URIs, which
# is the one place a pasted document could otherwise carry something executable.
_SAFE_URL = re.compile(r"^(https?://|mailto:|/|\./|\.\./|#|[\w.\-]+/)", re.I)


def _url(raw: str) -> str:
    raw = raw.strip()
    return html.escape(raw, quote=True) if _SAFE_URL.match(raw) else "#"


def inline(text: str) -> str:
    """Escape, then apply inline markup. Code spans are held out of the way so
    `**not bold**` inside backticks stays literal."""
    stash: list[str] = []

    def hold(m: re.Match) -> str:
        stash.append("<code>" + html.escape(m.group(1)) + "</code>")
        return f"\x00{len(stash) - 1}\x00"

    text = _CODE_SPAN.sub(lambda m: hold(m), html.escape(text))
    # html.escape already turned the quotes in ![alt](src "title") into &quot;,
    # so the patterns below match on the escaped form.
    text = _IMAGE.sub(
        lambda m: f'<img src="{_url(m.group(2))}" alt="{m.group(1)}">', text)
    text = _LINK.sub(
        lambda m: f'<a href="{_url(m.group(2))}" target="_blank" rel="noopener">{m.group(1)}</a>',
        text)
    text = _BOLD_ITALIC.sub(r"<strong><em>\1</em></strong>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    text = _UNDER_ITALIC.sub(r"<em>\1</em>", text)
    text = _STRIKE.sub(r"<del>\1</del>", text)
    text = _AUTOLINK.sub(r'<a href="\1" target="_blank" rel="noopener">\1</a>', text)
    # Two trailing spaces = hard break, per markdown convention.
    text = re.sub(r"  +\n", "<br>\n", text)
    for i, code in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", code)
    return text


# --------------------------------------------------------------------------- #
# Block
# --------------------------------------------------------------------------- #
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_HR = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_QUOTE = re.compile(r"^\s*>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def _slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", re.sub(r"<[^>]+>", "", text)).strip().lower()
    return re.sub(r"[\s_]+", "-", s) or "section"


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def render(md: str) -> str:
    """Render markdown to an HTML fragment (no <html>/<body> wrapper)."""
    lines = (md or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    para: list[str] = []
    # Open list stack: (indent, tag, nested) — lets nested lists close in the
    # right order. `nested` records that this list was opened *inside* the
    # previous <li> (whose closing tag was rewound), so closing it has to put
    # that </li> back.
    stack: list[tuple[int, str, bool]] = []
    i = 0

    def flush_para() -> None:
        if para:
            out.append("<p>" + inline("\n".join(para).strip()) + "</p>")
            para.clear()

    def open_list(indent: int, tag: str) -> None:
        """Open a list, tucking it inside the preceding <li> when nesting."""
        nested = bool(stack) and bool(out) and out[-1].endswith("</li>")
        if nested:
            out[-1] = out[-1][: -len("</li>")]
        out.append(f"<{tag}>")
        stack.append((indent, tag, nested))

    def close_lists(to_indent: int = -1) -> None:
        while stack and stack[-1][0] > to_indent:
            _, tag, nested = stack.pop()
            out.append(f"</{tag}>" + ("</li>" if nested else ""))

    while i < len(lines):
        line = lines[i]

        fence = _FENCE.match(line)
        if fence:
            flush_para(); close_lists()
            lang = fence.group(2)
            body: list[str] = []
            i += 1
            while i < len(lines) and not _FENCE.match(lines[i]):
                body.append(lines[i]); i += 1
            i += 1  # skip the closing fence
            cls = f' class="language-{html.escape(lang)}"' if lang else ""
            out.append(f"<pre><code{cls}>" + html.escape("\n".join(body)) + "</code></pre>")
            continue

        if not line.strip():
            flush_para(); close_lists()
            i += 1
            continue

        if _HR.match(line):
            flush_para(); close_lists()
            out.append("<hr>")
            i += 1
            continue

        h = _HEADING.match(line)
        if h:
            flush_para(); close_lists()
            level = len(h.group(1))
            text = inline(h.group(2))
            out.append(f'<h{level} id="{_slug(h.group(2))}">{text}</h{level}>')
            i += 1
            continue

        # Table: a header row followed by a |---|---| separator.
        if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
            flush_para(); close_lists()
            headers = _split_row(line)
            aligns = []
            for spec in _split_row(lines[i + 1]):
                left, right = spec.startswith(":"), spec.endswith(":")
                aligns.append("center" if left and right else "right" if right else "left" if left else "")
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                rows.append(_split_row(lines[i])); i += 1
            def cell(tag: str, val: str, idx: int) -> str:
                a = aligns[idx] if idx < len(aligns) else ""
                style = f' style="text-align:{a}"' if a else ""
                return f"<{tag}{style}>{inline(val)}</{tag}>"
            head = "".join(cell("th", h, n) for n, h in enumerate(headers))
            body = "".join(
                "<tr>" + "".join(cell("td", c, n) for n, c in enumerate(r)) + "</tr>"
                for r in rows
            )
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            continue

        q = _QUOTE.match(line)
        if q:
            flush_para(); close_lists()
            block: list[str] = []
            while i < len(lines):
                m = _QUOTE.match(lines[i])
                if m is None:
                    break
                block.append(m.group(1)); i += 1
            out.append("<blockquote>" + render("\n".join(block)) + "</blockquote>")
            continue

        ul, ol = _UL.match(line), _OL.match(line)
        if ul or ol:
            flush_para()
            indent = len(((ul or ol).group(1)).expandtabs(4))
            tag = "ul" if ul else "ol"
            content = ul.group(2) if ul else ol.group(3)
            close_lists(indent)
            if not stack or stack[-1][0] < indent:
                open_list(indent, tag)
            elif stack[-1][1] != tag:            # same level, different kind
                _, old, nested = stack.pop()
                out.append(f"</{old}>" + ("</li>" if nested else ""))
                open_list(indent, tag)
            task = _TASK.match(content)
            if task:
                checked = " checked" if task.group(1).lower() == "x" else ""
                out.append(
                    f'<li class="task"><input type="checkbox" disabled{checked}> '
                    f"{inline(task.group(2))}</li>")
            else:
                out.append(f"<li>{inline(content)}</li>")
            i += 1
            continue

        close_lists()
        para.append(line)
        i += 1

    flush_para()
    close_lists()
    return "\n".join(out)


def outline(md: str) -> list[dict]:
    """Headings, for the document sidebar's jump-to list."""
    items: list[dict] = []
    in_fence = False
    for line in (md or "").split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        h = _HEADING.match(line)
        if h:
            items.append({"level": len(h.group(1)), "text": h.group(2).strip(),
                          "id": _slug(h.group(2))})
    return items


def stats(text: str) -> dict:
    """Word/character/reading-time counts shown in the editor status bar."""
    words = len(re.findall(r"\b[\w'-]+\b", text or ""))
    return {
        "words": words,
        "chars": len(text or ""),
        "lines": len((text or "").split("\n")),
        # 200 wpm is the usual prose estimate; always show at least a minute.
        "read_mins": max(1, round(words / 200)) if words else 0,
    }

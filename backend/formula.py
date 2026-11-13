"""Spreadsheet formulas — parser and evaluator, zero dependencies.

Lives on the server, like `mdrender`, and for the same reason: the grid, the
CSV export and the JSON export must all agree about what a formula column
contains. A second implementation in the browser would eventually disagree, and
the disagreement would surface as a wrong number in an exported file.

    =[Price] * [Qty]                    row-wise arithmetic
    =SUM([Total])                       aggregate down a whole column
    =IF([Qty] > 10, "bulk", "single")   conditionals
    =ROUND([Total] / SUM([Total]) * 100, 1)

Deliberately NOT eval(). The grammar below is the entire language: there is no
attribute access, no indexing, no way to reach a Python object.
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from typing import Any

# Functions that consume a whole column rather than one row's cell.
AGGREGATES = {"SUM", "AVG", "MEAN", "MIN", "MAX", "COUNT", "COUNTA", "MEDIAN"}


class FormulaError(Exception):
    """Raised for anything malformed. Surfaces in the cell as #ERROR, never
    as a 500 — a typo in one formula must not take the sheet down."""


# --------------------------------------------------------------------------- #
# Tokeniser
# --------------------------------------------------------------------------- #
_TOKEN = re.compile(r"""
    (?P<ws>\s+)
  | (?P<num>\d+\.?\d*(?:[eE][-+]?\d+)?)
  | (?P<str>"[^"]*"|'[^']*')
  | (?P<ref>\[[^\]]*\])
  | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
  | (?P<op><>|<=|>=|[-+*/%^<>=&(),])
""", re.X)


def _tokenise(src: str) -> list[tuple[str, str]]:
    out, i = [], 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise FormulaError(f"unexpected character {src[i]!r}")
        i = m.end()
        kind = m.lastgroup
        if kind == "ws":
            continue
        out.append((kind, m.group()))
    return out


# --------------------------------------------------------------------------- #
# Parser — precedence climbing. Nodes are plain tuples.
# --------------------------------------------------------------------------- #
# Lowest precedence first; `expr(level)` walks down this list.
_BINARY = [
    {"=", "<>", "<", "<=", ">", ">="},
    {"&"},
    {"+", "-"},
    {"*", "/", "%"},
]


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.t = tokens
        self.i = 0

    def peek(self) -> tuple[str, str] | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self) -> tuple[str, str]:
        if self.i >= len(self.t):
            raise FormulaError("formula ends unexpectedly")
        self.i += 1
        return self.t[self.i - 1]

    def expect(self, value: str) -> None:
        tok = self.take()
        if tok[1] != value:
            raise FormulaError(f"expected {value!r}, found {tok[1]!r}")

    def parse(self) -> Any:
        node = self.expr(1)
        if self.peek():
            raise FormulaError(f"unexpected {self.peek()[1]!r}")
        return node

    def expr(self, level: int) -> Any:
        if level > len(_BINARY):
            return self.unary()
        ops = _BINARY[level - 1]
        node = self.expr(level + 1)
        while self.peek() and self.peek()[0] == "op" and self.peek()[1] in ops:
            op = self.take()[1]
            node = ("bin", op, node, self.expr(level + 1))
        return node

    def unary(self) -> Any:
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in "+-":
            self.take()
            return ("neg", self.unary()) if tok[1] == "-" else self.unary()
        return self.power()

    def power(self) -> Any:
        base = self.atom()
        if self.peek() and self.peek()[1] == "^":
            self.take()
            return ("bin", "^", base, self.unary())   # right-associative
        return base

    def atom(self) -> Any:
        kind, text = self.take()
        if kind == "num":
            return ("lit", float(text))
        if kind == "str":
            return ("lit", text[1:-1])
        if kind == "ref":
            return ("ref", text[1:-1].strip())
        if kind == "name":
            if self.peek() and self.peek()[1] == "(":
                self.take()
                args = []
                if self.peek() and self.peek()[1] != ")":
                    args.append(self.expr(1))
                    while self.peek() and self.peek()[1] == ",":
                        self.take()
                        args.append(self.expr(1))
                self.expect(")")
                return ("call", text.upper(), args)
            upper = text.upper()
            if upper in {"TRUE", "FALSE"}:
                return ("lit", upper == "TRUE")
            return ("ref", text)          # bare word = column name
        if text == "(":
            node = self.expr(1)
            self.expect(")")
            return node
        raise FormulaError(f"unexpected {text!r}")


def parse(src: str) -> Any:
    src = (src or "").strip()
    if src.startswith("="):
        src = src[1:]
    if not src.strip():
        raise FormulaError("empty formula")
    return _Parser(_tokenise(src)).parse()


# --------------------------------------------------------------------------- #
# Evaluator
# --------------------------------------------------------------------------- #
def _num(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").strip().rstrip("%"))
    except ValueError:
        raise FormulaError(f"{v!r} is not a number")


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return bool(v) and str(v).strip().lower() not in {"false", "no", "0"}


def _numbers(vals: list[Any]) -> list[float]:
    out = []
    for v in vals:
        if v is None or v == "" or isinstance(v, str) and not v.strip():
            continue
        try:
            out.append(_num(v))
        except FormulaError:
            continue
    return out


def _call(name: str, args: list[Any], column: Any) -> Any:
    """`column` yields a whole column's values, for aggregates."""
    if name in AGGREGATES:
        vals = column(args[0]) if args else []
        if name == "COUNTA":
            return float(len([v for v in vals if v not in (None, "")]))
        nums = _numbers(vals)
        if name == "COUNT":
            return float(len(nums))
        if not nums:
            return 0.0
        if name == "SUM":
            return math.fsum(nums)
        if name in {"AVG", "MEAN"}:
            return math.fsum(nums) / len(nums)
        if name == "MIN":
            return min(nums)
        if name == "MAX":
            return max(nums)
        if name == "MEDIAN":
            s = sorted(nums)
            mid = len(s) // 2
            return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2
    a = args
    if name == "IF":
        if len(a) < 2:
            raise FormulaError("IF needs a condition and a value")
        return a[1] if _truthy(a[0]) else (a[2] if len(a) > 2 else "")
    if name == "AND":
        return all(_truthy(x) for x in a)
    if name == "OR":
        return any(_truthy(x) for x in a)
    if name == "NOT":
        return not _truthy(a[0])
    if name == "ISBLANK":
        return a[0] in (None, "") if a else True
    if name == "ROUND":
        digits = int(_num(a[1])) if len(a) > 1 else 0
        return round(_num(a[0]), digits)
    if name == "FLOOR":
        return float(math.floor(_num(a[0])))
    if name == "CEIL" or name == "CEILING":
        return float(math.ceil(_num(a[0])))
    if name == "ABS":
        return abs(_num(a[0]))
    if name == "SQRT":
        return math.sqrt(_num(a[0]))
    if name == "POW":
        return _num(a[0]) ** _num(a[1])
    if name == "LEN":
        return float(len(_text(a[0])))
    if name == "UPPER":
        return _text(a[0]).upper()
    if name == "LOWER":
        return _text(a[0]).lower()
    if name == "TRIM":
        return _text(a[0]).strip()
    if name == "CONCAT":
        return "".join(_text(x) for x in a)
    if name == "TODAY":
        return datetime.now(timezone.utc).date().isoformat()
    if name == "NOW":
        return datetime.now(timezone.utc).isoformat(timespec="minutes")
    if name in {"YEAR", "MONTH", "DAY", "DAYS"}:
        def as_date(v: Any) -> date:
            s = _text(v)[:10]
            try:
                return date.fromisoformat(s)
            except ValueError:
                raise FormulaError(f"{v!r} is not a date")
        if name == "DAYS":
            return float((as_date(a[0]) - as_date(a[1])).days)
        d = as_date(a[0])
        return float({"YEAR": d.year, "MONTH": d.month, "DAY": d.day}[name])
    raise FormulaError(f"unknown function {name}")


def evaluate(node: Any, row: dict[str, Any], columns: dict[str, list[Any]]) -> Any:
    """Evaluate one parsed formula against one row.

    `row` and `columns` are both keyed by the column's *display name* folded to
    lowercase, so a formula reads the way the header does.
    """
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "ref":
        return row.get(node[1].strip().lower())
    if kind == "neg":
        return -_num(evaluate(node[1], row, columns))
    if kind == "call":
        _, name, args = node

        def column(arg_node: Any) -> list[Any]:
            if arg_node[0] != "ref":
                # SUM(1+2) is meaningless; make the mistake visible.
                raise FormulaError(f"{name} needs a column, like {name}([Price])")
            return columns.get(arg_node[1].strip().lower(), [])

        if name in AGGREGATES:
            return _call(name, args, column)
        return _call(name, [evaluate(a, row, columns) for a in args], column)
    if kind == "bin":
        _, op, left_n, right_n = node
        left = evaluate(left_n, row, columns)
        right = evaluate(right_n, row, columns)
        if op == "&":
            return _text(left) + _text(right)
        if op in {"=", "<>"}:
            same = _text(left).strip().lower() == _text(right).strip().lower()
            return same if op == "=" else not same
        if op in {"<", "<=", ">", ">="}:
            # Compare as numbers when both sides look numeric, else as text —
            # so a date column and a price column both sort sensibly.
            try:
                a, b = _num(left), _num(right)
            except FormulaError:
                a, b = _text(left), _text(right)
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]
        a, b = _num(left), _num(right)
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "^":
            return a ** b
        if op in {"/", "%"}:
            if b == 0:
                raise FormulaError("division by zero")
            return a / b if op == "/" else math.fmod(a, b)
    raise FormulaError("could not evaluate that formula")


def compute(columns: list[dict], rows: list[dict]) -> dict[str, dict[str, Any]]:
    """Compute every formula cell in a sheet.

    Returns {row id: {column key: value}}. Formula columns can reference other
    formula columns, so this runs in passes until nothing new resolves — with a
    hard cap, which is also what stops a circular reference from spinning.
    """
    formulas = [c for c in columns if c.get("type") == "formula" and (c.get("formula") or "").strip()]
    if not formulas:
        return {}

    by_name = {c["name"].strip().lower(): c for c in columns}
    parsed: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for col in formulas:
        try:
            parsed[col["key"]] = parse(col["formula"])
        except FormulaError as exc:
            errors[col["key"]] = f"#ERROR: {exc}"

    def cell(row: dict, col: dict) -> Any:
        if col["type"] == "link":
            return (row.get("links", {}).get(col["key"]) or {}).get("label", "")
        return row.get("cells", {}).get(col["key"])

    # Seed with the stored (non-formula) values.
    out: dict[str, dict[str, Any]] = {r["id"]: {} for r in rows}
    env: dict[str, dict[str, Any]] = {
        r["id"]: {name: cell(r, c) for name, c in by_name.items()} for r in rows}

    for _pass in range(len(formulas) + 1):
        changed = False
        col_vals = {name: [env[r["id"]].get(name) for r in rows] for name in by_name}
        for col in formulas:
            key = col["key"]
            name = col["name"].strip().lower()
            if key in errors:
                for r in rows:
                    out[r["id"]][key] = errors[key]
                continue
            for r in rows:
                try:
                    value = evaluate(parsed[key], env[r["id"]], col_vals)
                except FormulaError as exc:
                    value = f"#ERROR: {exc}"
                except Exception:            # noqa: BLE001 — never break a sheet
                    value = "#ERROR"
                if env[r["id"]].get(name) != value:
                    changed = True
                env[r["id"]][name] = value
                out[r["id"]][key] = value
        if not changed:
            break
    return out

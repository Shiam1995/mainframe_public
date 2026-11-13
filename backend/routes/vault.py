"""/api/vault — the Vault module: finance, inventory and assets (VAULT_SPEC).

This increment covers **Accounts** and **Transactions** — the data foundation.
Budget-vs-actual, the Overview dashboard and everything in Analytics is computed
from transactions, so nothing else can be built until these exist.

Amount convention: the spec says positive for income, negative for expense. The
sign is normalised from `type` on write, so a caller can send 12.50 or -12.50 for
an expense and the stored value is always -12.50. Downstream sums then never
have to care how the value was entered.
"""
from __future__ import annotations

import calendar
import csv
import io
import re
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response

from activity import record
from db import run_read, run_write
from models import (
    AccountCreate, AccountUpdate, BudgetCategoryCreate, BudgetCategoryUpdate, MonthCellSet,
    BulkImport, FinDiaryCreate, FinDiaryUpdate, IncomeSet, InventoryCreate,
    InventoryUpdate, InvestmentCreate, InvestmentUpdate, TransactionCreate,
    TransactionUpdate,
)

router = APIRouter(prefix="/api/vault", tags=["vault"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _own(var: str) -> str:
    return f"MERGE (mod:Module {{name: 'vault'}}) MERGE ({var})-[:OWNED_BY]->(mod)"


def _signed(amount: float, tx_type: str) -> float:
    """Expenses are stored negative, income positive, transfers as given."""
    a = abs(float(amount))
    if tx_type == "expense":
        return -a
    if tx_type == "income":
        return a
    return float(amount)


# =========================================================================== #
# ACCOUNTS
# =========================================================================== #
@router.get("/accounts")
async def list_accounts() -> list[dict]:
    rows = await run_read("MATCH (a:Account) RETURN a ORDER BY a.created_at")
    return [dict(r["a"]) for r in rows]


@router.post("/accounts", status_code=201)
async def create_account(body: AccountCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "an account needs a name")
    aid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (a:Account {{
            id: $id, name: $name, type: $type, provider: $provider,
            balance: $balance, currency: $currency,
            updated_at: $now, created_at: $now
        }})
        WITH a {_own('a')}
        RETURN a
        """,
        id=aid, name=body.name.strip(), type=body.type, provider=body.provider,
        balance=float(body.balance), currency=body.currency, now=_now(),
    )
    await record("account", "created", detail=body.name[:70], module="vault", entity_id=aid)
    return dict(rows[0]["a"])


@router.put("/accounts/{aid}")
async def update_account(aid: str, patch: AccountUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "balance" in fields:
        fields["balance"] = float(fields["balance"])
        fields["updated_at"] = _now()          # "last updated" means the balance
    sets = ", ".join(f"a.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (a:Account {{id: $id}}) SET {sets} RETURN a", id=aid, **fields)
    if not rows:
        raise HTTPException(404, "account not found")
    verb = "balance updated" if "balance" in fields else "updated"
    await record("account", verb, detail=", ".join(fields), module="vault", entity_id=aid)
    return dict(rows[0]["a"])


@router.delete("/accounts/{aid}", status_code=204, response_class=Response)
async def delete_account(aid: str) -> Response:
    # transactions survive an account deletion — losing spending history because
    # a bank account was closed would be wrong. They just lose the link.
    await run_write("MATCH (a:Account {id: $id}) DETACH DELETE a", id=aid)
    await run_write("MATCH (t:Transaction {account_id: $id}) SET t.account_id = ''", id=aid)
    await record("account", "deleted", detail=aid, module="vault")
    return Response(status_code=204)


# =========================================================================== #
# TRANSACTIONS
# =========================================================================== #
@router.get("/transactions")
async def list_transactions(
    month: str | None = None,        # "YYYY-MM"
    category: str | None = None,
    account_id: str | None = None,
    verdict: str | None = None,      # "needed"|"wanted"|"wasteful"|"unset"
    search: str | None = None,
    limit: int = 500,
) -> list[dict]:
    clauses, params = [], {}
    if month:
        clauses.append("t.date STARTS WITH $month")
        params["month"] = month
    if category:
        clauses.append("t.category = $category")
        params["category"] = category
    if account_id:
        clauses.append("t.account_id = $account_id")
        params["account_id"] = account_id
    if verdict:
        if verdict == "unset":
            clauses.append("coalesce(t.verdict, '') = ''")
        else:
            clauses.append("t.verdict = $verdict")
            params["verdict"] = verdict
    if search:
        clauses.append("toLower(t.description) CONTAINS toLower($search)")
        params["search"] = search
    cypher = "MATCH (t:Transaction)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN t ORDER BY t.date DESC, t.created_at DESC LIMIT $limit"
    rows = await run_read(cypher, limit=max(1, min(limit, 2000)), **params)
    return [dict(r["t"]) for r in rows]


async def _create_tx(body: TransactionCreate) -> str:
    tid = str(uuid.uuid4())
    await run_write(
        f"""
        CREATE (t:Transaction {{
            id: $id, date: $date, description: $description, amount: $amount,
            type: $type, category: $category, account_id: $account_id,
            verdict: $verdict, tags: $tags, notes: $notes, created_at: $now
        }})
        WITH t {_own('t')}
        WITH t
        OPTIONAL MATCH (a:Account {{id: $account_id}})
        FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END |
            MERGE (t)-[:FROM_ACCOUNT]->(a))
        """,
        id=tid, date=body.date, description=body.description.strip(),
        amount=_signed(body.amount, body.type), type=body.type,
        category=body.category, account_id=(body.account_id or ""),
        verdict=body.verdict, tags=body.tags, notes=body.notes, now=_now(),
    )
    return tid


@router.post("/transactions", status_code=201)
async def create_transaction(body: TransactionCreate) -> dict:
    if not body.description.strip():
        raise HTTPException(400, "a transaction needs a description")
    if not body.date:
        raise HTTPException(400, "a transaction needs a date")
    tid = await _create_tx(body)
    await record("transaction", "added",
                 detail=f"{body.description[:40]} · {_signed(body.amount, body.type)}",
                 module="vault", entity_id=tid)
    rows = await run_read("MATCH (t:Transaction {id: $id}) RETURN t", id=tid)
    return dict(rows[0]["t"])


@router.put("/transactions/{tid}")
async def update_transaction(tid: str, patch: TransactionUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    # keep the sign consistent whenever amount or type moves
    if "amount" in fields or "type" in fields:
        cur = await run_read("MATCH (t:Transaction {id: $id}) RETURN t", id=tid)
        if not cur:
            raise HTTPException(404, "transaction not found")
        c = dict(cur[0]["t"])
        fields["amount"] = _signed(fields.get("amount", c.get("amount", 0)),
                                   fields.get("type", c.get("type", "expense")))
    sets = ", ".join(f"t.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (t:Transaction {{id: $id}}) SET {sets} RETURN t", id=tid, **fields)
    if not rows:
        raise HTTPException(404, "transaction not found")
    if "account_id" in fields:
        await run_write(
            """
            MATCH (t:Transaction {id: $id})
            OPTIONAL MATCH (t)-[r:FROM_ACCOUNT]->(:Account)
            DELETE r
            WITH t
            OPTIONAL MATCH (a:Account {id: $aid})
            FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END |
                MERGE (t)-[:FROM_ACCOUNT]->(a))
            """,
            id=tid, aid=fields["account_id"] or "",
        )
    verb = "verdict set" if list(fields) == ["verdict"] else "updated"
    await record("transaction", verb, detail=", ".join(fields), module="vault", entity_id=tid)
    return dict(rows[0]["t"])


@router.delete("/transactions/{tid}", status_code=204, response_class=Response)
async def delete_transaction(tid: str) -> Response:
    await run_write("MATCH (t:Transaction {id: $id}) DETACH DELETE t", id=tid)
    await record("transaction", "deleted", detail=tid, module="vault")
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Bulk paste import — people copy straight out of a banking app
# --------------------------------------------------------------------------- #
# Keyword → category, checked against the description in order. Deliberately
# small and obvious; anything unmatched falls back to "Other" and the user fixes
# it in the preview before importing.
_KEYWORDS: list[tuple[str, str]] = [
    ("tesco", "Food & Drink"), ("sainsbury", "Food & Drink"), ("asda", "Food & Drink"),
    ("aldi", "Food & Drink"), ("lidl", "Food & Drink"), ("waitrose", "Food & Drink"),
    ("co-op", "Food & Drink"), ("greggs", "Food & Drink"), ("mcdonald", "Food & Drink"),
    ("deliveroo", "Food & Drink"), ("uber eats", "Food & Drink"), ("costa", "Food & Drink"),
    ("starbucks", "Food & Drink"), ("restaurant", "Food & Drink"), ("cafe", "Food & Drink"),
    ("uber", "Transport"), ("trainline", "Transport"), ("railway", "Transport"),
    ("bus", "Transport"), ("petrol", "Transport"), ("shell", "Transport"), ("bp ", "Transport"),
    ("netflix", "Subscriptions"), ("spotify", "Subscriptions"), ("prime", "Subscriptions"),
    ("youtube", "Subscriptions"), ("icloud", "Subscriptions"), ("adobe", "Subscriptions"),
    ("openai", "Subscriptions"), ("anthropic", "Subscriptions"), ("github", "Subscriptions"),
    ("rent", "Rent"), ("mortgage", "Rent"), ("council tax", "Rent"),
    ("amazon", "Tech & Gear"), ("currys", "Tech & Gear"), ("apple", "Tech & Gear"),
    ("argos", "Tech & Gear"),
    ("udemy", "Learning"), ("coursera", "Learning"), ("book", "Learning"),
    ("waterstones", "Learning"),
    ("cinema", "Fun & Social"), ("steam", "Fun & Social"), ("pub", "Fun & Social"),
    ("boots", "Medical"), ("pharmacy", "Medical"), ("nhs", "Medical"), ("dentist", "Medical"),
    ("trading 212", "Investing"), ("vanguard", "Investing"), ("coinbase", "Investing"),
    ("savings", "Savings"), ("transfer", "Transfer"),
    ("salary", "Income"), ("payroll", "Income"), ("refund", "Income"),
]

_DATE_PATTERNS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y"]


def _guess_category(description: str) -> str:
    d = (description or "").lower()
    for key, cat in _KEYWORDS:
        if key in d:
            return cat
    return "Other"


def _parse_date(raw: str) -> str | None:
    s = (raw or "").strip()
    for fmt in _DATE_PATTERNS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> float | None:
    s = (raw or "").strip()
    if not s:
        return None
    neg = s.startswith("(") and s.endswith(")")     # (12.34) accounting negative
    s = re.sub(r"[()£$€,\s]", "", s)
    try:
        val = float(s)
    except ValueError:
        return None
    return -val if neg else val


def _parse_rows(text: str) -> tuple[list[dict], list[str]]:
    """Auto-detect tab / comma / CSV and pull out date, description, amount,
    and category if a fourth column is present. Returns (rows, problems)."""
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return [], ["nothing to parse"]

    sep = "\t" if "\t" in lines[0] else ","
    reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=sep)
    raw_rows = [r for r in reader if any(c.strip() for c in r)]

    # drop a header row if the first cell clearly isn't a date
    if raw_rows and _parse_date(raw_rows[0][0]) is None and len(raw_rows) > 1:
        header = [c.strip().lower() for c in raw_rows[0]]
        if any(h in ("date", "description", "amount", "category") for h in header):
            raw_rows = raw_rows[1:]

    out, problems = [], []
    for i, cells in enumerate(raw_rows, start=1):
        cells = [c.strip() for c in cells]
        if len(cells) < 3:
            problems.append(f"line {i}: needs at least date, description, amount")
            continue
        date = _parse_date(cells[0])
        amount = _parse_amount(cells[2])
        if date is None:
            problems.append(f"line {i}: couldn't read the date “{cells[0]}”")
            continue
        if amount is None:
            problems.append(f"line {i}: couldn't read the amount “{cells[2]}”")
            continue
        desc = cells[1]
        category = cells[3] if len(cells) > 3 and cells[3] else _guess_category(desc)
        tx_type = "income" if amount > 0 else "expense"
        out.append({
            "date": date, "description": desc, "amount": _signed(amount, tx_type),
            "type": tx_type, "category": category, "verdict": "",
        })
    return out, problems


@router.post("/transactions/bulk")
async def bulk_import(body: BulkImport) -> dict:
    """dry_run=true (the default) parses and previews. dry_run=false writes.
    Everything imported starts with verdict unset, per spec."""
    rows, problems = _parse_rows(body.text)
    if body.dry_run:
        return {"parsed": rows, "problems": problems, "count": len(rows), "imported": False}
    if not rows:
        raise HTTPException(400, "nothing to import — " + (problems[0] if problems else "no rows parsed"))
    for r in rows:
        await _create_tx(TransactionCreate(
            date=r["date"], description=r["description"], amount=r["amount"],
            type=r["type"], category=r["category"], account_id=body.account_id, verdict="",
        ))
    await record("transaction", "bulk import", detail=f"{len(rows)} transactions",
                 module="vault")
    return {"parsed": rows, "problems": problems, "count": len(rows), "imported": True}


# =========================================================================== #
# MONTHLY PLAN — budget categories + income
# =========================================================================== #
@router.get("/budget")
async def list_budget() -> list[dict]:
    rows = await run_read("MATCH (b:BudgetCategory) RETURN b ORDER BY b.order, b.name")
    return [dict(r["b"]) for r in rows]


@router.post("/budget", status_code=201)
async def create_budget_category(body: BudgetCategoryCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "the category needs a name")
    bid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        OPTIONAL MATCH (x:BudgetCategory)
        WITH coalesce(max(x.order), -1) + 1 AS nextOrder
        CREATE (b:BudgetCategory {{id: $id, name: $name, icon: $icon,
                                   amount: $amount, order: nextOrder}})
        WITH b {_own('b')}
        RETURN b
        """,
        id=bid, name=body.name.strip(), icon=body.icon, amount=float(body.amount),
    )
    await record("budget", "category added", detail=body.name[:60], module="vault", entity_id=bid)
    return dict(rows[0]["b"])


@router.put("/budget/income")
async def set_income(body: IncomeSet) -> dict:
    """Income is per-month so the plan can change month to month."""
    year = int((body.month or "0000-00").split("-")[0] or 0)
    rows = await run_write(
        f"""
        MERGE (m:MonthlyIncome {{month: $month}})
          ON CREATE SET m.id = $id, m.year = $year
        SET m.amount = $amount
        WITH m {_own('m')}
        RETURN m
        """,
        month=body.month, id=str(uuid.uuid4()), year=year, amount=float(body.amount),
    )
    await record("budget", "income set", detail=f"{body.month} · {body.amount}", module="vault")
    return dict(rows[0]["m"])


@router.put("/budget/{bid}")
async def update_budget_category(bid: str, patch: BudgetCategoryUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    if "amount" in fields:
        fields["amount"] = float(fields["amount"])
    sets = ", ".join(f"b.{k} = ${k}" for k in fields)
    rows = await run_write(
        f"MATCH (b:BudgetCategory {{id: $id}}) SET {sets} RETURN b", id=bid, **fields)
    if not rows:
        raise HTTPException(404, "budget category not found")
    await record("budget", "target updated", detail=", ".join(fields), module="vault", entity_id=bid)
    return dict(rows[0]["b"])


@router.delete("/budget/{bid}", status_code=204, response_class=Response)
async def delete_budget_category(bid: str) -> Response:
    await run_write("MATCH (b:BudgetCategory {id: $id}) DETACH DELETE b", id=bid)
    await record("budget", "category deleted", detail=bid, module="vault")
    return Response(status_code=204)


async def budget_actual(month: str) -> dict:
    """Budget vs actual for one month, computed from transaction data — the spec
    is explicit that this is derived, never stored. Shared by Monthly Plan, the
    Overview dashboard and Analytics so the three can never disagree."""
    cats = await list_budget()
    rows = await run_read(
        """
        MATCH (t:Transaction)
        WHERE t.date STARTS WITH $month AND t.amount < 0
        RETURN t.category AS category, sum(-t.amount) AS spent
        """,
        month=month,
    )
    spent_by = {r["category"]: float(r["spent"] or 0) for r in rows}

    inc = await run_read("MATCH (m:MonthlyIncome {month: $month}) RETURN m.amount AS a", month=month)
    income_set = float(inc[0]["a"]) if inc else 0.0
    # If no income was set for the month, fall back to actual income received.
    earned = await run_read(
        "MATCH (t:Transaction) WHERE t.date STARTS WITH $month AND t.amount > 0 "
        "RETURN sum(t.amount) AS a", month=month)
    income_actual = float(earned[0]["a"] or 0) if earned else 0.0

    out = []
    for c in cats:
        target = float(c.get("amount") or 0)
        actual = spent_by.pop(c["name"], 0.0)
        out.append({
            **c, "actual": actual, "target": target,
            "pct": round(100 * actual / target) if target else 0,
            "over": actual > target and target > 0,
        })
    # spending in categories with no budget line — otherwise it vanishes
    unbudgeted = [{"id": None, "name": k, "icon": "📌", "amount": 0.0, "order": 999,
                   "actual": v, "target": 0.0, "pct": 0, "over": False}
                  for k, v in sorted(spent_by.items(), key=lambda kv: -kv[1])]

    allocated = sum(c["target"] for c in out)
    spent_total = sum(c["actual"] for c in out) + sum(c["actual"] for c in unbudgeted)
    income = income_set or income_actual
    return {
        "month": month, "categories": out, "unbudgeted": unbudgeted,
        "income_set": income_set, "income_actual": income_actual, "income": income,
        "allocated": allocated, "unallocated": income - allocated, "spent": spent_total,
    }


# =========================================================================== #
# MONTHS — spend by category, month by month
#
# Each cell is either typed by hand (a :MonthCell, for months before
# Transactions existed) or summed from expense transactions. A typed cell is
# never overwritten by an import: it wins, and the transaction sum rides along
# so the grid can show both when they disagree. Sums are derived on every read.
# =========================================================================== #
def _month_keys(end: str, n: int) -> list[str]:
    y, m = (int(x) for x in end.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]                     # oldest first


@router.get("/months")
async def months_grid(end: str | None = None, n: int = 6) -> dict:
    today = datetime.now(timezone.utc).date()
    cur = today.strftime("%Y-%m")
    end = end or cur
    try:
        keys = _month_keys(end, max(1, min(n, 36)))
    except ValueError:
        raise HTTPException(400, "end must be YYYY-MM")
    lo, hi = keys[0], keys[-1]

    tx = await run_read(
        """
        MATCH (t:Transaction)
        WHERE t.amount < 0 AND substring(t.date, 0, 7) >= $lo AND substring(t.date, 0, 7) <= $hi
        RETURN substring(t.date, 0, 7) AS month, coalesce(t.category, 'Other') AS category,
               sum(-t.amount) AS spent, count(t) AS n
        """, lo=lo, hi=hi)
    manual = await run_read(
        "MATCH (c:MonthCell) WHERE c.month >= $lo AND c.month <= $hi "
        "RETURN c.month AS month, c.category AS category, c.amount AS amount",
        lo=lo, hi=hi)
    budget = await list_budget()
    plan = {b["name"]: float(b.get("amount") or 0) for b in budget}
    icons = {b["name"]: b.get("icon") or "" for b in budget}

    # rows: budget categories in plan order, then anything with spend or a typed cell
    names = [b["name"] for b in budget]
    for r in list(tx) + list(manual):
        if r["category"] not in names:
            names.append(r["category"])

    txs = {(r["month"], r["category"]): (float(r["spent"] or 0), int(r["n"])) for r in tx}
    man = {(r["month"], r["category"]): float(r["amount"]) for r in manual}
    rows, totals = [], {k: 0.0 for k in keys}
    for name in names:
        cells = {}
        for k in keys:
            t_sum, t_n = txs.get((k, name), (0.0, 0))
            typed = man.get((k, name))
            value = typed if typed is not None else t_sum
            cells[k] = {
                "value": round(value, 2), "source": "manual" if typed is not None else "tx",
                "tx": round(t_sum, 2), "tx_count": t_n,
                "disagree": typed is not None and t_n > 0 and abs(typed - t_sum) >= 0.01,
                "over": plan.get(name, 0) > 0 and value > plan[name] + 0.005,
            }
            totals[k] += value
        done = [k for k in keys if k != cur]              # the running month skews an average
        avg = sum(cells[k]["value"] for k in done) / len(done) if done else None
        rows.append({"name": name, "icon": icons.get(name, ""), "plan": plan.get(name),
                     "cells": cells, "avg": round(avg, 2) if avg is not None else None})

    days_in = calendar.monthrange(today.year, today.month)[1]
    return {
        "months": keys, "current": cur, "rows": rows,
        "totals": {k: round(v, 2) for k, v in totals.items()},
        "plan_total": round(sum(plan.values()), 2),
        "day": today.day, "days_in_month": days_in,
        "pace": round(totals[cur] / today.day * days_in, 2) if cur in totals and today.day else None,
    }


@router.put("/months/cell")
async def set_month_cell(body: MonthCellSet) -> dict:
    try:
        _month_keys(body.month, 1)
    except ValueError:
        raise HTTPException(400, "month must be YYYY-MM")
    cat = body.category.strip()
    if not cat:
        raise HTTPException(400, "category required")
    if body.amount is None:
        await run_write("MATCH (c:MonthCell {month: $m, category: $c}) DETACH DELETE c",
                        m=body.month, c=cat)
        await record("budget", "month cell cleared", detail=f"{cat} · {body.month}", module="vault")
        return {"month": body.month, "category": cat, "amount": None}
    if body.amount < 0:
        raise HTTPException(400, "spend can't be negative")
    await run_write(
        f"""
        MERGE (c:MonthCell {{month: $m, category: $c}})
          ON CREATE SET c.id = $id
        SET c.amount = $a, c.updated_at = $now
        WITH c {_own('c')}
        """, m=body.month, c=cat, id=str(uuid.uuid4()), a=float(body.amount),
        now=datetime.now(timezone.utc).isoformat())
    await record("budget", "month cell typed", detail=f"{cat} · {body.month} · {body.amount}", module="vault")
    return {"month": body.month, "category": cat, "amount": float(body.amount)}


@router.get("/budget/actual")
async def get_budget_actual(month: str | None = None) -> dict:
    return await budget_actual(month or datetime.now(timezone.utc).strftime("%Y-%m"))


# =========================================================================== #
# INVESTMENTS — snapshots. Nothing auto-updates (spec).
# =========================================================================== #
@router.get("/investments")
async def list_investments() -> list[dict]:
    rows = await run_read("MATCH (i:Investment) RETURN i ORDER BY i.created_at DESC")
    return [dict(r["i"]) for r in rows]


@router.get("/investments/summary")
async def investments_summary() -> dict:
    rows = await run_read(
        "MATCH (i:Investment) RETURN sum(i.amount_invested) AS inv, sum(i.current_value) AS cur")
    inv = float(rows[0]["inv"] or 0)
    cur = float(rows[0]["cur"] or 0)
    pl = cur - inv
    return {"invested": inv, "current": cur, "pl": pl,
            "pl_pct": round(100 * pl / inv, 2) if inv else 0.0}


@router.post("/investments", status_code=201)
async def create_investment(body: InvestmentCreate) -> dict:
    props = body.model_dump(exclude_none=True)
    if not str(props.get("name", "")).strip():
        raise HTTPException(400, "the position needs a name")
    props["name"] = props["name"].strip()
    props["amount_invested"] = float(props.get("amount_invested") or 0)
    props["current_value"] = float(props.get("current_value") or 0)
    props["id"] = str(uuid.uuid4())
    props["created_at"] = props["updated_at"] = _now()
    rows = await run_write(
        f"CREATE (i:Investment $props) WITH i {_own('i')} RETURN i", props=props)
    await record("investment", "added", detail=props["name"][:60], module="vault",
                 entity_id=props["id"])
    return dict(rows[0]["i"])


@router.put("/investments/{iid}")
async def update_investment(iid: str, patch: InvestmentUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    for k in ("amount_invested", "current_value"):
        if k in fields:
            fields[k] = float(fields[k])
    if "current_value" in fields:
        fields["updated_at"] = _now()      # "last updated" means the valuation
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (i:Investment {{id: $id}}) SET {sets} RETURN i", id=iid, **fields)
    if not rows:
        raise HTTPException(404, "investment not found")
    verb = "value updated" if "current_value" in fields else "updated"
    await record("investment", verb, detail=", ".join(fields), module="vault", entity_id=iid)
    return dict(rows[0]["i"])


@router.delete("/investments/{iid}", status_code=204, response_class=Response)
async def delete_investment(iid: str) -> Response:
    await run_write("MATCH (i:Investment {id: $id}) DETACH DELETE i", id=iid)
    await record("investment", "deleted", detail=iid, module="vault")
    return Response(status_code=204)


# =========================================================================== #
# INVENTORY — what you own, and what you still want to buy
# =========================================================================== #
@router.get("/inventory")
async def list_inventory(category: str | None = None, status: str | None = None) -> list[dict]:
    clauses, params = [], {}
    if category:
        clauses.append("i.category = $category")
        params["category"] = category
    if status:
        clauses.append("i.status = $status")
        params["status"] = status
    cypher = "MATCH (i:InventoryItem)"
    if clauses:
        cypher += " WHERE " + " AND ".join(clauses)
    cypher += " RETURN i ORDER BY i.created_at DESC"
    rows = await run_read(cypher, **params)
    return [dict(r["i"]) for r in rows]


_ACQ_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _acquired(v: str | None) -> str:
    """When you got the thing, at whatever precision you actually remember it.

    "2019", "2019-06" and "2019-06-15" are all valid and all stored verbatim,
    because rounding "some time in 2019" up to a specific day would invent a
    fact. The UI reads the precision back off the string and says "~7y" rather
    than "7y 2m" when all it really knows is the year."""
    v = (v or "").strip()
    if not v:
        return ""
    if not _ACQ_RE.match(v):
        raise HTTPException(400, "acquired must be YYYY, YYYY-MM or YYYY-MM-DD")
    p = [int(x) for x in v.split("-")]
    try:
        # The earliest instant the string could mean: "2019" starts on 1 Jan.
        earliest = date(p[0], p[1] if len(p) > 1 else 1, p[2] if len(p) > 2 else 1)
    except ValueError:
        raise HTTPException(400, "that is not a real date")
    # A day of slack so someone east of UTC can still stamp their own "today".
    if earliest > datetime.now(timezone.utc).date() + timedelta(days=1):
        raise HTTPException(400, "you cannot have acquired it in the future")
    return v


def _hi(lo: float, hi: float | None) -> float:
    """The upper bound, normalised. 0 means "no range, just the one figure" —
    and a max typed below the min is a typo, not an inverted range, so the two
    swap rather than being stored backwards and rendered as "£60 – £40"."""
    lo, hi = float(lo or 0), float(hi or 0)
    return 0.0 if hi <= 0 else max(lo, hi)


@router.post("/inventory", status_code=201)
async def create_item(body: InventoryCreate) -> dict:
    if not body.name.strip():
        raise HTTPException(400, "the item needs a name")
    iid = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (i:InventoryItem {{
            id: $id, name: $name, category: $category, location: $location,
            status: $status, value: $value, value_max: $value_max,
            acquired: $acquired, notes: $notes, link: $link, created_at: $now
        }})
        WITH i {_own('i')}
        RETURN i
        """,
        id=iid, name=body.name.strip(), category=body.category, location=body.location,
        status=body.status, value=float(body.value), value_max=_hi(body.value, body.value_max),
        acquired=_acquired(body.acquired), notes=body.notes, link=body.link,
        now=_now(),
    )
    await record("inventory", "item added", detail=body.name[:60], module="vault", entity_id=iid)
    return dict(rows[0]["i"])


@router.put("/inventory/{iid}")
async def update_item(iid: str, patch: InventoryUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    for k in ("value", "value_max"):
        if k in fields:
            fields[k] = float(fields[k] or 0)
    if "acquired" in fields:
        fields["acquired"] = _acquired(fields["acquired"])
    # The range has to stay the right way round even when only one end is
    # edited, so re-check against whatever is already stored for the other end.
    if "value" in fields or "value_max" in fields:
        cur = await run_read("MATCH (i:InventoryItem {id: $id}) RETURN i", id=iid)
        if cur:
            node = dict(cur[0]["i"])
            lo = fields.get("value", node.get("value") or 0)
            hi = fields.get("value_max", node.get("value_max") or 0)
            fields["value"], fields["value_max"] = min(lo, hi or lo), _hi(lo, hi)
    sets = ", ".join(f"i.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (i:InventoryItem {{id: $id}}) SET {sets} RETURN i", id=iid, **fields)
    if not rows:
        raise HTTPException(404, "item not found")
    verb = "status changed" if "status" in fields else "updated"
    await record("inventory", verb, detail=", ".join(fields), module="vault", entity_id=iid)
    return dict(rows[0]["i"])


@router.delete("/inventory/{iid}", status_code=204, response_class=Response)
async def delete_item(iid: str) -> Response:
    await run_write("MATCH (i:InventoryItem {id: $id}) DETACH DELETE i", id=iid)
    await record("inventory", "item deleted", detail=iid, module="vault")
    return Response(status_code=204)


# =========================================================================== #
# DIARY — financial reflections. Its own thing, not transaction notes (spec).
# =========================================================================== #
@router.get("/diary")
async def list_diary() -> list[dict]:
    rows = await run_read("MATCH (d:FinanceDiary) RETURN d ORDER BY d.date DESC, d.created_at DESC")
    return [dict(r["d"]) for r in rows]


@router.post("/diary", status_code=201)
async def create_diary(body: FinDiaryCreate) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "write something first")
    did = str(uuid.uuid4())
    rows = await run_write(
        f"""
        CREATE (d:FinanceDiary {{id: $id, date: $date, title: $title,
                                 text: $text, tags: $tags, created_at: $now}})
        WITH d {_own('d')}
        RETURN d
        """,
        id=did, date=body.date, title=body.title, text=body.text.strip(),
        tags=body.tags, now=_now(),
    )
    await record("findiary", "entry added", detail=(body.title or body.text)[:60],
                 module="vault", entity_id=did)
    return dict(rows[0]["d"])


@router.put("/diary/{did}")
async def update_diary(did: str, patch: FinDiaryUpdate) -> dict:
    fields = patch.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "no fields to update")
    sets = ", ".join(f"d.{k} = ${k}" for k in fields)
    rows = await run_write(f"MATCH (d:FinanceDiary {{id: $id}}) SET {sets} RETURN d", id=did, **fields)
    if not rows:
        raise HTTPException(404, "entry not found")
    await record("findiary", "entry updated", detail=", ".join(fields), module="vault", entity_id=did)
    return dict(rows[0]["d"])


@router.delete("/diary/{did}", status_code=204, response_class=Response)
async def delete_diary(did: str) -> Response:
    await run_write("MATCH (d:FinanceDiary {id: $id}) DETACH DELETE d", id=did)
    await record("findiary", "entry deleted", detail=did, module="vault")
    return Response(status_code=204)


# =========================================================================== #
# OVERVIEW — the dashboard. Everything here is derived; nothing is stored.
# =========================================================================== #
@router.get("/overview")
async def overview(month: str | None = None) -> dict:
    m = month or datetime.now(timezone.utc).strftime("%Y-%m")

    acc = await run_read(
        """
        MATCH (a:Account)
        RETURN sum(a.balance) AS total,
               sum(CASE WHEN a.type = 'savings' THEN a.balance ELSE 0 END) AS savings
        """)
    total_balance = float(acc[0]["total"] or 0)
    savings = float(acc[0]["savings"] or 0)

    flow = await run_read(
        """
        MATCH (t:Transaction) WHERE t.date STARTS WITH $m
        RETURN sum(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) AS income,
               sum(CASE WHEN t.amount < 0 THEN -t.amount ELSE 0 END) AS spent
        """, m=m)
    income = float(flow[0]["income"] or 0)
    spent = float(flow[0]["spent"] or 0)

    inv = await run_read("MATCH (i:Investment) RETURN sum(i.amount_invested) AS a, sum(i.current_value) AS c")
    invested = float(inv[0]["a"] or 0)
    inv_current = float(inv[0]["c"] or 0)

    recent = await run_read(
        "MATCH (t:Transaction) RETURN t ORDER BY t.date DESC, t.created_at DESC LIMIT 10")

    return {
        "month": m,
        "cards": {
            "total_balance": total_balance,
            "income_month": income,
            "spent_month": spent,
            "free_cash_flow": income - spent,
            "invested": invested,
            "invested_current": inv_current,
            "savings": savings,
        },
        "budget": await budget_actual(m),
        "recent": [dict(r["t"]) for r in recent],
    }

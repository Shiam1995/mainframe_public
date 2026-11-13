"""/api/vault/analytics — the numbers behind the Analytics tab (VAULT_SPEC §6).

Everything here is derived from transactions. Kept in its own module because the
aggregations are chunkier than the CRUD in vault.py, and the spec asks for the
split.

Month keys are "YYYY-MM" throughout. Spending is returned POSITIVE (the store
holds expenses negative) — charts want magnitudes, and every caller would
otherwise negate it themselves.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter

from db import run_read
from routes.vault import budget_actual

router = APIRouter(prefix="/api/vault/analytics", tags=["vault"])


def _this_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _recent_months(n: int, end: str | None = None) -> list[str]:
    """n month keys ending at `end` (default this month), oldest first."""
    y, m = (int(x) for x in (end or _this_month()).split("-"))
    out: list[str] = []
    for i in range(n):
        mm = m - (n - 1 - i)
        yy = y
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


@router.get("/monthly")
async def monthly(months: int = 6, end: str | None = None) -> dict:
    """Spending per month, segmented by category — feeds the stacked bar chart."""
    keys = _recent_months(max(1, min(months, 24)), end)
    rows = await run_read(
        """
        MATCH (t:Transaction)
        WHERE t.amount < 0 AND t.date >= $lo AND t.date < $hi
        RETURN substring(t.date, 0, 7) AS month, t.category AS category,
               sum(-t.amount) AS spent
        """,
        lo=keys[0] + "-01", hi=keys[-1] + "-32",
    )
    by_month: dict[str, dict[str, float]] = {k: {} for k in keys}
    for r in rows:
        if r["month"] in by_month:
            by_month[r["month"]][r["category"]] = float(r["spent"] or 0)
    cats = sorted({c for m in by_month.values() for c in m})
    return {
        "months": [
            {"month": k, "by_category": by_month[k], "total": sum(by_month[k].values())}
            for k in keys
        ],
        "categories": cats,
        "current": _this_month(),
    }


@router.get("/categories")
async def categories(month: str | None = None) -> dict:
    """Category breakdown for one month, ranked by spend."""
    m = month or _this_month()
    rows = await run_read(
        """
        MATCH (t:Transaction)
        WHERE t.amount < 0 AND t.date STARTS WITH $m
        RETURN t.category AS name, sum(-t.amount) AS amount, count(t) AS n
        ORDER BY amount DESC
        """,
        m=m,
    )
    items = [{"name": r["name"], "amount": float(r["amount"] or 0), "count": r["n"]} for r in rows]
    total = sum(i["amount"] for i in items)
    for i in items:
        i["pct"] = round(100 * i["amount"] / total, 1) if total else 0.0
    return {"month": m, "total": total, "categories": items}


@router.get("/trend")
async def trend(months: int = 6, end: str | None = None) -> dict:
    """Spending vs income per month — the line chart."""
    keys = _recent_months(max(2, min(months, 24)), end)
    rows = await run_read(
        """
        MATCH (t:Transaction) WHERE t.date >= $lo AND t.date < $hi
        RETURN substring(t.date, 0, 7) AS month,
               sum(CASE WHEN t.amount < 0 THEN -t.amount ELSE 0 END) AS spending,
               sum(CASE WHEN t.amount > 0 THEN t.amount ELSE 0 END) AS income
        """,
        lo=keys[0] + "-01", hi=keys[-1] + "-32",
    )
    got = {r["month"]: (float(r["spending"] or 0), float(r["income"] or 0)) for r in rows}
    return {"points": [
        {"month": k, "spending": got.get(k, (0.0, 0.0))[0], "income": got.get(k, (0.0, 0.0))[1]}
        for k in keys
    ]}


@router.get("/verdicts")
async def verdicts(month: str | None = None) -> dict:
    """needed / wanted / wasteful split for a month — the purchase review."""
    m = month or _this_month()
    rows = await run_read(
        """
        MATCH (t:Transaction)
        WHERE t.amount < 0 AND t.date STARTS WITH $m
        RETURN coalesce(t.verdict, '') AS verdict, sum(-t.amount) AS amount, count(t) AS n
        """,
        m=m,
    )
    out = {k: {"amount": 0.0, "count": 0} for k in ("needed", "wanted", "wasteful", "")}
    for r in rows:
        key = r["verdict"] if r["verdict"] in out else ""
        out[key]["amount"] += float(r["amount"] or 0)
        out[key]["count"] += r["n"]
    total = sum(v["amount"] for v in out.values())
    for v in out.values():
        v["pct"] = round(100 * v["amount"] / total, 1) if total else 0.0
    return {"month": m, "total": total, "needed": out["needed"], "wanted": out["wanted"],
            "wasteful": out["wasteful"], "unset": out[""]}


@router.get("/allocation")
async def allocation(month: str | None = None) -> dict:
    """Target vs actual per category, as £ and as % — drives the sliders, the
    target/actual stacked bars and the donut. Reuses budget_actual so the
    targets here are the same ones Monthly Plan and Overview show."""
    m = month or _this_month()
    b = await budget_actual(m)
    income = b["income"] or 0.0
    spent = b["spent"] or 0.0
    cats = []
    for c in b["categories"]:
        cats.append({
            "id": c["id"], "name": c["name"], "icon": c.get("icon") or "📌",
            "target": c["target"], "actual": c["actual"],
            "target_pct": round(100 * c["target"] / income, 1) if income else 0.0,
            # two denominators on purpose: share-of-spending reads naturally in
            # the donut and breakdown, but the target is a share of INCOME, so
            # the target-vs-actual comparison must use the income base or it's
            # subtracting percentages of different things.
            "actual_pct": round(100 * c["actual"] / spent, 1) if spent else 0.0,
            "actual_pct_income": round(100 * c["actual"] / income, 1) if income else 0.0,
            "diff": c["actual"] - c["target"],
        })
    for u in b["unbudgeted"]:
        cats.append({
            "id": None, "name": u["name"], "icon": u.get("icon") or "📌",
            "target": 0.0, "actual": u["actual"], "target_pct": 0.0,
            "actual_pct": round(100 * u["actual"] / spent, 1) if spent else 0.0,
            "actual_pct_income": round(100 * u["actual"] / income, 1) if income else 0.0,
            "diff": u["actual"],
        })
    return {"month": m, "income": income, "spent": spent,
            "allocated": b["allocated"], "unallocated": b["unallocated"],
            "categories": cats}


@router.get("/insights")
async def insights(month: str | None = None) -> dict:
    """Observations pulled out of the data — the spec's auto-insights. Plain
    arithmetic, no LLM: trends up/down, over-budget warnings, wasteful share,
    investment consistency."""
    m = month or _this_month()
    out: list[dict] = []

    tr = (await trend(months=3, end=m))["points"]
    if len(tr) >= 2 and tr[-2]["spending"] > 0:
        delta = tr[-1]["spending"] - tr[-2]["spending"]
        pct = 100 * delta / tr[-2]["spending"]
        if abs(pct) >= 5:
            out.append({
                "kind": "up" if delta > 0 else "down",
                "text": f"Spending is {'up' if delta > 0 else 'down'} {abs(pct):.0f}% "
                        f"on last month ({abs(delta):.0f} {'more' if delta > 0 else 'less'}).",
            })

    mth = await monthly(months=2, end=m)
    if len(mth["months"]) == 2:
        prev, cur = mth["months"][0]["by_category"], mth["months"][1]["by_category"]
        moves = []
        for cat, amt in cur.items():
            was = prev.get(cat, 0.0)
            if was and abs(amt - was) / was >= 0.25 and abs(amt - was) >= 20:
                moves.append((cat, amt - was, 100 * (amt - was) / was))
        moves.sort(key=lambda x: -abs(x[1]))
        for cat, d, pct in moves[:3]:
            out.append({"kind": "up" if d > 0 else "down",
                        "text": f"{cat} {'rose' if d > 0 else 'fell'} {abs(pct):.0f}% this month."})

    alloc = await allocation(m)
    over = [c for c in alloc["categories"] if c["target"] > 0 and c["actual"] > c["target"]]
    for c in sorted(over, key=lambda c: -(c["actual"] - c["target"]))[:3]:
        out.append({"kind": "warn",
                    "text": f"{c['name']} is over budget by {c['actual'] - c['target']:.0f}."})
    if alloc["unallocated"] < 0:
        out.append({"kind": "warn",
                    "text": f"Budget is over-allocated by {abs(alloc['unallocated']):.0f} — "
                            f"targets exceed income."})

    v = await verdicts(m)
    if v["total"]:
        if v["wasteful"]["pct"] >= 10:
            out.append({"kind": "warn",
                        "text": f"{v['wasteful']['pct']:.0f}% of spending was marked wasteful."})
        if v["unset"]["pct"] >= 50:
            out.append({"kind": "info",
                        "text": f"{v['unset']['pct']:.0f}% of this month's spending hasn't been "
                                f"reviewed yet."})

    inv = await run_read(
        "MATCH (t:Transaction) WHERE t.amount < 0 AND t.category IN ['Investing','Savings'] "
        "AND t.date >= $lo RETURN substring(t.date,0,7) AS m, sum(-t.amount) AS a",
        lo=_recent_months(3, m)[0] + "-01")
    months_invested = len([r for r in inv if float(r["a"] or 0) > 0])
    if months_invested >= 3:
        out.append({"kind": "good", "text": "Invested or saved in each of the last 3 months."})
    elif months_invested == 0:
        out.append({"kind": "info", "text": "No investing or saving logged in the last 3 months."})

    if not out:
        out.append({"kind": "info", "text": "Not enough data yet — log a few months to see trends."})
    return {"month": m, "insights": out}

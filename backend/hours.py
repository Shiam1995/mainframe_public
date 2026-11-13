"""Hours roll-up: one number per node, shared by every surface that shows it.

hours(x) is the time logged ON x plus the time on everything under it. "Under"
follows CHILD_OF (sub-projects), GIVEN_TO (a project's tasks), PART_OF
(attachments, routes/attach.py), SOURCE_OF (what a doc is built on) and ABOUT
read backwards (the book a book project is about, routes/projects.py). The sum
runs over the DISTINCT set of nodes reached, so a paper that is both attached
and a doc's source counts once, and a cycle cannot loop.

`hours_index()` loads every edge and every session total in two queries. Build
it once per request and ask it for any node: the project list, project page,
phases and Repository all read it, so they cannot disagree.
"""
from __future__ import annotations

from db import run_read


# =========================================================================== #
class HoursIndex:
    def __init__(self, own: dict[str, tuple[int, int]], kids: dict[str, set[str]]):
        self.own = own                    # id → (mins, sessions) logged ON it
        self.kids = kids                  # id → ids directly under it
        self._memo: dict[str, frozenset[str]] = {}

    def under(self, nid: str) -> frozenset[str]:
        """Every node at or below `nid`. Cycle-safe: a node is visited once."""
        if nid in self._memo:
            return self._memo[nid]
        seen, stack = {nid}, [nid]
        while stack:
            for k in self.kids.get(stack.pop(), ()):
                if k not in seen:
                    seen.add(k)
                    stack.append(k)
        self._memo[nid] = frozenset(seen)
        return self._memo[nid]

    def of(self, nid: str) -> dict:
        mins = sessions = 0
        for n in self.under(nid):
            m, s = self.own.get(n, (0, 0))
            mins += m
            sessions += s
        return {"mins": mins, "sessions": sessions}

    def of_all(self, ids) -> dict:
        """The union of several nodes' subtrees, each node counted once: a
        phase's total over all its projects, however they nest or share."""
        seen: set[str] = set()
        for i in ids:
            seen |= self.under(i)
        mins = sum(self.own.get(n, (0, 0))[0] for n in seen)
        sessions = sum(self.own.get(n, (0, 0))[1] for n in seen)
        return {"mins": mins, "sessions": sessions}

    def of_except(self, nid: str, skip: set) -> dict:
        """hours(nid) leaving out nodes already counted elsewhere (`skip`)."""
        rest = self.under(nid) - skip
        return {"mins": sum(self.own.get(n, (0, 0))[0] for n in rest),
                "sessions": sum(self.own.get(n, (0, 0))[1] for n in rest)}

    def own_of(self, nid: str) -> dict:
        m, s = self.own.get(nid, (0, 0))
        return {"mins": m, "sessions": s}


async def hours_index(lo: str | None = None, hi: str | None = None) -> HoursIndex:
    """`lo`/`hi` (YYYY-MM-DD, inclusive) keep only sessions dated inside the
    window, which is how a phase counts the same roll-up over its own weeks."""
    own_rows = await run_read(
        "MATCH (w:WorkSession)-[:ON]->(x) "
        "WHERE ($lo IS NULL OR w.date >= $lo) AND ($hi IS NULL OR w.date <= $hi) "
        "RETURN x.id AS id, sum(coalesce(w.mins, 0)) AS mins, count(w) AS n", lo=lo, hi=hi)
    edge_rows = await run_read(
        """
        MATCH (c)-[r:CHILD_OF|GIVEN_TO|PART_OF|SOURCE_OF]->(p)
        WHERE (type(r) = 'CHILD_OF' AND c:Project AND p:Project)
           OR (type(r) = 'GIVEN_TO' AND c:Task AND c.kind = 'task' AND p:Project)
           OR (type(r) = 'PART_OF' AND p:Project)
           OR (type(r) = 'SOURCE_OF' AND p:Document)
        RETURN c.id AS c, p.id AS p
        UNION
        // ABOUT points the other way: (Project)-[:ABOUT]->(Paper). Reading
        // sessions are pushed ON the paper, so without this a book project
        // reads 0h while its book holds all the hours.
        MATCH (p:Project)-[:ABOUT]->(c)
        WHERE NOT c:Project
        RETURN c.id AS c, p.id AS p
        """)
    own = {r["id"]: (int(r["mins"] or 0), int(r["n"] or 0)) for r in own_rows if r["id"]}
    kids: dict[str, set[str]] = {}
    for r in edge_rows:
        if r["c"] and r["p"]:
            kids.setdefault(r["p"], set()).add(r["c"])
    return HoursIndex(own, kids)

/* vault-analytics.js — Vault · Analytics (VAULT_SPEC §6).

   The whole tab, hand-rolled, zero libraries. Sections, in spec order:
     · %/£/Both toggle — EVERY number on the page respects it
     · allocation sliders (0-50% of income), all charts update live
     · target vs actual stacked bars
     · detailed per-category comparison (faded target behind solid actual)
     · donut (target in % mode, actual in £ mode)
     · monthly stacked bars, 6 months, current highlighted
     · category breakdown ranked by spend
     · month-to-month table, red up / green down
     · spending vs income trend line
     · purchase review with verdict buttons
     · auto-insights

   Slider behaviour: dragging updates the page live without touching the server;
   releasing saves the new target (percent × income) to the budget. So it's a
   planning tool you can play with, and a commit when you let go. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const V = window.VAULT;
  const NS = "http://www.w3.org/2000/svg";

  let mode = "both";               // pct | gbp | both
  let month = V.thisMonth();
  let data = null;                 // last loaded payload
  let draft = {};                  // category name → target % while dragging

  const svg = (tag, attrs) => {
    const n = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) n.setAttribute(k, attrs[k]);
    return n;
  };

  /* Format one value per the toggle. `pct` is already a percentage. */
  function fmt(gbp, pct) {
    const p = (pct == null ? 0 : pct).toFixed(pct != null && pct < 10 ? 1 : 0) + "%";
    if (mode === "pct") return p;
    if (mode === "gbp") return V.money(gbp);
    return V.money(gbp) + "  ·  " + p;
  }

  const targetPct = (c) => (draft[c.name] != null ? draft[c.name] : c.target_pct);
  const targetGbp = (c, income) => (draft[c.name] != null ? draft[c.name] * income / 100 : c.target);
  // Both sides as a share of INCOME — the only way the difference means anything.
  const ppDiff = (c) => (c.actual_pct_income || 0) - targetPct(c);

  function sectionCard(title, note) {
    const box = el("div.vault-card");
    box.appendChild(el("div.spread", { style: "margin-bottom:10px" }, [
      el("span.sub", { text: title }),
      note ? el("span.sub", { text: note }) : null,
    ]));
    return box;
  }

  /* ---------- 1. allocation sliders ------------------------------------- */
  function slidersSection(rerender) {
    const a = data.alloc;
    const box = sectionCard("ALLOCATION — % OF INCOME",
      "drag to plan · release to save the target");
    if (!a.categories.filter((c) => c.id).length) {
      box.appendChild(el("div.sub", { style: "font-style:italic",
        text: "No budget categories yet — add them in Monthly Plan." }));
      return box;
    }
    const totalEl = el("span.vlt-figure");
    const paintTotal = () => {
      const t = a.categories.filter((c) => c.id).reduce((s, c) => s + targetPct(c), 0);
      totalEl.textContent = t.toFixed(0) + "% allocated";
      totalEl.style.color = t > 100 ? "var(--red)" : t === 100 ? "var(--green)" : "var(--dim)";
    };

    a.categories.filter((c) => c.id).forEach((c) => {
      const val = el("span.vlt-figure", { style: "width:150px;text-align:right" });
      const paint = () => { val.textContent = fmt(targetGbp(c, a.income), targetPct(c)); };
      const range = el("input", { type: "range", min: "0", max: "50", step: "0.5",
        value: String(targetPct(c)), style: "flex:1" });
      range.addEventListener("input", () => {
        draft[c.name] = parseFloat(range.value);
        paint(); paintTotal();
        redrawLive();                       // charts follow the slider immediately
      });
      range.addEventListener("change", () => guard(async () => {
        const amount = Math.round(parseFloat(range.value) * a.income / 100);
        await api.vault.updateBudget(c.id, { amount });
        toast(c.name + " target → " + V.money(amount));
        delete draft[c.name];
        rerender();
      }));
      paint();
      box.appendChild(el("div.row", { style: "gap:10px;padding:5px 0" }, [
        el("span", { style: "width:150px;flex:0 0 auto;font-size:12px",
          text: (c.icon || "📌") + " " + c.name }),
        range, val,
      ]));
    });
    paintTotal();
    box.appendChild(el("div.spread", { style: "margin-top:8px;padding-top:9px;border-top:1px solid var(--border)" }, [
      el("span.sub", { text: "income " + V.money(a.income) }), totalEl,
    ]));
    return box;
  }

  /* ---------- 2. target vs actual stacked bars --------------------------- */
  function stackRow(items, total, label) {
    const bar = el("div.vlt-stack");
    items.forEach((it) => {
      if (!it.value || !total) return;
      const seg = el("div.vlt-stack-seg", {
        style: "width:" + (100 * it.value / total) + "%;background:" + V.catColor(it.name),
        title: it.name + " — " + fmt(it.gbp, it.pct),
      });
      bar.appendChild(seg);
    });
    if (!bar.children.length) bar.appendChild(el("div.vlt-stack-seg", { style: "width:100%;background:var(--raised)" }));
    return el("div", { style: "margin-bottom:10px" }, [
      el("div.spread", { style: "margin-bottom:4px" }, [
        el("span.sub", { text: label }),
        el("span.sub", { text: fmt(total, 100) }),
      ]), bar,
    ]);
  }

  function targetVsActual() {
    const a = data.alloc;
    const box = sectionCard("TARGET VS ACTUAL");
    const tItems = a.categories.map((c) => ({ name: c.name, value: targetGbp(c, a.income),
      gbp: targetGbp(c, a.income), pct: targetPct(c) }));
    const aItems = a.categories.map((c) => ({ name: c.name, value: c.actual,
      gbp: c.actual, pct: c.actual_pct }));
    const tTotal = tItems.reduce((s, i) => s + i.value, 0);
    const aTotal = aItems.reduce((s, i) => s + i.value, 0);
    box.appendChild(stackRow(tItems, tTotal, "TARGET  " + V.money(tTotal)));
    box.appendChild(stackRow(aItems, aTotal, "ACTUAL  " + V.money(aTotal)));
    box.appendChild(legend(a.categories.map((c) => c.name)));
    return box;
  }

  function legend(names) {
    return el("div.row", { style: "gap:10px;flex-wrap:wrap;margin-top:6px" },
      [...new Set(names)].map((n) => el("div.row", { style: "gap:4px" }, [
        el("span.vlt-swatch", { style: "background:" + V.catColor(n) }),
        el("span.sub", { text: n }),
      ])));
  }

  /* ---------- 3. detailed comparison ------------------------------------ */
  function comparison() {
    const a = data.alloc;
    const box = sectionCard("DETAILED COMPARISON", "faded = target · solid = actual");
    const max = Math.max(1, ...a.categories.map((c) => Math.max(c.actual, targetGbp(c, a.income))));
    a.categories.forEach((c) => {
      const tg = targetGbp(c, a.income);
      const diff = c.actual - tg;
      const color = V.catColor(c.name);
      box.appendChild(el("div", { style: "padding:6px 0" }, [
        el("div.spread", {}, [
          el("span", { style: "font-size:12px", text: (c.icon || "📌") + " " + c.name }),
          el("div.row", { style: "gap:10px" }, [
            el("span.sub", { text: "target " + fmt(tg, targetPct(c)) }),
            el("span.sub", { text: "actual " + fmt(c.actual, c.actual_pct_income) }),
            el("span.vlt-figure", { style: "color:" + (diff > 0 ? "var(--red)" : "var(--green)"),
              text: mode === "pct"
                ? (ppDiff(c) > 0 ? "+" : "") + ppDiff(c).toFixed(1) + "pp"
                : (diff > 0 ? "+" : "") + V.money(diff) }),
          ]),
        ]),
        el("div.vlt-overlap", {}, [
          el("div.vlt-overlap-target", { style: "width:" + (100 * tg / max) + "%;background:" + color }),
          el("div.vlt-overlap-actual", { style: "width:" + (100 * c.actual / max) + "%;background:" + color }),
        ]),
      ]));
    });
    return box;
  }

  /* ---------- 4. donut --------------------------------------------------- */
  function donut() {
    const a = data.alloc;
    // % mode shows the target split, £ mode shows actual (spec)
    const useTarget = mode === "pct";
    const items = a.categories
      .map((c) => ({ name: c.name, value: useTarget ? targetGbp(c, a.income) : c.actual,
                     pct: useTarget ? targetPct(c) : c.actual_pct }))
      .filter((i) => i.value > 0)
      .sort((x, y) => y.value - x.value);
    const total = items.reduce((s, i) => s + i.value, 0);

    const box = sectionCard("SPLIT", useTarget ? "target allocation" : "actual spending");
    if (!total) {
      box.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing to show yet." }));
      return box;
    }
    const R = 66, C = 2 * Math.PI * R;
    const s = svg("svg", { viewBox: "0 0 180 180", class: "vlt-donut" });
    let offset = 0;
    items.forEach((i) => {
      const frac = i.value / total;
      const arc = svg("circle", {
        cx: 90, cy: 90, r: R, fill: "none", "stroke-width": 26,
        stroke: V.catColor(i.name),
        "stroke-dasharray": (C * frac) + " " + (C * (1 - frac)),
        "stroke-dashoffset": -offset, transform: "rotate(-90 90 90)",
      });
      arc.appendChild(svg("title", {})).textContent = i.name + " — " + fmt(i.value, i.pct);
      s.appendChild(arc);
      offset += C * frac;
    });
    const mid = svg("text", { x: 90, y: 88, "text-anchor": "middle", class: "vlt-donut-mid" });
    mid.textContent = mode === "pct" ? "100%" : V.money(total);
    const sub = svg("text", { x: 90, y: 104, "text-anchor": "middle", class: "vlt-donut-sub" });
    sub.textContent = useTarget ? "allocated" : "spent";
    s.appendChild(mid); s.appendChild(sub);

    box.appendChild(el("div.row", { style: "gap:22px;align-items:center;flex-wrap:wrap" }, [
      s,
      el("div", { style: "flex:1;min-width:180px" }, items.map((i) => el("div.spread", { style: "padding:3px 0" }, [
        el("div.row", { style: "gap:6px" }, [
          el("span.vlt-swatch", { style: "background:" + V.catColor(i.name) }),
          el("span", { style: "font-size:12px", text: i.name }),
        ]),
        el("span.sub", { text: fmt(i.value, i.pct) }),
      ]))),
    ]));
    return box;
  }

  /* ---------- 5. monthly stacked bars ------------------------------------ */
  function monthlyBars() {
    const m = data.monthly;
    const box = sectionCard("MONTHLY SPENDING", "last " + m.months.length + " months");
    const max = Math.max(1, ...m.months.map((x) => x.total));
    // Pixel heights, not percentages — a % height inside nested flex boxes
    // resolves against an auto-height parent and collapses to nothing.
    const MAXPX = 140;
    const chart = el("div.vlt-months");
    m.months.forEach((x) => {
      const col = el("div.vlt-month" + (x.month === month ? ".on" : ""));
      const barPx = Math.max(2, Math.round(MAXPX * x.total / max));
      const stack = el("div.vlt-mbar", { style: "height:" + barPx + "px" });
      Object.entries(x.by_category).sort((a, b) => b[1] - a[1]).forEach(([cat, amt]) => {
        stack.appendChild(el("div", {
          style: "height:" + Math.max(1, Math.round(barPx * amt / (x.total || 1))) + "px;"
               + "background:" + V.catColor(cat),
          title: cat + " — " + V.money(amt),
        }));
      });
      col.appendChild(el("div.vlt-mbar-wrap", {}, [stack]));
      col.appendChild(el("div.vlt-mlabel", { text: V.monthLabel(x.month).split(" ")[0] }));
      col.appendChild(el("div.vlt-mval", { text: V.money(x.total) }));
      col.addEventListener("click", () => { month = x.month; reloadRef(); });
      chart.appendChild(col);
    });
    box.appendChild(chart);
    box.appendChild(legend(m.categories));
    return box;
  }

  /* ---------- 6. category breakdown -------------------------------------- */
  function breakdown() {
    const c = data.cats;
    const box = sectionCard("CATEGORY BREAKDOWN", V.monthLabel(c.month));
    if (!c.categories.length) {
      box.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing spent this month." }));
      return box;
    }
    const max = Math.max(...c.categories.map((x) => x.amount));
    c.categories.forEach((x) => {
      box.appendChild(el("div", { style: "padding:5px 0" }, [
        el("div.spread", {}, [
          el("div.row", { style: "gap:6px" }, [
            el("span", { text: V.catIcon(x.name) }),
            el("span", { style: "font-size:12px", text: x.name }),
            el("span.sub", { text: x.count + "×" }),
          ]),
          el("span.vlt-figure", { text: fmt(x.amount, x.pct) }),
        ]),
        el("div.vlt-bar", { style: "margin-top:4px" }, [
          el("div.vlt-bar-fill", { style: "width:" + (100 * x.amount / max) + "%;background:" + V.catColor(x.name) }),
        ]),
      ]));
    });
    return box;
  }

  /* ---------- 7. month-to-month table ------------------------------------ */
  function comparisonTable() {
    const m = data.monthly;
    const box = sectionCard("MONTH TO MONTH", "red = up · green = down");
    const cats = m.categories;
    if (!cats.length) {
      box.appendChild(el("div.sub", { style: "font-style:italic", text: "No spending logged yet." }));
      return box;
    }
    const peak = m.months.reduce((a, b) => (b.total > a.total ? b : a), m.months[0]);
    const t = el("table");
    t.appendChild(el("tr", {}, [el("th", { text: "" }),
      ...m.months.map((x) => el("th", {
        style: x.month === peak.month ? "color:#D4A017" : "",
        text: V.monthLabel(x.month).split(" ")[0] + (x.month === peak.month ? " ▲" : ""),
      }))]));
    cats.forEach((cat) => {
      const cells = m.months.map((x, i) => {
        const v = x.by_category[cat] || 0;
        const prev = i ? (m.months[i - 1].by_category[cat] || 0) : null;
        const color = prev == null || v === prev ? "var(--dim)"
          : v > prev ? "var(--red)" : "var(--green)";
        return el("td", { style: "padding:4px 8px;text-align:right;color:" + color,
          text: v ? V.money(v) : "—" });
      });
      t.appendChild(el("tr", {}, [
        el("td", { style: "padding:4px 8px;white-space:nowrap",
          text: V.catIcon(cat) + " " + cat }), ...cells]));
    });
    t.appendChild(el("tr", {}, [
      el("th", { text: "TOTAL" }),
      ...m.months.map((x) => el("th", { style: "text-align:right", text: V.money(x.total) })),
    ]));
    box.appendChild(el("div.grid", {}, [t]));
    return box;
  }

  /* ---------- 8. spending vs income trend -------------------------------- */
  function trendChart() {
    const pts = data.trend.points;
    const box = sectionCard("SPENDING VS INCOME", "red = spending · green dashed = income");
    const max = Math.max(1, ...pts.map((p) => Math.max(p.spending, p.income)));
    const W = 640, H = 190, PAD = 26;
    const x = (i) => PAD + i * (W - 2 * PAD) / Math.max(1, pts.length - 1);
    const y = (v) => H - PAD - (v / max) * (H - 2 * PAD);
    const s = svg("svg", { viewBox: "0 0 " + W + " " + H, class: "vlt-line" });
    [0.25, 0.5, 0.75, 1].forEach((f) => s.appendChild(svg("line", {
      x1: PAD, x2: W - PAD, y1: y(max * f), y2: y(max * f),
      stroke: "var(--border)", "stroke-width": 1 })));
    const path = (key, color, dash) => {
      const d = pts.map((p, i) => (i ? "L" : "M") + x(i) + " " + y(p[key])).join(" ");
      s.appendChild(svg("path", { d, fill: "none", stroke: color, "stroke-width": 2,
        "stroke-dasharray": dash || "" }));
      pts.forEach((p, i) => {
        const c = svg("circle", { cx: x(i), cy: y(p[key]), r: 3, fill: color });
        c.appendChild(svg("title", {})).textContent =
          V.monthLabel(p.month) + " — " + key + " " + V.money(p[key]);
        s.appendChild(c);
      });
    };
    path("spending", "var(--red)");
    path("income", "var(--green)", "6 4");
    pts.forEach((p, i) => {
      const lbl = svg("text", { x: x(i), y: H - 7, "text-anchor": "middle", class: "vlt-axis" });
      lbl.textContent = V.monthLabel(p.month).split(" ")[0];
      s.appendChild(lbl);
    });
    box.appendChild(s);
    return box;
  }

  /* ---------- 9. purchase review ----------------------------------------- */
  function purchaseReview(txs, rerender) {
    const v = data.verdicts;
    const box = sectionCard("PURCHASE REVIEW", V.monthLabel(v.month));
    const line = (key, label, color) => el("div.spread", { style: "padding:3px 0" }, [
      el("div.row", { style: "gap:6px" }, [
        el("span.vlt-swatch", { style: "background:" + color }),
        el("span", { style: "font-size:12px", text: label }),
        el("span.sub", { text: v[key].count + "×" }),
      ]),
      el("span.vlt-figure", { style: "color:" + color, text: fmt(v[key].amount, v[key].pct) }),
    ]);
    box.appendChild(line("needed", "Needed", "var(--green)"));
    box.appendChild(line("wanted", "Wanted", "var(--amber)"));
    box.appendChild(line("wasteful", "Wasteful", "var(--red)"));
    box.appendChild(line("unset", "Not reviewed", "var(--dim)"));

    const list = el("div", { style: "margin-top:12px;padding-top:10px;border-top:1px solid var(--border)" });
    const spend = txs.filter((t) => t.amount < 0);
    if (!spend.length) {
      list.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing spent this month." }));
    } else {
      spend.forEach((t) => {
        const vd = V.verdictOf(t.verdict);
        list.appendChild(el("div.vlt-item", {}, [
          el("div.row", { style: "gap:8px;min-width:0" }, [
            el("span.sub", { style: "width:52px;flex:0 0 auto", text: V.dateFmt(t.date).slice(0, 6) }),
            el("span", { text: V.catIcon(t.category) }),
            el("span", { style: "font-size:12px", text: t.description }),
          ]),
          el("div.row", { style: "gap:8px;flex:0 0 auto" }, [
            el("span.vlt-figure", { style: "color:var(--red)", text: V.money(t.amount) }),
            el("button.vlt-verdict", { style: "background:" + vd.bg + ";color:" + vd.color,
              onclick: () => guard(async () => {
                await api.vault.updateTx(t.id, { verdict: V.nextVerdict(t.verdict) });
                rerender();
              }), text: vd.label }),
          ]),
        ]));
      });
    }
    box.appendChild(list);
    return box;
  }

  /* ---------- 10. auto-insights ------------------------------------------ */
  function insightsCard() {
    const ICON = { up: "📈", down: "📉", warn: "⚠", good: "✅", info: "·" };
    const COLOR = { up: "var(--red)", down: "var(--green)", warn: "var(--amber)",
                    good: "var(--green)", info: "var(--dim)" };
    const box = sectionCard("INSIGHTS");
    data.insights.insights.forEach((i) => box.appendChild(el("div.row", { style: "gap:8px;padding:4px 0" }, [
      el("span", { style: "color:" + COLOR[i.kind], text: ICON[i.kind] || "·" }),
      el("span", { style: "font-size:12px", text: i.text }),
    ])));
    return box;
  }

  /* ---------- page ------------------------------------------------------- */
  let liveHost = null, reloadRef = () => {};

  function redrawLive() {
    // Called on every slider tick — only the sections the sliders affect.
    if (!liveHost) return;
    clear(liveHost);
    liveHost.appendChild(targetVsActual());
    liveHost.appendChild(comparison());
    liveHost.appendChild(donut());
  }

  window.Views = window.Views || {};
  window.Views.analytics = {
    id: "analytics", label: "Analytics", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Analytics" }),
        el("div.sub", { text: "Where the money actually went. Every number switches between % and £ with the toggle." }),
      ])]));

      const bar = el("div"); view.appendChild(bar);
      const host = el("div"); view.appendChild(host);

      async function reload() {
        const [alloc, monthly, cats, trend, verdicts, insights, txs] = await guard(() => Promise.all([
          api.vault.analytics("allocation", month), api.vault.analytics("monthly"),
          api.vault.analytics("categories", month), api.vault.analytics("trend"),
          api.vault.analytics("verdicts", month), api.vault.analytics("insights", month),
          api.vault.transactions("?month=" + month),
        ]));
        data = { alloc, monthly, cats, trend, verdicts, insights };
        draft = {};

        // toolbar
        clear(bar);
        const seg = (label, val) => el("button.btn-sm" + (mode === val ? ".vlt-on" : ""), {
          onclick: () => { mode = val; reload(); }, text: label });
        const monthSel = el("select", {}, V.recentMonths(18).map((m) => el("option", { value: m, text: V.monthLabel(m) })));
        monthSel.value = month;
        monthSel.addEventListener("change", () => { month = monthSel.value; reload(); });
        bar.appendChild(el("div.row", { style: "margin-bottom:14px;gap:8px" }, [
          el("div.row", { style: "gap:4px" }, [seg("%", "pct"), seg("£", "gbp"), seg("Both", "both")]),
          el("span.sub", { text: "│" }), monthSel,
        ]));

        clear(host);
        host.appendChild(slidersSection(reload));
        liveHost = el("div"); host.appendChild(liveHost);
        redrawLive();
        host.appendChild(monthlyBars());
        host.appendChild(breakdown());
        host.appendChild(comparisonTable());
        host.appendChild(trendChart());
        host.appendChild(purchaseReview(txs, reload));
        host.appendChild(insightsCard());
      }
      reloadRef = reload;
      reload();
    },
  };
})();

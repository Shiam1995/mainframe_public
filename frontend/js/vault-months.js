/* vault-months.js — Vault · Months (mainframe_vault_months.html).

   Spend by category, month by month. Every cell is either typed by hand
   (amber dot, for months before Transactions existed) or summed from expense
   transactions (blue dot). A typed cell is never overwritten by an import; if
   the transactions disagree it says so. Clearing a typed cell falls back to
   the transaction sum. Focus a cell to see the transactions behind it.
   Plan figures are the Monthly Plan targets — one source, never re-entered. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  let span = 6, end = null;                 // window: `span` months ending at `end` (null = this month)
  let showPlan = (() => { try { return localStorage.getItem("vault.months.plan") === "1"; } catch { return false; } })();
  let drawer = null;                        // { month, category }
  const extraRows = new Set();              // categories added here but not typed into yet

  const short = (key) => ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"][Number(key.slice(5)) - 1];
  const gbp = (n) => "£" + Math.round(n).toLocaleString("en-GB");
  const num = (n) => Math.round(n).toLocaleString("en-GB");
  function shift(key, by) {
    const [y, m] = key.split("-").map(Number);
    const d = new Date(y, m - 1 + by, 1);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0");
  }

  function strip(data) {
    const max = Math.max(1, ...data.months.map((k) => data.totals[k]));
    return el("div.vm-strip", {}, data.months.map((k, i) => {
      const v = data.totals[k], prev = i ? data.totals[data.months[i - 1]] : null;
      const now = k === data.current;
      let d = null;
      if (now && data.pace != null) d = el("div.d", { text: "day " + data.day + " · on pace for " + gbp(data.pace) });
      else if (prev) {
        const pct = Math.round(100 * (v - prev) / prev);
        d = el("div.d" + (pct > 0 ? ".up" : pct < 0 ? ".dn" : ""), { text: (pct > 0 ? "+" : pct < 0 ? "−" : "") + Math.abs(pct) + "%" });
      }
      return el("div.vm-mo" + (now ? ".now" : ""), {}, [
        el("div.n", { text: short(k) + " " + k.slice(2, 4) + (now ? " · so far" : "") }),
        el("div.v", { text: gbp(v) }),
        el("div.b", {}, [el("i", { style: "width:" + Math.round(100 * v / max) + "%" })]),
        d,
      ]);
    }));
  }

  function grid(data, reload) {
    const months = data.months;
    const nowCls = (k) => (k === data.current ? ".now" : "");
    const table = el("table.vm-table");
    table.appendChild(el("tr", {}, [el("th.lbl", { text: "category" })]
      .concat(months.map((k) => el("th" + nowCls(k), { text: short(k) + " " + k.slice(2, 4) })))
      .concat([el("th", { text: "avg", title: "average of the finished months shown" })])));

    const rows = data.rows.slice();
    extraRows.forEach((name) => { if (!rows.some((r) => r.name === name)) rows.push({ name, icon: "", plan: null, cells: {}, avg: null }); });
    if (!rows.length) table.appendChild(el("tr", {}, [el("td.lbl.sub", { colspan: String(months.length + 2), text: "No spending or categories yet." })]));

    rows.forEach((r) => {
      const planTxt = r.plan ? "plan " + gbp(r.plan) : "no plan";
      table.appendChild(el("tr", {}, [
        el("td.lbl", {}, [el("span", { text: (r.icon ? r.icon + " " : "") + r.name }), el("span.pl", { text: planTxt })]),
      ].concat(months.map((k) => {
        const c = r.cells[k] || { value: 0, source: "tx", tx: 0, tx_count: 0 };
        const inp = el("input", { value: c.value ? String(c.value) : "", placeholder: "0", inputmode: "decimal" });
        const tip = c.source === "manual"
          ? "typed by hand" + (c.disagree ? " · transactions say " + V.money(c.tx) : "") + " — clear it to use transactions"
          : c.tx_count + " transaction" + (c.tx_count === 1 ? "" : "s");
        inp.title = tip;
        inp.addEventListener("focus", () => {
          if (!drawer || drawer.month !== k || drawer.category !== r.name) { drawer = { month: k, category: r.name }; paintDrawer(); }
        });
        inp.addEventListener("keydown", (e) => { if (e.key === "Enter") inp.blur(); });
        inp.addEventListener("change", () => guard(async () => {
          const raw = inp.value.replace(/[£,\s]/g, "");
          if (raw !== "" && !(Number(raw) >= 0)) { inp.value = c.value || ""; return toast("type an amount", true); }
          // an empty cell, or retyping exactly the transaction sum, hands it back to Transactions
          const amount = raw === "" || (c.source === "tx" && Number(raw) === c.tx) ? null : Number(raw);
          await api.vault.setMonthCell({ month: k, category: r.name, amount });
          extraRows.delete(r.name);
          reload();
        }));
        return el("td" + nowCls(k) + (c.over ? ".over" : ""), {}, [
          inp,
          el("span.src." + (c.source === "manual" ? "man" : "tx") + (c.disagree ? ".dis" : ""), { title: tip }),
        ]);
      })).concat([el("th.avg", { text: r.avg == null ? "" : num(r.avg) })])));
      if (showPlan && r.plan) {
        table.appendChild(el("tr.plan", {}, [el("td.lbl", { text: "plan" })]
          .concat(months.map((k) => el("td" + nowCls(k), { text: num(r.plan) }))).concat([el("td")])));
      }
    });

    const done = months.filter((k) => k !== data.current);
    const avgTot = done.length ? done.reduce((s, k) => s + data.totals[k], 0) / done.length : null;
    table.appendChild(el("tr.tot", {}, [el("td.lbl", { text: "total" })]
      .concat(months.map((k) => el("td" + nowCls(k), { text: num(data.totals[k]) })))
      .concat([el("td", { text: avgTot == null ? "" : num(avgTot) })])));
    if (showPlan && data.plan_total) {
      table.appendChild(el("tr.plan", {}, [el("td.lbl", { text: "plan total" })]
        .concat(months.map((k) => el("td" + nowCls(k), { text: num(data.plan_total) }))).concat([el("td")])));
    }
    return el("div.vm-wrap", {}, [table]);
  }

  let drawerHost = null;
  async function paintDrawer() {
    if (!drawerHost) return;
    clear(drawerHost);
    if (!drawer) return;
    const { month, category } = drawer;
    const txs = await guard(() => api.vault.transactions("?month=" + encodeURIComponent(month) + "&category=" + encodeURIComponent(category)));
    const spend = txs.filter((t) => t.amount < 0);
    const total = spend.reduce((s, t) => s - t.amount, 0);
    const box = el("div.vm-drawer", {}, [
      el("div.spread", {}, [
        el("h2", { text: category + " · " + V.monthLabel(month) + " · " + V.money(total) + " from " + spend.length + " transaction" + (spend.length === 1 ? "" : "s") }),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "↗ Transactions, filtered", onclick: () => {
            if (window.VAULT_TX_FILTER) window.VAULT_TX_FILTER({ month, category });
            window.openTab("transactions");
          } }),
          el("button.btn-sm", { text: "×", title: "close", onclick: () => { drawer = null; paintDrawer(); } }),
        ]),
      ]),
    ]);
    if (!spend.length) box.appendChild(el("div.sub", { style: "margin-top:6px", text: "No transactions behind this cell." }));
    else {
      const t = el("table.vm-dtable", {}, [el("tr", {}, [el("th", { text: "date" }), el("th", { text: "description" }), el("th", { text: "verdict" }), el("th.n", { text: "£" })])]);
      spend.forEach((x) => t.appendChild(el("tr", {}, [
        el("td.meta", { text: V.dateFmt(x.date) }), el("td", { text: x.description || "" }),
        el("td.meta", { text: x.verdict || "" }), el("td.n", { text: (-x.amount).toFixed(2) }),
      ])));
      box.appendChild(t);
    }
    drawerHost.appendChild(box);
  }

  window.Views = window.Views || {};
  window.Views.months = {
    id: "months", label: "Months", scoped: false,
    async render(view) {
      clear(view);
      const planBtn = el("button.btn-sm", { text: showPlan ? "hide plan rows" : "show plan rows" });
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Months" }),
          el("div.sub", { text: "Spend by category, month by month. Type a number into any cell, or let it sum from Transactions." }),
        ]),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "‹", title: "earlier", onclick: () => { end = shift(end || V.thisMonth(), -1); reload(); } }),
          el("button.btn-sm", { text: "›", title: "later", onclick: () => {
            const nxt = shift(end || V.thisMonth(), 1);
            end = nxt >= V.thisMonth() ? null : nxt; reload();
          } }),
          planBtn,
          el("button.btn-primary", { text: "+ month", title: "show one more month further back", onclick: () => { span = Math.min(36, span + 1); reload(); } }),
        ]),
      ]));
      planBtn.addEventListener("click", () => {
        showPlan = !showPlan;
        try { localStorage.setItem("vault.months.plan", showPlan ? "1" : "0"); } catch { /* */ }
        planBtn.textContent = showPlan ? "hide plan rows" : "show plan rows";
        reload();
      });
      const stripHost = el("div"); view.appendChild(stripHost);
      const card = el("div.vm-card"); view.appendChild(card);
      drawerHost = el("div"); view.appendChild(drawerHost);

      async function reload() {
        const data = await guard(() => api.vault.months({ end: end || "", n: span }));
        clear(stripHost); stripHost.appendChild(strip(data));
        clear(card);
        card.appendChild(el("div.spread", { style: "margin-bottom:8px;flex-wrap:wrap" }, [
          el("h2", { style: "margin:0;font-size:14px", text: "By category" }),
          el("div.vm-legend", {}, [
            el("span", {}, [el("i", { style: "background:#5A9DE0" }), "summed from Transactions"]),
            el("span", {}, [el("i", { style: "background:#F0A030" }), "typed by hand"]),
            el("span", {}, [el("i.ring"), "typed, transactions disagree"]),
            el("span", { text: "red = over plan" }),
            el("span", { text: "click a cell for what's behind it" }),
          ]),
        ]));
        card.appendChild(grid(data, reload));
        const addIn = el("input.vm-addrow", { placeholder: "+ category (press Enter)" });
        addIn.addEventListener("keydown", (e) => {
          if (e.key !== "Enter" || !addIn.value.trim()) return;
          extraRows.add(addIn.value.trim()); reload();
        });
        card.appendChild(addIn);
        card.appendChild(el("div.meta", { style: "margin-top:8px", text: "A typed cell is never overwritten by an import; it just shows both if they disagree. Empty a typed cell to go back to the transaction sum. A new category stays once you type a number into it." }));
        paintDrawer();
      }
      reload();
    },
  };
})();

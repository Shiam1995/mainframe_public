/* vault-overview.js — Vault · Overview (VAULT_SPEC §1).

   The dashboard. Everything here is DERIVED — summary cards from accounts and
   this month's transactions, budget bars from the same shared calculator the
   Monthly Plan uses, recent transactions straight off the log. Nothing on this
   page is a stored number, so it can't drift out of step with the data. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  let month = V.thisMonth();

  const statCard = (label, value, color) => el("div.vlt-stat", {}, [
    el("div.vlt-stat-val", color ? { style: "color:" + color, text: value } : { text: value }),
    el("div.vlt-stat-lbl", { text: label }),
  ]);

  function budgetBar(c) {
    const pct = c.target ? Math.round(100 * c.actual / c.target) : 0;
    const color = c.over ? "var(--red)" : pct >= 100 ? "#D4A017" : "var(--teal)";
    return el("div", { style: "padding:7px 0" }, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:6px" }, [
          el("span", { text: c.icon || "📌" }),
          el("span", { style: "font-size:12px", text: c.name }),
          c.over ? el("span.vlt-over", { text: "⚠" }) : null,
        ]),
        el("span.sub", { style: c.over ? "color:var(--red)" : "",
          text: V.money(c.actual) + " / " + V.money(c.target) }),
      ]),
      el("div.vlt-bar", { style: "margin-top:5px" }, [
        el("div.vlt-bar-fill", { style: "width:" + Math.min(100, pct) + "%;background:" + color }),
      ]),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.overview = {
    id: "overview", label: "Overview", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Overview" }),
        el("div.sub", { text: "Everything on this page is calculated from your accounts and transactions." }),
      ])]));

      const monthSel = el("select", {}, V.recentMonths(18).map((m) => el("option", { value: m, text: V.monthLabel(m) })));
      monthSel.value = month;
      monthSel.addEventListener("change", () => { month = monthSel.value; reload(); });
      view.appendChild(el("div.row", { style: "margin-bottom:14px" }, [
        el("span.sub", { text: "showing" }), monthSel,
      ]));

      const host = el("div"); view.appendChild(host);

      async function reload() {
        const d = await guard(() => api.vault.overview(month));
        const c = d.cards;
        clear(host);

        host.appendChild(el("div.vlt-stat-grid", { style: "margin-bottom:14px" }, [
          statCard("TOTAL BALANCE", V.money(c.total_balance)),
          statCard("INCOME THIS MONTH", V.money(c.income_month), "var(--green)"),
          statCard("SPENT THIS MONTH", V.money(c.spent_month), "var(--red)"),
          statCard("FREE CASH FLOW", V.money(c.free_cash_flow),
            c.free_cash_flow < 0 ? "var(--red)" : "var(--green)"),
          statCard("INVESTED", V.money(c.invested), "var(--teal)"),
          statCard("SAVINGS", V.money(c.savings)),
        ]));

        // budget vs actual — same numbers as the Monthly Plan, same calculator
        const bud = el("div.vault-card");
        bud.appendChild(el("div.spread", { style: "margin-bottom:6px" }, [
          el("span.sub", { text: "BUDGET VS ACTUAL" }),
          el("span.sub", { text: V.monthLabel(d.month) }),
        ]));
        if (!d.budget.categories.length) {
          bud.appendChild(el("div.sub", { style: "font-style:italic",
            text: "No budget categories yet — set them up in Monthly Plan." }));
        } else {
          d.budget.categories.forEach((cat) => bud.appendChild(budgetBar(cat)));
          const over = d.budget.categories.filter((x) => x.over);
          if (over.length) {
            bud.appendChild(el("div.sub", { style: "margin-top:8px;color:var(--red)",
              text: "⚠ over budget in " + over.map((x) => x.name).join(", ") }));
          }
        }
        host.appendChild(bud);

        // recent transactions
        const rec = el("div.vault-card");
        rec.appendChild(el("div.sub", { style: "margin-bottom:8px", text: "RECENT TRANSACTIONS" }));
        if (!d.recent.length) {
          rec.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing logged yet." }));
        } else {
          d.recent.forEach((t) => rec.appendChild(el("div.vlt-item", {}, [
            el("div.row", { style: "gap:8px;min-width:0" }, [
              el("span.sub", { style: "width:74px;flex:0 0 auto", text: V.dateFmt(t.date).slice(0, 6) }),
              el("span", { style: "font-size:13px", text: V.catIcon(t.category) }),
              el("span", { style: "font-size:13px", text: t.description }),
            ]),
            el("span.vlt-figure", { style: "color:" + V.amountColor(t.amount), text: V.money(t.amount) }),
          ])));
        }
        host.appendChild(rec);
      }
      reload();
    },
  };
})();

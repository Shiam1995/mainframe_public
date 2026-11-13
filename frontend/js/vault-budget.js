/* vault-budget.js — Vault · Monthly Plan (VAULT_SPEC §4).

   Budget targets vs what actually happened. **Actual is never stored** — the
   backend sums transactions by category for the month and compares. Categories
   are entirely user-defined; nothing is hardcoded (spec). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  let month = V.thisMonth();

  // teal under budget, gold at 100%, red over — spec's colour rule
  function barColor(pct, over) {
    if (over) return "var(--red)";
    if (pct >= 100) return "#D4A017";
    return "var(--teal)";
  }

  function categoryRow(c, reload) {
    const pct = c.target ? Math.round(100 * c.actual / c.target) : 0;
    const fill = Math.min(100, pct);
    const amtIn = el("input", { type: "number", step: "1", value: String(c.target || 0),
      style: "width:92px;text-align:right" });
    amtIn.addEventListener("blur", () => guard(async () => {
      const nv = parseFloat(amtIn.value);
      if (isNaN(nv) || nv === Number(c.target)) { amtIn.value = String(c.target || 0); return; }
      await api.vault.updateBudget(c.id, { amount: nv }); toast("target updated"); reload();
    }));

    return el("div.vlt-budget-row", {}, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:7px;min-width:0" }, [
          el("span", { style: "font-size:15px", text: c.icon || "📌" }),
          el("span", { style: "font-weight:600;font-size:13px", text: c.name }),
          c.over ? el("span.vlt-over", { text: "⚠ over" }) : null,
        ]),
        el("div.row", { style: "gap:8px;flex:0 0 auto" }, [
          el("span.vlt-figure", { style: "color:" + (c.over ? "var(--red)" : "var(--text)"),
            text: V.money(c.actual) }),
          el("span.sub", { text: "/" }), amtIn,
          el("button.ord-btn", { title: "delete category", text: "×",
            onclick: () => confirmDo("Delete the “" + c.name + "” budget line?", async () => {
              await api.vault.delBudget(c.id); reload();
            }) }),
        ]),
      ]),
      el("div.vlt-bar", {}, [
        el("div.vlt-bar-fill", { style: "width:" + fill + "%;background:" + barColor(pct, c.over) }),
      ]),
      el("div.sub", { style: "margin-top:3px", text: pct + "% of target" + (c.target ? "" : " (no target set)") }),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.budget = {
    id: "budget", label: "Monthly Plan", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Monthly Plan" }),
        el("div.sub", { text: "Set a target per category. Actual spend is calculated from your transactions — never typed in." }),
      ])]));

      const monthSel = el("select", {}, V.recentMonths(18).map((m) => el("option", { value: m, text: V.monthLabel(m) })));
      monthSel.value = month;
      monthSel.addEventListener("change", () => { month = monthSel.value; reload(); });
      const nameIn = el("input", { placeholder: "category name", style: "flex:1;min-width:150px" });
      const iconIn = el("input", { placeholder: "📌", style: "width:56px;text-align:center" });
      const amtIn = el("input", { type: "number", step: "1", placeholder: "target £", style: "width:100px" });
      const add = () => guard(async () => {
        if (!nameIn.value.trim()) return toast("name the category", true);
        await api.vault.createBudget({ name: nameIn.value.trim(),
          icon: iconIn.value.trim() || "📌", amount: parseFloat(amtIn.value) || 0 });
        nameIn.value = iconIn.value = amtIn.value = ""; toast("category added"); reload();
      });
      nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      view.appendChild(el("div.row", { style: "margin-bottom:14px" }, [
        monthSel, el("span.sub", { text: "│" }), nameIn, iconIn, amtIn,
        el("button.btn-primary", { onclick: add, text: "+ category" }),
      ]));

      const host = el("div"); view.appendChild(host);

      async function reload() {
        const d = await guard(() => api.vault.budgetActual(month));
        clear(host);

        // --- income + allocation summary ---
        const incomeIn = el("input", { type: "number", step: "1",
          value: String(d.income_set || ""), placeholder: String(Math.round(d.income_actual) || 0),
          style: "width:130px;text-align:right" });
        incomeIn.addEventListener("blur", () => guard(async () => {
          const nv = parseFloat(incomeIn.value);
          if (isNaN(nv)) return;
          await api.vault.setIncome({ month, amount: nv }); toast("income set"); reload();
        }));
        const unalloc = d.unallocated;
        host.appendChild(el("div.vault-card", {}, [
          el("div.spread", {}, [
            el("div", {}, [
              el("div.sub", { text: "MONTHLY INCOME" }),
              el("div.sub", { style: "margin-top:2px",
                text: d.income_set ? "set manually" : "using actual income received this month" }),
            ]),
            el("div.row", { style: "gap:6px;align-items:center" }, [el("span.sub", { text: "£" }), incomeIn]),
          ]),
          el("div.spread", { style: "margin-top:12px;padding-top:11px;border-top:1px solid var(--border)" }, [
            el("span.sub", { text: "ALLOCATED" }),
            el("span.vlt-figure", { text: V.money(d.allocated) }),
          ]),
          el("div.spread", { style: "margin-top:5px" }, [
            el("span.sub", { text: "UNALLOCATED" }),
            el("span.vlt-figure", { style: "color:" + (unalloc < 0 ? "var(--red)" : "var(--green)"),
              text: (unalloc < 0 ? "over by " : "") + V.money(unalloc) }),
          ]),
          el("div.spread", { style: "margin-top:5px" }, [
            el("span.sub", { text: "SPENT THIS MONTH" }),
            el("span.vlt-figure", { style: "color:var(--red)", text: V.money(d.spent) }),
          ]),
        ]));

        // --- category bars ---
        if (!d.categories.length) {
          host.appendChild(el("div.empty", { text: "No budget categories yet. Add one above — they're entirely yours to define." }));
        } else {
          const box = el("div.vault-card");
          box.appendChild(el("div.sub", { style: "margin-bottom:10px", text: "BUDGET VS ACTUAL" }));
          d.categories.forEach((c) => box.appendChild(categoryRow(c, reload)));
          host.appendChild(box);
        }

        // --- spending with no budget line ---
        if (d.unbudgeted.length) {
          const box = el("div.vault-card");
          box.appendChild(el("div.sub", { style: "margin-bottom:8px",
            text: "SPENT OUTSIDE THE PLAN — no budget line for these" }));
          d.unbudgeted.forEach((c) => box.appendChild(el("div.spread", { style: "padding:5px 0" }, [
            el("div.row", { style: "gap:7px" }, [
              el("span", { text: V.catIcon(c.name) }),
              el("span", { style: "font-size:13px", text: c.name }),
            ]),
            el("div.row", { style: "gap:8px" }, [
              el("span.vlt-figure", { style: "color:var(--amber)", text: V.money(c.actual) }),
              el("button.btn-sm", { title: "create a budget line for this category",
                onclick: () => guard(async () => {
                  await api.vault.createBudget({ name: c.name, icon: V.catIcon(c.name), amount: 0 });
                  toast("budget line added"); reload();
                }), text: "+ budget it" }),
            ]),
          ])));
          host.appendChild(box);
        }
      }
      reload();
    },
  };
})();

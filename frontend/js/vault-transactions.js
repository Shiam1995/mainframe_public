/* vault-transactions.js — Vault · Transactions (VAULT_SPEC §3).

   The log everything else is computed from: budget-vs-actual, the Overview
   dashboard and every chart in Analytics all sum these rows.

   Two things the spec insists on and this file owns:
     · the VERDICT button — one click cycles unset → needed → wanted → wasteful
     · BULK PASTE — paste out of a banking app, preview what was parsed, then
       import. Tab, comma and CSV are all accepted. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  let accounts = [], filters = { month: "", category: "", account_id: "", verdict: "", search: "" };

  const acctName = (id) => (accounts.find((a) => a.id === id) || {}).name || "";

  /* --- bulk paste ---------------------------------------------------------- */
  function bulkModal(reload) {
    const ta = el("textarea.mform-input", { rows: "10",
      placeholder: "Paste from your banking app.\n\nDate, Description, Amount[, Category]\ntab / comma / CSV all work — e.g.\n2026-07-14, Tesco Express, -18.40",
      style: "font-family:var(--mono);font-size:12px" });
    const acctSel = el("select.mform-input", {}, [
      el("option", { value: "", text: "— no account —" }),
      ...accounts.map((a) => el("option", { value: a.id, text: a.name })),
    ]);
    const preview = el("div", { style: "margin-top:12px" });
    let parsed = [];

    const doPreview = () => guard(async () => {
      const r = await api.vault.bulkImport({ text: ta.value, account_id: acctSel.value || null, dry_run: true });
      parsed = r.parsed;
      clear(preview);
      if (r.problems.length) {
        preview.appendChild(el("div.sub", { style: "color:var(--amber);margin-bottom:6px",
          text: "⚠ " + r.problems.length + " line" + (r.problems.length === 1 ? "" : "s") + " skipped:" }));
        r.problems.slice(0, 5).forEach((p) => preview.appendChild(el("div.sub", { text: "· " + p })));
      }
      if (!parsed.length) {
        preview.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing parsed yet." }));
        return;
      }
      preview.appendChild(el("div.sub", { style: "margin:8px 0 5px",
        text: parsed.length + " row" + (parsed.length === 1 ? "" : "s") + " ready — categories were guessed from the description:" }));
      const t = el("table");
      t.appendChild(el("tr", {}, ["Date", "Description", "Category", "Amount"].map((h) => el("th", { text: h }))));
      parsed.slice(0, 40).forEach((p) => t.appendChild(el("tr", {}, [
        el("td", { style: "padding:4px 8px", text: p.date }),
        el("td", { style: "padding:4px 8px", text: p.description }),
        el("td", { style: "padding:4px 8px", text: V.catIcon(p.category) + " " + p.category }),
        el("td", { style: "padding:4px 8px;text-align:right;color:" + V.amountColor(p.amount),
          text: V.money(p.amount) }),
      ])));
      preview.appendChild(el("div.grid", {}, [t]));
      if (parsed.length > 40) preview.appendChild(el("div.sub", { text: "…and " + (parsed.length - 40) + " more" }));
    });

    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.appendChild(el("div.modal.vis-modal", {}, [
      el("div.modal-title", { text: "Bulk import" }),
      el("div.mform-full", {}, [el("div.mform-label", { text: "Paste" }), ta]),
      el("div.mform-full", {}, [el("div.mform-label", { text: "Import into account" }), acctSel]),
      el("div.row", { style: "margin-top:8px" }, [
        el("button.btn-sm", { onclick: doPreview, text: "preview" }),
        el("span.sub", { text: "check what was parsed before importing" }),
      ]),
      preview,
      el("div.row", { style: "margin-top:16px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
          if (!parsed.length) return toast("preview it first", true);
          const r = await api.vault.bulkImport({ text: ta.value, account_id: acctSel.value || null, dry_run: false });
          close(); toast("imported " + r.count + " transactions"); reload();
        }), text: "Import" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    ta.focus();
  }

  /* --- one row ------------------------------------------------------------- */
  function row(t, reload) {
    const vd = V.verdictOf(t.verdict);
    const catSel = el("select.cellinput", {}, V.CATEGORIES.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key })));
    if (!V.CATEGORIES.some((c) => c.key === t.category)) {
      catSel.appendChild(el("option", { value: t.category, text: t.category }));
    }
    catSel.value = t.category;
    catSel.addEventListener("change", () => guard(async () => {
      await api.vault.updateTx(t.id, { category: catSel.value }); reload();
    }));

    return el("tr", {}, [
      el("td", { style: "padding:5px 8px;white-space:nowrap", text: V.dateFmt(t.date) }),
      el("td", { style: "padding:5px 8px", text: t.description }),
      el("td", { style: "padding:0" }, [catSel]),
      el("td", { style: "padding:5px 8px;text-align:right;white-space:nowrap;color:" + V.amountColor(t.amount),
        text: V.money(t.amount) }),
      el("td", { style: "padding:5px 8px;white-space:nowrap" },
        [el("span.sub", { text: acctName(t.account_id) })]),
      el("td", { style: "padding:5px 8px" }, [
        el("button.vlt-verdict", { style: "background:" + vd.bg + ";color:" + vd.color,
          title: "click to cycle: unset → needed → wanted → wasteful",
          onclick: () => guard(async () => {
            await api.vault.updateTx(t.id, { verdict: V.nextVerdict(t.verdict) }); reload();
          }), text: vd.label }),
      ]),
      el("td", { style: "padding:5px 8px" }, [
        el("button.ord-btn", { title: "delete", text: "×",
          onclick: () => confirmDo("Delete this transaction?", async () => {
            await api.vault.delTx(t.id); reload();
          }) }),
      ]),
    ]);
  }

  // Other tabs (Vault · Months) open the ledger pre-filtered through this.
  window.VAULT_TX_FILTER = (f) => {
    filters = { month: "", category: "", account_id: "", verdict: "", search: "", ...f };
    sub = "ledger";
  };

  window.Views = window.Views || {};
  /* Transactions is what MOVED; Recurring is what you've COMMITTED to. They
     belong together but must not be the same list, so Recurring rides in as a
     sub-header rather than as more rows. */
  let sub = (() => {
    try { return localStorage.getItem("vault.txn.sub") || "ledger"; } catch { return "ledger"; }
  })();

  window.Views.transactions = {
    id: "transactions", label: "Transactions", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Transactions" }),
          el("div.sub", { text: "Every purchase and payment. Budget, dashboard and analytics are all computed from this." }),
        ]),
        el("div.row", {}, [el("button.btn-sm", { onclick: () => bulkModal(reload), text: "⤓ bulk paste" })]),
      ]));

      const TABS = [{ key: "ledger", label: "Ledger" }].concat(window.VAULT_TXN_TABS || []);
      const bar = el("div.fit-subtabs.vlt-subtabs");
      TABS.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
        onclick: () => {
          sub = t.key;
          try { localStorage.setItem("vault.txn.sub", sub); } catch { /* ignore */ }
          window.Views.transactions.render(view);
        },
        text: t.label,
      })));
      view.appendChild(bar);

      if (sub !== "ledger") {
        const tab = TABS.find((t) => t.key === sub);
        const host = el("div");
        view.appendChild(host);
        if (tab && tab.render) await guard(() => tab.render(host));
        return;
      }

      // --- add one ---
      const dIn = el("input", { type: "date", value: V.todayStr() });
      const descIn = el("input", { placeholder: "description", style: "flex:1;min-width:160px" });
      const amtIn = el("input", { type: "number", step: "0.01", placeholder: "amount", style: "width:110px" });
      const typeSel = el("select", {}, ["expense", "income", "transfer"].map((t) => el("option", { value: t, text: t })));
      const catSel = el("select", {}, V.CATEGORIES.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key })));
      const acctSel = el("select", {});
      const add = () => guard(async () => {
        if (!descIn.value.trim()) return toast("describe the transaction", true);
        const amt = parseFloat(amtIn.value);
        if (isNaN(amt)) return toast("enter an amount", true);
        await api.vault.createTx({ date: dIn.value, description: descIn.value.trim(),
          amount: amt, type: typeSel.value, category: catSel.value, account_id: acctSel.value || null });
        descIn.value = amtIn.value = ""; toast("added"); reload();
      });
      descIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      view.appendChild(el("div.row", { style: "margin-bottom:12px" }, [
        dIn, descIn, amtIn, typeSel, catSel, acctSel,
        el("button.btn-primary", { onclick: add, text: "+ add" }),
      ]));

      // --- filters ---
      const search = el("input", { placeholder: "search description…", style: "flex:1;min-width:160px", value: filters.search });
      let timer = null;
      search.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(() => { filters.search = search.value; reload(); }, 250);
      });
      const monthSel = el("select", {}, [el("option", { value: "", text: "all months" }),
        ...V.recentMonths(18).map((m) => el("option", { value: m, text: V.monthLabel(m) }))]);
      monthSel.value = filters.month;
      monthSel.addEventListener("change", () => { filters.month = monthSel.value; reload(); });
      const catFilter = el("select", {}, [el("option", { value: "", text: "all categories" }),
        ...V.CATEGORIES.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key }))]);
      if (filters.category && !V.CATEGORIES.some((c) => c.key === filters.category))
        catFilter.appendChild(el("option", { value: filters.category, text: filters.category }));
      catFilter.value = filters.category;
      catFilter.addEventListener("change", () => { filters.category = catFilter.value; reload(); });
      const acctFilter = el("select", {});
      const vFilter = el("select", {}, [el("option", { value: "", text: "all verdicts" }),
        ...["needed", "wanted", "wasteful", "unset"].map((x) => el("option", { value: x, text: x }))]);
      vFilter.value = filters.verdict;
      vFilter.addEventListener("change", () => { filters.verdict = vFilter.value; reload(); });
      view.appendChild(el("div.row", { style: "margin-bottom:14px" }, [
        search, monthSel, catFilter, acctFilter, vFilter,
      ]));

      const summary = el("div"); view.appendChild(summary);
      const host = el("div"); view.appendChild(host);

      async function reload() {
        accounts = await guard(() => api.vault.accounts());
        [acctSel, acctFilter].forEach((sel, i) => {
          const keep = sel.value;
          clear(sel);
          sel.appendChild(el("option", { value: "", text: i ? "all accounts" : "— no account —" }));
          accounts.forEach((a) => sel.appendChild(el("option", { value: a.id, text: a.name })));
          sel.value = keep;
        });
        acctFilter.onchange = () => { filters.account_id = acctFilter.value; reload(); };

        const qs = [];
        Object.entries(filters).forEach(([k, v]) => { if (v) qs.push(k + "=" + encodeURIComponent(v)); });
        const txs = await guard(() => api.vault.transactions(qs.length ? "?" + qs.join("&") : ""));

        clear(summary); clear(host);
        if (!txs.length) {
          host.appendChild(el("div.empty", { text: "No transactions match. Add one above, or bulk-paste from your bank." }));
          return;
        }
        const income = txs.filter((t) => t.amount > 0).reduce((s, t) => s + t.amount, 0);
        const spend = txs.filter((t) => t.amount < 0).reduce((s, t) => s + t.amount, 0);
        summary.appendChild(el("div.row", { style: "gap:16px;margin-bottom:10px" }, [
          el("span.sub", { text: txs.length + " shown" }),
          el("span.sub", { style: "color:var(--green)", text: "in " + V.money(income) }),
          el("span.sub", { style: "color:var(--red)", text: "out " + V.money(spend) }),
          el("span.sub", { style: "color:" + V.amountColor(income + spend), text: "net " + V.money(income + spend) }),
        ]));

        const table = el("table");
        table.appendChild(el("tr", {}, ["Date", "Description", "Category", "Amount", "Account", "Verdict", ""]
          .map((h) => el("th", { text: h }))));
        txs.forEach((t) => table.appendChild(row(t, reload)));
        host.appendChild(el("div.grid", {}, [table]));
      }
      reload();
    },
  };
})();

/* vault-recurring.js — Vault → Transactions → Recurring.

   Subscriptions and one-off payments: what leaves, how often, when next, and
   a note about why you're still paying for it.

   These are commitments, not transactions. "paid" mints a real transaction in
   the ledger and rolls the due date forward — so the Transactions tab stays
   the single record of money that actually moved, and this tab stays a record
   of what you've signed up for. */
(function () {
  const { el, clear, toast, guard, todayISO } = window.ui;
  const api = window.api;

  const CADENCES = ["monthly", "weekly", "fortnightly", "4weekly", "quarterly", "yearly", "once"];
  const money = (n) => "£" + (Math.round((n || 0) * 100) / 100).toFixed(2);

  function dueLabel(r) {
    if (!r.next_due) return { text: "no date", cls: "" };
    const d = r.days_until;
    if (d === null || d === undefined) return { text: r.next_due, cls: "" };
    if (d < 0) return { text: Math.abs(d) + "d overdue", cls: "vr-overdue" };
    if (d === 0) return { text: "due today", cls: "vr-soon" };
    if (d === 1) return { text: "tomorrow", cls: "vr-soon" };
    if (d <= 7) return { text: "in " + d + "d", cls: "vr-soon" };
    return { text: r.next_due, cls: "" };
  }

  function row(r, reload, accounts) {
    const due = dueLabel(r);
    const isOnce = r.cadence === "once";

    const nameIn = el("input.vr-name", { value: r.name || "" });
    nameIn.addEventListener("change", () => guard(async () => {
      await api.recurring.update(r.id, { name: nameIn.value.trim() || "Untitled" });
      toast("renamed");
    }));

    const amtIn = el("input.vr-amt", { type: "number", step: "0.01",
                                       value: String(r.amount ?? 0) });
    amtIn.addEventListener("change", () => guard(() =>
      api.recurring.update(r.id, { amount: parseFloat(amtIn.value) || 0 })));

    const cadSel = el("select.vr-mini", {}, CADENCES.map((c) =>
      el("option", { value: c, text: c })));
    cadSel.value = r.cadence || "monthly";
    cadSel.addEventListener("change", () => guard(async () => {
      await api.recurring.update(r.id, { cadence: cadSel.value });
      reload();
    }));

    const dueIn = el("input.vr-mini", { type: "date", value: r.next_due || "" });
    dueIn.addEventListener("change", () => guard(async () => {
      await api.recurring.update(r.id, { next_due: dueIn.value });
      reload();
    }));

    const notesIn = el("input.vr-notes", { value: r.notes || "",
      placeholder: "why you're paying for this — and when to cancel" });
    notesIn.addEventListener("change", () => guard(() =>
      api.recurring.update(r.id, { notes: notesIn.value })));

    const remindIn = el("input.vr-tiny", { type: "number", min: "0", max: "60",
                                           value: String(r.remind_days_before ?? 2),
                                           title: "warn me this many days before" });
    remindIn.addEventListener("change", () => guard(() =>
      api.recurring.update(r.id, { remind_days_before: parseInt(remindIn.value, 10) || 0 })));

    const pay = el("button.vr-pay", {
      title: "record that this went out — writes a transaction and moves the date on",
      text: isOnce ? "✓ paid" : "✓ paid",
      onclick: () => guard(async () => {
        const res = await api.recurring.pay(r.id, {});
        const next = res.recurring && res.recurring.next_due;
        toast(isOnce ? "logged — one-off closed" : "logged · next " + (next || "—"));
        reload();
      }),
    });

    const live = el("button.vr-toggle" + (r.active ? ".on" : ""), {
      title: r.active ? "stop tracking this" : "start tracking it again",
      text: r.active ? "active" : "paused",
      onclick: () => guard(async () => {
        await api.recurring.update(r.id, { active: !r.active });
        reload();
      }),
    });

    const del = el("button.vr-x", { text: "×", title: "delete" });
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) {
        armed = true; del.textContent = "sure?"; del.classList.add("armed");
        setTimeout(() => { armed = false; del.textContent = "×"; del.classList.remove("armed"); }, 3000);
        return;
      }
      guard(async () => { await api.recurring.del(r.id); toast("deleted"); reload(); });
    });

    const acct = accounts.find((a) => a.id === r.account_id);

    return el("div.vr-row" + (r.active ? "" : ".off") + (r.overdue ? ".overdue" : ""),
      { "data-eid": r.id }, [
      el("div.vr-line", {}, [
        nameIn,
        amtIn,
        cadSel,
        dueIn,
        el("span.vr-due " + due.cls, { text: due.text }),
        el("span.vr-bell", { title: "reminds this many days before" }, [
          document.createTextNode("🔔"), remindIn,
        ]),
        pay, live, del,
      ]),
      el("div.vr-line2", {}, [
        notesIn,
        el("span.vr-meta", {
          text: [acct ? acct.name : null,
                 r.category,
                 r.paid_count ? r.paid_count + "× paid" : null,
                 r.last_paid ? "last " + r.last_paid : null].filter(Boolean).join(" · "),
        }),
      ]),
    ]);
  }

  async function render(host) {
    clear(host);
    const [items, summary, accounts] = await Promise.all([
      api.recurring.list(), api.recurring.summary(), api.vault.accounts(),
    ]);
    // Paying or rescheduling something here changes what's due, so the topbar
    // bell has to re-count — otherwise it keeps claiming a bill you just
    // settled is still waiting.
    const reload = () => {
      if (window.Reminders) window.Reminders.refresh();
      return render(host);
    };
    if (window.Reminders) window.Reminders.refresh();

    /* --- what it all costs --- */
    const stat = (v, l, c) => el("div.vr-stat", {}, [
      el("div.vr-stat-v", { style: c ? "color:" + c : "", text: v }),
      el("div.vr-stat-l", { text: l }),
    ]);
    host.appendChild(el("div.vr-summary", {}, [
      stat(money(summary.monthly), "per month", "var(--accent)"),
      stat(money(summary.yearly), "per year", "var(--amber)"),
      stat(String(summary.count), "active"),
      summary.overdue.length
        ? stat(String(summary.overdue.length), "overdue", "var(--red)") : null,
    ]));

    /* --- add --- */
    const nameIn = el("input", { placeholder: "what is it?", style: "flex:2;min-width:150px" });
    const amtIn = el("input", { type: "number", step: "0.01", placeholder: "amount",
                                style: "width:100px" });
    const cadSel = el("select", {}, CADENCES.map((c) => el("option", { value: c, text: c })));
    const dueIn = el("input", { type: "date", value: todayISO() });
    const catIn = el("input", { placeholder: "category", value: "Subscriptions",
                                style: "width:130px" });
    const acctSel = el("select", {}, [el("option", { value: "", text: "account…" })]
      .concat(accounts.map((a) => el("option", { value: a.id, text: a.name }))));
    const add = el("button.btn-primary", { text: "+ add", onclick: () => guard(async () => {
      if (!nameIn.value.trim()) return toast("what is it?", true);
      await api.recurring.create({
        name: nameIn.value.trim(),
        amount: parseFloat(amtIn.value) || 0,
        cadence: cadSel.value,
        next_due: dueIn.value,
        category: catIn.value.trim() || "Subscriptions",
        account_id: acctSel.value || null,
      });
      nameIn.value = amtIn.value = "";
      reload();
    }) });
    host.appendChild(el("div.row.vr-add", {},
      [nameIn, amtIn, cadSel, dueIn, catIn, acctSel, add]));

    if (!items.length) {
      host.appendChild(el("div.empty", {
        text: "Nothing tracked yet. Add a subscription, or a one-off payment you need to remember.",
      }));
      return;
    }

    /* --- grouped: what repeats, what doesn't, what you've stopped --- */
    const groups = [
      { key: "repeating", label: "Subscriptions",
        of: (r) => r.active && r.cadence !== "once" },
      { key: "once", label: "One-off payments",
        of: (r) => r.active && r.cadence === "once" },
      { key: "paused", label: "Paused / finished", of: (r) => !r.active },
    ];
    groups.forEach((g) => {
      const list = items.filter(g.of);
      if (!list.length) return;
      host.appendChild(el("div.vr-group", { text: g.label + " · " + list.length }));
      list.forEach((r) => host.appendChild(row(r, reload, accounts)));
    });
  }

  window.VAULT_TXN_TABS = window.VAULT_TXN_TABS || [];
  window.VAULT_TXN_TABS.push({ key: "recurring", label: "Recurring", render });
  // Also expose it directly, so the Transactions view can mount it as a
  // sub-header without knowing anything about this file.
  window.VaultRecurring = { render };
})();

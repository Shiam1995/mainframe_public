/* reminders.js — messages you leave for yourself, and the payments about to
   leave your account.

   Two ways in, because a reminder you have to go looking for isn't a reminder:

     · a bell in the topbar, showing how many things have landed
     · a panel that opens by itself the first time you open the app each day

   The once-a-day rule matters. A panel that appears on every navigation gets
   dismissed reflexively within a week and stops being read; once a day it
   still carries weight. */
(function () {
  const { el, clear, toast, guard, todayISO } = window.ui;
  const api = window.api;

  const SEEN_KEY = "mainframe.reminders.seen";     // the day we last auto-opened
  let feed = { reminders: [], payments: [], total: 0 };
  let panel = null;

  const money = (n) => "£" + (Math.round((n || 0) * 100) / 100).toFixed(2);

  function whenText(days) {
    if (days === null || days === undefined) return "";
    if (days < 0) return Math.abs(days) + "d overdue";
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    return "in " + days + "d";
  }

  /* ------------------------------------------------------------------ *
   * The panel
   * ------------------------------------------------------------------ */
  function close() { if (panel) { panel.remove(); panel = null; } }

  function open() {
    close();
    panel = el("div.rm-panel");

    const head = el("div.rm-head", {}, [
      el("span.rm-title", { text: feed.total
        ? feed.total + " thing" + (feed.total === 1 ? "" : "s") + " for you today"
        : "Nothing due" }),
      el("button.rm-x", { text: "×", onclick: close }),
    ]);
    panel.appendChild(head);

    const body = el("div.rm-body");

    if (feed.reminders.length) {
      body.appendChild(el("div.rm-group", { text: "reminders" }));
      feed.reminders.forEach((r) => {
        body.appendChild(el("div.rm-item", {}, [
          el("div.rm-msg", { text: r.message }),
          el("div.rm-meta", {}, [
            el("span" + (r.days_until < 0 ? ".rm-late" : ""), { text: whenText(r.days_until) }),
            r.ref_title ? el("span", { text: " · " + r.ref_title }) : null,
            r.repeat && r.repeat !== "once" ? el("span", { text: " · " + r.repeat }) : null,
          ]),
          el("button.rm-btn", { text: "done", onclick: () => guard(async () => {
            await api.reminders.update(r.id, { done: true });
            await refresh();
            open();
          }) }),
        ]));
      });
    }

    if (feed.payments.length) {
      body.appendChild(el("div.rm-group", { text: "money going out" }));
      feed.payments.forEach((p) => {
        body.appendChild(el("div.rm-item", {}, [
          el("div.rm-msg", { text: p.name + " · " + money(p.amount) }),
          el("div.rm-meta", {}, [
            el("span" + (p.overdue ? ".rm-late" : ""), { text: whenText(p.days_until) }),
            el("span", { text: " · " + (p.cadence || "") }),
            p.notes ? el("span", { text: " · " + p.notes }) : null,
          ]),
          el("button.rm-btn", { text: "paid", onclick: () => guard(async () => {
            await api.recurring.pay(p.id, {});
            await refresh();
            open();
            toast("logged to the ledger");
          }) }),
        ]));
      });
    }

    if (!feed.total) {
      body.appendChild(el("div.rm-empty", {
        text: "Nothing due today. Anything you add below will find you on the day.",
      }));
    }

    /* --- leave yourself a new one --- */
    const msgIn = el("input", { placeholder: "remind me to…", style: "flex:1;min-width:150px" });
    const dateIn = el("input", { type: "date", value: todayISO() });
    const repSel = el("select.vr-mini", {}, ["once", "weekly", "monthly", "quarterly", "yearly"]
      .map((c) => el("option", { value: c, text: c })));
    const add = el("button.rm-btn.rm-add", { text: "+ set", onclick: () => guard(async () => {
      if (!msgIn.value.trim()) return toast("what should it say?", true);
      await api.reminders.create({
        message: msgIn.value.trim(), due: dateIn.value, repeat: repSel.value,
      });
      msgIn.value = "";
      await refresh();
      open();
      toast("reminder set");
    }) });
    body.appendChild(el("div.rm-new", {}, [msgIn, dateIn, repSel, add]));

    panel.appendChild(body);
    document.body.appendChild(panel);
  }

  /* ------------------------------------------------------------------ *
   * The bell
   * ------------------------------------------------------------------ */
  function paintBell() {
    const b = document.getElementById("rm-bell");
    if (!b) return;
    const late = feed.reminders.some((r) => r.days_until < 0)
              || feed.payments.some((p) => p.overdue);
    b.className = "rm-bell" + (feed.total ? (late ? " late" : " on") : "");
    b.textContent = feed.total ? "🔔 " + feed.total : "🔔";
    b.title = feed.total
      ? feed.total + " reminder(s) / payment(s) due — click to see"
      : "nothing due · click to leave yourself a reminder";
  }

  async function refresh() {
    try { feed = await api.reminders.due(); } catch { /* backend down; leave it */ }
    paintBell();
  }

  function mount() {
    const host = document.getElementById("status-pill");
    if (!host) return;
    const bell = el("button.rm-bell", { id: "rm-bell", text: "🔔",
      onclick: (e) => { e.stopPropagation(); panel ? close() : open(); } });
    host.insertBefore(bell, host.firstChild);
    document.addEventListener("click", (e) => {
      if (panel && !panel.contains(e.target) && e.target.id !== "rm-bell") close();
    });

    guard(async () => {
      await refresh();
      // Auto-open once a day, and only when there's actually something to say.
      let seen = "";
      try { seen = localStorage.getItem(SEEN_KEY) || ""; } catch { /* ignore */ }
      if (feed.total && seen !== todayISO()) {
        try { localStorage.setItem(SEEN_KEY, todayISO()); } catch { /* ignore */ }
        open();
      }
    });
  }

  window.Reminders = { open, refresh, count: () => feed.total };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

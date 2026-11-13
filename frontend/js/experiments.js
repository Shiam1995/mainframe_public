/* experiments.js — Pulse: Experiments. Test a habit for N days before committing.
   Hypothesis → clickable day-dots → conclusion. Amber while active, green when done. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const DAY = P.DAY;

  function endDate(e) {
    try { const d = new Date(e.start_date + "T00:00:00"); d.setDate(d.getDate() + (e.days - 1)); return P.fmtDay(P.dateStr(d)); }
    catch { return "?"; }
  }

  function newExpModal(reload) {
    const name = el("input.mform-input", { placeholder: "the habit being tested" });
    const days = el("input.mform-input", { type: "number", min: "1", value: "14" });
    const unit = el("select.mform-input", {}, [
      el("option", { value: "days", text: "days" }), el("option", { value: "weeks", text: "weeks" })]);
    const start = el("input.mform-input", { type: "date", value: P.today() });
    const hyp = el("input.mform-input", { placeholder: "I think this will…" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("New experiment", [
      field("Name", name), el("div.mform-row", {}, [field("Duration", days), field("Unit", unit), field("Start date", start)]), field("Hypothesis", hyp),
    ], [
      { label: "Create", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        await api.pulse.createExperiment({ name: name.value.trim(), days: parseInt(days.value) || 14, unit: unit.value, start_date: start.value, hypothesis: hyp.value.trim() });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function expCard(e, reload) {
    const done = e.days_done || [];
    const pct = Math.round((done.length / e.days) * 100);
    const completed = e.status === "completed";
    const card = el("div.pulse-card" + (completed ? ".exp-done" : ".exp-active"), {}, [
      el("div.spread", {}, [
        el("span", { style: "font-weight:600;font-size:15px", text: e.name }),
        el("div.row", { style: "gap:6px" }, [
          completed ? el("span.pulse-tag", { style: "background:var(--green-d);color:var(--green)", text: "completed" }) : null,
          el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete experiment “" + e.name + "”?", async () => { await api.pulse.delExperiment(e.id); reload(); }), text: "×" }),
        ]),
      ]),
      el("div.sub", { style: "margin-top:3px", text: e.days + " days · " + P.fmtDay(e.start_date) + " → " + endDate(e) + " · " + done.length + "/" + e.days + " done" }),
      el("div.exp-bar", {}, [el("div.exp-bar-fill", { style: "width:" + pct + "%" })]),
    ]);
    if (e.hypothesis) card.appendChild(el("p.sub", { style: "margin:8px 0 6px;font-style:italic", text: "“" + e.hypothesis + "”" }));

    /* Days — each one opens a journal entry, not a toggle. The dot shows
       adherence 0-4 at a glance; clicking opens the day to write in. */
    const dayHost = el("div", { style: "margin-top:8px" });
    card.appendChild(dayHost);
    guard(async () => {
      const days = await api.get("/api/pulse/experiments/" + e.id + "/days");
      clear(dayHost);
      const written = days.filter((d) => d.written).length;
      dayHost.appendChild(el("div.sub", { style: "font-size:11px;margin-bottom:6px",
        text: written + " of " + days.length + " days written" }));
      const grid = el("div.exp-dots");
      days.forEach((d) => {
        const lvl = d.adherence == null ? (d.done ? 4 : -1) : d.adherence;
        const dot = el("div.exp-dot" + (d.done ? ".on" : "") + (lvl >= 0 ? ".adh" + lvl : ""), {
          title: "day " + d.day + " · " + d.date + (d.what_happened ? " — " + d.what_happened.slice(0, 60) : " — not written yet"),
          text: String(d.day),
        });
        dot.addEventListener("click", () => dayModal(e, d, reload));
        grid.appendChild(dot);
      });
      dayHost.appendChild(grid);
    });

    if (completed && e.conclusion) card.appendChild(el("p.sub", { style: "margin-top:10px", text: "Conclusion: " + e.conclusion }));
    window.Images.mount(card, { module: "pulse", contextId: e.id, surface: "pulse-experiment", title: "Images" });
    if (!completed) {
      card.appendChild(el("div.row", { style: "margin-top:10px" }, [
        el("button.btn-sm.btn-primary", { onclick: () => completeModal(e, reload), text: "Complete" }),
      ]));
    }
    return card;
  }

  /* One day of an experiment — what happened, how it went, how it felt. */
  function dayModal(e, d, reload) {
    const what = el("textarea.mform-input", { rows: "3", placeholder: "what happened today" });
    what.value = d.what_happened || "";
    const notes = el("textarea.mform-input", { rows: "2", placeholder: "anything else" });
    notes.value = d.notes || "";
    const feel = el("input.mform-input", { placeholder: "how it felt", value: d.feel || "" });
    const adh = el("select.mform-input", {}, [
      { v: "", t: "—" }, { v: "0", t: "0 · missed it" }, { v: "1", t: "1 · barely" },
      { v: "2", t: "2 · okay" }, { v: "3", t: "3 · good" }, { v: "4", t: "4 · nailed it" },
    ].map((o) => {
      const n = el("option", { value: o.v, text: o.t });
      if (String(d.adherence == null ? "" : d.adherence) === o.v) n.setAttribute("selected", "");
      return n;
    }));
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Day " + d.day + " · " + d.date, [
      field("What happened", what),
      el("div.mform-row", {}, [field("Adherence", adh), field("Feel", feel)]),
      field("Notes", notes),
    ], [
      { label: "Save", primary: true, onClick: (close) => guard(async () => {
        await api.put("/api/pulse/experiments/" + e.id + "/days/" + d.day, {
          what_happened: what.value.trim(), notes: notes.value.trim(),
          feel: feel.value.trim(),
          adherence: adh.value === "" ? null : parseInt(adh.value),
        });
        toast("day " + d.day + " saved"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function completeModal(e, reload) {
    const concl = el("input.mform-input", { placeholder: "What did you conclude? Keep it, drop it, adjust it?" });
    P.modal("Complete “" + e.name + "”", [el("div.mform-full", {}, [el("div.mform-label", { text: "Conclusion" }), concl])], [
      { label: "Complete", primary: true, onClick: (close) => guard(async () => {
        await api.pulse.updateExperiment(e.id, { status: "completed", conclusion: concl.value.trim() }); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  window.Views = window.Views || {};
  window.Views.experiments = {
    id: "experiments", label: "Experiments", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [el("h1", { text: "Experiments" }), el("div.sub", { text: "Test a habit for a set number of days — hypothesis → test → conclusion." })]),
        el("button.btn-primary", { onclick: () => newExpModal(reload), text: "＋ new experiment" }),
      ]));
      const host = el("div"); view.appendChild(host);
      async function reload() {
        const exps = await guard(() => api.pulse.experiments());
        clear(host);
        if (!exps.length) { host.appendChild(el("div.empty", { text: "No experiments yet. Start one above." })); return; }
        exps.forEach((e) => host.appendChild(expCard(e, reload)));
      }
      reload();
    },
  };
})();

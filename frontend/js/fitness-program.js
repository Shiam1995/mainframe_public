/* fitness-program.js — Pulse Fitness Program: training cycles with a clickable
   week grid (current week highlighted, completed weeks filled), each cycle's
   training days with what they prescribe, and your maxes.

   A day repeats every week of its cycle. The Log workout form reads all of
   this from GET /fitness/today: the day after the last one logged this week,
   its prescriptions, and the maxes a "% of max" is taken from. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const TYPES = ["Push", "Pull", "Legs", "Upper", "Lower", "Full Body", "Cardio", "HIIT", "Sport", "Other"];
  const PHASES = ["Hypertrophy", "Strength", "Power", "Endurance", "Deload", "Cut", "Bulk", "Maintenance", "Rehab"];

  function newCycleModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Hypertrophy Block" });
    const weeks = el("input.mform-input", { type: "number", min: "1", value: "12" });
    const start = el("input.mform-input", { type: "date", value: P.today() });
    // End = start + weeks*7 - 1, filled in as you go. Set the end instead and
    // the weeks follow (rounded up to whole weeks, so the end moves to match).
    const end = el("input.mform-input", { type: "date" });
    const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
    const syncEnd = () => {
      const w = parseInt(weeks.value) || 0;
      if (!start.value || w < 1) { end.value = ""; return; }
      const d = new Date(start.value + "T00:00:00"); d.setDate(d.getDate() + w * 7 - 1);
      end.value = iso(d);
    };
    const syncWeeks = () => {
      if (!start.value || !end.value) return;
      const days = Math.round((new Date(end.value + "T00:00:00") - new Date(start.value + "T00:00:00")) / 86400000) + 1;
      if (days < 1) return toast("the end is before the start", true);
      weeks.value = String(Math.ceil(days / 7));
      syncEnd();
    };
    weeks.addEventListener("input", syncEnd);
    start.addEventListener("change", syncEnd);
    end.addEventListener("change", syncWeeks);
    syncEnd();
    const phase = el("select.mform-input", {}, PHASES.map((p) => el("option", { value: p, text: p })));
    // + rows, held until the cycle exists and then committed onto it.
    const goals = window.RowBox({ label: "goals", kind: "goal", noun: "goal", placeholder: "what do you want to achieve?" });
    const notes = window.RowBox({ label: "notes", placeholder: "split, frequency, key lifts, deload schedule" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("New cycle", [
      field("Name", name), el("div.mform-row-3", {}, [field("Start", start), field("Weeks", weeks), field("End (automatic)", end)]),
      field("Phase", phase),
      goals.node, notes.node,
    ], [
      { label: "Create", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        const made = await api.pulse.fitness.createCycle({ name: name.value.trim(), weeks: parseInt(weeks.value) || 12, start_date: start.value, phase: phase.value });
        await goals.commit(made.id); await notes.commit(made.id);
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  /* ---- program days -------------------------------------------------------- */
  const prescLine = (p) => {
    let t = p.exercise + " " + (p.sets || "?") + "×" + (p.reps || "?");
    if (p.pct_max) t += " @ " + p.pct_max + "%";
    return t;
  };

  // Add or edit one day: its number, a label (a workout type sets the Log
  // form's type), and the exercises it prescribes, one row each.
  function dayModal(c, day, nextDay, reload) {
    const num = el("input.mform-input", { type: "number", min: "1", value: String(day ? day.day : nextDay) });
    const listId = "fw-day-types";
    const label = el("input.mform-input", { value: day ? day.label || "" : "", placeholder: "Legs, Push, Upper…", list: listId });
    const types = el("datalist", { id: listId }, TYPES.map((t) => el("option", { value: t })));
    const rows = (day && day.prescriptions.length ? day.prescriptions : [{}]).map((p) => ({
      exercise: p.exercise || "", sets: p.sets || "", reps: p.reps || "", pct_max: p.pct_max || "" }));
    const body = el("tbody");
    function draw() {
      clear(body);
      rows.forEach((r, i) => {
        const inp = (k, attrs) => {
          const n = el("input.mform-input", Object.assign({ value: r[k] }, attrs || {}));
          n.addEventListener("input", () => { r[k] = n.value; });
          return el("td", {}, [n]);
        };
        body.appendChild(el("tr", {}, [
          inp("exercise", { placeholder: "squat" }),
          inp("sets", { type: "number", min: "1", style: "width:64px" }),
          inp("reps", { type: "number", min: "1", style: "width:64px" }),
          inp("pct_max", { type: "number", min: "1", max: "150", step: "2.5", style: "width:74px", placeholder: "none" }),
          el("td", {}, [rows.length > 1 ? el("button.btn-sm", { text: "×", onclick: () => { rows.splice(i, 1); draw(); } }) : null]),
        ]));
      });
    }
    draw();
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    const table = el("table.fw-day-tbl", { style: "width:100%" }, [
      el("thead", {}, [el("tr", {}, ["exercise", "sets", "reps", "% of max", ""].map((t) => el("th.mform-label", { text: t, style: "text-align:left" })))]),
      body,
    ]);
    const actions = [
      { label: day ? "Save" : "Add day", primary: true, onClick: (close) => guard(async () => {
        const d = parseInt(num.value);
        if (!(d >= 1)) return toast("day number is 1 or more", true);
        const n = (v) => (v === "" || v === null || isNaN(+v) ? null : +v);
        const payload = { day: d, label: label.value.trim(), prescriptions: rows.filter((r) => r.exercise.trim()).map((r) => ({
          exercise: r.exercise.trim(), sets: n(r.sets), reps: n(r.reps), pct_max: n(r.pct_max) })) };
        if (day) await api.pulse.fitness.updateDay(day.id, payload);
        else await api.pulse.fitness.addDay(c.id, payload);
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ];
    P.modal((day ? "Day " + day.day : "New day") + " · " + c.name, [
      el("div.mform-row-3", {}, [field("Day", num), field("Label", label)]), types,
      field("Prescribed", table),
      el("button.btn-sm", { style: "margin-top:6px", text: "+ exercise", onclick: () => { rows.push({ exercise: "", sets: "", reps: "", pct_max: "" }); draw(); } }),
      el("p.sub", { style: "margin-top:8px", text: "The day repeats every week of the cycle. % of max is worked out from your maxes below." }),
    ], actions);
  }

  function daysBlock(c, days, reload) {
    const next = days.reduce((a, d) => Math.max(a, d.day), 0) + 1;
    const wrap = el("div", { style: "margin-top:12px;border-top:1px solid var(--border);padding-top:10px" }, [
      el("div.spread", { style: "margin-bottom:6px" }, [
        el("span.mform-label", { text: "Days, every week" }),
        el("button.btn-sm", { text: "+ day", onclick: () => dayModal(c, null, next, reload) }),
      ]),
    ]);
    if (!days.length) {
      wrap.appendChild(el("div.sub", { text: "No days yet. Add the days of your week and what each prescribes; the Log workout form then picks today's." }));
      return wrap;
    }
    days.forEach((d) => wrap.appendChild(el("div.spread", { style: "padding:4px 0;gap:10px" }, [
      el("div", {}, [
        el("b", { text: "Day " + d.day }), d.label ? el("span.pulse-tag", { style: "margin-left:6px", text: d.label }) : null,
        el("span.sub", { style: "margin-left:8px", text: d.prescriptions.length ? d.prescriptions.map(prescLine).join(", ") : "nothing prescribed" }),
      ]),
      el("div.row", { style: "gap:6px" }, [
        el("button.btn-sm", { text: "edit", onclick: () => dayModal(c, d, next, reload) }),
        el("button.btn-sm.btn-danger", { text: "×", onclick: () => confirmDo("Delete day " + d.day + (d.label ? " (" + d.label + ")" : "") + "? Workouts logged on it keep their cycle.",
          async () => { await api.pulse.fitness.delDay(d.id); reload(); }) }),
      ]),
    ])));
    return wrap;
  }

  /* ---- maxes ------------------------------------------------------------------ */
  function maxesCard(maxes, reload) {
    const ex = el("input.mform-input", { placeholder: "exercise, e.g. squat", style: "width:240px" });
    const kg = el("input.mform-input", { type: "number", min: "0", step: "0.5", placeholder: "kg", style: "width:90px" });
    const add = () => guard(async () => {
      if (!ex.value.trim() || !(+kg.value > 0)) return toast("exercise and kg", true);
      await api.pulse.fitness.addMax({ exercise: ex.value.trim(), kg: +kg.value, reps: 1 });
      reload();
    });
    kg.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    const card = el("div.pulse-card", { style: "margin-bottom:14px" }, [
      el("div.spread", { style: "margin-bottom:8px" }, [
        el("span", { style: "font-weight:600;font-size:15px", text: "Maxes" }),
        el("span.sub", { text: "one-rep max per exercise; % of max prescriptions use these" }),
      ]),
    ]);
    if (!maxes.length) card.appendChild(el("div.sub", { style: "margin-bottom:8px", text: "No maxes yet. Add one here, or tick a new one when a logged set estimates it." }));
    maxes.forEach((m) => {
      const how = m.source === "workout" && m.from_kg ? "from " + m.from_kg + "kg × " + m.from_reps : m.source === "workout" ? "from a workout" : "set by hand";
      const prev = m.previous && m.previous.length ? " · was " + m.previous[0].kg + "kg" : "";
      card.appendChild(el("div.spread", { style: "padding:3px 0" }, [
        el("div", {}, [el("b", { text: m.exercise }), " ", el("span.mono", { text: m.kg + "kg" }),
          el("span.sub", { style: "margin-left:8px", text: P.fmtDay(m.date) + " · " + how + prev })]),
        el("button.btn-sm.btn-danger", { title: "delete this record; the one before it becomes current",
          text: "×", onclick: () => confirmDo("Delete the " + m.kg + "kg " + m.exercise + " max?" + (prev ? " The previous one becomes current." : ""),
            async () => { await api.pulse.fitness.delMax(m.id); reload(); }) }),
      ]));
    });
    card.appendChild(el("div.row", { style: "gap:8px;margin-top:8px" }, [ex, kg, el("button.btn-sm.btn-primary", { text: "add max", onclick: add })]));
    return card;
  }

  // The week a cycle card has open, kept across reloads so ticking a week
  // doesn't snap the panel back to the current one.
  const openWeek = {};

  function cycleCard(c, days, reload) {
    const manual = c.weeks_done || [];
    const auto = c.weeks_auto || [];
    const done = [...new Set(manual.concat(auto))];
    const completed = c.status === "completed";
    const card = el("div.pulse-card" + (completed ? ".exp-done" : ""), {}, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:6px" }, [
          el("span", { style: "font-weight:600;font-size:15px", text: c.name }),
          el("span.pulse-tag", { text: c.phase }),
          el("span.pulse-tag", { text: c.weeks + " wk" }),
          c.start_date && c.end_date ? el("span.sub", { text: P.fmtDay(c.start_date.slice(0, 10)) + " to " + P.fmtDay(c.end_date) }) : null,
          c.current_week ? el("span.pulse-tag", { text: "week " + c.current_week }) : null,
          el("span.sub", { text: done.length + "/" + c.weeks + " done" }),
        ]),
        el("div.row", { style: "gap:6px" }, [
          completed ? null : el("button.btn-sm.btn-primary", { onclick: () => guard(async () => { await api.pulse.fitness.updateCycle(c.id, { status: "completed" }); reload(); }), text: "complete" }),
          el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete cycle “" + c.name + "”?", async () => { await api.pulse.fitness.delCycle(c.id); reload(); }), text: "×" }),
        ]),
      ]),
    ]);
    // week grid: a square is done when its workouts cover every training day
    // (auto) or when you tick it by hand. Clicking opens that week's log.
    const grid = el("div.week-grid");
    const panel = el("div.week-log");
    let sel = openWeek[c.id] || c.current_week || 1;
    const squares = [];
    const showWeek = (i) => {
      sel = openWeek[c.id] = i;
      squares.forEach((q, k) => q.classList.toggle("sel", k + 1 === i));
      clear(panel);
      const logged = (c.week_workouts || {})[String(i)] || [];
      const isAuto = auto.includes(i), isManual = manual.includes(i);
      const status = isAuto ? "done: every training day logged"
        : isManual ? "done: ticked by hand"
        : days.length ? logged.filter((w) => w.day_id).length + " of " + days.length + " training days logged"
        : "no training days set, so tick it by hand";
      panel.appendChild(el("div.spread", {}, [
        el("div.row", { style: "gap:8px" }, [
          el("span", { style: "font-weight:600", text: "Week " + i }),
          el("span.sub", { text: status }),
        ]),
        isAuto ? null : el("button.btn-sm", { text: isManual ? "undo done" : "mark done",
          onclick: () => guard(async () => {
            const next = isManual ? manual.filter((x) => x !== i) : manual.concat(i);
            await api.pulse.fitness.updateCycle(c.id, { weeks_done: next }); reload();
          }) }),
      ]));
      if (!logged.length) { panel.appendChild(el("div.sub", { style: "margin-top:6px", text: "No workouts logged in this week." })); return; }
      logged.forEach((w) => panel.appendChild(el("div.row.week-log-row", {}, [
        el("span.sub", { style: "font-family:var(--mono);min-width:86px", text: P.fmtDay(String(w.date).slice(0, 10)) }),
        el("span", { text: w.type || "workout" }),
        w.day != null ? el("span.pulse-tag", { text: "day " + w.day + (w.label ? " · " + w.label : "") })
          : el("span.sub", { text: "no program day" }),
      ])));
    };
    for (let i = 1; i <= c.weeks; i++) {
      const cls = (i === c.current_week ? ".current" : "") + (done.includes(i) ? ".done" : "");
      const sq = el("div.week-sq" + cls, {
        title: "week " + i + (auto.includes(i) ? " · done (all days logged)" : manual.includes(i) ? " · done (by hand)" : ""),
        text: done.includes(i) && i === c.current_week ? "✓" : String(i) });
      sq.addEventListener("click", () => showWeek(i));
      squares.push(sq);
      grid.appendChild(sq);
    }
    card.appendChild(grid);
    card.appendChild(panel);
    if (c.weeks) showWeek(Math.min(sel, c.weeks));
    card.appendChild(window.RowBox({ label: "goals", kind: "goal", noun: "goal", parentId: c.id }).node);
    card.appendChild(window.RowBox({ label: "notes", parentId: c.id }).node);
    card.appendChild(daysBlock(c, days, reload));
    window.Images.mount(card, { module: "pulse", contextId: c.id, surface: "pulse-cycle", title: "Images" });
    return card;
  }

  async function render(host) {
    async function reload() {
      const [cycles, maxes] = await guard(() => Promise.all([api.pulse.fitness.cycles(), api.pulse.fitness.maxes()]));
      const days = await guard(() => Promise.all(cycles.map((c) => api.pulse.fitness.days(c.id))));
      clear(host);
      host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [
        el("button.btn-primary", { onclick: () => newCycleModal(reload), text: "＋ new cycle" }),
      ]));
      host.appendChild(maxesCard(maxes, reload));
      if (!cycles.length) { host.appendChild(el("div.empty", { text: "No training cycles yet. Start one above." })); return; }
      cycles.forEach((c, i) => host.appendChild(cycleCard(c, days[i], reload)));
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "program", label: "Program", render });
})();

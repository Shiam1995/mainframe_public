/* routines.js — Pulse: Routines. Multi-step routines with an inline last-5-logs
   view per step and a FAST 3-field quick-log (date/time/note). Pink cards. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const UNITS = ["days", "weeks", "months", "ongoing"];

  const open = new Set();

  /* Calendar scheduling — shared by habits and routines so a calendar module
     can read either without knowing which it is. 0 = Monday. */
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  function schedulePicker() {
    const boxes = DOW.map(() => el("input", { type: "checkbox" }));
    const time = el("input.mform-input", { type: "time" });
    const mins = el("input.mform-input", { type: "number", min: "0", placeholder: "mins" });
    const days = el("div.row", { style: "gap:10px;flex-wrap:wrap" },
      DOW.map((d, i) => el("label.wl-check", {}, [boxes[i], el("span", { text: " " + d })])));
    return {
      days, time, mins,
      value: () => ({
        days_of_week: boxes.map((b, i) => (b.checked ? i : -1)).filter((i) => i >= 0),
        time_of_day: time.value || "",
        duration_mins: parseInt(mins.value) || 0,
      }),
    };
  }

  function newRoutineModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. 8-Week Deep Clean" });
    const dur = el("input.mform-input", { type: "number", min: "0", placeholder: "duration (optional)" });
    const unit = el("select.mform-input", {}, UNITS.map((u) => el("option", { value: u, text: u })));
    const cat = el("select.mform-input", {}, P.ROUTINE_CATS.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key })));
    const notes = el("input.mform-input", { placeholder: "describe the routine…" });
    const sched = schedulePicker();
    const start = el("input.mform-input", { type: "date" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("New routine", [
      field("Name", name), el("div.mform-row-3", {}, [field("Duration", dur), field("Unit", unit), field("Category", cat)]), field("Days (for the calendar)", sched.days),
      el("div.mform-row-3", {}, [field("Time of day", sched.time), field("Duration (mins)", sched.mins), field("Start date", start)]),
      field("Notes", notes),
    ], [
      { label: "Create", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        await api.pulse.createRoutine({ name: name.value.trim(), duration: parseInt(dur.value) || null, unit: unit.value, category: cat.value, main_notes: notes.value.trim(), start_date: start.value || null, ...sched.value() });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function quickLogModal(r, step, reload) {
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const time = el("input.mform-input", { placeholder: "e.g. 20 min" });
    const note = el("input.mform-input", { placeholder: "quick note about this session…" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Log — " + step.name, [el("div.mform-row", {}, [field("Date", date), field("Time spent", time)]), field("Note", note)], [
      { label: "Save", primary: true, onClick: (close) => guard(async () => {
        await api.pulse.logStep(r.id, step.id, { date: date.value, time: time.value.trim(), note: note.value.trim() });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function routineCard(r, reload) {
    const isOpen = open.has(r.id);
    const totalLogs = (r.steps || []).reduce((a, s) => a + (s.logs ? s.logs.length : 0), 0);
    const header = el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(r.id) : open.add(r.id); reload(); } }, [
      el("div.row", { style: "gap:8px" }, [
        el("span", { style: "font-size:18px", text: P.catIcon(P.ROUTINE_CATS, r.category) }),
        el("span", { style: "font-weight:600;font-size:15px", text: r.name }),
      ]),
      el("div.row", { style: "gap:6px" }, [
        el("span.pulse-tag", { text: r.category }),
        r.duration ? el("span.pulse-tag", { text: r.duration + " " + r.unit }) : el("span.pulse-tag", { text: r.unit }),
        el("span.sub", { text: (r.steps.length) + " steps · " + totalLogs + " logs · " + (r.notes.length) + " notes" }),
      ]),
    ]);
    const card = el("div.pulse-card", {}, [header]);
    card.appendChild(el("div.row", { style: "gap:6px;margin-top:8px" }, [
      el("button.btn-sm", { onclick: () => addStepModal(r, reload), text: "＋ step" }),
      el("button.btn-sm", { onclick: () => addNoteModal(r, reload), text: "＋ note" }),
      el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete routine “" + r.name + "”?", async () => { await api.pulse.delRoutine(r.id); reload(); }), text: "× delete" }),
    ]));
    if (isOpen) {
      const body = el("div", { style: "margin-top:12px;border-top:1px solid var(--border);padding-top:12px" });
      if (r.main_notes) body.appendChild(el("p.sub", { style: "line-height:1.5;margin:0 0 10px", text: r.main_notes }));
      (r.steps || []).forEach((s, i) => {
        const stepBox = el("div.routine-step");
        stepBox.appendChild(el("div.spread", {}, [
          el("div.row", { style: "gap:8px" }, [
            el("span.step-num", { text: String(i + 1) }),
            el("span", { style: "font-weight:500", text: s.name }),
            s.logs.length ? el("span.pulse-streak", { text: s.logs.length + " logs" }) : null,
          ]),
          el("div.row", { style: "gap:6px" }, [
            el("button.btn-sm.btn-primary", { onclick: () => quickLogModal(r, s, reload), text: "＋ Log" }),
            el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.pulse.delStep(r.id, s.id); reload(); }), text: "×" }),
          ]),
        ]));
        (s.logs || []).slice(0, 5).forEach((l) => stepBox.appendChild(el("div.sub", { style: "padding:2px 0 2px 30px", text: P.fmtDay((l.date || "").slice(0, 10)) + (l.time ? " · " + l.time : "") + (l.note ? " — " + l.note : "") })));
        body.appendChild(stepBox);
      });
      if (r.notes.length) {
        body.appendChild(el("div.mform-label", { style: "margin-top:12px", text: "Notes" }));
        r.notes.forEach((n) => body.appendChild(el("div", { style: "padding:5px 0;border-bottom:1px solid var(--border)" }, [
          el("div.sub", { text: P.fmtDay((n.date || "").slice(0, 10)) }), el("div", { text: n.text }),
        ])));
      }
      window.Images.mount(body, { module: "pulse", contextId: r.id, surface: "pulse-routine", title: "Images" });
      card.appendChild(body);
    }
    return card;
  }

  function addStepModal(r, reload) {
    const inp = el("input.mform-input", { placeholder: "step name, e.g. Kitchen deep clean" });
    P.modal("Add step to “" + r.name + "”", [el("div.mform-full", {}, [inp])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!inp.value.trim()) return; await api.pulse.addStep(r.id, { name: inp.value.trim() }); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }
  function addNoteModal(r, reload) {
    const inp = el("input.mform-input", { placeholder: "note…" });
    P.modal("Add note to “" + r.name + "”", [el("div.mform-full", {}, [inp])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!inp.value.trim()) return; await api.pulse.addRoutineNote(r.id, { text: inp.value.trim() }); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  window.Views = window.Views || {};
  window.Views.routines = {
    id: "routines", label: "Routines", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [el("h1", { text: "Routines" }), el("div.sub", { text: "Structured multi-step routines with fast per-step logging." })]),
        el("button.btn-primary", { onclick: () => newRoutineModal(reload), text: "＋ new routine" }),
      ]));
      const host = el("div"); view.appendChild(host);
      async function reload() {
        const routines = await guard(() => api.pulse.routines());
        clear(host);
        if (!routines.length) { host.appendChild(el("div.empty", { text: "No routines yet. Create one above." })); return; }
        routines.forEach((r) => host.appendChild(routineCard(r, reload)));
      }
      reload();
    },
  };
})();

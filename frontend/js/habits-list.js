/* habits-list.js — Habits ▸ My Habits. Expandable pink-bordered cards with
   sub-habits, a notes timeline, tags, and a 🔥 streak (from Active-Tracking day
   logs). Registers into HABIT_TABS; the habits.js shell renders the sub-tab bar. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const FREQS = ["daily", "weekdays", "3x-week", "weekly", "custom"];

  const open = new Set(); // expanded habit ids (kept across re-draws)

  function tag(text, style) { return el("span.pulse-tag", { style: style || "", text }); }

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

  function newHabitModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Read for 30 minutes" });
    const cat = el("select.mform-input", {}, P.HABIT_CATS.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key })));
    const freq = el("select.mform-input", {}, FREQS.map((f) => el("option", { value: f, text: f })));
    const target = el("input.mform-input", { placeholder: "target (optional, e.g. 30 min)" });
    const tags = el("input.mform-input", { placeholder: "tags, comma-separated (optional)" });
    const notes = el("input.mform-input", { placeholder: "why this habit? the intention…" });
    const sched = schedulePicker();
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("New habit", [
      field("Name", name), el("div.mform-row", {}, [field("Category", cat), field("Frequency", freq)]),
      field("Target", target), field("Tags", tags),
      field("Days (for the calendar)", sched.days),
      el("div.mform-row", {}, [field("Time of day", sched.time), field("Duration (mins)", sched.mins)]),
      field("Intention / notes", notes),
    ], [
      { label: "Create", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        await api.pulse.createHabit({
          name: name.value.trim(), category: cat.value, frequency: freq.value,
          target: target.value.trim() || null, main_notes: notes.value.trim(),
          tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
          ...sched.value(),
        });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function habitCard(h, reload) {
    const isOpen = open.has(h.id);
    const st = P.streak(h.logs);
    const header = el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(h.id) : open.add(h.id); reload(); } }, [
      el("div.row", { style: "gap:8px" }, [
        el("span", { style: "font-size:18px", text: P.catIcon(P.HABIT_CATS, h.category) }),
        el("span", { style: "font-weight:600;font-size:15px", text: h.name }),
      ]),
      el("div.row", { style: "gap:6px" }, [
        tag(h.category), tag(h.frequency),
        h.target ? el("span.sub", { text: h.target }) : null,
        st > 0 ? el("span.pulse-streak", { text: "🔥 " + st + " day" + (st === 1 ? "" : "s") }) : null,
        el("span.sub", { text: (h.subs.length) + " sub · " + (h.notes.length) + " notes" }),
      ]),
    ]);
    const card = el("div.pulse-card", {}, [header]);
    card.appendChild(el("div.row", { style: "gap:6px;margin-top:8px" }, [
      el("button.btn-sm", { onclick: () => addSubModal(h, reload), text: "＋ sub-habit" }),
      el("button.btn-sm", { onclick: () => addNoteModal(h, reload), text: "＋ note" }),
      el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete habit “" + h.name + "”?", async () => { await api.pulse.delHabit(h.id); reload(); }), text: "× delete" }),
    ]));
    if (isOpen) {
      const body = el("div", { style: "margin-top:12px;border-top:1px solid var(--border);padding-top:12px" });
      if (h.main_notes) body.appendChild(el("p.sub", { style: "line-height:1.5;margin:0 0 10px", text: h.main_notes }));

      /* Why this habit. The same (:Note {kind:'why'}) every other tab writes,
         so it shows up in the Reasoning tab alongside the reasons for goals,
         ideas and projects — one node, editable from either end, and editing
         from either end appends a new dated why rather than overwriting.

         Separate from the "Intention / notes" field above it, which is part of
         the habit and is rewritten in place. This is the record of what you
         thought at the time, which is a different thing from what you think. */
      if (window.Notes) {
        body.appendChild(el("div.mform-label", { style: "margin-top:4px", text: "Why this habit" }));
        body.appendChild(window.Notes.panel({ target_id: h.id }, {
          kind: "why",
          empty: "no reason written down yet. what is it for, and what changes if you keep it?",
          placeholder: "why this habit",
        }));
      }
      if (h.tags && h.tags.length) body.appendChild(el("div.row", { style: "gap:5px;margin-bottom:10px" }, h.tags.map((t) => el("span.pulse-chip", { text: t }))));
      if (h.subs.length) {
        body.appendChild(el("div.mform-label", { text: "Sub-habits" }));
        h.subs.forEach((s) => body.appendChild(el("div.spread", { style: "padding:4px 0;border-bottom:1px solid var(--border)" }, [
          el("span", { text: "◦ " + s.name }),
          el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.pulse.delSub(h.id, s.id); reload(); }), text: "×" }),
        ])));
      }
      if (h.notes.length) {
        body.appendChild(el("div.mform-label", { style: "margin-top:12px", text: "Notes" }));
        h.notes.forEach((n) => body.appendChild(el("div", { style: "padding:5px 0;border-bottom:1px solid var(--border)" }, [
          el("div.sub", { text: P.fmtDay((n.date || "").slice(0, 10)) }),
          el("div", { text: n.text }),
        ])));
      }
      // progress pics / reference shots for this habit
      window.Images.mount(body, { module: "pulse", contextId: h.id, surface: "pulse-habit", title: "Images" });
      card.appendChild(body);
    }
    return card;
  }

  function addSubModal(h, reload) {
    const inp = el("input.mform-input", { placeholder: "sub-habit name" });
    P.modal("Add sub-habit to “" + h.name + "”", [el("div.mform-full", {}, [inp])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!inp.value.trim()) return; await api.pulse.addSub(h.id, { name: inp.value.trim() }); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }
  function addNoteModal(h, reload) {
    const inp = el("input.mform-input", { placeholder: "what happened / a thought…" });
    P.modal("Add note to “" + h.name + "”", [el("div.mform-full", {}, [inp])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!inp.value.trim()) return; await api.pulse.addHabitNote(h.id, { text: inp.value.trim() }); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    async function reload() {
      const habits = await guard(() => api.pulse.habits());
      clear(host);
      host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [
        el("button.btn-primary", { onclick: () => newHabitModal(reload), text: "＋ new habit" }),
      ]));
      if (!habits.length) { host.appendChild(el("div.empty", { text: "No habits yet. Add your first above." })); return; }
      habits.forEach((h) => host.appendChild(habitCard(h, reload)));
    }
    reload();
  }

  window.HABIT_TABS = window.HABIT_TABS || [];
  window.HABIT_TABS.push({ key: "list", label: "My Habits", render });
})();

/* habits-areas.js — Habits ▸ By area (mainframe_habits_areas.html).

   Every habit sits in an AREA (Fitness, Sleep, Diet, …) that links to the
   module its data lives in. The week is Mon–Sun. Each day is worked out by the
   server from the habit's source — a workout, a food entry, study minutes, a
   recovery session, a day with no spending — or ticked by hand. Day squares:
   green done · amber missed · blue excused · light red moved/made up ·
   hatched no data yet · grey not yet.

   Click a past day to cycle your hand mark: done → excused → moved → clear.
   A future day toggles a planned make-up ("moved"). Registers into HABIT_TABS. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const A = () => api.pulse.areas;

  let anchor = null;                       // a date inside the shown week; null = this week
  let areaFilter = null;                   // area key, or null for all
  let chip = "all";                        // all · main · experimental · needs
  let recoveryTypes = null;

  const SOURCES = [
    { key: "tick", label: "tick by hand" },
    { key: "workout", label: "derived from workouts" },
    { key: "food", label: "derived from Nutrition entries" },
    { key: "study", label: "derived from study / build sessions" },
    { key: "recovery", label: "derived from recovery sessions" },
    { key: "no_spend", label: "derived from Transactions (no-spend day)" },
  ];
  const FREQS = [
    { key: "daily", label: "daily" }, { key: "weekdays", label: "weekdays" },
    { key: "3x-week", label: "times per week" },
  ];
  const STATE_TITLE = { done: "done", miss: "missed", exception: "excused", adjust: "moved / made up",
    today: "today, not done yet", future: "not yet", open: "not done", nodata: "no data yet",
    off: "not due", before: "before this habit existed" };

  const shiftDay = (iso, days) => { const d = new Date(iso + "T00:00:00"); d.setDate(d.getDate() + days); return P.dateStr(d); };

  function describe(h) {
    const w = h.week;
    const freq = w.weekly ? w.target + " per week" : h.frequency === "weekdays" ? "weekdays" : "daily";
    let how;
    switch (w.source) {
      case "workout": how = "derived from workouts" + (h.source_types.length ? " (" + h.source_types.join(", ") + ")" : ""); break;
      case "food": how = "derived from Nutrition entries"; break;
      case "study": how = "derived from " + (h.source_types.length ? h.source_types.join(" + ") : "study + build") + " sessions" + (h.source_min ? " ≥ " + (h.source_min >= 60 ? (h.source_min / 60) + "h" : h.source_min + "m") : ""); break;
      case "recovery": how = "derived from recovery sessions: " + h.source_types.join(", "); break;
      case "no_spend": how = "derived from Transactions · back-fills on import"; break;
      default: how = "tick";
    }
    const bits = [freq, how];
    if (w.trial) bits.unshift("trial · week " + Math.min(w.trial.week, w.trial.of) + " of " + w.trial.of + (w.trial.week > w.trial.of ? " · decide" : ""));
    if (h.in_protocol) bits.push("in the Recovery protocol");
    return bits.join(" · ");
  }

  function rate(h) {
    const w = h.week;
    const bits = [w.due ? w.done + " of " + w.due : "—"];
    if (w.exceptions) bits.push(w.exceptions + " exc");
    if (w.adjust_pending) bits.push(w.adjust_pending + " make-up");
    return bits.join(" · ");
  }

  /* ---- modals ------------------------------------------------------------ */
  async function habitModal(areas, existing, presetArea, reload) {
    if (!recoveryTypes) recoveryTypes = await api.pulse.recovery.types().catch(() => []);
    const f = (k, d) => (existing && existing[k] != null ? existing[k] : d);
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    const name = el("input.mform-input", { value: f("name", ""), placeholder: "e.g. Gym, legs push pull" });
    const icon = el("input.mform-input", { value: f("icon", ""), placeholder: "emoji", maxLength: "3", style: "width:70px;text-align:center" });
    const area = el("select.mform-input", {}, areas.map((a) => el("option", { value: a.key, text: a.name })));
    area.value = existing ? existing.area : (presetArea || areas[0].key);
    const freq = el("select.mform-input", {}, FREQS.map((x) => el("option", { value: x.key, text: x.label })));
    const isWeekly = existing && existing.week.weekly;
    freq.value = isWeekly ? "3x-week" : (existing && existing.frequency === "weekdays" ? "weekdays" : "daily");
    const perWeek = el("input.mform-input", { type: "number", min: "1", max: "7", value: String(isWeekly ? existing.week.target : 3) });
    const perWeekField = field("Times per week", perWeek);
    const source = el("select.mform-input", {}, SOURCES.map((x) => el("option", { value: x.key, text: x.label })));
    source.value = existing ? existing.week.source : "tick";
    const types = el("input.mform-input", { value: (existing ? existing.source_types : []).join(", "), placeholder: "optional, comma-separated — e.g. Run, Swim" });
    const typesField = field("Only these types", types);
    const recBoxes = (recoveryTypes || []).filter((t, i, all) => all.findIndex((x) => x.name.toLowerCase() === t.name.toLowerCase()) === i).map((t) => {
      const b = el("input", { type: "checkbox" }); b.dataset.name = t.name;
      b.checked = (existing ? existing.source_types : []).some((x) => x.toLowerCase() === t.name.toLowerCase());
      return el("label.wl-check", {}, [b, el("span", { text: " " + (t.icon || "✨") + " " + t.name })]);
    });
    const recField = field("Recovery sessions that count", el("div.row", { style: "gap:10px;flex-wrap:wrap" }, recBoxes));
    const minH = el("input.mform-input", { type: "number", min: "0", step: "0.25", value: existing && existing.source_min ? String(existing.source_min / 60) : "1" });
    const minField = field("At least (hours a day)", minH);
    const tier = el("select.mform-input", {}, ["main", "experimental", "minor"].map((t) => el("option", { value: t, text: t })));
    tier.value = f("tier", "main");
    const trialWeeks = el("input.mform-input", { type: "number", min: "1", max: "52", value: String(f("trial_weeks", 4)) });
    const trialField = field("Trial length (weeks)", trialWeeks);
    const sync = () => {
      perWeekField.style.display = freq.value === "3x-week" ? "" : "none";
      typesField.style.display = source.value === "workout" ? "" : "none";
      recField.style.display = source.value === "recovery" ? "" : "none";
      minField.style.display = source.value === "study" ? "" : "none";
      trialField.style.display = tier.value === "experimental" ? "" : "none";
    };
    [freq, source, tier].forEach((n) => n.addEventListener("change", sync)); sync();

    const actions = [{ label: existing ? "Save" : "Add", primary: true, onClick: (close) => guard(async () => {
      if (!name.value.trim()) return toast("name it", true);
      let source_types = [];
      if (source.value === "workout") source_types = types.value.split(",").map((t) => t.trim()).filter(Boolean);
      if (source.value === "recovery") {
        source_types = recBoxes.map((l) => l.querySelector("input")).filter((b) => b.checked).map((b) => b.dataset.name);
        if (!source_types.length) return toast("tick at least one recovery type", true);
      }
      const weekly = freq.value === "3x-week";
      const body = {
        name: name.value.trim(), icon: icon.value.trim(), area: area.value, tier: tier.value,
        frequency: weekly ? "3x-week" : freq.value, per_week: weekly ? Math.max(1, Math.min(7, parseInt(perWeek.value) || 3)) : null,
        source: source.value, source_types,
        source_min: source.value === "study" ? Math.round((parseFloat(minH.value) || 0) * 60) : null,
        trial_weeks: tier.value === "experimental" ? parseInt(trialWeeks.value) || 4 : null,
      };
      if (existing) await api.pulse.updateHabit(existing.id, body);
      else await api.pulse.createHabit({ ...body, category: existing ? existing.category : "other" });
      close(); reload();
    }) }];
    if (existing) actions.push({ label: "Delete", onClick: (close) => confirmDo("Delete “" + existing.name + "” and its history?", async () => {
      await api.pulse.delHabit(existing.id); close(); reload();
    }) });
    actions.push({ label: "Cancel", onClick: (close) => close() });
    P.modal(existing ? "Edit habit" : "New habit", [
      el("div.row", { style: "gap:8px" }, [icon, name]),
      el("div.mform-row", {}, [field("Area", area), field("Tier", tier)]),
      trialField,
      el("div.mform-row", {}, [field("How often", freq), perWeekField]),
      field("Counts when", source), typesField, recField, minField,
    ], actions);
  }

  function noteModal(h, reload) {
    const inp = el("input.mform-input", { placeholder: "what happened / a thought…" });
    P.modal("Note on “" + h.name + "”", [el("div.mform-full", {}, [inp])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => {
        if (!inp.value.trim()) return;
        await api.pulse.addHabitNote(h.id, { text: inp.value.trim() }); close(); toast("noted"); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function areasModal(areas, reload) {
    const host = el("div");
    const TABS = Object.keys(window.Views || {}).sort();
    const tabSel = (v) => {
      const s = el("select.mform-input", { style: "width:140px" }, [el("option", { value: "", text: "— no link —" })]
        .concat(TABS.map((t) => el("option", { value: t, text: (window.Views[t].label || t) + " (" + t + ")" }))));
      s.value = v || ""; return s;
    };
    areas.forEach((a) => {
      const nm = el("input.mform-input", { value: a.name, style: "flex:1" });
      const col = el("input", { type: "color", value: a.color || "#8a97a8" });
      const link = tabSel(a.link_tab);
      const save = (k, v) => guard(async () => { await A().update(a.key, { [k]: v }); reload(); });
      nm.addEventListener("change", () => nm.value.trim() && save("name", nm.value.trim()));
      col.addEventListener("change", () => save("color", col.value));
      link.addEventListener("change", () => save("link_tab", link.value));
      host.appendChild(el("div.row", { style: "gap:8px;padding:5px 0;border-bottom:1px solid var(--border);flex-wrap:nowrap" }, [
        col, nm, link,
        el("button.btn-sm.btn-danger", { text: "×", title: "remove area (its habits move back to their category's area)",
          onclick: () => confirmDo("Remove the " + a.name + " area? Its habits are kept.", async () => { await A().del(a.key); reload(); }) }),
      ]));
    });
    const newName = el("input.mform-input", { placeholder: "new area name", style: "flex:1" });
    const newCol = el("input", { type: "color", value: "#8a97a8" });
    const newLink = tabSel("");
    P.modal("Areas", [host, el("div.mform-label", { style: "margin-top:12px", text: "Add an area" }),
      el("div.row", { style: "gap:8px;flex-wrap:nowrap" }, [newCol, newName, newLink])], [
      { label: "Add", primary: true, onClick: () => guard(async () => {
        if (!newName.value.trim()) return toast("name it", true);
        await A().add({ name: newName.value.trim(), color: newCol.value, link_tab: newLink.value });
        newName.value = ""; reload(); toast("area added");
      }) },
      { label: "Done", onClick: (close) => close() },
    ]);
  }

  /* Nightly review: every hand-ticked habit due today, one tap each. Derived
     habits are listed read-only — their source already decided. */
  function reviewModal(data, reload) {
    const today = data.today;
    const rows = [];
    data.areas.forEach((a) => a.habits.forEach((h) => {
      const d = h.week.days.find((x) => x.date === today);
      if (!d || d.state === "off" || d.state === "before") return;
      rows.push({ a, h, d });
    }));
    const host = el("div");
    if (!rows.length) host.appendChild(el("div.sub", { text: "No habits due today — or you're looking at another week." }));
    rows.forEach(({ a, h, d }) => {
      const tick = h.week.source === "tick";
      const mark = (state) => guard(async () => { await A().markDay(h.id, { date: today, state }); btns.dataset.done = state; paint(state); reload(); });
      const status = el("span.sub", { style: "min-width:90px", text: STATE_TITLE[d.state] || d.state });
      const paint = (s) => { status.textContent = { done: "done ✓", exception: "excused", clear: "not done" }[s] || s; };
      const btns = el("span.row", { style: "gap:4px" }, tick ? [
        el("button.btn-sm", { text: "✓ done", onclick: () => mark("done") }),
        el("button.btn-sm", { text: "excuse", onclick: () => mark("exception") }),
        el("button.btn-sm", { text: "✗ no", onclick: () => mark("clear") }),
      ] : [el("span.meta", { text: "from " + a.name + " data" })]);
      host.appendChild(el("div.spread", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
        el("span", { style: "border-left:3px solid " + a.color + ";padding-left:8px", text: (h.icon ? h.icon + " " : "") + h.name }),
        el("span.row", { style: "gap:8px" }, [status, btns]),
      ]));
    });
    P.modal("Nightly review · " + P.fmtDay(today), [host], [{ label: "Done", primary: true, onClick: (close) => close() }]);
  }

  /* ---- the page ---------------------------------------------------------- */
  function dots(h, data, reload) {
    const CYCLE = { done: "exception", exception: "adjust", adjust: "clear" };
    return el("div.ha-dots", {}, h.week.days.map((d) => {
      const isToday = d.date === data.today;
      const sq = el("i.s-" + d.state + (isToday ? ".today" : ""), { title: P.fmtDay(d.date) + " · " + (STATE_TITLE[d.state] || d.state) });
      const future = d.date > data.today;
      if (d.state !== "before" && d.state !== "off") {
        sq.classList.add("click");
        sq.title += future ? " — click to plan a make-up" : " — click to change";
        sq.addEventListener("click", () => guard(async () => {
          const next = future ? (d.state === "adjust" ? "clear" : "adjust") : (CYCLE[d.state] || "done");
          await A().markDay(h.id, { date: d.date, state: next }); reload();
        }));
      }
      return sq;
    }));
  }

  function habitRow(a, h, data, areas, reload) {
    const today = data.today;
    const inWeek = data.week_start <= today && today <= data.week_end;
    const t = h.tier;
    const acts = [];
    if (inWeek) acts.push(el("button.btn-sm", { text: h.week.weekly ? "adjustment" : "exception",
      title: h.week.weekly ? "mark today as moved / made up" : "excuse today",
      onclick: () => guard(async () => { await A().markDay(h.id, { date: today, state: h.week.weekly ? "adjust" : "exception" }); reload(); }) }));
    if (t === "experimental") {
      acts.push(el("button.btn-sm", { text: "promote", onclick: () => guard(async () => { await api.pulse.updateHabit(h.id, { tier: "main" }); reload(); }) }));
      acts.push(el("button.btn-sm", { text: "drop", title: "stop tracking (kept in history)", onclick: () => confirmDo("Drop the trial “" + h.name + "”? It stops showing here; its history is kept.",
        async () => { await api.pulse.updateHabit(h.id, { active: false }); reload(); }) }));
    } else {
      acts.push(el("button.btn-sm", { text: "note", onclick: () => noteModal(h, reload) }));
    }
    acts.push(el("button.btn-sm", { text: "✎", onclick: () => habitModal(areas, h, null, reload) }));
    return el("div.ha-hab", { style: "--c:" + a.color }, [
      el("span", { text: h.icon || P.catIcon(P.HABIT_CATS, h.category) }),
      el("div.nm", {}, [el("span", { text: h.name }), el("span.meta", { text: describe(h) })]),
      dots(h, data, reload),
      el("span.ha-tier." + (t === "experimental" ? "exp" : t), { text: t }),
      el("span.ha-rate", { text: rate(h) }),
      el("span.ha-acts", {}, acts),
    ]);
  }

  function areaCard(a, data) {
    const n = a.habits.length;
    const meta = n ? n + " habit" + (n > 1 ? "s" : "") + (a.exceptions ? " · " + a.exceptions + " exc" : "") : "no habits yet";
    const view = a.link_tab && window.Views[a.link_tab];
    return el("div.ha-area" + (n ? "" : ".empty") + (areaFilter === a.key ? ".on" : ""), {
      style: "--c:" + a.color, title: n ? "show only " + a.name : "",
      onclick: () => { areaFilter = areaFilter === a.key ? null : a.key; render.reload(); },
    }, [
      el("div.t", {}, [el("b", { text: a.name }), el("span.p", { text: a.pct == null ? "—" : a.pct + "%" })]),
      el("div.d", {}, a.strip.map((s) => el("i" + (s ? "." + s : "")))),
      el("div.m", {}, [el("span", { text: meta }),
        view ? el("a", { text: (view.label || a.link_tab) + " ↗", onclick: (e) => { e.stopPropagation(); window.openTab(a.link_tab); } }) : null]),
    ]);
  }

  async function render(host) {
    async function reload() {
      const data = await guard(() => A().week(anchor));
      const areas = data.areas;
      const today = data.today;
      clear(host);

      const label = P.fmtDay(data.week_start) + " – " + P.fmtDay(data.week_end);
      host.appendChild(el("div.spread", { style: "margin-bottom:6px;flex-wrap:wrap" }, [
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "‹", title: "previous week", onclick: () => { anchor = shiftDay(data.week_start, -7); reload(); } }),
          el("span.sub", { style: "font-family:var(--mono)", text: label }),
          el("button.btn-sm", { text: "›", title: "next week", onclick: () => { const n = shiftDay(data.week_start, 7); anchor = n > today ? null : n; reload(); } }),
          anchor ? el("button.btn-sm", { text: "this week", onclick: () => { anchor = null; reload(); } }) : null,
        ]),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "nightly review", onclick: () => reviewModal(data, reload) }),
          el("button.btn-sm", { text: "areas", onclick: () => areasModal(areas, reload) }),
          el("button.btn-primary", { text: "+ habit", onclick: () => habitModal(areas, null, areaFilter, reload) }),
        ]),
      ]));

      host.appendChild(el("div.ha-areas", {}, areas.map((a) => areaCard(a, data))));

      const chips = [["all", areaFilter ? "all areas" : "all areas"], ["main", "main only"], ["experimental", "experimental"], ["needs", "needs work"]];
      host.appendChild(el("div.ha-filters", {}, chips.map(([k, l]) => el("span.ha-chip" + (chip === k && !(k === "all" && areaFilter) ? ".on" : ""), {
        text: l, onclick: () => { chip = k; if (k === "all") areaFilter = null; reload(); } }))
        .concat([el("span.meta", { style: "margin-left:auto", text: "green done · amber missed · blue excused · light red moved · hatched no data · grey not yet" })])));

      const keep = (h) => chip === "main" ? h.tier === "main"
        : chip === "experimental" ? h.tier === "experimental"
          : chip === "needs" ? h.week.pct != null && h.week.pct < 50 : true;
      let shown = 0;
      areas.filter((a) => !areaFilter || a.key === areaFilter).forEach((a) => {
        const hs = a.habits.filter(keep);
        if (!hs.length && (chip !== "all" || !areaFilter)) return;
        shown += hs.length;
        const view = a.link_tab && window.Views[a.link_tab];
        const grp = el("div.ha-grp", { style: "--c:" + a.color }, [
          el("div.gh", {}, [
            el("b", { text: a.name }),
            el("span.meta", { text: [a.pct == null ? null : a.pct + "% this week", a.extra || null,
              a.adjust_pending ? a.adjust_pending + " make-up pending" : null].filter(Boolean).join(" · ") }),
            view ? el("a.meta.ha-link", { text: "↗ " + (view.label || a.link_tab), onclick: () => window.openTab(a.link_tab) }) : null,
          ]),
        ].concat(hs.map((h) => habitRow(a, h, data, areas, reload)))
          .concat([el("div.ha-addh", { text: "+ habit in " + a.name, onclick: () => habitModal(areas, null, a.key, reload) })]));
        host.appendChild(grp);
      });
      if (!shown && !areaFilter) host.appendChild(el("div.empty", { text: chip === "all" ? "No habits yet. Add one above." : "Nothing matches this filter." }));
    }
    render.reload = reload;
    reload();
  }

  window.HABIT_TABS = window.HABIT_TABS || [];
  window.HABIT_TABS.unshift({ key: "areas", label: "By area", render });
})();

/* fitness-dashboard.js — Pulse Fitness Dashboard: cockpit view. Active-cycle
   progress, key stats, goals (current → target), recent workouts. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  function statBox(val, label) {
    return el("div.fit-stat", {}, [el("div.fit-stat-val", { text: String(val) }), el("div.fit-stat-lbl", { text: label })]);
  }

  function goalRow(g, reload) {
    return el("div.spread", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
      el("div", {}, [
        el("span", { style: "font-weight:500", text: g.text }),
        el("div.sub", { text: (g.current || "—") + " → " + (g.target || "—") }),
      ]),
      el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.pulse.fitness.delGoal(g.id); reload(); }), text: "×" }),
    ]);
  }

  function addGoalModal(reload) {
    const text = el("input.mform-input", { placeholder: "e.g. Bench 90kg" });
    const cur = el("input.mform-input", { placeholder: "current, e.g. 70kg" });
    const tgt = el("input.mform-input", { placeholder: "target, e.g. 90kg" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Add goal", [field("Goal", text), el("div.mform-row", {}, [field("Current", cur), field("Target", tgt)])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => {
        if (!text.value.trim()) return toast("goal text?", true);
        await api.pulse.fitness.addGoal({ text: text.value.trim(), current: cur.value.trim(), target: tgt.value.trim() });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    async function reload() {
      const d = await guard(() => api.pulse.fitness.dashboard());
      clear(host);
      // active cycle banner
      const c = d.active_cycle;
      if (c) {
        const pct = Math.round((c.current_week / c.weeks) * 100);
        host.appendChild(el("div.pulse-card", {}, [
          el("div.spread", {}, [
            el("div.row", { style: "gap:8px" }, [el("span", { style: "font-weight:600;font-size:15px", text: c.name }), el("span.pulse-tag", { text: c.phase })]),
            el("span.pulse-tag", { text: "week " + c.current_week + "/" + c.weeks }),
          ]),
          el("div.fit-bar", {}, [el("div.fit-bar-fill", { style: "width:" + pct + "%" })]),
          c.goals ? el("p.sub", { style: "margin-top:8px", text: c.goals }) : null,
        ]));
      }
      // stats grid
      const s = d.stats;
      host.appendChild(el("div.fit-stat-grid", {}, [
        statBox(s.total_workouts, "Total Workouts"), statBox(s.this_week, "This Week"),
        statBox(s.total_hours + "h", "Total Hours"), statBox(s.stretch_sessions, "Stretch Sessions"),
        statBox(s.pain_points + (s.imbalance ? " / " + s.imbalance : ""), "Pain / Imbalance"),
      ]));
      // goals
      const goalCard = el("div.pulse-card", {}, [el("div.spread", {}, [el("h3", { style: "margin:0", text: "Goals" }), el("button.btn-sm", { onclick: () => addGoalModal(reload), text: "＋ add goal" })])]);
      if (!d.goals.length) goalCard.appendChild(el("div.sub", { style: "margin-top:8px", text: "No goals yet." }));
      d.goals.forEach((g) => goalCard.appendChild(goalRow(g, reload)));
      host.appendChild(goalCard);
      // recent workouts
      const recent = el("div.pulse-card", {}, [el("h3", { style: "margin:0 0 8px", text: "Recent Workouts" })]);
      if (!d.recent_workouts.length) recent.appendChild(el("div.sub", { text: "No workouts logged yet." }));
      d.recent_workouts.forEach((w) => recent.appendChild(el("div.spread", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
        el("div.row", { style: "gap:8px" }, [el("span.sub", { text: P.fmtDay((w.date || "").slice(0, 10)) }), el("span.pulse-tag", { text: w.type })]),
        el("span.sub", { text: (w.exercises ? w.exercises.length : 0) + " ex · " + (w.duration || 0) + "min" }),
      ])));
      host.appendChild(recent);
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "dashboard", label: "Dashboard", render });
})();

/* fitness-activity.js — Pulse Fitness Activity: configurable daily-movement
   metrics. Toggle which metrics you track; the log form builds dynamically from
   the tracked list only. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  // image widget for one activity-log row (built as a child so it can sit
  // inline in the card's children array)
  function imgHost(a) {
    const host = el("div");
    window.Images.mount(host, { module: "pulse", contextId: a.id, surface: "pulse-activity", title: "Images" });
    return host;
  }

  const META = {
    steps: { icon: "👟", label: "Steps", unit: "count" }, walking: { icon: "🚶", label: "Walking", unit: "min" },
    running: { icon: "🏃", label: "Running", unit: "min" }, cycling: { icon: "🚴", label: "Cycling", unit: "min" },
    swimming: { icon: "🏊", label: "Swimming", unit: "min" }, standing: { icon: "🧍", label: "Standing", unit: "min" },
    sedentary: { icon: "🪑", label: "Sedentary", unit: "min" }, exercise: { icon: "💪", label: "Exercise", unit: "min" },
    intensity: { icon: "🔥", label: "Intensity", unit: "/10" }, calories: { icon: "🔋", label: "Calories", unit: "kcal" },
  };

  function logModal(tracked, reload) {
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const inputs = {};
    const rows = [el("div.mform-full", {}, [el("div.mform-label", { text: "Date" }), date])];
    tracked.forEach((m) => {
      const inp = el("input.mform-input", { type: "number", min: "0", placeholder: META[m].unit });
      inputs[m] = inp;
      rows.push(el("div.mform-full", {}, [el("div.mform-label", { text: META[m].icon + " " + META[m].label + " (" + META[m].unit + ")" }), inp]));
    });
    // + rows, held until the log exists and then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "one note per line" });
    rows.push(notes.node);
    P.modal("Log activity", rows, [
      { label: "Log", primary: true, onClick: (close) => guard(async () => {
        const body = { date: date.value };
        tracked.forEach((m) => { if (inputs[m].value !== "") body[m] = parseInt(inputs[m].value) || 0; });
        const made = await api.pulse.fitness.logActivity(body);
        await notes.commit(made.id); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    async function reload() {
      const [cfg, logs] = await guard(() => Promise.all([api.pulse.fitness.activityConfig(), api.pulse.fitness.activity()]));
      const tracked = cfg.tracked || [];
      clear(host);
      // toggle row
      const toggles = el("div.row", { style: "gap:6px;flex-wrap:wrap;margin-bottom:14px" });
      cfg.metrics.forEach((m) => {
        const on = tracked.includes(m);
        toggles.appendChild(el("button.fit-toggle" + (on ? ".on" : ""), {
          onclick: () => guard(async () => {
            const next = on ? tracked.filter((x) => x !== m) : tracked.concat(m);
            await api.pulse.fitness.setActivityConfig({ tracked: next }); reload();
          }), text: META[m].icon + " " + META[m].label,
        }));
      });
      host.appendChild(el("div.spread", { style: "align-items:flex-start" }, [toggles,
        el("button.btn-primary", { onclick: () => { if (!tracked.length) return toast("track at least one metric", true); logModal(tracked, reload); }, text: "＋ log" }),
      ]));
      // logs
      if (!logs.length) { host.appendChild(el("div.empty", { text: "No activity logged yet." })); return; }
      logs.forEach((a) => {
        const vals = tracked.filter((m) => a[m] != null).map((m) => META[m].icon + " " + a[m]);
        host.appendChild(el("div.pulse-card", {}, [
          el("div.spread", {}, [
            el("div.row", { style: "gap:10px;flex-wrap:wrap" }, [el("span.sub", { text: P.fmtDay((a.date || "").slice(0, 10)) }), ...vals.map((v) => el("span", { style: "font-size:13px", text: v }))]),
            el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.pulse.fitness.delActivity(a.id); reload(); }), text: "×" }),
          ]),
          window.RowBox({ label: "notes", parentId: a.id }).node,
          imgHost(a),
        ]));
      });
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "activity", label: "Activity", render });
})();

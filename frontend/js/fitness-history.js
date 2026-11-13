/* fitness-history.js — Pulse Fitness History: search past workouts by type,
   exercise name, or notes. Reuses window.FIT.workoutCard. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  async function render(host) {
    const search = el("input.mform-input", { placeholder: "search workouts — type, exercise, notes…", style: "width:100%;margin-bottom:14px" });
    const list = el("div");
    host.appendChild(search);
    host.appendChild(list);

    async function reload() {
      const q = search.value.trim();
      const workouts = await guard(() => api.pulse.fitness.workouts(q ? "?q=" + encodeURIComponent(q) : ""));
      clear(list);
      if (!workouts.length) { list.appendChild(el("div.empty", { text: q ? "No matches." : "No workouts in history yet." })); return; }
      list.appendChild(el("div.sub", { style: "margin-bottom:8px", text: workouts.length + " workout" + (workouts.length === 1 ? "" : "s") }));
      const card = window.FIT && window.FIT.workoutCard;
      workouts.forEach((w) => list.appendChild(card ? card(w, reload) : el("div.pulse-card", { text: w.type + " · " + w.date })));
    }
    let t = null;
    search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(reload, 200); });
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "history", label: "History", render });
})();

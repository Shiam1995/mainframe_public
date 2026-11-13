/* fitness-workouts.js — Pulse Fitness Workouts: the list of logged workouts,
   colour-coded intensity, interrupted flag. The Log form is fitness-logworkout.js. Exposes
   window.FIT.workoutCard for History to reuse. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  function intensityClass(n) { return n <= 4 ? "intensity-lo" : n <= 7 ? "intensity-mid" : "intensity-hi"; }
  const open = new Set();
  const cardioLabel = (list) => {
    const km = list.reduce((a, c) => a + (c.distance_km || 0), 0);
    return km ? "cardio " + (Math.round(km * 10) / 10) + " km" : "cardio";
  };

  function workoutCard(w, reload) {
    const isOpen = open.has(w.id);
    const card = el("div.pulse-card", {}, [
      el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(w.id) : open.add(w.id); reload(); } }, [
        el("div.row", { style: "gap:8px" }, [
          el("span.sub", { text: P.fmtDay((w.date || "").slice(0, 10)) }),
          el("span.pulse-tag", { text: w.type }),
          w.cycle_name ? el("span.sub", { text: "· " + w.cycle_name
            + (w.program_week ? " · week " + w.program_week : "")
            + (w.program_day ? " · day " + w.program_day + (w.program_day_label ? " " + w.program_day_label : "") : "") }) : null,
          el("span.sub", { text: (w.duration || 0) + "min" }),
          el("span", { class: "mono " + intensityClass(w.intensity), style: "font-size:11px", text: "⚡" + w.intensity }),
          w.interrupted && w.interrupted !== "no" ? el("span.pulse-tag", { style: "background:var(--red-d);color:var(--red)", text: "⚠ " + w.interrupted.replace("yes — ", "") }) : null,
        ]),
        el("span.sub", { text: [(w.exercises || []).length || !(w.cardio || []).length ? (w.exercises || []).length + " ex" : "",
          (w.cardio || []).length ? cardioLabel(w.cardio) : ""].filter(Boolean).join(" · ") }),
      ]),
    ]);
    if (isOpen) {
      const body = el("div", { style: "margin-top:10px;border-top:1px solid var(--border);padding-top:10px" });
      // Logged with the timed form: its blocks, as entered. Older workouts: the exercise list.
      if ((w.blocks || []).length || (w.cardio || []).length) {
        const time = (b) => (b.from || b.to ? (b.from || "?") + "–" + (b.to || "?") : "");
        const facts = [w.warmup_min ? "warm up " + w.warmup_min + " min" : "", w.fatigue_before ? "fatigue before " + w.fatigue_before + "/10" : ""].filter(Boolean);
        if (facts.length) body.appendChild(el("div.sub", { style: "margin-bottom:4px", text: facts.join(" · ") }));
        w.blocks.forEach((b) => {
          const what = b.kind === "warmup" ? "warm up" + (b.exercise ? ": " + b.exercise : "")
            : (b.exercise || b.raw) + (b.reps ? " × " + b.reps : "") + (b.kg ? " @ " + b.kg + "kg" : "") + (b.rpe ? " · rpe " + b.rpe : "");
          body.appendChild(el("div", { style: "padding:2px 0" + (b.kind === "warmup" ? ";color:var(--muted)" : "") }, [
            el("span.mono", { style: "display:inline-block;width:96px;font-size:11px;color:var(--muted)", text: time(b) }),
            (b.group ? b.group + ": " : "") + what,
          ]));
        });
        (w.cardio || []).forEach((c) => {
          const pace = c.pace_min_per_km ? Math.floor(c.pace_min_per_km) + ":" + String(Math.round((c.pace_min_per_km % 1) * 60)).padStart(2, "0") + " /km" : "";
          const bits = [c.distance_km ? c.distance_km + " km" : "", c.duration_mins ? c.duration_mins + " min" : "", pace,
            c.avg_hr ? "♥ " + c.avg_hr : "", c.perceived_effort ? "effort " + c.perceived_effort : ""].filter(Boolean);
          body.appendChild(el("div", { style: "padding:2px 0" }, [
            el("span.mono", { style: "display:inline-block;width:96px;font-size:11px;color:var(--muted)",
              text: c.from || c.to ? (c.from || "?") + "–" + (c.to || "?") : "" }),
            "cardio: " + c.type + (c.style ? " " + c.style.toUpperCase() : "") + (c.style === "hiit" && c.sets ? " × " + c.sets + " sets" : "")
              + (bits.length ? " · " + bits.join(" · ") : ""),
          ]));
        });
        (w.maxes_set || []).forEach((m) => body.appendChild(el("div", { style: "padding:2px 0;color:var(--amber)", text: "new max: " + m.exercise + " " + m.kg + "kg" })));
      } else {
        (w.exercises || []).forEach((e) => body.appendChild(el("div", { style: "padding:3px 0", text: "• " + e.name + (e.detail ? "  — " + e.detail : "") })));
      }
      body.appendChild(window.RowBox({ label: "notes", parentId: w.id }).node);
      // Questions the session raised (form, load, recovery) and what you assumed.
      if (window.QABoxes) body.appendChild(window.QABoxes(w.id, "workout"));
      window.Images.mount(body, { module: "pulse", contextId: w.id, surface: "pulse-workout", title: "Images" });
      body.appendChild(el("button.btn-sm", { style: "margin-top:8px;margin-right:6px", title: "change anything, add sets, cardio or notes",
        onclick: () => guard(() => window.FIT.logWorkout(reload, w)), text: "✎ edit" }));
      body.appendChild(el("button.btn-sm.btn-danger", { style: "margin-top:8px", onclick: () => confirmDo("Delete this workout?" + ((w.maxes_set || []).length ? " The max it set goes too." : "")
            + ((w.cardio || []).length ? " Its cardio sessions go too." : ""), async () => { await api.pulse.fitness.delWorkout(w.id); reload(); }), text: "× delete" }));
      card.appendChild(body);
    }
    return card;
  }
  window.FIT = window.FIT || {};
  window.FIT.workoutCard = workoutCard;

  // Log workout lives in fitness-logworkout.js (timed blocks, program, maxes).

  async function render(host) {
    async function reload() {
      const workouts = await guard(() => api.pulse.fitness.workouts());
      clear(host);
      host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [
        el("button.btn-primary", { onclick: () => guard(() => window.FIT.logWorkout(reload)), text: "＋ log workout" }),
      ]));
      if (!workouts.length) { host.appendChild(el("div.empty", { text: "No workouts yet. Log your first above." })); return; }
      workouts.forEach((w) => host.appendChild(workoutCard(w, reload)));
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "workouts", label: "Workouts", render });
})();

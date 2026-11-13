/* fitness-logworkout.js — the Log workout form (Pulse > Fitness > Workouts).

   Built from notes: the log-workout mockup. A workout is timed
   blocks, read against the program and your maxes:

     header     the program day you are on and what it prescribes today
     top row    date · type · fatigue before (1 to 10) · interrupted
     warm up    from · to · what · min
     exercises  from · to · exercise · reps · kg · vs max · rpe, where
                consecutive rows of one exercise group under a header that
                carries the sets, minutes, top set and today's prescription
     cardio     from · to · type · style (LISS/HIIT) · sets (HIIT only) · km ·
                avg hr · effort · min; each row is
                saved as a Cardio session linked to the workout, so it shows
                on the Cardio tab too
     totals     warm up · exercises · cardio · total · volume · avg rpe · vs prescribed
     notes      + rows (RowBox), with the ◉ dictation button (voicetype.js)

   A new max is never written on its own. If a set's estimated 1RM (Epley)
   beats the stored max, Log first asks "record 61kg as squat max?" and only
   the ones you tick are sent.

   Context comes from GET /api/pulse/fitness/today: a program is a cycle on
   the Program tab, its days repeat weekly, and today's day is the one after
   the last logged this week. With no cycle the header says "no program" and
   the form works without one: no prescriptions, nothing else changes.

   window.FIT.logWorkout(reload) opens it empty; window.FIT.logWorkout(reload, w)
   opens workout w filled in to edit (PUT /workouts/{id}/replace keeps its id,
   images and the maxes it set). A workout from before the timed form has no
   blocks: its exercises come back as rows, "20 reps @ 60kg" read into reps
   and kg, and without times its duration and intensity are kept as they were. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  const TYPES = ["Push", "Pull", "Legs", "Upper", "Lower", "Full Body", "Cardio", "HIIT", "Sport", "Other"];
  const CARDIO_TYPES = ["run", "walk", "cycle", "swim", "row", "hike", "other"];
  const CARDIO_STYLES = [["", "style"], ["liss", "LISS"], ["hiit", "HIIT"]];
  const INTERRUPTED = ["no", "yes — pain", "yes — time", "yes — fatigue"];
  const INTERRUPTED_LABEL = { "no": "no", "yes — pain": "yes, pain", "yes — time": "yes, time", "yes — fatigue": "yes, fatigue" };

  /* ---- small pure helpers ------------------------------------------------ */
  // One exercise, however it was typed: "Squats", "squat", "Back squat." all
  // compare on lowercase letters with a trailing plural s dropped per word.
  const exKey = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9 ]+/g, " ")
    .split(/\s+/).filter(Boolean).map((w) => (w.length > 3 ? w.replace(/s$/, "") : w)).join(" ");

  function mins(from, to) {
    const m = (t) => { const x = /^(\d{1,2}):(\d{2})$/.exec(t || ""); return x ? +x[1] * 60 + +x[2] : null; };
    const a = m(from), b = m(to);
    if (a === null || b === null) return 0;
    return b >= a ? b - a : b + 1440 - a;           // across midnight
  }

  // Epley. One rep is the lift itself.
  const e1rm = (kg, reps) => (kg > 0 && reps > 0 ? (reps === 1 ? kg : kg * (1 + reps / 30)) : 0);
  const r1 = (n) => Math.round(n * 10) / 10;
  const plate = (n) => Math.round(n / 2.5) * 2.5;   // what you could load

  /* "20 squats at 40kg" · "squats 20 @ 40" · "5x40kg bench" · "8 pull ups".
     Returns {exercise, reps, kg} or null; null keeps the text as raw. */
  function parseSet(text) {
    const t = String(text || "").trim();
    if (!t) return null;
    const num = "(\\d+(?:\\.\\d+)?)";
    const pats = [
      // 20 squats at 40kg · 20 x squats @ 40
      [new RegExp("^(\\d+)\\s*(?:x\\s+)?([a-z][a-z \\-']*?)\\s*(?:at|@|x|with)\\s*" + num + "\\s*(?:kg|kgs)?$", "i"), (m) => ({ reps: +m[1], exercise: m[2], kg: +m[3] })],
      // squats 20 at 40kg · squats 20 reps @ 40
      [new RegExp("^([a-z][a-z \\-']*?)\\s+(\\d+)\\s*(?:reps?)?\\s*(?:at|@|x|with)\\s*" + num + "\\s*(?:kg|kgs)?$", "i"), (m) => ({ exercise: m[1], reps: +m[2], kg: +m[3] })],
      // 5x40kg bench · 5 x 40 bench
      [new RegExp("^(\\d+)\\s*x\\s*" + num + "\\s*(?:kg|kgs)?\\s+([a-z][a-z \\-']*)$", "i"), (m) => ({ reps: +m[1], kg: +m[2], exercise: m[3] })],
      // bench 5x40kg
      [new RegExp("^([a-z][a-z \\-']*?)\\s+(\\d+)\\s*x\\s*" + num + "\\s*(?:kg|kgs)?$", "i"), (m) => ({ exercise: m[1], reps: +m[2], kg: +m[3] })],
      // 8 pull ups (bodyweight)
      [/^(\d+)\s+([a-z][a-z \-']*)$/i, (m) => ({ reps: +m[1], exercise: m[2], kg: 0 })],
    ];
    for (const [re, f] of pats) {
      const m = re.exec(t);
      if (m) { const o = f(m); o.exercise = o.exercise.trim(); return o.exercise ? o : null; }
    }
    return null;
  }

  function prescText(p, max) {
    let s = (p.sets || "?") + "×" + (p.reps || "?");
    if (p.pct_max) {
      s += " @ " + p.pct_max + "%";
      if (max && max.kg) s += " = " + plate(max.kg * p.pct_max / 100) + "kg";
    }
    return s;
  }

  /* ---- the strips -------------------------------------------------------- */
  // 1 to 10, click to set, click the same value again to clear.
  function scale(value, onPick, cls) {
    const wrap = el("div." + cls);
    const paint = (v) => [...wrap.children].forEach((c, i) => c.classList.toggle("on", v !== null && i < v));
    for (let i = 1; i <= 10; i++) {
      wrap.appendChild(el("span", {
        text: cls === "fw-scale" ? String(i) : "",
        title: String(i),
        onclick: () => { value = value === i ? null : i; paint(value); onPick(value); },
      }));
    }
    paint(value);
    return wrap;
  }

  /* ---- the form ---------------------------------------------------------- */
  // An exercise from before the timed form: name + "20 reps @ 60kg rpe 6".
  function legacyRow(e) {
    const d = String(e.detail || "");
    const reps = /(\d+)\s*reps?/i.exec(d), kg = /@\s*(\d+(?:\.\d+)?)\s*kg/i.exec(d), rpe = /rpe\s*(\d+)/i.exec(d);
    const read = reps || kg || rpe;
    return { from: "", to: "", exercise: read || !d.trim() ? e.name : e.name + " — " + d.trim(),
      reps: reps ? reps[1] : "", kg: kg ? kg[1] : "", rpe: rpe ? +rpe[1] : null, raw: "", group: "" };
  }

  async function logWorkout(reload, existing) {
    // The program context from GET /fitness/today: the program (a cycle on the
    // Program tab), today's day and its prescriptions, your maxes, and every
    // cycle for the picker. A failed fetch reads as no program.
    const NONE = { program: null, day: null, prescriptions: [], maxes: {}, days: [], cycles: [] };
    let ctx;
    const s = {
      date: P.today(), type: "Other", fatigue: null, interrupted: "no",
      warm: [{ from: "", to: "", what: "" }],
      ex: [{ from: "", to: "", exercise: "", reps: "", kg: "", rpe: null, raw: "", group: "" }],
      cardio: [{ from: "", to: "", type: "run", style: "", sets: "", km: "", hr: "", effort: null }],
      dayId: null,
      cycleId: null,
      confirming: false,
      confirmed: new Set(),
    };
    function applyCtx(next) {
      ctx = Object.assign({}, NONE, next || {});
      // Re-key maxes the way rows are keyed, so "Squat" finds "squats". The
      // server's copy is kept: exKey isn't idempotent ("press" → "pres" → "pre").
      ctx.rawMaxes = ctx.maxes || {};
      const maxes = {};
      Object.entries(ctx.maxes || {}).forEach(([name, m]) => { maxes[exKey(name)] = m; });
      ctx.maxes = maxes;
      s.cycleId = ctx.program ? ctx.program.id : null;
      s.dayId = ctx.day ? ctx.day.id : null;
      if (ctx.day && TYPES.includes(ctx.day.label)) s.type = ctx.day.label;
    }
    if (!existing) {
      applyCtx(await api.pulse.fitness.today().catch(() => null));
    } else {
      // Its own program and day, not today's; with none, "no program".
      const t = await api.pulse.fitness.today(existing.cycle_id ? "?cycle_id=" + encodeURIComponent(existing.cycle_id) : "").catch(() => null);
      applyCtx(existing.cycle_id ? t : { maxes: (t && t.maxes) || {}, cycles: (t && t.cycles) || [] });
      const d = (ctx.days || []).find((x) => x.id === existing.program_day_id) || null;
      ctx.day = d; ctx.prescriptions = d ? d.prescriptions || [] : []; s.dayId = d ? d.id : null;
      const str = (v) => (v ? String(v) : "");
      const blocks = existing.blocks || [];
      const warm = blocks.filter((b) => b.kind === "warmup").map((b) => ({ from: b.from || "", to: b.to || "", what: b.exercise || "" }));
      const ex = blocks.length
        ? blocks.filter((b) => b.kind === "exercise").map((b) => ({ from: b.from || "", to: b.to || "", exercise: b.exercise || "",
            reps: str(b.reps), kg: str(b.kg), rpe: b.rpe || null, raw: b.raw || "", group: b.group || "" }))
        : (existing.exercises || []).map(legacyRow);
      const cardio = (existing.cardio || []).map((c) => ({ from: c.from || "", to: c.to || "", type: c.type || "run",
        style: c.style || "", sets: str(c.sets), km: str(c.distance_km), hr: str(c.avg_hr), effort: c.perceived_effort || null }));
      Object.assign(s, {
        date: (existing.date || P.today()).slice(0, 10), type: existing.type || "Other",
        fatigue: existing.fatigue_before || null, interrupted: existing.interrupted || "no",
      });
      if (warm.length) s.warm = warm;
      if (ex.length) s.ex = ex;
      if (cardio.length) s.cardio = cardio;
    }

    const maxOf = (name) => ctx.maxes[exKey(name)] || null;
    const prescOf = (name) => (ctx.prescriptions || []).find((p) => exKey(p.exercise) === exKey(name)) || null;

    const root = el("div.fw-log");
    const { close, card } = P.modal(existing ? "Edit workout" : "Log workout", [root], []);
    card.style.maxWidth = "900px";
    card.style.width = "96vw";

    /* header: which program and day this is */
    const progHost = el("div");
    // Every cycle, active first. Picking one re-reads /today for it, so its
    // days, today's day and the prescriptions all follow; "no program" logs
    // the workout unlinked.
    function programPicker() {
      const cycles = ctx.cycles || [];
      const opt = (c) => el("option", { value: c.id, text: c.name + (c.status === "completed" ? " (completed)" : "") });
      const sel = el("select.btn-sm", {}, [el("option", { value: "", text: "no program" }),
        ...cycles.filter((c) => c.status === "active").map(opt), ...cycles.filter((c) => c.status !== "active").map(opt)]);
      sel.value = s.cycleId || "";
      sel.addEventListener("change", () => guard(async () => {
        const cycles = ctx.cycles;
        const next = sel.value ? await api.pulse.fitness.today("?cycle_id=" + encodeURIComponent(sel.value)) : { maxes: ctx.rawMaxes, cycles };
        applyCtx(next);
        if (!sel.value) ctx.cycles = cycles;
        typeSel.value = s.type;
        drawProgram(); drawEx(); drawTotals();
      }));
      return sel;
    }
    function drawProgram() {
      clear(progHost);
      if (!(ctx.cycles || []).length) {
        progHost.appendChild(el("div.fw-prog", {}, [
          el("div", { text: "no program" }),
          el("button.btn-sm", { text: "create one", onclick: () => {
            close();
            if (window.FIT && window.FIT.go) window.FIT.go("program");
          } }),
        ]));
        return;
      }
      if (!ctx.program) {
        progHost.appendChild(el("div.fw-prog", {}, [el("div", {}, ["Program: ", programPicker()])]));
        return;
      }
      const day = (ctx.days || []).find((d) => d.id === s.dayId) || ctx.day;
      const presc = day && day.id === (ctx.day && ctx.day.id) ? ctx.prescriptions : (day && day.prescriptions) || [];
      const line = !(ctx.days || []).length ? "no days set up yet"
        : presc.length ? "prescribed: " + presc.map((p) => p.exercise + " " + prescText(p, maxOf(p.exercise))).join(", ")
        : "nothing prescribed";
      const changeBtn = el("button.btn-sm", { text: "change day" });
      const right = el("div.row", { style: "gap:8px" }, [el("span.fw-presc", { text: line }), changeBtn]);
      changeBtn.addEventListener("click", () => {
        if (!(ctx.days || []).length) return toast("this program has no days yet, add them on the Program tab", true);
        const sel = el("select.btn-sm", {}, [el("option", { value: "", text: "no day" }), ...ctx.days.map((d) =>
          el("option", { value: d.id, text: "week " + d.week + " · day " + d.day + " · " + (d.label || "") }))]);
        sel.value = s.dayId || "";
        sel.addEventListener("change", () => {
          s.dayId = sel.value || null;
          const d = ctx.days.find((x) => x.id === s.dayId);
          ctx.prescriptions = (d && d.prescriptions) || [];
          ctx.day = d || null;
          if (d && TYPES.includes(d.label)) { s.type = d.label; typeSel.value = s.type; }
          drawProgram(); drawEx(); drawTotals();
        });
        right.replaceChild(sel, changeBtn);
        sel.focus();
      });
      progHost.appendChild(el("div.fw-prog", {}, [
        el("div", {}, [
          "Program: ", programPicker(),
          day ? " · week " + day.week + " · day " + day.day + " · " : "",
          day ? el("b", { text: day.label || "" }) : null,
        ]),
        right,
      ]));
    }

    /* top row */
    const dateIn = el("input.mform-input", { type: "date", value: s.date });
    dateIn.addEventListener("change", () => { s.date = dateIn.value; });
    const typeSel = el("select.mform-input", {}, TYPES.map((t) => el("option", { value: t, text: t })));
    typeSel.value = s.type;
    typeSel.addEventListener("change", () => { s.type = typeSel.value; });
    const intSel = el("select.mform-input", {}, INTERRUPTED.map((i) => el("option", { value: i, text: INTERRUPTED_LABEL[i] })));
    intSel.value = s.interrupted;
    intSel.addEventListener("change", () => { s.interrupted = intSel.value; });
    const lab = (t) => el("div.mform-label", { text: t });
    const top = el("div.fw-top", {}, [
      el("div", {}, [lab("date"), dateIn]),
      el("div", {}, [lab("type"), typeSel]),
      el("div", {}, [lab("fatigue before, 1 to 10"), scale(s.fatigue, (v) => { s.fatigue = v; }, "fw-scale")]),
      el("div", {}, [lab("interrupted?"), intSel]),
    ]);

    /* a time cell: HH:MM, redraw totals when it changes */
    // Plain 24h text, like the mockup: a native time picker renders "10:40 AM"
    // in a 12h locale and eats the exercise column. "1040", "10.40", "9:5" and
    // "10:40" all normalise to HH:MM; anything else is left for you to fix.
    function normTime(v) {
      const t = String(v || "").trim();
      if (!t) return "";
      const m = /^(\d{1,2})(?:[:.h ]?(\d{1,2}))?$/.exec(t.length === 4 && /^\d{4}$/.test(t) ? t.slice(0, 2) + ":" + t.slice(2) : t);
      if (!m) return null;
      const h = +m[1], mi = +(m[2] || 0);
      if (h > 23 || mi > 59) return null;
      return String(h).padStart(2, "0") + ":" + String(mi).padStart(2, "0");
    }
    function timeIn(row, key, placeholder, after, pos) {
      const i = el("input", { type: "text", inputmode: "numeric", maxlength: "5", value: row[key] || "",
        placeholder: placeholder || "hh:mm", "data-pos": pos || null });
      i.addEventListener("change", () => {
        const v = normTime(i.value);
        if (v === null) { i.classList.add("fw-bad"); return; }
        i.classList.remove("fw-bad");
        i.value = v; row[key] = v; after();
      });
      return el("td.t", {}, [i]);
    }

    /* warm up */
    const warmBody = el("tbody");
    function drawWarm() {
      clear(warmBody);
      s.warm.forEach((w, idx) => {
        const minCell = el("td.fw-min");
        const refresh = () => { minCell.textContent = mins(w.from, w.to) || ""; drawTotals(); };
        const what = el("input", { value: w.what, placeholder: idx ? "dynamic set" : "static warm up" });
        what.addEventListener("change", () => { w.what = what.value; });
        warmBody.appendChild(el("tr", {}, [
          timeIn(w, "from", "", refresh), timeIn(w, "to", "", refresh),
          el("td", {}, [what]), minCell,
          el("td.fw-x", {}, [s.warm.length > 1 ? el("button.btn-sm", { text: "×", title: "remove row",
            onclick: () => { s.warm.splice(idx, 1); drawWarm(); drawTotals(); } }) : null]),
        ]));
        minCell.textContent = mins(w.from, w.to) || "";
      });
    }
    const warmBlk = el("div.fw-blk", {}, [
      el("div.fw-blk-head", {}, [el("h2", { text: "Warm up" }),
        el("button.btn-sm", { text: "+ row", onclick: () => {
          const prev = s.warm[s.warm.length - 1];
          s.warm.push({ from: (prev && prev.to) || "", to: "", what: "" });
          drawWarm();
        } })]),
      el("table.fw-tbl", { "data-no-now": "" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "from", style: "width:66px" }), el("th", { text: "to", style: "width:66px" }),
          el("th", { text: "what" }), el("th", { text: "min", style: "width:50px" }), el("th", { style: "width:30px" })])]),
        warmBody,
      ]),
    ]);

    /* exercises */
    const exBody = el("tbody");
    // Consecutive rows with one group key form a group. A named group (from
    // "+ group") wins over the exercise name, so a circuit stays one group.
    const gkey = (r) => (r.group ? "g:" + r.group : "e:" + exKey(r.exercise));

    function groupSummary(rows) {
      const sets = rows.filter((r) => +r.reps > 0 || +r.kg > 0);
      const m = rows.reduce((a, r) => a + mins(r.from, r.to), 0);
      let top = null;
      sets.forEach((r) => {
        if (!top || +r.kg > +top.kg || (+r.kg === +top.kg && +r.reps > +top.reps)) top = r;
      });
      const bits = [sets.length + " set" + (sets.length === 1 ? "" : "s")];
      if (m) bits.push(m + " min");
      if (top && +top.kg) bits.push("top " + top.kg + "kg × " + (top.reps || 0));
      else if (top && +top.reps) bits.push("top " + top.reps + " reps");
      return bits.join(" · ");
    }

    function vsMax(r) {
      const kg = +r.kg, reps = +r.reps;
      if (!r.exercise || !(kg > 0)) return { text: "", cls: "" };
      const max = maxOf(r.exercise);
      const est = e1rm(kg, reps);
      if (!max || !max.kg) return est ? { text: "no max yet · est 1RM " + r1(est) + "kg", cls: "" } : { text: "", cls: "" };
      let text = Math.round(kg / max.kg * 100) + "% of " + max.kg + "kg";
      if (est > max.kg) return { text: text + " · est 1RM " + r1(est) + "kg, PR?", cls: ".high" };
      return { text, cls: "" };
    }

    // Redraw after the browser has moved focus (change fires before the next
    // field is focused), then put focus back on the same row and column, so
    // tabbing reps to kg doesn't drop you out of the table.
    function redraw() {
      setTimeout(() => {
        const a = document.activeElement;
        const pos = a && exBody.contains(a) ? a.dataset.pos : null;
        drawEx();
        if (pos) { const n = exBody.querySelector('[data-pos="' + pos + '"]'); if (n) n.focus(); }
      }, 0);
    }

    function drawEx() {
      clear(exBody);
      let i = 0;
      while (i < s.ex.length) {
        const k = gkey(s.ex[i]);
        let j = i;
        while (j + 1 < s.ex.length && gkey(s.ex[j + 1]) === k) j++;
        const rows = s.ex.slice(i, j + 1);
        const named = rows[0].group;
        const label = named || rows[0].exercise;
        if (label) {
          const p = named ? null : prescOf(rows[0].exercise);
          const head = named
            ? el("input.fw-grp-name", { value: named, title: "rename this group" })
            : el("span", { text: label });
          if (named) head.addEventListener("change", () => {
            const nv = head.value.trim() || named;
            rows.forEach((r) => { r.group = nv; });
            drawEx();
          });
          exBody.appendChild(el("tr.fw-grp", {}, [el("td", { colspan: "8" }, [
            head,
            el("span.fw-meta", { text: groupSummary(rows) }),
            p ? el("span.fw-presc", { style: "margin-left:10px", text: "prescribed " + prescText(p, maxOf(p.exercise)) }) : null,
          ])]));
        }
        rows.forEach((r) => exBody.appendChild(exRow(r)));
        i = j + 1;
      }
    }

    function exRow(r) {
      const idx = () => s.ex.indexOf(r);
      const cmp = el("td.fw-cmp");
      const paintCmp = () => { const v = vsMax(r); cmp.textContent = v.text; cmp.className = "fw-cmp" + (v.cls ? " high" : ""); };
      const after = () => drawTotals();

      const at = (c) => idx() + ":" + c;
      const name = el("input", { value: r.exercise || r.raw, placeholder: "exercise, or 20 squats at 40kg", "data-pos": at("x") });
      const reps = el("input", { type: "number", min: "0", value: r.reps, "data-pos": at("r") });
      const kg = el("input", { type: "number", min: "0", step: "0.5", value: r.kg, "data-pos": at("k") });
      name.addEventListener("change", () => {
        const text = name.value.trim();
        const before = gkey(r);
        const parsed = !r.reps && !r.kg ? parseSet(text) : null;
        if (parsed) {
          Object.assign(r, { exercise: parsed.exercise, reps: parsed.reps || "", kg: parsed.kg || "", raw: "" });
        } else {
          // Didn't read as a set: keep what was typed, word for word.
          r.exercise = text;
          r.raw = r.reps || r.kg ? "" : text;
        }
        if (gkey(r) !== before || parsed) redraw(); else paintCmp();
        after();
      });
      reps.addEventListener("change", () => { r.reps = reps.value; paintCmp(); redraw(); after(); });
      kg.addEventListener("change", () => { r.kg = kg.value; paintCmp(); redraw(); after(); });
      paintCmp();

      return el("tr", {}, [
        timeIn(r, "from", "", () => { redraw(); after(); }, at("f")),
        timeIn(r, "to", "", () => { redraw(); after(); }, at("t")),
        el("td", {}, [name]),
        el("td.n", {}, [reps]),
        el("td.n", {}, [kg]),
        cmp,
        el("td", {}, [scale(r.rpe, (v) => { r.rpe = v; drawTotals(); }, "fw-rpe")]),
        el("td.fw-x", {}, [s.ex.length > 1 ? el("button.btn-sm", { text: "×", title: "remove row",
          onclick: () => { s.ex.splice(idx(), 1); drawEx(); after(); } }) : null]),
      ]);
    }

    // A new row starts where the last one ended; after a warm up, where that ended.
    const lastTo = () => {
      const e = s.ex[s.ex.length - 1];
      if (e && e.to) return e.to;
      const w = [...s.warm].reverse().find((x) => x.to);
      return (w && w.to) || "";
    };
    const exBlk = el("div.fw-blk", {}, [
      el("div.fw-blk-head", {}, [el("h2", { text: "Exercises" }), el("div.row", { style: "gap:8px" }, [
        el("span.fw-meta", { text: "type \"20 squats at 40kg\" and it parses; consecutive same-exercise rows group" }),
        el("button.btn-sm", { text: "+ row", onclick: () => {
          const prev = s.ex[s.ex.length - 1] || {};
          // Next set of the same thing is the common case: carry the name and group.
          s.ex.push({ from: lastTo(), to: "", exercise: prev.exercise || "", reps: "", kg: "", rpe: null, raw: "", group: prev.group || "" });
          drawEx();
        } }),
        el("button.btn-sm", { text: "+ group", title: "start a named group by hand, for a circuit or superset", onclick: () => {
          const n = new Set(s.ex.map((r) => r.group).filter(Boolean)).size + 1;
          s.ex.push({ from: lastTo(), to: "", exercise: "", reps: "", kg: "", rpe: null, raw: "", group: "group " + n });
          drawEx();
          const inp = exBody.querySelectorAll("input.fw-grp-name");
          if (inp.length) { inp[inp.length - 1].focus(); inp[inp.length - 1].select(); }
        } }),
      ])]),
      el("table.fw-tbl", { "data-no-now": "" }, [
        el("thead", {}, [el("tr", {}, [
          el("th", { text: "from", style: "width:66px" }), el("th", { text: "to", style: "width:66px" }),
          el("th", { text: "exercise", style: "min-width:170px" }), el("th", { text: "reps", style: "width:60px" }),
          el("th", { text: "kg", style: "width:70px" }), el("th", { text: "vs max" }),
          el("th", { text: "rpe", style: "width:150px" }), el("th", { style: "width:30px" })])]),
        exBody,
      ]),
    ]);

    /* cardio: its own rows, since sets and reps say nothing about a row or a run */
    const cardioUsed = (c) => c.from || c.to || c.style || +c.km > 0 || +c.hr > 0 || c.effort;
    const cardioBody = el("tbody");
    function drawCardio() {
      clear(cardioBody);
      s.cardio.forEach((c, idx) => {
        const minCell = el("td.fw-min");
        const refresh = () => { minCell.textContent = mins(c.from, c.to) || ""; drawTotals(); };
        const type = el("select", {}, CARDIO_TYPES.map((t) => el("option", { value: t, text: t })));
        type.value = c.type;
        type.addEventListener("change", () => { c.type = type.value; });
        // HIIT is counted in sets; LISS is one steady block, so no sets box.
        const style = el("select", {}, CARDIO_STYLES.map(([v, t]) => el("option", { value: v, text: t })));
        style.value = c.style || "";
        const sets = el("input", { type: "number", min: "1", value: c.sets, placeholder: "sets", title: "HIIT sets" });
        const paintSets = () => { sets.disabled = c.style !== "hiit"; sets.style.visibility = c.style === "hiit" ? "" : "hidden"; };
        style.addEventListener("change", () => { c.style = style.value; if (c.style !== "hiit") { c.sets = ""; sets.value = ""; } paintSets(); });
        sets.addEventListener("change", () => { c.sets = sets.value; });
        paintSets();
        const km = el("input", { type: "number", min: "0", step: "0.01", value: c.km, placeholder: "km" });
        km.addEventListener("change", () => { c.km = km.value; drawTotals(); });
        const hr = el("input", { type: "number", min: "0", value: c.hr, placeholder: "bpm" });
        hr.addEventListener("change", () => { c.hr = hr.value; });
        cardioBody.appendChild(el("tr", {}, [
          timeIn(c, "from", "", refresh), timeIn(c, "to", "", refresh),
          el("td", {}, [type]), el("td", {}, [style]), el("td.n", {}, [sets]), el("td.n", {}, [km]), el("td.n", {}, [hr]),
          el("td", {}, [scale(c.effort, (v) => { c.effort = v; }, "fw-rpe")]),
          minCell,
          el("td.fw-x", {}, [s.cardio.length > 1 ? el("button.btn-sm", { text: "×", title: "remove row",
            onclick: () => { s.cardio.splice(idx, 1); drawCardio(); drawTotals(); } }) : null]),
        ]));
        minCell.textContent = mins(c.from, c.to) || "";
      });
    }
    const cardioBlk = el("div.fw-blk", {}, [
      el("div.fw-blk-head", {}, [el("h2", { text: "Cardio" }), el("div.row", { style: "gap:8px" }, [
        el("span.fw-meta", { text: "each row is also a session on the Cardio tab" }),
        el("button.btn-sm", { text: "+ row", onclick: () => {
          const prev = s.cardio[s.cardio.length - 1];
          s.cardio.push({ from: (prev && prev.to) || lastTo(), to: "", type: (prev && prev.type) || "run",
            style: (prev && prev.style) || "", sets: "", km: "", hr: "", effort: null });
          drawCardio();
        } }),
      ])]),
      el("table.fw-tbl", { "data-no-now": "" }, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "from", style: "width:66px" }), el("th", { text: "to", style: "width:66px" }),
          el("th", { text: "type" }), el("th", { text: "style", style: "width:80px" }), el("th", { text: "sets", style: "width:58px" }),
          el("th", { text: "km", style: "width:76px" }), el("th", { text: "avg hr", style: "width:70px" }),
          el("th", { text: "effort", style: "width:150px" }), el("th", { text: "min", style: "width:50px" }), el("th", { style: "width:30px" })])]),
        cardioBody,
      ]),
    ]);

    /* totals */
    const totHost = el("div.fw-tot");
    function vsPrescribed() {
      const presc = ctx.prescriptions || [];
      if (!presc.length) return null;
      const out = [];
      let clean = true;
      presc.forEach((p) => {
        const done = s.ex.filter((r) => exKey(r.exercise) === exKey(p.exercise) && (+r.reps > 0 || +r.kg > 0));
        const bits = [];
        if (+p.sets && done.length < +p.sets) bits.push(done.length + " of " + p.sets + " sets");
        if (+p.reps && done.some((r) => +r.reps < +p.reps)) bits.push("short on reps");
        const max = maxOf(p.exercise);
        if (p.pct_max && max && max.kg) {
          const target = plate(max.kg * p.pct_max / 100);
          if (done.length && Math.max(...done.map((r) => +r.kg || 0)) < target) bits.push("under weight");
        }
        if (bits.length) { clean = false; out.push(p.exercise + " " + bits.join(", ")); }
      });
      return { text: clean ? "on plan" : out.join("; "), clean };
    }
    function drawTotals() {
      clear(totHost);
      const wm = s.warm.reduce((a, w) => a + mins(w.from, w.to), 0);
      const em = s.ex.reduce((a, r) => a + mins(r.from, r.to), 0);
      const cm = s.cardio.reduce((a, c) => a + mins(c.from, c.to), 0);
      const km = s.cardio.reduce((a, c) => a + (+c.km || 0), 0);
      const hiitSets = s.cardio.reduce((a, c) => a + (c.style === "hiit" ? +c.sets || 0 : 0), 0);
      const vol = s.ex.reduce((a, r) => a + (+r.reps || 0) * (+r.kg || 0), 0);
      const rpes = s.ex.map((r) => r.rpe).filter((v) => v);
      const avg = rpes.length ? r1(rpes.reduce((a, b) => a + b, 0) / rpes.length) : null;
      const vp = vsPrescribed();
      const item = (l, v, style) => el("span", {}, [l + " ", el("b", { text: v, style: style || "" })]);
      [item("warm up", wm + " min"), item("exercises", em + " min"),
       cm || km || hiitSets ? item("cardio", cm + " min" + (km ? " · " + r1(km) + " km" : "") + (hiitSets ? " · " + hiitSets + " HIIT sets" : "")) : null,
       item("total", (wm + em + cm) + " min"),
       item("volume", Math.round(vol).toLocaleString("en-GB") + " kg"), item("avg rpe", avg === null ? "none" : String(avg)),
       vp ? item("vs prescribed", vp.text, "color:" + (vp.clean ? "var(--green)" : "var(--amber)")) : null,
      ].forEach((n) => n && totHost.appendChild(n));
      drawFoot();
    }

    /* notes, as + rows, with dictation. Editing: rows on the workout save as
       you type them. New: held until the workout exists, then committed. */
    const notes = window.RowBox({ label: "notes", parentId: existing ? existing.id : null,
      placeholder: "how it felt, energy, form, PRs. speak or type." });
    // Dictation needs a box to type into: open the row editor and speak into it.
    const mic = el("button.btn-sm.fw-mic", { title: "dictate a note (F2 works too)",
      text: "◉ dictate", onclick: () => {
        if (!window.voiceType) return toast("dictation isn't loaded", true);
        if (window.voiceType.recording) return window.voiceType.stop();
        let ta = notes.node.querySelector(".lb-editor .lb-input");
        if (!ta) { notes.node.querySelector(".lb-add").click(); ta = notes.node.querySelector(".lb-editor .lb-input"); }
        if (!ta) return;
        ta.focus();
        window.voiceType.start(ta);
      } });

    /* new maxes: best estimate per exercise that beats the stored one */
    function maxCandidates() {
      const best = new Map();
      s.ex.forEach((r) => {
        const est = e1rm(+r.kg, +r.reps);
        if (!r.exercise || !est) return;
        const k = exKey(r.exercise);
        const cur = maxOf(r.exercise);
        if (cur && cur.kg && est <= cur.kg) return;
        const b = best.get(k);
        if (!b || est > b.kg) best.set(k, { key: k, exercise: r.exercise, kg: r1(est), from_kg: +r.kg, from_reps: +r.reps, previous: cur ? cur.kg : null });
      });
      return [...best.values()];
    }

    const foot = el("div.fw-foot");
    const confirmHost = el("div");
    function drawFoot() {
      clear(foot);
      const c = maxCandidates();
      foot.appendChild(el("span.fw-meta", { text: c.length
        ? c.map((m) => m.from_kg + "kg × " + m.from_reps + " estimates a " + m.kg + "kg " + m.exercise + " max").join("; ")
          + "; saving will ask whether to record " + (c.length > 1 ? "them" : "it")
        : "" }));
      foot.appendChild(el("div.row", { style: "gap:8px" }, [
        el("button.btn-sm", { text: "Cancel", onclick: close }),
        el("button.btn-primary.fw-logbtn", { text: (s.confirming ? (existing ? "Save with these" : "Log with these") : (existing ? "Save" : "Log")), onclick: () => submit() }),
      ]));
    }

    function drawConfirm(cands) {
      clear(confirmHost);
      if (!s.confirming) return;
      confirmHost.appendChild(el("div.fw-confirm", {}, [
        el("div", { style: "margin-bottom:6px", text: "These sets imply a new max. Tick the ones to record; nothing is written unless ticked." }),
        ...cands.map((m) => {
          const box = el("input", { type: "checkbox" });
          box.checked = s.confirmed.has(m.key);
          box.addEventListener("change", () => { box.checked ? s.confirmed.add(m.key) : s.confirmed.delete(m.key); });
          return el("label.row", { style: "gap:8px;align-items:center" }, [box,
            el("span", { text: "record " + m.kg + "kg as " + m.exercise + " max?" }),
            el("span.fw-meta", { text: "from " + m.from_kg + "kg × " + m.from_reps + (m.previous ? ", was " + m.previous + "kg" : ", first max") })]);
        }),
      ]));
    }

    function submit() {
      guard(async () => {
        const cands = maxCandidates();
        if (cands.length && !s.confirming) {
          s.confirming = true;
          drawConfirm(cands); drawFoot();
          confirmHost.scrollIntoView({ block: "nearest" });
          return;
        }
        const warmup = s.warm.filter((w) => w.what || w.from || w.to);
        const exercise = s.ex.filter((r) => r.exercise || r.raw || r.reps || r.kg);
        const blocks = [
          ...warmup.map((w) => ({ kind: "warmup", from: w.from, to: w.to, exercise: w.what, reps: 0, kg: 0, rpe: null, raw: "", group: "" })),
          ...exercise.map((r) => ({ kind: "exercise", from: r.from, to: r.to, exercise: r.exercise, reps: +r.reps || 0,
            kg: +r.kg || 0, rpe: r.rpe, raw: r.raw || "", group: r.group || "" })),
        ];
        const warmup_min = warmup.reduce((a, w) => a + mins(w.from, w.to), 0);
        const cardio = s.cardio.filter(cardioUsed);
        const duration_min = warmup_min + exercise.reduce((a, r) => a + mins(r.from, r.to), 0)
          + cardio.reduce((a, c) => a + mins(c.from, c.to), 0);
        const rpes = [...exercise.map((r) => r.rpe), ...cardio.map((c) => c.effort)].filter(Boolean);
        const body = {
          date: s.date, type: s.type, fatigue_before: s.fatigue, interrupted: s.interrupted,
          duration_min, warmup_min, program_day_id: s.dayId,
          cycle_id: s.cycleId,
          blocks,
          cardio: cardio.map((c) => ({ from: c.from, to: c.to, type: c.type, style: c.style || null,
            sets: c.style === "hiit" && +c.sets > 0 ? Math.round(+c.sets) : null, distance_km: +c.km || 0,
            avg_hr: +c.hr > 0 ? Math.round(+c.hr) : null, perceived_effort: c.effort })),
          confirmed_maxes: cands.filter((m) => s.confirmed.has(m.key)).map((m) => ({
            exercise: m.exercise, kg: m.kg, reps: 1, from_kg: m.from_kg, from_reps: m.from_reps })),
          // Read by the pre-Block endpoint, ignored by the new one.
          // Editing an untimed workout: nothing to add up, so keep what it had.
          duration: duration_min || (existing && existing.duration) || 0,
          intensity: rpes.length ? Math.min(10, Math.max(1, Math.round(rpes.reduce((a, b) => a + b, 0) / rpes.length)))
            : (existing && existing.intensity) || 5,
          exercises: exercise.map((r) => ({ name: r.exercise || r.raw,
            detail: [r.reps ? r.reps + " reps" : "", r.kg ? "@ " + r.kg + "kg" : "", r.rpe ? "rpe " + r.rpe : ""].filter(Boolean).join(" ") })),
        };
        if (existing) await api.pulse.fitness.replaceWorkout(existing.id, body);
        else { const made = await api.pulse.fitness.createWorkout(body); await notes.commit(made.id); }
        toast(existing ? "workout updated" : "workout logged");
        close();
        reload && reload();
      });
    }

    root.appendChild(el("div.fw-meta", { style: "margin:-8px 0 12px", text: "timed blocks, against the program and your maxes" }));
    root.appendChild(progHost);
    root.appendChild(top);
    root.appendChild(warmBlk);
    root.appendChild(exBlk);
    root.appendChild(cardioBlk);
    root.appendChild(totHost);
    root.appendChild(el("div.fw-notes", {}, [el("div.spread", { style: "margin-bottom:4px" }, [el("span"), mic]), notes.node]));
    root.appendChild(confirmHost);
    root.appendChild(foot);

    drawProgram(); drawWarm(); drawEx(); drawCardio(); drawTotals();
    // P.modal focused the first field; the date is a fine place to start.
  }

  window.FIT = window.FIT || {};
  window.FIT.logWorkout = logWorkout;
  // exposed for a quick console check of the parser
  window.FIT._parseSet = parseSet;
})();

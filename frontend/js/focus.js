/* focus.js — the snapshot: where am I right now, from the top bar.

   The phase you're in sits in the chrome as text, always visible, because
   "what am I actually doing with this period" is the one thing worth being
   reminded of without asking. Clicking it opens the whole picture.

   Which sections appear is yours to choose (⚙). The choice is stored on the
   :Focus node rather than in localStorage, so the panel looks the same in
   whichever browser you open it in — and it's sent to the API as the section
   list, so a section you've turned off costs nothing to compute rather than
   being fetched and hidden.

   Almost nothing here is stored: the phase and the goals, and that's it. Every
   other section is derived from work that already happened elsewhere in the
   Mainframe. An overview that needed its own upkeep would be stale within a
   fortnight, and a stale overview is worse than none. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const HORIZONS = ["now", "quarter", "year", "someday"];
  const HORIZON_C = { now: "var(--accent)", quarter: "var(--blue)",
                      year: "var(--purple)", someday: "var(--dim)" };
  const SEV_C = { high: "var(--red)", medium: "var(--amber)", low: "var(--dim)" };

  let catalogue = [];        // every section the backend can serve
  let chosen = null;         // the keys shown, in order — null until loaded
  let focus = { phase: "", note: "" };
  let panel = null, clockTimer = null, editing = false, generation = 0;

  /* ------------------------------------------------------------------ *
   * Small helpers
   * ------------------------------------------------------------------ */
  function ago(iso) {
    if (!iso) return "";
    const days = Math.round((Date.now() - new Date(iso).getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return days + "d ago";
    return Math.round(days / 30) + "mo ago";
  }

  function hoursMins(mins) {
    mins = Math.max(0, Math.round(mins || 0));
    const h = Math.floor(mins / 60);
    return h ? h + "h " + (mins % 60) + "m" : mins + "m";
  }

  const money = (n) => (n < 0 ? "−£" : "£") + Math.abs(n || 0)
    .toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  /* Days between today and an ISO date, as a short phrase. */
  function whenDue(iso) {
    const today = new Date(); today.setHours(0, 0, 0, 0);
    const d = new Date(iso + "T00:00:00");
    const n = Math.round((d - today) / 86400000);
    if (n < 0) return Math.abs(n) + "d late";
    if (n === 0) return "today";
    if (n === 1) return "tomorrow";
    return "in " + n + "d";
  }

  const line = (title, meta) => el("div.sn-line", {}, [
    el("span.sn-line-t", { text: title }),
    meta ? el("span.sn-line-m", { text: meta }) : null,
  ]);

  const empty = (text) => el("div.sn-empty", { text });

  /* Jump to a tab in the shell, closing the panel behind you. */
  function goto(tab) {
    close();
    window.openModule((window.PM && window.PM.activeModule) || "synapse", tab);
  }

  /* ------------------------------------------------------------------ *
   * Section renderers — one per key in the backend's catalogue.
   *
   * Each takes its own slice of the payload and returns nodes. A section that
   * failed on the server arrives as {error} and is rendered as such by the
   * caller, so nothing here has to defend against a missing field.
   * ------------------------------------------------------------------ */
  const R = {};

  /* --- what I'm doing ---------------------------------------------------- */
  R.now = (d) => {
    const out = [];
    const live = (window.Timers ? window.Timers.list() : []).filter((t) => t.running);

    live.forEach((t) => {
      out.push(el("div.sn-run", {}, [
        el("span.sn-run-dot", { text: "●" }),
        el("span.sn-line-t", { text: t.what || t.label }),
        // Marked so the one-second repaint can find the digits without
        // touching anything else in the panel. Its own attribute rather than
        // the dock's `data-timer`: both are scoped to their own container, but
        // one name for two owners is a trap for whoever queries globally next.
        el("span.sn-clock", { "data-sn-timer": t.id, text: t.clock }),
      ]));
    });

    if (!live.length && !d.count) out.push(empty("Nothing running, nothing logged yet today."));
    else if (!live.length) out.push(el("div.sn-note", { text: "No timer running." }));

    d.sessions.forEach((s) => out.push(line(
      s.label, (s.start ? s.start + (s.end ? "–" + s.end : "") + " · " : "")
               + hoursMins(s.mins))));

    if (d.count) {
      out.push(el("div.sn-tot", {
        text: d.count + " session" + (d.count === 1 ? "" : "s") + " · " + hoursMins(d.total_mins) + " today",
      }));
    }
    return out;
  };

  /* --- today's calendar -------------------------------------------------- */
  R.calendar = (d) => {
    const out = [];
    if (!d.events.length) out.push(empty("Nothing in the calendar today."));
    d.events.forEach((e) => out.push(line(
      e.title, e.all_day ? "all day" : (e.start + (e.end ? "–" + e.end : "")))));

    if (d.next_free) {
      out.push(el("div.sn-free", {}, [
        el("span.sn-free-t", { text: "next free " + d.next_free.start + "–" + d.next_free.end }),
        el("span.sn-line-m", { text: hoursMins(d.next_free.mins) }),
      ]));
    }
    out.push(el("div.sn-tot", {
      text: hoursMins(d.busy_mins) + " booked · " + hoursMins(d.free_mins) + " free (08:00–22:00)",
    }));
    out.push(el("button.sn-go", { text: "open calendar →", onclick: () => goto("calendar") }));
    return out;
  };

  /* --- what's due -------------------------------------------------------- */
  R.due = (d) => {
    const out = [];
    const group = (key, label, colour) => {
      if (!d[key] || !d[key].length) return;
      out.push(el("div.sn-sub", { text: label + " · " + d[key].length, style: "color:" + colour }));
      d[key].forEach((t) => out.push(line(t.title, whenDue(t.due_date))));
    };
    group("overdue", "overdue", "var(--red)");
    group("today", "due today", "var(--accent)");
    group("soon", "this week", "var(--dim)");
    if (!out.length) out.push(empty("Nothing due in the next seven days."));
    out.push(el("div.sn-tot", { text: d.open_total + " open task" + (d.open_total === 1 ? "" : "s") }));
    return out;
  };

  /* --- goals and phase --------------------------------------------------- */
  R.goals = (d) => {
    const out = [];
    if (!d.goals.length) out.push(empty("No goals set."));

    d.goals.forEach((g) => {
      const tick = el("button.fc-tick", { title: "mark done", text: "○",
        onclick: () => guard(async () => {
          await api.focus.updateGoal(g.id, { status: "done" });
          refresh();
        }) });
      const title = el("input.fc-goal-t", { value: g.title });
      title.addEventListener("change", () => guard(() =>
        api.focus.updateGoal(g.id, { title: title.value.trim() || "Untitled" })));
      const hz = el("select.fc-mini", {}, HORIZONS.map((h) =>
        el("option", { value: h, text: h })));
      hz.value = g.horizon || "now";
      hz.style.color = HORIZON_C[hz.value];
      hz.addEventListener("change", () => guard(async () => {
        await api.focus.updateGoal(g.id, { horizon: hz.value });
        hz.style.color = HORIZON_C[hz.value];
      }));
      const del = el("button.fc-del", { text: "×", title: "delete",
        onclick: () => guard(async () => { await api.focus.delGoal(g.id); refresh(); }) });
      out.push(el("div.fc-goal", {}, [tick, title, hz, del]));
    });

    const add = el("input.fc-goal-new", { placeholder: "+ a goal…" });
    add.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !add.value.trim()) return;
      guard(async () => {
        await api.focus.addGoal({ title: add.value.trim(), horizon: "now" });
        add.value = "";
        refresh();
      });
    });
    out.push(add);
    if (d.done_goals) out.push(el("div.sn-tot", { text: d.done_goals + " done" }));
    return out;
  };

  /* --- suggestions, and the agent --------------------------------------- */
  R.suggest = (d) => {
    const out = [];
    if (!d.suggestions.length) out.push(empty("Nothing flagged. The day looks clear."));

    d.suggestions.forEach((s) => {
      const row = el("div.sn-sug", {}, [
        el("span.sn-sev", { text: "●", style: "color:" + (SEV_C[s.severity] || "var(--dim)") }),
        el("div", { style: "flex:1;min-width:0" }, [
          el("div.sn-sug-t", { text: s.title }),
          // The numbers it came from. A planner that can't show its working is
          // one you stop trusting the first time it's wrong.
          el("div.sn-why", { text: s.why }),
        ]),
      ]);
      if (s.action && s.action.type === "schedule_task") {
        row.appendChild(el("button.sn-act", { text: "book", title: "find it a slot in the calendar",
          onclick: () => goto("calendar") }));
      }
      out.push(row);
    });

    if (d.total > d.suggestions.length) {
      out.push(el("div.sn-tot", { text: d.total - d.suggestions.length + " more not shown" }));
    }

    /* Facts above, prose on demand. The list is computed and cannot invent a
       meeting; the assistant reads the same day back in sentences when asked. */
    out.push(el("button.sn-brief", {
      text: "▷ brief me",
      title: "ask " + (window.Agent ? window.Agent.name() : "the assistant")
             + " to talk through today",
      onclick: () => {
        close();
        if (!window.Agent) return toast("assistant not loaded", true);
        window.Agent.open();
        window.Agent.ask("What's my schedule today, and what should I focus on? "
                       + "Use whats_next and calendar_suggestions.");
      },
    }));
    return out;
  };

  /* --- reminders and bills ---------------------------------------------- */
  R.owing = (d) => {
    const out = [];
    d.reminders.forEach((r) => out.push(line(r.title,
      r.days_until < 0 ? Math.abs(r.days_until) + "d late" : "today")));
    d.payments.forEach((p) => out.push(line(
      p.name, money(p.amount) + " · " + whenDue0(p.days_until))));
    if (!out.length) out.push(empty("Nothing waiting."));
    return out;
  };
  const whenDue0 = (n) => (n <= 0 ? "due" : "in " + n + "d");

  /* --- money ------------------------------------------------------------- */
  R.vault = (d) => {
    const out = [el(
      "div.sn-big", { text: money(d.total_balance) }, [
        el("span.sn-big-m", { text: " across " + d.accounts.length + " accounts" }),
      ])];
    out.push(line("spent this month", money(d.spent)
      + (d.allocated ? " of " + money(d.allocated) : "")));
    if (d.unbudgeted) out.push(line("outside the plan", money(d.unbudgeted)));
    d.over.forEach((c) => out.push(el("div.sn-line", {}, [
      el("span.sn-line-t", { text: (c.icon ? c.icon + " " : "") + c.name,
                             style: "color:var(--red)" }),
      el("span.sn-line-m", { text: money(c.actual) + " / " + money(c.target) }),
    ])));
    out.push(el("button.sn-go", { text: "open vault →",
      onclick: () => { close(); window.openModule("vault", "vault-overview"); } }));
    return out;
  };

  /* --- pulse ------------------------------------------------------------- */
  R.habits = (d) => {
    const out = [];
    if (!d.total) return [empty("No habits set up.")];
    d.habits.forEach((h) => out.push(el("div.sn-line", {}, [
      el("span.sn-tickmark", { text: h.done ? "✓" : "○",
                               style: "color:" + (h.done ? "var(--green)" : "var(--dim)") }),
      el("span.sn-line-t", { text: h.name,
                             style: h.done ? "color:var(--dim)" : "" }),
    ])));
    out.push(el("div.sn-tot", { text: d.done + " of " + d.total + " done today" }));
    return out;
  };

  R.scores = (d) => (d.scores || []).map((s) => el("div.sn-score", {}, [
    el("span.sn-line-t", { text: s.label }),
    // null is "not tracked", never a red zero — scoring silence as failure
    // teaches you to ignore the dashboard.
    el("span.sn-score-v", { text: s.value == null ? "–" : s.value,
                            title: s.basis || "",
                            style: "color:" + (s.value == null ? "var(--dim)" : "var(--accent)") }),
  ]));

  R.nutrition = (d) => {
    const out = [];
    if (d.target) {
      out.push(line("calories", (d.calories || 0) + " / " + d.target
        + " · " + (d.remaining >= 0 ? d.remaining + " left" : Math.abs(d.remaining) + " over")));
    } else out.push(line("calories", String(d.calories || 0)));
    if (d.protein != null) {
      out.push(line("protein", Math.round(d.protein) + "g"
        + (d.protein_target ? " / " + d.protein_target + "g" : "")));
    }
    if (d.water_ml) out.push(line("water", d.water_ml + "ml"));
    if (!d.entries) out.push(empty("Nothing logged today."));
    return out;
  };

  /* --- the rest ---------------------------------------------------------- */
  R.projects = (d) => (d.projects.length
    ? d.projects.map((p) => line(p.name, hoursMins(p.mins) + " · " + p.last_worked))
    : [empty("No project worked in the last three weeks.")]);

  R.learning = (d) => (d.learning.length
    ? d.learning.map((l) => line(l.title, l.status))
    : [empty("Nothing open.")]);

  R.mind = (d) => {
    const out = d.items.map((m) => line(m.text, m.kind));
    if (!out.length) out.push(empty("Inbox clear."));
    else if (d.total > d.items.length) {
      out.push(el("div.sn-tot", { text: d.total + " open in total" }));
    }
    out.push(el("button.sn-go", { text: "open mind dump →", onclick: () => goto("mind") }));
    return out;
  };

  R.activity = (d) => (d.events.length
    ? d.events.map((e) => line(
        (e.action || "") + (e.detail ? " · " + e.detail : ""),
        (e.module || "") + " " + String(e.timestamp || "").slice(11, 16)))
    : [empty("Nothing logged yet.")]);

  /* ------------------------------------------------------------------ *
   * The ⚙ editor — which sections show, and in what order
   * ------------------------------------------------------------------ */
  function saveChoice() {
    return guard(() => api.focus.set({ sections: JSON.stringify(chosen) }));
  }

  function editor() {
    const box = el("div.sn-editor");
    box.appendChild(el("div.sn-ed-head", { text: "show in the snapshot" }));

    // On, in order, first — dragging is overkill for a list this short, so the
    // arrows move a section relative to the others that are actually on.
    chosen.forEach((key, i) => {
      const spec = catalogue.find((c) => c.key === key);
      if (!spec) return;                       // a key from an older version
      box.appendChild(el("div.sn-ed-row.on", {}, [
        el("button.sn-ed-tick", { text: "☑", title: "hide this section",
          onclick: () => guard(async () => {
            chosen = chosen.filter((k) => k !== key);
            await saveChoice(); refresh();
          }) }),
        el("span.sn-ed-t", { text: spec.label, title: spec.blurb }),
        el("button.sn-ed-mv", { text: "▲", title: "move up", disabled: i === 0,
          onclick: () => guard(async () => {
            chosen.splice(i - 1, 0, chosen.splice(i, 1)[0]);
            await saveChoice(); refresh();
          }) }),
        el("button.sn-ed-mv", { text: "▼", title: "move down", disabled: i === chosen.length - 1,
          onclick: () => guard(async () => {
            chosen.splice(i + 1, 0, chosen.splice(i, 1)[0]);
            await saveChoice(); refresh();
          }) }),
      ]));
    });

    const off = catalogue.filter((c) => !chosen.includes(c.key));
    if (off.length) box.appendChild(el("div.sn-ed-head", { text: "off" }));
    off.forEach((spec) => {
      box.appendChild(el("div.sn-ed-row", {}, [
        el("button.sn-ed-tick", { text: "☐", title: "show this section",
          onclick: () => guard(async () => {
            chosen = chosen.concat([spec.key]);
            await saveChoice(); refresh();
          }) }),
        el("span.sn-ed-t", { text: spec.label, title: spec.blurb }),
      ]));
    });

    box.appendChild(el("div.sn-ed-foot", { text: "stored on the server — the same in any browser" }));
    return box;
  }

  /* ------------------------------------------------------------------ *
   * The panel
   * ------------------------------------------------------------------ */
  function close() {
    if (panel) { panel.remove(); panel = null; }
    clearInterval(clockTimer);
    clockTimer = null;
    editing = false;
  }

  /* Only the digits repaint, so nothing you're typing in loses focus and the
     panel's scroll position survives a running timer. */
  function tickClocks() {
    if (!panel || !window.Timers) return;
    const live = {};
    window.Timers.list().forEach((t) => { live[t.id] = t.clock; });
    panel.querySelectorAll("[data-sn-timer]").forEach((n) => {
      const c = live[n.getAttribute("data-sn-timer")];
      if (c && n.textContent !== c) n.textContent = c;
    });
  }

  async function load() {
    if (!catalogue.length) {
      const cat = await api.snapshot.sections();
      catalogue = cat.sections;
      if (chosen === null) chosen = cat.defaults.slice();
    }
    const f = await api.focus.get();
    focus = f;
    if (f.sections) {
      try {
        const saved = JSON.parse(f.sections);
        // Keep only keys this backend still serves — a renamed section
        // degrades to a smaller panel rather than an empty box.
        if (Array.isArray(saved)) {
          chosen = saved.filter((k) => catalogue.some((c) => c.key === k));
        }
      } catch { /* keep the defaults */ }
    }
    return api.snapshot.get(chosen);
  }

  function draw(snap) {
    clear(panel);

    /* --- the phase, editable in place --- */
    const phaseIn = el("input.fc-phase-in", {
      value: focus.phase || "", placeholder: "what phase are you in?" });
    const noteIn = el("input.fc-note-in", {
      placeholder: "why this phase — and what would end it" });
    noteIn.value = focus.note || "";
    const savePhase = () => guard(async () => {
      await api.focus.set({ phase: phaseIn.value.trim(), note: noteIn.value });
      focus.phase = phaseIn.value.trim();
      focus.note = noteIn.value;
      paintChip(focus.phase);
      toast("phase saved");
    });
    phaseIn.addEventListener("change", savePhase);
    noteIn.addEventListener("change", savePhase);

    panel.appendChild(el("div.fc-head", {}, [
      el("div", { style: "flex:1;min-width:0" }, [
        el("div.fc-label", { text: "current phase" }),
        phaseIn,
      ]),
      el("button.sn-gear", { text: "⚙", title: "choose what this panel shows",
        onclick: () => { editing = !editing; refresh(); } }),
      el("button.fc-x", { text: "×", onclick: close }),
    ]));
    panel.appendChild(el("div.fc-body", {}, [noteIn]));
    if (focus.updated_at) {
      panel.appendChild(el("div.fc-stamp", { text: "set " + ago(focus.updated_at) }));
    }

    if (editing) { panel.appendChild(editor()); return; }

    const body = el("div.fc-body");
    chosen.forEach((key) => {
      const spec = catalogue.find((c) => c.key === key);
      const data = snap.sections[key];
      if (!spec || !data) return;
      body.appendChild(el("div.fc-group", { text: spec.label }));
      if (data.error) {
        // One module with nothing set up must never blank the whole overview.
        body.appendChild(el("div.sn-err", { text: data.error, title: data.error }));
        return;
      }
      (R[key] ? R[key](data) : [empty("no renderer")]).forEach((n) => n && body.appendChild(n));
    });

    if (!chosen.length) {
      body.appendChild(empty("Every section is switched off. Press ⚙ to pick some."));
    }
    panel.appendChild(body);
    panel.appendChild(el("div.fc-foot", { text: "as of " + (snap.generated_at || "").slice(11, 16) }));
  }

  /* Re-fetch and repaint an already-open panel, keeping where you'd scrolled. */
  function refresh() {
    if (!panel) return;
    const top = panel.scrollTop;
    guard(async () => {
      const snap = await load();
      if (!panel) return;
      draw(snap);
      panel.scrollTop = top;
    });
  }

  async function open() {
    close();
    // Opening is async, so two fast clicks can overlap. The later one wins and
    // the earlier bails on resuming — otherwise it would draw into a panel it
    // no longer owns and start a second clock nobody ever clears.
    const mine = ++generation;
    panel = el("div.fc-panel.sn-panel");
    panel.appendChild(el("div.sn-loading", { text: "…" }));
    document.body.appendChild(panel);

    const snap = await load();
    if (!panel || mine !== generation) return;   // closed or superseded
    draw(snap);
    clockTimer = setInterval(tickClocks, 1000);
    if (!focus.phase) {
      const p = panel.querySelector(".fc-phase-in");
      if (p) p.focus();
    }
  }

  /* ------------------------------------------------------------------ *
   * The chip
   * ------------------------------------------------------------------ */
  function paintChip(phase) {
    const c = document.getElementById("fc-chip");
    if (!c) return;
    const text = (phase || "").trim();
    // Empty state is the glyph alone — an unset phase shouldn't cost tab space.
    c.textContent = text ? "◈ " + text : "◈";
    c.className = "fc-chip" + (text ? "" : " empty");
    c.title = text ? "current phase — click for your snapshot"
                   : "your snapshot: what's on, what's due, what you're doing";
  }

  function mount() {
    const host = document.getElementById("status-pill");
    if (!host) return;
    const chip = el("button.fc-chip.empty", { id: "fc-chip", text: "◈",
      onclick: (e) => { e.stopPropagation(); panel ? close() : guard(open); } });
    host.insertBefore(chip, host.firstChild);
    document.addEventListener("click", (e) => {
      if (panel && !panel.contains(e.target) && e.target.id !== "fc-chip") close();
    });
    guard(async () => {
      focus = await api.focus.get();
      paintChip(focus.phase);
    });
  }

  window.Focus = {
    open, close, refresh,
    chip: () => guard(async () => paintChip((await api.focus.get()).phase)),
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

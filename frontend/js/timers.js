/* timers.js — running clocks for whatever you're actually doing.

   Several at once, because a real afternoon is not one activity: a project
   building, a task in the background, a paper half-read. Each timer points at
   a real thing (project · task · idea · paper · document · habit) or just
   carries a label, and stopping one writes a :WorkSession — the same rows the
   Instances tab, the Database tab and the contribution grid already read.
   Nothing here invents a second way to record time.

   The dock shows or hides on demand and remembers which you chose. Hidden it
   is a single ghost button, so a timer is never running somewhere you can't
   see or stop it.

   Elapsed time is stored as `startedAt` + accumulated milliseconds rather than
   a tick count, so closing the tab, sleeping the laptop or leaving it
   overnight all still produce the right duration. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const STORE = "mainframe.timers";
  const UI_STORE = "mainframe.timers.ui";
  const KINDS = ["project", "task", "idea", "paper", "document", "habit", "other"];

  let timers = [];
  let ui = { hidden: false, open: false };
  let dock = null, tick = null;

  /* ------------------------------------------------------------------ *
   * State
   * ------------------------------------------------------------------ */
  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(timers)); } catch { /* ignore */ }
  }
  function saveUI() {
    try { localStorage.setItem(UI_STORE, JSON.stringify(ui)); } catch { /* ignore */ }
  }
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || "[]");
      if (Array.isArray(raw)) timers = raw;
    } catch { timers = []; }
    try {
      Object.assign(ui, JSON.parse(localStorage.getItem(UI_STORE) || "{}"));
    } catch { /* defaults */ }
  }

  /* Wall-clock elapsed, not a counter — a paused timer keeps what it banked,
     a running one adds the time since it last started. */
  function elapsedMs(t) {
    return (t.accumulatedMs || 0) + (t.running ? Date.now() - t.startedAt : 0);
  }

  function fmtClock(ms) {
    const total = Math.max(0, Math.floor(ms / 1000));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return h ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`;
  }

  const pad2 = (n) => String(n).padStart(2, "0");
  const hm = (d) => pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  const isoDay = (d) =>
    d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());

  const running = () => timers.filter((t) => t.running);

  /* ------------------------------------------------------------------ *
   * Actions
   * ------------------------------------------------------------------ */
  function start(opts) {
    opts = opts || {};
    const t = {
      id: "t" + Date.now() + Math.floor(Math.random() * 1000),
      kind: opts.kind || "other",
      ref_id: opts.ref_id || null,
      // Which project pass this clock belongs to, when it was started from one.
      // Carried through to the logged session so the hours land in the right
      // run rather than in the project's undifferentiated pile.
      pass_id: opts.pass_id || "",
      label: opts.label || "untitled",
      module: opts.module || (window.PM && window.PM.activeModule) || "synapse",
      startedAt: Date.now(),
      // The wall-clock time the FIRST run began, so the logged session says
      // when the work actually happened rather than when you pressed stop.
      startHM: hm(new Date()),
      date: isoDay(new Date()),
      accumulatedMs: 0,
      running: true,
      what: "",
    };
    timers.push(t);
    ui.hidden = false;
    ui.open = true;
    save(); saveUI(); render();
    return t;
  }

  function toggle(id) {
    const t = timers.find((x) => x.id === id);
    if (!t) return;
    if (t.running) {
      t.accumulatedMs = elapsedMs(t);
      t.running = false;
    } else {
      t.startedAt = Date.now();
      t.running = true;
    }
    save(); render();
  }

  function discard(id) {
    timers = timers.filter((t) => t.id !== id);
    save(); render();
  }

  /* Stop a clock and hand back what it measured, WITHOUT writing a session.

     For the one caller that is going to write the session itself: a document
     push opens the full session form with this bracket in it, and the user
     presses push. Logging here as well would put the same time in the database
     twice. Returns null if the timer is already gone. */
  function release(id) {
    const t = timers.find((x) => x.id === id);
    if (!t) return null;
    const bracket = {
      date: t.date,
      start: t.startHM,
      end: hm(new Date()),
      mins: Math.round(elapsedMs(t) / 60000),
      label: t.label,
      ref_id: t.ref_id,
      kind: t.kind,
    };
    discard(id);
    return bracket;
  }

  /* Stop → write a work session. Anything under a minute is almost always a
     misfire (started, immediately stopped), so it's discarded rather than
     polluting the log with 0-minute rows. */
  async function stop(id) {
    const t = timers.find((x) => x.id === id);
    if (!t) return;
    const mins = Math.round(elapsedMs(t) / 60000);
    if (mins < 1) {
      discard(id);
      toast("under a minute — not logged");
      return;
    }
    await api.work.create({
      date: t.date,
      start: t.startHM,
      end: hm(new Date()),
      mins,
      module: t.module,
      ref_kind: t.kind,
      ref_id: t.ref_id,
      ref_title: t.label,
      what: (t.what || "").trim(),
      focus: "none",
      pass_id: t.pass_id || "",
    });
    discard(id);
    toast(`logged ${mins}m to ${t.label}`);
    if (window.refreshActive) window.refreshActive();
  }

  /* ------------------------------------------------------------------ *
   * Rendering
   * ------------------------------------------------------------------ */
  function timerRow(t) {
    const whatIn = el("input.tm-what", {
      value: t.what || "", placeholder: "what are you doing?",
    });
    whatIn.addEventListener("input", () => { t.what = whatIn.value; save(); });

    return el("div.tm-row" + (t.running ? ".on" : ""), {}, [
      el("div.tm-line", {}, [
        el("span.tm-kind", { text: t.kind }),
        el("span.tm-label", { title: t.label, text: t.label }),
        el("span.tm-clock", { "data-timer": t.id, text: fmtClock(elapsedMs(t)) }),
      ]),
      whatIn,
      el("div.tm-acts", {}, [
        el("button.tm-btn", {
          title: t.running ? "pause" : "resume",
          text: t.running ? "⏸" : "▶",
          onclick: () => toggle(t.id),
        }),
        el("button.tm-btn.tm-stop", {
          title: "stop and log this to the work database",
          text: "■ log",
          onclick: () => guard(() => stop(t.id)),
        }),
        el("button.tm-btn.tm-drop", {
          title: "discard without logging",
          text: "×",
          onclick: () => discard(t.id),
        }),
      ]),
    ]);
  }

  function newTimerForm() {
    const kindSel = el("select.tm-mini", {}, KINDS.map((k) =>
      el("option", { value: k, text: k })));
    const targetSel = el("select.tm-mini", {}, [el("option", { value: "", text: "loading…" })]);
    const freeIn = el("input.tm-mini", { placeholder: "what are you timing?" });

    function refreshTargets() {
      const kind = kindSel.value;
      freeIn.style.display = kind === "other" ? "" : "none";
      targetSel.style.display = kind === "other" ? "none" : "";
      if (kind === "other") return;
      clear(targetSel);
      targetSel.appendChild(el("option", { value: "", text: "loading…" }));
      guard(async () => {
        const list = await api.work.targets(kind);
        clear(targetSel);
        if (!list.length) {
          targetSel.appendChild(el("option", { value: "", text: "nothing of this kind yet" }));
          return;
        }
        list.forEach((x) => targetSel.appendChild(
          el("option", { value: x.id, text: x.label })));
      });
    }
    kindSel.addEventListener("change", refreshTargets);
    refreshTargets();

    const go = el("button.tm-btn.tm-go", { text: "▶ start", onclick: () => {
      const kind = kindSel.value;
      if (kind === "other") {
        const label = freeIn.value.trim();
        if (!label) return toast("say what you're timing", true);
        start({ kind, label });
      } else {
        const opt = targetSel.selectedOptions[0];
        if (!opt || !opt.value) return toast("pick something to time", true);
        start({ kind, ref_id: opt.value, label: opt.textContent });
      }
    } });

    return el("div.tm-new", {}, [
      el("div.row", { style: "gap:5px" }, [kindSel, targetSel, freeIn]),
      el("div.row", { style: "gap:5px;justify-content:flex-end;margin-top:6px" }, [go]),
    ]);
  }

  function render() {
    if (!dock) return;
    clear(dock);
    dock.classList.toggle("tm-hidden", ui.hidden);

    // Hidden: one ghost button. A running timer still shows its count, because
    // "hidden" must never mean "forgotten".
    if (ui.hidden) {
      const n = running().length;
      dock.appendChild(el("button.tm-ghost" + (n ? ".on" : ""), {
        title: n ? n + " timer(s) running — click to show" : "show timers",
        text: n ? "⏱ " + n : "⏱",
        onclick: () => { ui.hidden = false; ui.open = true; saveUI(); render(); },
      }));
      return;
    }

    const total = timers.reduce((ms, t) => ms + elapsedMs(t), 0);
    const head = el("div.tm-head", {}, [
      el("button.tm-title", {
        onclick: () => { ui.open = !ui.open; saveUI(); render(); },
        text: (ui.open ? "▾ " : "▸ ") + "timers"
              + (timers.length ? " (" + timers.length + ")" : ""),
      }),
      timers.length ? el("span.tm-total", { "data-total": "1", text: fmtClock(total) }) : null,
      el("button.tm-btn.tm-hide", {
        title: "hide the dock", text: "–",
        onclick: () => { ui.hidden = true; saveUI(); render(); },
      }),
    ]);
    dock.appendChild(head);
    if (!ui.open) return;

    const body = el("div.tm-body");
    if (!timers.length) {
      body.appendChild(el("div.tm-empty", {
        text: "No timers running. Start one for a project, a task, or anything else.",
      }));
    } else {
      timers.forEach((t) => body.appendChild(timerRow(t)));
    }
    body.appendChild(newTimerForm());
    dock.appendChild(body);
  }

  /* Only the digits change every second. Re-rendering the whole dock would
     throw away focus in the "what are you doing?" box you're typing into. */
  function tickClocks() {
    if (!dock || ui.hidden) {
      // The ghost button still shows a running count, so keep it honest.
      if (dock && ui.hidden) {
        const g = dock.querySelector(".tm-ghost");
        const n = running().length;
        if (g) g.textContent = n ? "⏱ " + n : "⏱";
      }
      return;
    }
    let total = 0;
    timers.forEach((t) => {
      const ms = elapsedMs(t);
      total += ms;
      const node = dock.querySelector(`[data-timer="${t.id}"]`);
      if (node) node.textContent = fmtClock(ms);
    });
    const totalNode = dock.querySelector("[data-total]");
    if (totalNode) totalNode.textContent = fmtClock(total);
  }

  /* ------------------------------------------------------------------ *
   * Mount
   * ------------------------------------------------------------------ */
  function mount() {
    load();
    dock = el("div.tm-dock");
    document.body.appendChild(dock);
    render();
    clearInterval(tick);
    tick = setInterval(tickClocks, 1000);
    // A running timer's elapsed time is derived from the clock, so coming back
    // to a backgrounded tab just needs a repaint, not a correction.
    document.addEventListener("visibilitychange", () => { if (!document.hidden) tickClocks(); });
  }

  window.Timers = {
    start,
    // Views call this to offer a ⏱ button against a specific thing.
    button(opts, label) {
      return el("button.tm-start", {
        title: "start a timer for " + (opts.label || "this"),
        text: label || "⏱",
        onclick: (e) => { e.stopPropagation(); start(opts); },
      });
    },
    show() { ui.hidden = false; saveUI(); render(); },
    hide() { ui.hidden = true; saveUI(); render(); },
    running: () => running().length,
    /* What's on the clock right now, for anything that wants to display it —
       the snapshot panel asks every second. Elapsed is computed on each call
       rather than stored, so a caller repainting on its own timer stays right
       without having to be told when a timer starts or stops. */
    list() {
      return timers.map((t) => ({
        id: t.id, label: t.label, kind: t.kind, what: t.what || "",
        running: !!t.running, ms: elapsedMs(t), clock: fmtClock(elapsedMs(t)),
        // What it is a clock FOR, and when it began — a caller that shows its
        // own chip for one timer needs both to draw it and to bracket a session.
        ref_id: t.ref_id || null, date: t.date, startHM: t.startHM,
      }));
    },
    release,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

/* calendar.js — the Mainframe's calendar. A top-level service, next to Tasks.

   What makes it not just another calendar
   ---------------------------------------
   Google knows your commitments. The Mainframe already knows your tasks, the
   work you actually logged, your workouts and habits. This puts them in one
   grid, which is the only place plan and actual can be compared:

     ▪ events  — commitments with a time. Yours, or imported from an .ics.
     ◆ due     — tasks due that day, read live from :Task. Never copied here,
                 so a due date can't disagree with itself in two places.
     ● done    — what actually happened. Read-only; the calendar reports it.

   The suggestions panel is deterministic — every line names the numbers it came
   from, and each one that can be acted on carries a one-click action. That's
   deliberate: a planner that can't show its working is one you stop trusting the
   first time it's wrong, and this is also the surface a voice agent will drive
   later, so it has to return facts rather than prose.

   Zero libraries, like everything else here. The month grid, the week's hour
   axis and the event blocks are all plain DOM and CSS. */
(function () {
  const { el, clear, toast, guard, confirmDo, todayISO } = window.ui;
  const api = window.api;

  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                  "August", "September", "October", "November", "December"];
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  // The hour window the week/day grids draw. Matches the backend's suggestion
  // window so "free" means the same thing in both places.
  const HOUR_FROM = 7, HOUR_TO = 23;
  const PX_PER_HOUR = 44;

  let view = "month";              // month | week | day
  let anchor = todayISO();         // the date the current view is built around
  let feed = null;                 // last /range response
  let suggestions = [];
  let showSuggestions = true;
  // Planner blocks are a layer you can hide: an auto-placed plan is useful,
  // but three study slots a day can drown what actually happened.
  let showPlan = (() => { try { return localStorage.getItem("cal.showPlan") !== "0"; } catch (_e) { return true; } })();

  /* One border colour per module, everywhere on this calendar: Synapse green,
     Pulse (fitness) pink, Vision red, Vault (money) gold. Anything that
     belongs to no module, or to Mainframe itself, is the neutral blue-grey. */
  const MOD_COLOUR = { synapse: "#00D4AA", pulse: "#DE7BA4", fitness: "#DE7BA4",
    vision: "#FF4757", vault: "#D4A017", money: "#D4A017" };
  const modColour = (m) => MOD_COLOUR[(m || "").toLowerCase()] || "#7FA8C8";
  const KIND_GLYPH = { review: "↻ ", planning: "✎ " };

  /* ------------------------------------------------------------------ dates */
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`
                   + `-${String(d.getDate()).padStart(2, "0")}`;
  const parse = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
  const addMonths = (s, n) => {
    const d = parse(s);
    const day = d.getDate();
    d.setDate(1);
    d.setMonth(d.getMonth() + n);
    // Clamp: 31 Jan + 1 month has no correct answer, and setDate(31) on a
    // 28-day month silently rolls into the next one.
    const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate();
    d.setDate(Math.min(day, last));
    return iso(d);
  };
  // Monday-first weeks: getDay() is Sunday-first, so Sunday (0) becomes 6.
  const mondayOf = (s) => { const d = parse(s); const off = (d.getDay() + 6) % 7; d.setDate(d.getDate() - off); return iso(d); };
  const mins = (hhmm) => {
    if (!hhmm || hhmm.indexOf(":") < 0) return null;
    const [h, m] = hhmm.split(":").map(Number);
    return isNaN(h) || isNaN(m) ? null : h * 60 + m;
  };
  const prettyDay = (s) => {
    const d = parse(s);
    return `${DOW[(d.getDay() + 6) % 7]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}`;
  };

  function rangeFor() {
    if (view === "day") return [anchor, anchor];
    if (view === "week") { const m = mondayOf(anchor); return [m, addDays(m, 6)]; }
    const d = parse(anchor);
    const first = iso(new Date(d.getFullYear(), d.getMonth(), 1));
    const last = iso(new Date(d.getFullYear(), d.getMonth() + 1, 0));
    // The month grid always shows whole weeks, so it spills into both neighbours.
    return [mondayOf(first), addDays(mondayOf(last), 41)];
  }

  /* ------------------------------------------------------------- day buckets */
  function bucket() {
    const byDay = {};
    const get = (d) => (byDay[d] = byDay[d] || { events: [], due: [], work: [], logged: [] });
    (feed.events || []).forEach((e) => {
      // A multi-day event belongs to every day it covers, not just its first.
      const last = e.end_date && e.end_date > e.date ? e.end_date : e.date;
      for (let d = e.date; d <= last; d = addDays(d, 1)) get(d).events.push(e);
    });
    // Inbox rows you said you'd do on a day. Shaped like events so the same
    // lanes, strips and chips draw them; __inbox marks them so a click opens
    // the Inbox rather than the event editor (they aren't :CalEvents).
    (feed.planned || []).forEach((t) => {
      const s = t.do_at || "";
      let end = "";
      if (s) {
        const [h, m] = s.split(":").map(Number);
        const e = h * 60 + m + (t.takes_min || 30);
        end = e < 1440 ? String(Math.floor(e / 60)).padStart(2, "0") + ":" + String(e % 60).padStart(2, "0") : "23:59";
      }
      get(t.do_on).events.push({ id: "inbox-" + t.id, title: (t.status === "done" ? "✓ " : "") + t.title,
        date: t.do_on, start: s, end, all_day: !s, module: t.module, __inbox: t });
    });
    // What you did, drawn as real blocks now rather than a faint strip behind
    // the plan: logged work (its module's colour) and workouts (always Pulse).
    const hm = (x) => { const m = /^(\d{1,2}):(\d{2})/.exec(x || ""); return m ? +m[1] * 60 + +m[2] : null; };
    const plus = (st, n) => { const e = hm(st) + n; return e >= 1440 ? "23:59" : String(Math.floor(e / 60)).padStart(2, "0") + ":" + String(e % 60).padStart(2, "0"); };
    (feed.work || []).forEach((w) => {
      if (hm(w.start) === null) return;          // untimed work stays a dot
      get(w.date).events.push({ id: "work-" + w.id, title: w.title || w.kind || "work",
        date: w.date, start: w.start, end: w.end || plus(w.start, w.minutes || 30),
        module: w.module, __work: w });
    });
    (feed.workouts || []).forEach((x) => {
      const label = "Workout · " + (x.name || x.type || "") + (x.duration ? " · " + x.duration + "m" : "");
      const timed = hm(x.start) !== null;
      get(x.date).events.push({ id: "workout-" + x.id, title: label, date: x.date,
        start: timed ? x.start : "", end: timed ? plus(x.start, x.duration || 30) : "",
        all_day: !timed, module: "pulse", __workout: x });
    });
    if (showPlan) (feed.plan_blocks || []).forEach((b) => {
      get(b.date).events.push({ id: "plan-" + b.id, title: b.title, date: b.date,
        start: b.start, end: b.end, module: b.module, __plan: b });
    });
    (feed.due || []).forEach((t) => get(t.due_date).due.push(t));
    (feed.work || []).forEach((w) => get(w.date).work.push(w));
    (feed.logged || []).forEach((l) => get(l.date).logged.push(l));
    return byDay;
  }

  // An Inbox block opens the Inbox; everything else is a real event.
  function openItem(e, day, reload) {
    if (e.__inbox) { window.openTab("inbox"); return; }
    if (e.__work) { window.openTab("work"); return; }
    if (e.__plan) { window.openTab("planner"); return; }
    if (e.__workout) {
      window.openModule("pulse", "fitness");
      if (window.FIT && window.FIT.go) setTimeout(() => window.FIT.go("workouts"), 300);
      return;
    }
    eventModal(e, day, reload);
  }

  // Classes + inline border colour for anything drawn on the grid.
  function itemCls(e) {
    return (e.source === "ics" ? ".ics" : "") + (e.task_id ? ".planned" : "")
      + (e.__inbox ? ".inbox" : "") + (e.__work ? ".done-work" : "")
      + (e.__workout ? ".workout" : "") + (e.__plan ? ".plan" : "")
      + (e.kind === "review" ? ".review" : e.kind === "planning" ? ".planning" : "");
  }
  const itemStyle = (e) => "border-left-color:" + modColour(e.module) + ";--mod:" + modColour(e.module) + ";";
  const itemTitle = (e) => (KIND_GLYPH[e.kind] || "") + (e.repeat === "weekly" ? "" : "") + e.title;

  /* ------------------------------------------------------------------ modals */
  function openModal(titleText, nodes, submitLabel, onSubmit, extra) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const card = el("div.modal", {}, [
      el("div.modal-title", { text: titleText }),
      ...nodes,
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: submitLabel, onclick: () => onSubmit(close) }),
        ...(extra ? extra(close) : []),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const first = card.querySelector("input,select,textarea");
    if (first) first.focus();
  }

  const field = (label, node) => el("div.mform-full", {}, [
    el("div.mform-label", { text: label }), node]);

  function eventModal(existing, day, reload, preset) {
    const e = existing || {};
    const p = preset || {};
    const readOnly = e.source === "ics";

    const title = el("input.mform-input", {
      // "book time for it" already knows which task it is, so typing the name
      // again is a step for nothing. Still editable.
      value: e.title || p.title || "", placeholder: "What is it?" });
    const date = el("input.mform-input", { type: "date", value: e.date || day || todayISO() });
    const start = el("input.mform-input", { type: "time", value: e.start || p.start || "" });
    const end = el("input.mform-input", { type: "time", value: e.end || p.end || "" });
    const allDay = el("input", { type: "checkbox" });
    allDay.checked = !!e.all_day;
    const location = el("input.mform-input", { value: e.location || "", placeholder: "optional" });
    // Notes are + rows on the event: on an existing one they save as typed, on a
    // new one they are held until it's created. An imported event keeps its
    // .ics description as read-only text, since the next import rewrites it.
    const notes = readOnly ? null : window.RowBox({ label: "notes", parentId: existing ? e.id : null });
    const kind = el("select.mform-input", {}, [
      el("option", { value: "event", text: "Event — a commitment" }),
      el("option", { value: "block", text: "Block — time set aside to work" }),
      el("option", { value: "reminder", text: "Reminder" }),
      el("option", { value: "review", text: "Review, looking back at the week" }),
      el("option", { value: "planning", text: "Planning, deciding the week ahead" }),
    ]);
    kind.value = e.kind || (p.task_id ? "block" : "event");
    const module = el("select.mform-input", {}, [
      ["", "none (Mainframe)"], ["synapse", "Synapse"], ["pulse", "Pulse (fitness)"],
      ["vision", "Vision"], ["vault", "Vault (money)"]].map(([v, t]) => el("option", { value: v, text: t })));
    module.value = e.module || "";
    const repeat = el("input", { type: "checkbox" });
    repeat.checked = e.repeat === "weekly";
    const until = el("input.mform-input", { type: "date", value: e.repeat_until || "", title: "last week it repeats (empty: for ever)" });
    // A review or planning session is a weekly habit: default it to repeat.
    kind.addEventListener("change", () => {
      if (!existing && (kind.value === "review" || kind.value === "planning")) repeat.checked = true;
    });

    // Link to a task. This is what turns the calendar into a planner: a block
    // that points at a task is the difference between "busy" and "progress".
    // Tasks have no `api.tasks` namespace — the app fetches them with the
    // generic client, so this does too rather than inventing one.
    const taskSel = el("select.mform-input", {}, [el("option", { value: "", text: "— none —" })]);
    guard(async () => {
      let list = [];
      try {
        const all = await api.get("/api/tasks");
        list = (Array.isArray(all) ? all : []).filter((t) => !t.done && t.status !== "done");
      } catch (_err) {
        // A missing task list must not stop you creating an event.
        list = (feed && feed.due ? feed.due : []).filter((t) => t.status !== "done");
      }
      list.forEach((t) => taskSel.appendChild(el("option", {
        value: t.id,
        text: String(t.title || "").slice(0, 60) + (t.due_date ? "  · due " + t.due_date : ""),
      })));
      taskSel.value = e.task_id || p.task_id || "";
    });

    const timesRow = el("div.mform-row", {}, [
      el("div", {}, [el("div.mform-label", { text: "Start" }), start]),
      el("div", {}, [el("div.mform-label", { text: "End" }), end]),
    ]);
    const syncAllDay = () => { timesRow.style.opacity = allDay.checked ? ".4" : "1";
                               start.disabled = end.disabled = allDay.checked; };
    allDay.addEventListener("change", syncAllDay);
    syncAllDay();

    if (readOnly) {
      // Imported events are a mirror of the .ics file. Editing one here would
      // be silently undone by the next import, so the app doesn't pretend.
      [title, date, start, end, location, kind, taskSel, module, repeat, until].forEach((n) => { n.disabled = true; });
      allDay.disabled = true;
    }

    const nodes = [
      readOnly ? el("div.cal-readonly", { text:
        "Imported from " + (e.calendar_name || "an .ics file") + " — read-only. "
        + "Editing here would be overwritten by the next import; change it in the source calendar and re-import." }) : null,
      field("Title", title),
      el("div.mform-row", {}, [
        el("div", {}, [el("div.mform-label", { text: "Date" }), date]),
        el("div", {}, [el("div.mform-label", { text: "Kind" }), kind]),
      ]),
      el("label.cal-check", {}, [allDay, el("span", { text: " all day" })]),
      timesRow,
      el("div.mform-row", {}, [
        el("div", {}, [el("div.mform-label", { text: "Module (border colour)" }), module]),
        el("div", {}, [el("div.mform-label", { text: "Repeat" }),
          el("label.cal-check", {}, [repeat, el("span", { text: " every week, until" })]), until]),
      ]),
      e.series_id ? el("div.sub", { style: "margin:-4px 0 8px", text:
        "This repeats weekly. Changes here apply to every week; the date is the first one." }) : null,
      field("Advances which task?", taskSel),
      field("Location", location),
      readOnly ? (e.notes ? field("Notes", el("div.sub", { style: "white-space:pre-wrap", text: e.notes })) : null) : notes.node,
    ].filter(Boolean);

    openModal(existing ? (readOnly ? "Imported event" : "Edit event") : "New event",
      nodes, readOnly ? "Close" : (existing ? "Save" : "Create"),
      (close) => {
        if (readOnly) return close();
        guard(async () => {
          if (!title.value.trim()) return toast("an event needs a title", true);
          const body = {
            title: title.value.trim(), date: date.value,
            start: allDay.checked ? "" : start.value, end: allDay.checked ? "" : end.value,
            all_day: allDay.checked, location: location.value.trim(),
            kind: kind.value,
            task_id: taskSel.value || null,
            module: module.value,
            repeat: repeat.checked ? "weekly" : "", repeat_until: repeat.checked ? until.value : "",
          };
          // Editing one week of a series edits the series: keep its first date.
          if (e.series_id) body.date = e.series_first || body.date;
          if (existing) await api.calendar.updateEvent(existing.id, body);
          else { const made = await api.calendar.addEvent(body); await notes.commit(made.id); }
          toast(existing ? "saved" : "added");
          close(); reload();
        });
      },
      existing && !readOnly
        ? (close) => [el("button.tk-btn.danger", { text: "Delete", onclick: () =>
            confirmDo(`Delete “${e.title}”?`, async () => {
              await api.calendar.delEvent(existing.id); toast("deleted"); close(); reload();
            }) })]
        : null);
  }

  /* -------------------------------------------------------------- month view */
  function monthGrid(byDay, reload) {
    const [from] = rangeFor();
    const cur = parse(anchor).getMonth();
    const today = todayISO();
    const grid = el("div.cal-month");
    DOW.forEach((d) => grid.appendChild(el("div.cal-dow", { text: d })));

    for (let i = 0; i < 42; i++) {
      const day = addDays(from, i);
      const d = parse(day);
      const b = byDay[day] || { events: [], due: [], work: [], logged: [] };
      const cell = el("div.cal-cell" + (d.getMonth() !== cur ? ".dim" : "")
                      + (day === today ? ".today" : ""));
      cell.appendChild(el("div.cal-daynum", {}, [
        el("span", { text: String(d.getDate()) }),
        b.work.length || b.logged.length
          ? el("span.cal-dot", { title: `${b.work.length} work · ${b.logged.length} logged`,
                                 text: "●" })
          : null,
      ]));

      b.events.slice(0, 3).forEach((e) => cell.appendChild(
        el("div.cal-chip" + (e.all_day ? ".allday" : "") + itemCls(e), {
          style: itemStyle(e),
          title: (e.start ? e.start + " " : "") + itemTitle(e),
          onclick: (ev) => { ev.stopPropagation(); openItem(e, day, reload); },
        }, [
          e.all_day ? null : el("span.cal-chip-t", { text: e.start || "" }),
          el("span", { text: itemTitle(e) }),
        ].filter(Boolean))));
      if (b.events.length > 3) {
        cell.appendChild(el("div.cal-more", { text: `+${b.events.length - 3} more`,
          onclick: (ev) => { ev.stopPropagation(); anchor = day; view = "day"; reload(); } }));
      }
      b.due.forEach((t) => cell.appendChild(
        el("div.cal-due" + (t.status === "done" ? ".done" : ""), {
          title: `Task due: ${t.title}`, text: "◆ " + t.title })));

      // Click empty space in a cell to create an event on that day.
      cell.addEventListener("click", () => eventModal(null, day, reload));
      grid.appendChild(cell);
    }
    return grid;
  }

  /* --------------------------------------------------- week / day time grid */
  function timeGrid(days, byDay, reload) {
    const today = todayISO();
    const hours = HOUR_TO - HOUR_FROM;
    const wrap = el("div.cal-time");

    const axis = el("div.cal-axis");
    axis.appendChild(el("div.cal-axis-head"));
    for (let h = HOUR_FROM; h < HOUR_TO; h++) {
      axis.appendChild(el("div.cal-hour", { style: `height:${PX_PER_HOUR}px`,
        text: String(h).padStart(2, "0") + ":00" }));
    }
    wrap.appendChild(axis);

    days.forEach((day) => {
      const b = byDay[day] || { events: [], due: [], work: [], logged: [] };
      const col = el("div.cal-col" + (day === today ? ".today" : ""));
      const head = el("div.cal-col-head", {}, [
        el("div", { text: prettyDay(day) }),
        b.due.length ? el("div.cal-head-due", { text: `◆ ${b.due.length} due` }) : null,
      ].filter(Boolean));
      head.addEventListener("click", () => { anchor = day; view = "day"; reload(); });
      col.appendChild(head);

      const body = el("div.cal-colbody", { style: `height:${hours * PX_PER_HOUR}px` });
      for (let h = HOUR_FROM; h < HOUR_TO; h++) {
        const line = el("div.cal-slot", { style: `height:${PX_PER_HOUR}px` });
        // Click an empty hour to create an event starting there.
        line.addEventListener("click", () => eventModal(null, day, reload,
          { start: String(h).padStart(2, "0") + ":00",
            end: String(h + 1).padStart(2, "0") + ":00" }));
        body.appendChild(line);
      }

      // All-day events can't sit on a clock, so they get their own strip.
      const allDay = b.events.filter((e) => e.all_day || mins(e.start) === null);
      if (allDay.length) {
        const strip = el("div.cal-allday-strip");
        allDay.forEach((e) => strip.appendChild(el("div.cal-chip.allday" + itemCls(e), {
          style: itemStyle(e), text: itemTitle(e), title: itemTitle(e),
          onclick: (ev) => { ev.stopPropagation(); openItem(e, day, reload); } })));
        col.appendChild(strip);
      }

      // Timed events, positioned by the minute. Overlapping events share the
      // column width rather than hiding each other — a clash you can't see is
      // a clash you don't fix.
      const timed = b.events.filter((e) => !e.all_day && mins(e.start) !== null)
                            .sort((a, c) => mins(a.start) - mins(c.start));
      const lanes = [];
      timed.forEach((e) => {
        const s = mins(e.start);
        const en = mins(e.end) !== null && mins(e.end) > s ? mins(e.end) : s + 30;
        let lane = lanes.findIndex((end) => end <= s);
        if (lane < 0) { lane = lanes.length; lanes.push(en); } else { lanes[lane] = en; }
        e.__lane = lane; e.__s = s; e.__e = en;
      });
      const laneCount = Math.max(1, lanes.length);
      timed.forEach((e) => {
        const top = ((e.__s - HOUR_FROM * 60) / 60) * PX_PER_HOUR;
        const h = Math.max(16, ((e.__e - e.__s) / 60) * PX_PER_HOUR - 2);
        body.appendChild(el("div.cal-block" + itemCls(e), {
          style: `top:${top}px;height:${h}px;left:${(e.__lane / laneCount) * 100}%;`
               + `width:${100 / laneCount}%;` + itemStyle(e),
          title: `${e.start}–${e.end || "?"}  ${itemTitle(e)}`
               + (e.__work ? "  (logged)" : e.__plan ? "  (Planner)" : e.repeat === "weekly" ? "  (every week)" : ""),
          onclick: (ev) => { ev.stopPropagation(); openItem(e, day, reload); },
        }, [
          el("div.cal-block-t", { text: e.start + (e.end ? "–" + e.end : "") }),
          el("div.cal-block-n", { text: itemTitle(e) }),
        ]));
      });

      col.appendChild(body);
      wrap.appendChild(col);
    });
    return wrap;
  }

  /* ------------------------------------------------------- suggestions panel */
  function suggestionPanel(reload) {
    const panel = el("div.cal-sug");
    panel.appendChild(el("div.cal-sug-head", {}, [
      el("span", { text: "Suggestions" }),
      el("span.sub", { style: "font-size:10px", text: suggestions.length + "" }),
    ]));
    if (!suggestions.length) {
      panel.appendChild(el("div.cal-sug-empty", {
        text: "Nothing to flag — no clashes, nothing overdue, and everything due soon has time booked." }));
      return panel;
    }
    suggestions.forEach((s) => {
      const card = el("div.cal-sug-card." + s.severity, {}, [
        el("div.cal-sug-title", { text: s.title }),
        el("div.cal-sug-why", { text: s.why }),
      ]);
      const row = el("div.row", { style: "gap:6px;margin-top:7px;flex-wrap:wrap" });
      if (s.action && s.action.type === "schedule_task") {
        // The task's own name, pulled off the suggestion, becomes the block's
        // title — the suggestion quoted it, so it's already known.
        const quoted = (s.title.match(/“([^”]+)”/) || [])[1] || "";
        row.appendChild(el("button.btn-sm.btn-primary", { text: "book time for it",
          onclick: () => eventModal(null, s.action.date || s.date, reload, {
            task_id: s.action.task_id, start: s.action.start, end: s.action.end,
            title: quoted }) }));
      }
      if (s.date) {
        row.appendChild(el("button.btn-sm", { text: "go to " + s.date,
          onclick: () => { anchor = s.date; view = "day"; reload(); } }));
      }
      if (row.childNodes.length) card.appendChild(row);
      panel.appendChild(card);
    });
    return panel;
  }

  /* --------------------------------------------------------------- importing */
  function importModal(reload) {
    const box = el("div", { style: "min-height:80px" });
    const refresh = () => guard(async () => {
      const st = await api.calendar.importStatus();
      clear(box);
      box.appendChild(el("div.mform-label", { text: "Drop .ics files here" }));
      box.appendChild(el("div.cal-path", { text: st.dir }));
      box.appendChild(el("div.sub", { style: "font-size:11px;margin:10px 0;line-height:1.6",
        text: "In Google Calendar: Settings → Import & export → Export. Unzip it and put the "
            + ".ics files in that folder, then press Re-import. Everything stays on this machine — "
            + "nothing is sent anywhere, and no Google account is connected." }));
      if (!st.files.length) {
        box.appendChild(el("div.empty", { text: "No .ics files in that folder yet." }));
      } else {
        st.files.forEach((f) => box.appendChild(el("div.cal-file", {}, [
          el("span", { text: "📄 " + f.name }),
          el("span.sub", { style: "font-size:10px", text: `${f.size_kb} KB · ${f.modified}` }),
        ])));
      }
      if (st.calendars.length) {
        box.appendChild(el("div.mform-label", { style: "margin-top:12px", text: "Imported" }));
        st.calendars.forEach((c) => box.appendChild(el("div.cal-file", {}, [
          el("span", { text: c.name }), el("span.sub", { text: c.events + " events" })])));
      }
    });
    refresh();
    openModal("Calendar import", [box], "Re-import now", (close) => guard(async () => {
      const r = await api.calendar.runImport();
      toast(`${r.imported} events imported${r.removed ? `, ${r.removed} removed` : ""}`);
      close(); reload();
    }));
  }

  /* -------------------------------------------------------------------- view */
  window.Views = window.Views || {};
  window.Views.calendar = {
    id: "calendar", label: "Calendar", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Calendar" }),
        el("div.sub", { text: "Commitments, what's due, and what you actually did — in one grid. "
                           + "Suggestions are computed from your own numbers, never guessed." }),
      ])]));
      const host = el("div");
      viewEl.appendChild(host);

      async function reload() {
        const [from, to] = rangeFor();
        const [f, s] = await guard(() => Promise.all([
          api.calendar.range(from, to),
          api.calendar.suggestions(todayISO(), 7),
        ]));
        feed = f; suggestions = s || [];
        draw();
      }

      function draw() {
        clear(host);
        const byDay = bucket();
        const d = parse(anchor);

        const label = view === "month"
          ? `${MONTHS[d.getMonth()]} ${d.getFullYear()}`
          : view === "week"
            ? `Week of ${prettyDay(mondayOf(anchor))}`
            : prettyDay(anchor) + " " + d.getFullYear();

        const step = (n) => {
          anchor = view === "month" ? addMonths(anchor, n)
                 : view === "week" ? addDays(anchor, 7 * n)
                 : addDays(anchor, n);
          reload();
        };

        host.appendChild(el("div.cal-bar", {}, [
          el("div.row", { style: "gap:6px;align-items:center" }, [
            el("button.btn-sm", { text: "◀", onclick: () => step(-1) }),
            el("button.btn-sm", { text: "today", onclick: () => { anchor = todayISO(); reload(); } }),
            el("button.btn-sm", { text: "▶", onclick: () => step(1) }),
            el("div.cal-label", { text: label }),
          ]),
          el("div.row", { style: "gap:6px;flex-wrap:wrap" }, [
            ...["month", "week", "day"].map((v) => el("button.btn-sm" + (view === v ? ".btn-primary" : ""), {
              text: v, onclick: () => { view = v; reload(); } })),
            el("button.btn-sm" + (showPlan ? ".btn-primary" : ""), { text: "planner blocks",
              title: "show or hide the Planner's placed work blocks",
              onclick: () => { showPlan = !showPlan; try { localStorage.setItem("cal.showPlan", showPlan ? "1" : "0"); } catch (_e) { /* */ } draw(); } }),
            el("button.btn-sm", { text: showSuggestions ? "hide suggestions" : "suggestions",
              onclick: () => { showSuggestions = !showSuggestions; draw(); } }),
            el("button.btn-sm", { text: "⤓ import", title: "import an .ics export",
              onclick: () => importModal(reload) }),
            el("button.btn-sm.btn-primary", { text: "+ event",
              onclick: () => eventModal(null, anchor, reload) }),
          ]),
        ]));

        const layout = el("div.cal-layout" + (showSuggestions ? ".with-side" : ""));
        const main = el("div", { style: "min-width:0" });
        if (view === "month") main.appendChild(monthGrid(byDay, reload));
        else if (view === "week") {
          const m = mondayOf(anchor);
          main.appendChild(timeGrid([0, 1, 2, 3, 4, 5, 6].map((i) => addDays(m, i)), byDay, reload));
        } else {
          main.appendChild(timeGrid([anchor], byDay, reload));
          const b = byDay[anchor] || { due: [], logged: [], work: [] };
          if (b.due.length || b.logged.length) {
            const side = el("div.cal-daylists");
            if (b.due.length) {
              side.appendChild(el("div.mform-label", { text: "Due today" }));
              b.due.forEach((t) => side.appendChild(el("div.cal-due", { text: "◆ " + t.title })));
            }
            if (b.logged.length) {
              side.appendChild(el("div.mform-label", { style: "margin-top:10px", text: "Logged" }));
              b.logged.forEach((l) => side.appendChild(
                el("div.cal-logged", { text: `● ${l.kind} · ${l.label || ""}` })));
            }
            main.appendChild(side);
          }
        }
        layout.appendChild(main);
        if (showSuggestions) layout.appendChild(suggestionPanel(reload));
        host.appendChild(layout);

        host.appendChild(el("div.cal-legend", {}, [
          el("span", {}, [el("i.k-ev"), el("span", { text: " event" })]),
          el("span", {}, [el("i.k-ics"), el("span", { text: " imported" })]),
          el("span", {}, [el("i.k-plan"), el("span", { text: " planned against a task" })]),
          el("span", {}, [el("i.k-act"), el("span", { text: " work you logged" })]),
          el("span", { text: "◆ task due" }),
        ]));
      }

      await reload();
    },
  };
})();

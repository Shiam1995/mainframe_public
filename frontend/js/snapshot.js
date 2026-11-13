/* snapshot.js — Snapshot (topbar): the day as it happens.

   Live view of TODAY that refreshes itself as information is filled in
   anywhere in the Mainframe — every mutation already lands in the ChangeEvent
   log, so the feed needs no bookkeeping of its own. Arrow back through past
   days to see what happened then, and pin a free-text note to any day.
   Reads /api/snapshot (today's overview tiles) + /api/snapshot/day (the feed);
   writes only /api/snapshot/note. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const POLL_MS = 12000;
  const TILE_SECTIONS = "now,pace,calendar,due,goals,habits,nutrition";

  const MOD_COLOR = {
    synapse: "var(--teal)", pulse: "var(--pulse)",
    vision: "var(--red)", vault: "var(--amber)",
  };

  function localISO(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
  }
  function shift(iso, days) {
    const d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + days);
    return localISO(d);
  }
  function dayLabel(iso) {
    try {
      return new Date(iso + "T12:00:00").toLocaleDateString("en-GB",
        { weekday: "long", day: "numeric", month: "long", year: "numeric" });
    } catch { return iso; }
  }
  function timeOf(ts) {
    try {
      return new Date(ts).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    } catch { return (ts || "").slice(11, 16); }
  }

  /* ---- overview tiles (today only) — compact renderers per section ------- */
  function tile(title, bodyEl, accent) {
    return el("div.snap-tile", accent ? { style: "border-top-color:" + accent } : {}, [
      el("div.snap-tile-title", { text: title }), bodyEl]);
  }
  function line(txt, cls) { return el("div.snap-line" + (cls ? "." + cls : ""), { text: txt }); }

  function renderTiles(host, sections) {
    clear(host);
    const s = sections || {};
    const bad = (x) => !x || x.error;

    if (!bad(s.now)) {
      const b = el("div");
      b.appendChild(line(s.now.count + " session" + (s.now.count === 1 ? "" : "s") +
        " · " + s.now.total_mins + " min logged"));
      s.now.sessions.slice(-4).forEach((w) =>
        b.appendChild(line((w.start ? w.start + " " : "") + w.label, "dim")));
      if (!s.now.sessions.length) b.appendChild(line("nothing logged yet", "dim"));
      host.appendChild(tile("Now", b, "var(--teal)"));
    }
    /* Pace: today against the phase's plan. The whole tile is the daily half of
       Phases → pace (see phase-pace.js) — catch-up is the number that moves, so
       it is the one that gets the colour. Click through for the rest. */
    if (!bad(s.pace) && s.pace.phase) {
      const p = s.pace;
      const b = el("div");
      const hh = (n) => (n == null ? "—" : (Math.round(n * 10) / 10).toFixed(1) + "h");
      if (!p.started) {
        b.appendChild(line("starts in " + p.days_until_start +
          (p.days_until_start === 1 ? " day" : " days")));
        const x = p.capacity_total_h ? p.plan_total_h / p.capacity_total_h : null;
        b.appendChild(line(x ? "the plan is " + (Math.round(x * 100) / 100) + "× capacity"
                             : hh(p.plan_total_h) + " planned", x && x > 1.05 ? "warn" : "dim"));
      } else {
        b.appendChild(line(hh(p.logged_h) + " today · " + hh(p.share_h) + " even share"));
        b.appendChild(line("catch-up " + hh(p.catchup_h) + " a day to finish week " + p.week_index,
          (p.catchup_h || 0) > 10 ? "warn" : "dim"));
        b.appendChild(line("week " + p.week_index + " of " + p.weeks + ": " +
          hh(p.week_logged_h) + " of " + hh(p.week_planned_h) + " planned", "dim"));
      }
      // The verdict only earns a line once it means something; until then the
      // tile says how far off that is rather than showing a grey non-answer.
      // .snap-line is one nowrap line with an ellipsis, so the verdict and its
      // evidence get a line each rather than one that clips halfway through the
      // number that justifies it.
      if (p.weeks_complete >= p.weeks_needed) {
        b.appendChild(line(p.verdict, p.verdict === "about right" ? "ok" : "warn"));
        b.appendChild(line("real " + hh(p.real_week_h) + " vs " + hh(p.plan_week_h) + " a week", "dim"));
      } else {
        const need = p.weeks_needed - p.weeks_complete;
        b.appendChild(line(need + " more " + (need === 1 ? "week" : "weeks") +
          " before the plan can be judged", "dim"));
      }
      host.appendChild(tile("Pace", b, "var(--amber)"));
    }
    if (!bad(s.calendar)) {
      const b = el("div");
      const evs = s.calendar.events || [];
      evs.slice(0, 4).forEach((e) => b.appendChild(line(
        (e.all_day ? "all day" : (e.start || "") + (e.end ? "–" + e.end : "")) + "  " + e.title)));
      if (!evs.length) b.appendChild(line("no events", "dim"));
      if (s.calendar.next_free) b.appendChild(line(
        "free " + s.calendar.next_free.start + "–" + s.calendar.next_free.end, "ok"));
      host.appendChild(tile("Calendar", b, "var(--blue)"));
    }
    if (!bad(s.due)) {
      const b = el("div");
      if (s.due.overdue.length) b.appendChild(line(s.due.overdue.length + " overdue", "warn"));
      s.due.today.slice(0, 3).forEach((t) => b.appendChild(line("today · " + t.title)));
      if (!s.due.today.length && !s.due.overdue.length) b.appendChild(line("nothing due today", "dim"));
      b.appendChild(line(s.due.open_total + " open tasks · " + s.due.soon.length + " due this week", "dim"));
      host.appendChild(tile("Due", b, "var(--red)"));
    }
    if (!bad(s.goals)) {
      const b = el("div");
      if (s.goals.phase) b.appendChild(line("◈ " + s.goals.phase));
      (s.goals.goals || []).slice(0, 4).forEach((g) => b.appendChild(line("· " + g.title, "dim")));
      if (!s.goals.phase && !(s.goals.goals || []).length)
        b.appendChild(line("no phase or goals set — see the Goals tab", "dim"));
      host.appendChild(tile("Goals & phase", b, "var(--purple)"));
    }
    if (!bad(s.habits) && s.habits.total) {
      const b = el("div");
      b.appendChild(line(s.habits.done + " / " + s.habits.total + " done"));
      s.habits.habits.filter((h) => !h.done).slice(0, 4)
        .forEach((h) => b.appendChild(line("○ " + h.name, "dim")));
      host.appendChild(tile("Habits", b, "var(--pulse)"));
    }
    if (!bad(s.nutrition)) {
      const b = el("div");
      const kcal = s.nutrition.calories, tgt = s.nutrition.target;
      b.appendChild(line((kcal != null ? Math.round(kcal) : 0) + " kcal" +
        (tgt ? " of " + tgt : "") + " · " + (s.nutrition.entries || 0) + " entries"));
      if (s.nutrition.protein != null) b.appendChild(line(
        Math.round(s.nutrition.protein) + "g protein" +
        (s.nutrition.protein_target ? " of " + s.nutrition.protein_target + "g" : ""), "dim"));
      host.appendChild(tile("Nutrition", b, "var(--green)"));
    }
  }

  /* ---- the feed ----------------------------------------------------------- */
  function renderFeed(host, data) {
    clear(host);
    if (!data.events.length) {
      host.appendChild(el("div.snap-empty", {
        text: "Nothing recorded on this day" +
          (data.date === localISO(new Date()) ? " yet — it fills in as you work." : "."),
      }));
      return;
    }
    const mods = Object.entries(data.by_module || {})
      .map(([m, n]) => m + " " + n).join(" · ");
    host.appendChild(el("div.snap-feed-sum", { text: data.count + " events · " + mods }));

    let lastHour = null;
    data.events.forEach((e) => {
      const hour = timeOf(e.ts).slice(0, 2) + ":00";
      if (hour !== lastHour) {
        host.appendChild(el("div.snap-hour", { text: hour }));
        lastHour = hour;
      }
      host.appendChild(el("div.snap-ev", {}, [
        el("span.snap-ev-t", { text: timeOf(e.ts) }),
        el("span.snap-ev-mod", {
          text: e.module || "·",
          style: "color:" + (MOD_COLOR[e.module] || "var(--dim)"),
        }),
        el("span.snap-ev-what", { text: (e.category || "") + " " + (e.action || "") }),
        e.detail ? el("span.snap-ev-detail", { text: e.detail }) : null,
      ]));
    });
  }

  window.Views = window.Views || {};
  window.Views.snapshot = {
    id: "snapshot", label: "Snapshot", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      let cur = localISO(new Date());
      let timer = null;

      const liveDot = el("span.snap-live", { title: "refreshing every " + POLL_MS / 1000 + "s" },
        [el("span.snap-live-dot"), "LIVE"]);
      const dateLbl = el("span.snap-date");
      const prevB = el("button.btn-sm", { text: "◂", title: "previous day" });
      const nextB = el("button.btn-sm", { text: "▸", title: "next day" });
      const todayB = el("button.btn-sm", { text: "today" });

      viewEl.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Snapshot" }),
          el("div.sub", { text: "The day as it happens — every module feeds this as you fill things in." }),
        ]),
        el("div.snap-controls", {}, [prevB, dateLbl, nextB, todayB, liveDot]),
      ]));

      const tilesHost = el("div.snap-grid");
      const noteBox = el("textarea.snap-note", { rows: 3, placeholder: "Notes for this day…" });
      const feedHost = el("div.snap-feed");
      viewEl.appendChild(tilesHost);
      viewEl.appendChild(el("div.snap-note-wrap", {}, [
        el("div.snap-tile-title", { text: "Day note" }), noteBox]));
      viewEl.appendChild(feedHost);

      noteBox.addEventListener("change", () =>
        guard(async () => {
          await api.put("/api/snapshot/note", { date: cur, text: noteBox.value });
          toast("day note saved");
        }));

      async function load(quiet) {
        const isToday = cur === localISO(new Date());
        dateLbl.textContent = dayLabel(cur);
        nextB.disabled = isToday;
        liveDot.style.display = isToday ? "" : "none";
        tilesHost.style.display = isToday ? "" : "none";
        try {
          const [day, snap] = await Promise.all([
            api.get("/api/snapshot/day?date=" + cur),
            isToday ? api.get("/api/snapshot?sections=" + TILE_SECTIONS) : Promise.resolve(null),
          ]);
          renderFeed(feedHost, day);
          if (snap) renderTiles(tilesHost, snap.sections);
          // never clobber a note mid-edit on a background poll
          if (document.activeElement !== noteBox) noteBox.value = day.note || "";
        } catch (e) {
          if (!quiet) toast(e.message || String(e), true);
        }
      }

      function go(iso) { cur = iso; load(); }
      prevB.addEventListener("click", () => go(shift(cur, -1)));
      nextB.addEventListener("click", () => { if (!nextB.disabled) go(shift(cur, 1)); });
      todayB.addEventListener("click", () => go(localISO(new Date())));

      await load();
      // #view is shared by every tab — key the poll off an element this view
      // owns, so switching tabs kills the timer.
      timer = setInterval(() => {
        if (!feedHost.isConnected) { clearInterval(timer); return; }
        if (cur === localISO(new Date())) load(true);
      }, POLL_MS);
    },
  };
})();

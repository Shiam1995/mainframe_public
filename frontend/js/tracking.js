/* tracking.js — Pulse: Active Tracking.

   Two labelled views over the same habit logs, switchable in the toolbar:
     · Month — calendar months stacked vertically, clear gap + rule between them
     · Week  — ISO weeks laid out left-to-right, clear gap between them
   ◀ ▶ step through time in whichever unit is active. Every block carries its
   label (month name / "Wk 30 · 20–26 Jul") and its own stats, and the same
   labelled buckets back the Report view + its Markdown/CSV/JSON exports.
   Click any day → the Day Log modal (level 1-4, time, what happened, feel,
   connections). All data comes from GET /api/pulse/tracking/report. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  // image widget for an entity row/modal, returned as a child node
  function imgHost(id, surface) {
    const host = window.ui.el("div");
    window.Images.mount(host, { module: "pulse", contextId: id, surface });
    return host;
  }


  const DOW = ["M", "T", "W", "T", "F", "S", "S"];
  const MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const COUNTS = { month: [3, 6, 12, 24], week: [4, 8, 12, 26], year: [1, 2, 3, 5] };
  let mode = "month";            // month | week | year
  let count = 3;                 // periods shown
  let offset = 0;                // periods back from today
  let showReport = false;
  let rep = null, host = null, headHost = null;

  /* --- date helpers (Monday-start, matching the ISO weeks used server-side) - */
  const d0 = (iso) => new Date(iso + "T00:00:00");
  const mondayIdx = (d) => (d.getDay() + 6) % 7;
  function anchorDate() {
    // The end anchor the server buckets back from: today, stepped back `offset`.
    const t = new Date(); t.setHours(0, 0, 0, 0);
    if (!offset) return P.dateStr(t);
    if (mode === "week") return P.dateStr(new Date(t.getTime() - offset * 7 * P.DAY));
    if (mode === "year") return P.dateStr(new Date(t.getFullYear() - offset, 0, 1));
    return P.dateStr(new Date(t.getFullYear(), t.getMonth() - offset, 1));
  }

  function dayLogModal(h, ds, existing, reload) {
    let level = existing ? (existing.level || 0) : 0;
    const dateIn = el("input.mform-input", { type: "date", value: ds });
    const timeIn = el("input.mform-input", { placeholder: "e.g. 30 min", value: existing ? existing.time_spent || "" : "" });
    const LBL = ["Barely", "Okay", "Good", "Crushed it"];
    const btns = [];
    const lvlWrap = el("div.row", { style: "gap:6px;flex-wrap:wrap" });
    const paint = () => btns.forEach((b, i) => b.classList.toggle("on", i + 1 <= level));
    for (let i = 1; i <= 4; i++) {
      const b = el("button.plevel-btn", { text: i + " — " + LBL[i - 1], onclick: () => { level = i; paint(); } });
      btns.push(b); lvlWrap.appendChild(b);
    }
    paint();
    const notes = el("textarea.mform-input", { placeholder: "what happened during the session?", value: existing ? existing.notes || "" : "" });
    const feel = el("textarea.mform-input", { placeholder: "energy, mood, resistance, motivation", value: existing ? existing.feel || "" : "" });
    const conn = el("textarea.mform-input", { placeholder: "e.g. ties into my Synapse reading on sleep science", value: existing ? existing.connections || "" : "" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Log — " + h.name, [
      el("div.mform-row", {}, [field("Date", dateIn), field("Time spent", timeIn)]),
      field("How well did it go?", lvlWrap),
      field("What happened?", notes),
      field("How did you feel?", feel),
      field("Connections to other Mainframe modules", conn),
      existing && existing.id ? field("Images", imgHost(existing.id, "pulse-daylog")) : null,
    ].filter(Boolean), [
      { label: "Save log", primary: true, onClick: (close) => guard(async () => {
        if (!level) return toast("pick a level 1–4", true);
        await api.pulse.logDay(h.id, { date: dateIn.value, level, time_spent: timeIn.value.trim(), notes: notes.value.trim(), feel: feel.value.trim(), connections: conn.value.trim() });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  /* --- shared bits ------------------------------------------------------- */
  function dayCell(h, ds, log, reload, opts) {
    const o = opts || {};
    const lvl = log ? (log.level || 0) : 0;
    const future = ds > P.dateStr(new Date());
    const cell = el("div.ptrack-day" + (o.small ? ".ptrack-ycell" : "") + (future ? ".ptrack-future" : ""), {
      style: future ? "" : "background:" + P.LEVELS[lvl].color,
      title: P.fmtDay(ds) + (lvl ? " · " + P.LEVELS[lvl].label : " · no log")
        + (log && log.time_spent ? " · " + log.time_spent : ""),
      text: o.num ? String(d0(ds).getDate()) : "",
    });
    if (!future) cell.addEventListener("click", () => dayLogModal(h, ds, log, reload));
    return cell;
  }

  function statLine(r) {
    const bits = [
      r.logged_days + "/" + r.elapsed_days + " days",
      r.rate + "%",
      r.avg_level ? "avg " + r.avg_level : null,
      r.minutes ? fmtMins(r.minutes) : null,
      r.best_streak > 1 ? "run " + r.best_streak : null,
    ].filter(Boolean);
    return el("div.ptrack-stat", { text: bits.join(" · ") });
  }

  const fmtMins = (m) => (!m ? "" : m >= 60 ? Math.floor(m / 60) + "h " + (m % 60) + "m" : m + "m");

  /* --- month view: one calendar per month, side by side with a gap -------- */
  function monthBlock(h, period, row, reload) {
    const byDate = {}; (row.entries || []).forEach((e) => { byDate[e.date] = e; });
    const start = d0(period.start), end = d0(period.end);
    const cal = el("div.ptrack-cal");
    DOW.forEach((d) => cal.appendChild(el("div.ptrack-dow", { text: d })));
    for (let i = 0; i < mondayIdx(start); i++) cal.appendChild(el("div"));
    for (let t = start.getTime(); t <= end.getTime(); t += P.DAY) {
      const ds = P.dateStr(new Date(t));
      cal.appendChild(dayCell(h, ds, byDate[ds], reload, { num: true }));
    }
    return el("div.ptrack-month", {}, [
      el("div.ptrack-plabel", { text: period.label }),
      cal,
      statLine(row),
    ]);
  }

  /* --- year view: a full-year grid (53 week columns × 7 days) ------------- */
  function yearBlock(h, period, row, reload) {
    const byDate = {}; (row.entries || []).forEach((e) => { byDate[e.date] = e; });
    const start = d0(period.start), end = d0(period.end);
    const first = new Date(start.getTime() - mondayIdx(start) * P.DAY);  // Monday on/before Jan 1
    const cols = Math.ceil(((end.getTime() - first.getTime()) / P.DAY + 1) / 7);
    const colOf = (d) => Math.floor((d.getTime() - first.getTime()) / P.DAY / 7);

    // month labels, each spanning the columns its days occupy
    const labels = el("div.ptrack-ylabels", { style: "grid-template-columns:repeat(" + cols + ",var(--yc))" });
    for (let m = 0; m < 12; m++) {
      const c = colOf(new Date(start.getFullYear(), m, 1));
      const nc = m === 11 ? cols : colOf(new Date(start.getFullYear(), m + 1, 1));
      labels.appendChild(el("div.ptrack-ylabel", {
        style: "grid-column:" + (c + 1) + " / span " + Math.max(1, nc - c), text: MON3[m] }));
    }

    // days, column-major so each column is one Mon–Sun week
    const grid = el("div.ptrack-ygrid");
    for (let c = 0; c < cols; c++) {
      for (let r = 0; r < 7; r++) {
        const d = new Date(first.getTime() + (c * 7 + r) * P.DAY);
        if (d < start || d > end) { grid.appendChild(el("div.ptrack-yblank")); continue; }
        const ds = P.dateStr(d);
        grid.appendChild(dayCell(h, ds, byDate[ds], reload, { small: true }));
      }
    }
    return el("div.ptrack-yearblock", {}, [
      el("div.ptrack-plabel", { text: period.label }),
      el("div.row", { style: "gap:6px;align-items:flex-start;flex-wrap:nowrap" }, [
        el("div.ptrack-ygutter", {}, [
          el("div.ptrack-ylabel"),   // spacer, keeps the letters level with row 1
          ...DOW.map((d, i) => el("div.ptrack-ydow", { text: i % 2 ? "" : d })),
        ]),
        el("div", {}, [labels, grid]),
      ]),
      statLine(row),
    ]);
  }

  /* --- week view: one column per week, laid out with a horizontal gap ----- */
  function weekBlock(h, period, row, reload) {
    const byDate = {}; (row.entries || []).forEach((e) => { byDate[e.date] = e; });
    const col = el("div.ptrack-wcol");
    for (let i = 0; i < 7; i++) {
      const ds = P.dateStr(new Date(d0(period.start).getTime() + i * P.DAY));
      col.appendChild(dayCell(h, ds, byDate[ds], reload));
    }
    return el("div.ptrack-week", {}, [
      el("div.ptrack-wnum", { text: period.short }),
      col,
      el("div.ptrack-wsub", { text: period.label.split("· ")[1] || "" }),
      el("div.ptrack-wcount" + (row.logged_days ? ".on" : ""), { text: row.logged_days + "/7" }),
    ]);
  }

  /* --- one habit card ----------------------------------------------------- */
  function habitCard(h, rowsFor, reload) {
    const st = (rep.summary.find((s) => s.habit_id === h.id) || {});
    const head = el("div.row", { style: "gap:8px;margin-bottom:12px" }, [
      el("span", { style: "font-size:18px", text: P.catIcon(P.HABIT_CATS, h.category) }),
      el("span", { style: "font-weight:600;font-size:15px", text: h.name }),
      st.current_streak > 0 ? el("span.pulse-streak", { text: "🔥 " + st.current_streak + " day" + (st.current_streak === 1 ? "" : "s") }) : null,
      el("span.sub", { style: "margin-left:auto", text: st.logged_days + " logged · " + st.rate + "% over this range" }),
    ]);
    // every mode lays its periods out left-to-right, oldest first, with a
    // clear gap + divider between them
    let body;
    if (mode === "month") {
      body = el("div.ptrack-strip", {}, rep.periods.map((p) => monthBlock(h, p, rowsFor[p.id], reload)));
    } else if (mode === "year") {
      body = el("div.ptrack-strip", {}, rep.periods.map((p) => yearBlock(h, p, rowsFor[p.id], reload)));
    } else {
      body = el("div.ptrack-strip", {}, [
        // weekday gutter, aligned to the day cells in every week column
        el("div.ptrack-wgutter", {}, [
          el("div.ptrack-wnum", { text: "" }),
          ...DOW.map((d) => el("div.ptrack-dowv", { text: d })),
        ]),
        ...rep.periods.map((p) => weekBlock(h, p, rowsFor[p.id], reload)),
      ]);
    }
    return el("div.pulse-card", {}, [head, body]);
  }

  /* --- report view -------------------------------------------------------- */
  function exportUrl(fmt) {
    return "/api/pulse/tracking/report/export?format=" + fmt
      + "&period=" + mode + "&periods=" + count + "&end=" + anchorDate();
  }

  function reportView() {
    const wrap = el("div");
    wrap.appendChild(el("div.pulse-card", {}, [
      el("div.spread", {}, [
        el("div", {}, [
          el("div", { style: "font-weight:600;font-size:15px", text: "Active Tracking Report" }),
          el("div.sub", { text: { month: "Monthly", week: "Weekly", year: "Yearly" }[mode]
            + " · " + rep.range.start + " → " + rep.range.end + " · generated " + rep.generated_at.slice(0, 10) }),
        ]),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm.btn-primary", { onclick: () => window.open(exportUrl("md"), "_blank"), text: "⤓ Markdown" }),
          el("button.btn-sm", { onclick: () => window.open(exportUrl("csv"), "_blank"), text: "⤓ CSV" }),
          el("button.btn-sm", { onclick: () => window.open(exportUrl("json"), "_blank"), text: "⤓ JSON" }),
        ]),
      ]),
    ]));

    // summary table
    const sum = el("table");
    sum.appendChild(el("tr", {}, ["Habit", "Logged", "Elapsed", "Rate", "Avg level", "Time", "Best run", "Streak"]
      .map((t) => el("th", { text: t }))));
    rep.summary.forEach((s) => sum.appendChild(el("tr", {}, [
      s.habit_name, s.logged_days, s.elapsed_days, s.rate + "%", s.avg_level || "—",
      fmtMins(s.minutes) || "—", s.best_streak, s.current_streak,
    ].map((v) => el("td", { style: "padding:6px 8px", text: String(v) })))));
    wrap.appendChild(el("div.pulse-card", {}, [
      el("div.ptrack-plabel", { text: "Summary" }), el("div.grid", {}, [sum]),
    ]));

    // one section per labelled period, newest first
    rep.periods.slice().reverse().forEach((p) => {
      const rows = rep.rows.filter((r) => r.period_id === p.id && r.logged_days);
      const card = el("div.pulse-card", {}, [
        el("div.spread.ptrack-plabel", {}, [
          el("span", { text: p.label }),
          el("span.sub", { text: p.start + " → " + p.end }),
        ]),
      ]);
      if (!rows.length) {
        card.appendChild(el("div.sub", { style: "font-style:italic", text: "No logs in this period." }));
      }
      rows.forEach((r) => {
        card.appendChild(el("div", { style: "margin-top:14px" }, [
          el("div.row", { style: "gap:8px" }, [
            el("span", { style: "font-weight:600", text: r.habit_name }),
            statLine(r),
          ]),
          el("div.sub", { style: "margin:4px 0 8px", text:
            "Barely " + r.levels["1"] + " · Okay " + r.levels["2"] + " · Good " + r.levels["3"] + " · Crushed it " + r.levels["4"]
            + (r.untimed_entries ? "  ·  " + r.untimed_entries + " entr" + (r.untimed_entries === 1 ? "y" : "ies") + " with unparseable time" : "") }),
        ]));
        const t = el("table");
        t.appendChild(el("tr", {}, ["Date", "Level", "Time", "What happened", "Felt", "Connections"]
          .map((x) => el("th", { text: x }))));
        r.entries.forEach((e) => t.appendChild(el("tr", {}, [
          e.date, e.level_label || "", e.time_spent || "—", e.notes || "", e.feel || "", e.connections || "",
        ].map((v) => el("td", { style: "padding:6px 8px;white-space:pre-wrap", text: String(v) })))));
        card.appendChild(el("div.grid", {}, [t]));
      });
      wrap.appendChild(card);
    });
    return wrap;
  }

  /* --- toolbar + load ----------------------------------------------------- */
  function toolbar(reload) {
    const seg = (label, val) => el("button.btn-sm" + (mode === val ? ".ptrack-on" : ""), {
      onclick: () => { if (mode === val) return; mode = val; count = COUNTS[val][1]; offset = 0; reload(); },
      text: label });
    const cnt = el("select", {}, COUNTS[mode].map((n) => el("option", { value: n, text: n + " " + mode + (n === 1 ? "" : "s") })));
    cnt.value = String(count);
    cnt.addEventListener("change", () => { count = Number(cnt.value); reload(); });

    const range = rep ? rep.periods[0].label + "  →  " + rep.periods[rep.periods.length - 1].label : "";
    return el("div.row", { style: "margin-bottom:16px;gap:8px" }, [
      el("div.row", { style: "gap:4px" }, [seg("Week", "week"), seg("Month", "month"), seg("Year", "year")]),
      el("span.sub", { text: "│" }),
      el("button.btn-sm", { title: "earlier", onclick: () => { offset += 1; reload(); }, text: "◀" }),
      el("button.btn-sm", { title: "later", onclick: () => { if (offset > 0) { offset -= 1; reload(); } }, text: "▶" }),
      offset ? el("button.btn-sm", { onclick: () => { offset = 0; reload(); }, text: "today" }) : null,
      cnt,
      el("span.sub", { style: "font-family:var(--mono);font-size:11px", text: range }),
      el("button.btn-sm" + (showReport ? ".ptrack-on" : ""), { style: "margin-left:auto",
        onclick: () => { showReport = !showReport; reload(); },
        text: showReport ? "▤ Grid" : "📄 Report" }),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.tracking = {
    id: "tracking", label: "Active Tracking", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Active Tracking" }),
        el("div.sub", { text: "Log each day — click a square. Switch between labelled weeks, months and years, step through with ◀ ▶, and build a report from any range." }),
      ])]));
      headHost = el("div"); view.appendChild(headHost);
      host = el("div"); view.appendChild(host);

      async function reload() {
        const qs = "?period=" + mode + "&periods=" + count + "&end=" + anchorDate();
        rep = await guard(() => api.pulse.trackingReport(qs));
        clear(headHost); headHost.appendChild(toolbar(reload));
        clear(host);
        if (!rep.habits.length) {
          host.appendChild(el("div.empty", { text: "No active habits. Add one in My Habits first." }));
          return;
        }
        if (showReport) { host.appendChild(reportView()); return; }
        rep.habits.forEach((h) => {
          const rowsFor = {};
          rep.rows.filter((r) => r.habit_id === h.id).forEach((r) => { rowsFor[r.period_id] = r; });
          host.appendChild(habitCard(h, rowsFor, reload));
        });
        host.appendChild(el("div.row", { style: "gap:5px;margin-top:4px;font-size:10px;color:var(--dim);align-items:center" }, [
          el("span", { text: "Less" }),
          ...P.LEVELS.map((lv) => el("div.ptrack-day", { style: "background:" + lv.color + ";cursor:default" })),
          el("span", { text: "More" }),
        ]));
      }
      reload();
    },
  };
})();

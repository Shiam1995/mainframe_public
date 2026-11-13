/* projects.js — the Project area: a GitHub-style light-blue contribution grid
   (all activity, click a square to recolour) + projects that hold uploaded files
   and linked files/repos, each with a note. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const DAY = 86400000;
  // light-blue ramp: level 0 (subtle) → 4 (bright cyan-blue = most work)
  const RAMP = ["rgba(120,170,210,.10)", "#1f5f7a", "#2b87b0", "#1aa7e0", "#2de2ff"];
  // A square's colour is TIME WORKED that day. Thresholds in minutes — a full
  // day of work saturates, so ordinary days still separate from each other.
  const MIN_STEPS = [0, 30, 90, 180, 300];
  function level(mins) {
    let lv = 0;
    for (let i = 1; i < MIN_STEPS.length; i++) if (mins >= MIN_STEPS[i]) lv = i;
    return mins > 0 ? Math.max(1, lv) : 0;
  }
  function fmtMins(m) { return window.WorkLog ? window.WorkLog.fmtMins(m) : String(m || 0) + "m"; }

  function fmtSize(b) {
    if (b == null) return "";
    if (b < 1024) return b + " B";
    if (b < 1048576) return (b / 1024).toFixed(1) + " KB";
    return (b / 1048576).toFixed(1) + " MB";
  }
  const utc = (s) => new Date(s + "T00:00:00Z");
  const toStr = (d) => d.toISOString().slice(0, 10);

  // ---------- contribution grid ----------
  // Zoom level: each cell is one day / week / month / year. Survives reload().
  let heatMode = "day";
  let heatFocus = null;   // ISO day to centre on after a re-render (null → newest)

  const MODE_LABEL = { day: "Day", week: "Week", month: "Month", year: "Year" };
  const NEXT_ZOOM = { year: "month", month: "week", week: "day" };
  // cell width per mode; day keeps the classic 12px square grid
  const CELL_W = { week: 14, month: 34, year: 62 };

  const sunday = (d) => new Date(d.getTime() - d.getUTCDay() * DAY);
  const monthStart = (d) => new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
  const yearStart = (d) => new Date(Date.UTC(d.getUTCFullYear(), 0, 1));

  // bucket a day into the current mode → the ISO date that starts its bucket
  function bucketOf(d, mode) {
    if (mode === "day") return toStr(d);
    if (mode === "week") return toStr(sunday(d));
    if (mode === "month") return toStr(monthStart(d));
    return toStr(yearStart(d));
  }

  // walk bucket starts from `from` to `to` inclusive
  function bucketRange(from, to, mode) {
    const out = [];
    let d = mode === "day" ? from : utc(bucketOf(from, mode));
    while (d.getTime() <= to.getTime()) {
      out.push(new Date(d));
      if (mode === "day") d = new Date(d.getTime() + DAY);
      else if (mode === "week") d = new Date(d.getTime() + 7 * DAY);
      else if (mode === "month") d = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1));
      else d = new Date(Date.UTC(d.getUTCFullYear() + 1, 0, 1));
    }
    return out;
  }

  function bucketLabel(d, mode) {
    if (mode === "year") return String(d.getUTCFullYear());
    if (mode === "month") return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" });
    if (mode === "week") return "w/c " + d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
    return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  }

  // roll the per-day work summaries up into one bucket
  function bucketAgg(days, start, mode) {
    const end = mode === "day" ? start
      : mode === "week" ? new Date(start.getTime() + 6 * DAY)
        : mode === "month" ? new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0))
          : new Date(Date.UTC(start.getUTCFullYear(), 11, 31));
    const agg = { mins: 0, sessions: 0, pushed: false, contributed: false };
    for (let d = new Date(start); d.getTime() <= end.getTime(); d = new Date(d.getTime() + DAY)) {
      const s = days[toStr(d)];
      if (!s) continue;
      agg.mins += s.mins || 0;
      agg.sessions += s.sessions || 0;
      if (s.pushed) agg.pushed = true;
      if (s.contributed) agg.contributed = true;
    }
    return agg;
  }

  function buildHeatmap(data, reload) {
    const wrap = el("div.card");
    const today = utc(data.today);
    // scrollable range: first recorded day (or a year back, whichever is earlier)
    const earliest = data.first ? utc(data.first) : today;
    const yearBack = new Date(today.getTime() - 52 * 7 * DAY);
    const from = earliest.getTime() < yearBack.getTime() ? earliest : yearBack;
    const overrides = { ...data.overrides };
    const counts = data.counts || {};      // raw app mutations — tooltip only now
    const days = data.days || {};          // work sessions — what actually colours a square

    // scroll container is built up front so the toolbar can drive it
    const scroller = el("div.heat-scroll");
    const inner = el("div.heat-inner");
    scroller.appendChild(inner);
    let dragged = false;   // set while panning, so a drag doesn't fire a cell click
    function pan(dir) { scroller.scrollBy({ left: dir * Math.max(160, scroller.clientWidth * 0.8), behavior: "smooth" }); }

    wrap.appendChild(el("div.spread", {}, [
      el("h3", { text: "Contributions" }),
      el("span.sub", { text: heatMode === "day"
        ? "darker = more time worked · outline = tracked project · ★ = pushed · click to recolour, right-click to reset"
        : "each square is one " + heatMode + " · click to zoom in · scroll or drag to pan" }),
    ]));

    // --- zoom toggle + pan controls ---
    const seg = (val) => el("button.btn-sm" + (heatMode === val ? ".heat-on" : ""), {
      onclick: () => { if (heatMode === val) return; heatMode = val; heatFocus = null; reload(); },
      text: MODE_LABEL[val] });
    wrap.appendChild(el("div.row", { style: "gap:8px;margin:10px 0" }, [
      el("div.row", { style: "gap:4px" }, [seg("day"), seg("week"), seg("month"), seg("year")]),
      el("span.sub", { text: "│" }),
      el("button.btn-sm", { title: "earlier", onclick: () => pan(-1), text: "◀" }),
      el("button.btn-sm", { title: "later", onclick: () => pan(1), text: "▶" }),
      el("button.btn-sm", { onclick: () => { scroller.scrollLeft = scroller.scrollWidth; }, text: "today" }),
    ]));

    // hidden color input reused for editing (day mode only)
    const picker = el("input", { type: "color", style: "position:absolute;left:-9999px" });
    wrap.appendChild(picker);
    let editing = null;

    let focusCell = null;

    if (heatMode === "day") {
      // classic 7-row × week-column grid
      const monthRow = el("div.heat-months");
      const grid = el("div.heat-grid");
      const first = sunday(from);
      const cols = Math.ceil((today.getTime() - first.getTime()) / (7 * DAY)) + 1;
      let lastMonth = -1;

      function paint(cell, date) {
        const ov = overrides[date];
        const s = days[date] || {};
        const mins = s.mins || 0;
        const events = counts[date] || 0;
        cell.style.background = ov || RAMP[level(mins)];
        // outline = worked on a project flagged "add to the contributions"
        cell.classList.toggle("heat-contrib", !!s.contributed);
        // ★ = something was pushed that day
        cell.classList.toggle("heat-push", !!s.pushed);
        cell.textContent = s.pushed ? "★" : "";
        cell.title = bucketLabel(utc(date), "day")
          + " · " + fmtMins(mins) + " worked"
          + (s.sessions ? " · " + s.sessions + " session" + (s.sessions === 1 ? "" : "s") : "")
          + (s.pushed ? " · pushed" : "")
          + (s.contributed ? " · tracked project" : "")
          + (events ? " · " + events + " app event" + (events === 1 ? "" : "s") : "")
          + (ov ? " (custom colour)" : "");
      }

      for (let c = 0; c < cols; c++) {
        const col = el("div.heat-col");
        const col0 = new Date(first.getTime() + c * 7 * DAY);
        const m = col0.getUTCMonth();
        if (m !== lastMonth) {
          monthRow.appendChild(el("span.heat-month", { style: "left:" + (c * 15) + "px",
            text: col0.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" }) }));
          lastMonth = m;
        }
        for (let r = 0; r < 7; r++) {
          const d = new Date(first.getTime() + (c * 7 + r) * DAY);
          if (d.getTime() > today.getTime() || d.getTime() < from.getTime()) { col.appendChild(el("div.heat-cell.heat-blank")); continue; }
          const date = toStr(d);
          const cell = el("div.heat-cell");
          paint(cell, date);
          if (heatFocus && date === heatFocus) focusCell = cell;
          cell.addEventListener("click", () => {
            if (dragged) return;
            editing = { cell, date };
            picker.value = overrides[date] || "#2de2ff";
            picker.click();
          });
          cell.addEventListener("contextmenu", (e) => {
            e.preventDefault();
            delete overrides[date]; paint(cell, date);
            guard(() => api.heatmap.setCell({ date, color: "" }));
          });
          col.appendChild(cell);
        }
        grid.appendChild(col);
      }
      picker.addEventListener("input", () => {
        if (!editing) return;
        overrides[editing.date] = picker.value; paint(editing.cell, editing.date);
        guard(() => api.heatmap.setCell({ date: editing.date, color: picker.value }));
      });
      inner.appendChild(el("div", { style: "position:relative;height:14px;width:" + (cols * 15) + "px" }, [monthRow]));
      inner.appendChild(grid);
    } else {
      // week / month / year → a single strip of wider cells, scaled to the busiest bucket
      const w = CELL_W[heatMode];
      const starts = bucketRange(from, today, heatMode);
      const aggs = starts.map((d) => bucketAgg(days, d, heatMode));
      const max = Math.max(1, ...aggs.map((a) => a.mins));
      const pitch = w + 3;                       // cell width + flex gap
      const strip = el("div.heat-strip");
      // labels are absolutely positioned (same trick as the day view's month row)
      // so a narrow cell can't squash its neighbour's text
      const labels = el("div.heat-strip-labels", { style: "width:" + (starts.length * pitch) + "px" });
      let lastMonth = -1;
      starts.forEach((d, i) => {
        const a = aggs[i];
        const lv = a.mins === 0 ? 0 : Math.min(4, 1 + Math.floor((a.mins / max) * 3.999));
        const cell = el("div.heat-bucket", {
          style: "width:" + w + "px;background:" + RAMP[lv],
          title: bucketLabel(d, heatMode) + " · " + fmtMins(a.mins) + " worked"
            + (a.sessions ? " · " + a.sessions + " session" + (a.sessions === 1 ? "" : "s") : "")
            + (a.pushed ? " · pushed" : ""),
          // only the wider month/year cells have room for the total
          text: a.mins && heatMode !== "week" ? fmtMins(a.mins) : "",
        });
        if (a.contributed) cell.classList.add("heat-contrib");
        if (a.pushed) cell.classList.add("heat-push-mark");
        if (heatFocus && toStr(d) === bucketOf(utc(heatFocus), heatMode)) focusCell = cell;
        cell.addEventListener("click", () => {
          if (dragged) return;
          heatFocus = toStr(d); heatMode = NEXT_ZOOM[heatMode]; reload();
        });
        strip.appendChild(cell);

        // year → every cell; month → every cell; week → only when the month turns over
        const m = d.getUTCMonth();
        const tick = heatMode === "year" ? String(d.getUTCFullYear())
          : (heatMode === "month" || m !== lastMonth)
            ? d.toLocaleDateString("en-GB", m === 0
              ? { month: "short", year: "2-digit", timeZone: "UTC" }
              : { month: "short", timeZone: "UTC" })
            : null;
        lastMonth = m;
        if (tick) labels.appendChild(el("span.heat-month", { style: "left:" + (i * pitch) + "px", text: tick }));
      });
      inner.appendChild(strip);
      inner.appendChild(labels);
    }

    // --- panning: wheel scrolls sideways, drag pans ---
    scroller.addEventListener("wheel", (e) => {
      if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;  // let native handle it
      if (scroller.scrollWidth <= scroller.clientWidth) return;
      e.preventDefault();
      scroller.scrollLeft += e.deltaY;
    }, { passive: false });
    let down = null;
    scroller.addEventListener("pointerdown", (e) => { down = { x: e.clientX, left: scroller.scrollLeft }; dragged = false; });
    scroller.addEventListener("pointermove", (e) => {
      if (!down) return;
      const dx = e.clientX - down.x;
      if (Math.abs(dx) > 4) { dragged = true; scroller.classList.add("heat-dragging"); }
      if (dragged) scroller.scrollLeft = down.left - dx;
    });
    const endDrag = () => { down = null; scroller.classList.remove("heat-dragging"); setTimeout(() => { dragged = false; }, 0); };
    scroller.addEventListener("pointerup", endDrag);
    scroller.addEventListener("pointerleave", endDrag);

    wrap.appendChild(scroller);
    wrap.appendChild(el("div.row", { style: "gap:5px;margin-top:8px;font-size:10px;color:var(--dim);justify-content:flex-end;flex-wrap:wrap" }, [
      el("span.heat-cell.heat-contrib", { style: "background:" + RAMP[2] }),
      el("span", { style: "margin-right:10px", text: "tracked project" }),
      el("span.heat-cell.heat-push", { style: "background:" + RAMP[3], text: "★" }),
      el("span", { style: "margin-right:10px", text: "pushed" }),
      el("span", { text: "less time" }),
      ...RAMP.map((c) => el("span.heat-cell", { style: "background:" + c })),
      el("span", { text: "more time" }),
    ]));

    // start at today, or centre the period we just zoomed into
    requestAnimationFrame(() => {
      if (focusCell) scroller.scrollLeft = focusCell.offsetLeft - scroller.clientWidth / 2 + focusCell.offsetWidth / 2;
      else scroller.scrollLeft = scroller.scrollWidth;
      heatFocus = null;
    });
    return wrap;
  }

  // ---------- project cards ----------
  function fileRow(p, f, reload) {
    if (f.kind === "upload") {
      return el("div.proj-file", {}, [
        el("span", { text: "⬆ " + f.name }),
        el("span.sub", { text: fmtSize(f.size) }),
        el("a.btn-sm", { href: api.projects.downloadUrl(p.id, f.id), style: "text-decoration:none", text: "download" }),
        el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.projects.delFile(p.id, f.id); reload(); }), text: "×" }),
      ]);
    }
    const target = f.url || f.path || "";
    const link = f.url ? el("a", { href: f.url, target: "_blank", rel: "noopener noreferrer", style: "color:var(--blue)", text: target }) : el("span.mono", { style: "font-size:11px;color:var(--dim)", text: target });
    return el("div.proj-file", {}, [
      el("span", {}, [document.createTextNode("🔗 " + f.name + "  "), link]),
      f.note ? el("span.sub", { text: f.note }) : el("span"),
      el("span"),
      el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.projects.delFile(p.id, f.id); reload(); }), text: "×" }),
    ]);
  }

  // ---------- master view: every word written about a project, plus totals ----
  function masterPanel(p) {
    const box = el("div.proj-master");
    box.appendChild(el("div.sub", { text: "loading…" }));
    guard(async () => {
      const m = await api.projects.master(p.id);
      clear(box);
      const stat = (v, l, c) => el("div.prog-box", {}, [
        el("div.prog-val", { style: "color:" + c, text: v }), el("div.prog-label", { text: l }),
      ]);
      box.appendChild(el("div.prog-grid", {}, [
        stat(fmtMins(m.total_mins), "hours spent", "#2de2ff"),
        stat(String(m.session_count), "sessions", "#7FA8C8"),
        stat(String(m.distinct_days), "days", "#7FA8C8"),
        stat(String(m.push_count), "pushes", "#DE7BA4"),
        stat(fmtMins(m.focus_mins.active), "active", "#00F5D4"),
        stat(fmtMins(m.focus_mins.passive), "passive", "#D4A017"),
        stat(fmtMins(m.distraction_mins), "distracted", "#FF4757"),
      ]));
      box.appendChild(el("div.sub", { style: "margin:10px 0 4px", text:
        (m.first_worked ? "First worked " + m.first_worked + " · last " + m.last_worked : "Not worked on yet")
        + " · " + m.file_count + " file" + (m.file_count === 1 ? "" : "s") }));
      if (!m.blocks.length) {
        box.appendChild(el("div.empty", { text: "Nothing written yet — the note, file notes and session text all land here." }));
        return;
      }
      const doc = el("div.proj-doc");
      m.blocks.forEach((b) => doc.appendChild(el("div.proj-block", {}, [
        el("div.proj-block-src", { text: b.source + (b.mins ? " · " + fmtMins(b.mins) : "") }),
        el("div", { style: "white-space:pre-wrap", text: b.text }),
      ])));
      box.appendChild(doc);
    });
    return box;
  }

  /* --- Documents written for this project ------------------------------
     Docs bound with (:Document)-[:FOR]->(:Project), and the work done inside
     each. Those hours reached the project through the same sessions the totals
     above already count: this block breaks them out, it never adds to them. */
  function docsBlock(p) {
    const host = el("div.doc-block", { style: "margin-top:12px" });
    const body = el("div");

    const draw = (rows) => {
      clear(body);
      if (!rows.length) {
        body.appendChild(el("div.sub", { style: "margin-top:6px",
          text: "No documents for this project yet — write one and its hours land here." }));
        return;
      }
      const table = el("table.doc-table", {}, [
        el("tr", {}, ["doc", "hours", "sessions", "last", ""].map((h) =>
          el("th", { text: h }))),
      ]);
      rows.forEach((d) => table.appendChild(el("tr", {}, [
        el("td", { text: d.title || "Untitled" }),
        el("td.mono", { text: fmtMins(d.mins) }),
        el("td.mono", { text: String(d.session_count || 0) }),
        el("td.sub", { text: d.last_worked || "not worked in yet" }),
        el("td", { style: "text-align:right" }, [
          el("button.btn-sm", { text: "open",
            onclick: () => window.Docs && window.Docs.open(d.id) }),
        ]),
      ])));
      body.appendChild(table);
      body.appendChild(el("div.sub", { style: "margin-top:8px;font-size:10.5px",
        text: "Hours here are the sessions pushed from inside a document. They are "
            + "already in the " + fmtMins(p.total_mins || 0) + " above, not on top of it." }));
    };

    host.appendChild(el("div.spread", {}, [
      el("span.doc-block-h", { text: "Documents" }),
      el("button.btn-sm", {
        title: "start a document already bound to this project",
        text: "+ new doc for this project",
        onclick: () => guard(async () => {
          const d = await api.docs.create({ title: "Untitled", format: "markdown", content: "" });
          await api.docs.setProject(d.id, p.id);
          if (window.Docs) window.Docs.open(d.id);
        }),
      }),
    ]));
    host.appendChild(body);
    body.appendChild(el("div.sub", { style: "margin-top:6px", text: "loading…" }));
    guard(async () => draw(await api.projects.docs(p.id)));
    return host;
  }

  let allProjects = [];

  /* Ideas given to this project, the goals raised off the back of them, the
     projects underneath, and the reasons written on the project itself. */
  function chainSections(p, reload) {
    const host = el("div.pj-chain");
    const ideasHost = el("div.card.pj-sec");
    const goalsHost = el("div.card.pj-sec");
    const kidsHost = el("div.card.pj-sec");
    const whyHost = el("div.card.pj-sec");
    host.appendChild(ideasHost);
    host.appendChild(goalsHost);
    host.appendChild(kidsHost);
    host.appendChild(whyHost);

    // ticked ideas become the sources of the next goal raised
    const picked = new Set();

    function drawIdeas(ideas) {
      clear(ideasHost);
      ideasHost.appendChild(el("div.spread", {}, [
        el("h4.pj-sech", { text: "Ideas given to this" }),
        el("span.ph-meta", { text: ideas.length ? ideas.length + " in" : "" }),
      ]));
      if (!ideas.length) {
        ideasHost.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
          text: "nothing handed here yet. give an idea to this project from the Ideas tab "
              + "and it arrives with the reason you gave." }));
        return;
      }
      // Same column design as the Ideas table, minus the columns that only
      // make sense while an idea is still loose.
      const t = el("table.pj-given");
      t.appendChild(el("tr", {}, [
        el("th", { style: "width:1%" }), el("th", { text: "idea" }),
        el("th", { text: "kind" }), el("th", { text: "given" }), el("th", { text: "why" }),
      ]));
      ideas.forEach((i) => {
        const cb = el("input", { type: "checkbox", title: "tick to use as a source when raising a goal" });
        cb.addEventListener("change", () => { cb.checked ? picked.add(i.id) : picked.delete(i.id); });
        t.appendChild(el("tr", {}, [
          el("td", {}, [cb]),
          el("td", { text: i.title || "(untitled)" }),
          el("td", {}, [window.IdeaKinds ? window.IdeaKinds.chip(i.category) : el("span")]),
          el("td.ph-meta", { text: i.given_on || "" }),
          el("td.pj-why", { text: i.why || "no reason written" }),
        ]));
      });
      ideasHost.appendChild(t);
    }

    function drawGoals(goals) {
      clear(goalsHost);
      goalsHost.appendChild(el("div.spread", {}, [
        el("h4.pj-sech", { text: "Goals raised from this" }),
        el("button.btn-sm.btn-primary", { text: "+ raise to goal",
          onclick: () => openRaise(p, picked, reload) }),
      ]));
      if (!goals.length) {
        goalsHost.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
          text: "nothing committed to yet. raising a goal here is the only way one is made "
              + "anywhere, so this is where a project turns into work." }));
        return;
      }
      goals.forEach((g) => {
        const claims = (g.claims || []).map((c) =>
          el("span.pill.pj-claim", { title: c.hours ? c.hours + "h claimed on " + c.date : c.date,
            text: "phase " + String(c.number).padStart(2, "0") + (c.hours ? " · " + c.hours + "h" : "") }));
        goalsHost.appendChild(el("div.pj-goal" + (g.status === "done" ? ".done" : ""), {}, [
          el("div.spread", {}, [
            el("span", { text: g.text }),
            el("span.ph-meta", { text: g.meta }),
          ]),
          claims.length
            ? el("div.row", { style: "gap:4px;margin-top:4px" }, claims)
            : el("div.ph-meta", { style: "margin-top:4px", text: "not claimed by a phase yet" }),
          (g.ideas || []).length
            ? el("div.ph-meta", { style: "margin-top:3px",
                text: "from: " + g.ideas.map((i) => i.title).join(", ") })
            : null,
        ]));
      });
    }

    function drawKids(kids) {
      clear(kidsHost);
      kidsHost.appendChild(el("div.spread", {}, [
        el("h4.pj-sech", { text: "Under this project" }),
        el("span.ph-meta", { text: p.parent_name ? "sits under " + p.parent_name : "" }),
      ]));
      if (!kids.length) {
        kidsHost.appendChild(el("div.ph-meta", { style: "display:block",
          text: "nothing under it. set a parent on another project to nest it here." }));
      } else {
        kids.forEach((c) => kidsHost.appendChild(el("div.pj-kid", {}, [
          el("span", { text: c.name }),
          el("span.ph-meta", { text: fmtMins(c.mins || 0) + " · " + (c.sessions || 0) + " sessions" }),
        ])));
      }
      // where this one sits, changed in place
      const sel = el("select.mform-input", { style: "margin-top:8px" });
      sel.appendChild(el("option", { value: "", text: "— top level —" }));
      (allProjects || []).forEach((o) => {
        if (o.id === p.id) return;
        const opt = el("option", { value: o.id, text: o.name });
        if (o.id === p.parent_id) opt.selected = true;
        sel.appendChild(opt);
      });
      sel.addEventListener("change", () => guard(async () => {
        await api.projects.update(p.id, { parent_id: sel.value });
        toast(sel.value ? "nested" : "moved to the top level");
        reload();
      }));
      kidsHost.appendChild(el("label.md-field", {}, [
        el("span.sub", { text: "sits under" }), sel]));
    }

    clear(whyHost);
    whyHost.appendChild(el("h4.pj-sech", { text: "Why this project" }));
    whyHost.appendChild(window.Notes.panel({ target_id: p.id }, {
      kind: "why",
      empty: "no reason written down yet. what is this for, and what would make it done?",
      placeholder: "why this project exists",
    }));

    guard(async () => {
      const [ideas, goals, kids] = await Promise.all([
        api.get("/api/projects/" + p.id + "/given"),
        api.get("/api/projects/" + p.id + "/goals"),
        api.get("/api/projects/" + p.id + "/children"),
      ]);
      drawIdeas(ideas); drawGoals(goals); drawKids(kids);
    });
    return host;
  }

  /* "raise to goal" — the one place in the Mainframe a goal is created. */
  function openRaise(p, picked, reload) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const text = el("input", { placeholder: "what will be true when this is done" });
    const est = el("input", { type: "number", step: "0.5", min: "0", placeholder: "hours" });
    const due = el("input", { type: "date" });
    const horizon = el("select", {}, ["week", "month", "day"].map((h) =>
      el("option", { value: h, text: h })));
    horizon.value = "month";
    const why = el("input", { placeholder: "why this, and why now" });

    const sources = el("div.ph-meta", { text: picked.size
      ? picked.size + (picked.size === 1 ? " idea ticked above will be recorded as its source"
                                         : " ideas ticked above will be recorded as its sources")
      : "no ideas ticked above. tick some in the table to record what this came out of." });

    const save = el("button.btn-primary", { text: "raise it" });
    save.addEventListener("click", () => guard(async () => {
      if (!text.value.trim()) return toast("say what the goal is", true);
      await api.post("/api/projects/" + p.id + "/goals", {
        text: text.value.trim(),
        estimate_h: parseFloat(est.value) || 0,
        due: due.value, horizon: horizon.value,
        why: why.value.trim(),
        idea_ids: [...picked],
      });
      picked.clear();
      close();
      toast("goal raised");
      reload();
    }));

    overlay.appendChild(el("div.modal", {}, [
      el("div.ph-mhead", {}, [
        el("h2", { text: "Raise a goal" }),
        el("div.sub", { text: "from " + p.name + ". this is the only place a goal is made, "
          + "so it always has somewhere it came from." }),
      ]),
      el("div", { style: "margin-bottom:12px" }, [
        el("div.mform-label", { text: "goal" }), text]),
      el("div.mform-row", {}, [
        el("div", {}, [el("div.mform-label", { text: "estimate, hours" }), est]),
        el("div", {}, [el("div.mform-label", { text: "due" }), due]),
      ]),
      el("div.mform-row", {}, [
        el("div", {}, [el("div.mform-label", { text: "horizon" }), horizon]),
        el("div", {}, [el("div.mform-label", { text: "sources" }), sources]),
      ]),
      el("div", { style: "margin-bottom:12px" }, [
        el("div.mform-label", { text: "why" }), why]),
      el("div.ph-mfoot", {}, [
        el("button", { text: "cancel", onclick: close }),
        save,
      ]),
    ]));
    document.body.appendChild(overlay);
    text.focus();
  }

  function projectCard(p, reload, opts) {
    const inWorkspace = opts && opts.workspace;
    const card = el("div.card", { style: "margin-bottom:12px" });

    // editable title — click the name to rename
    const title = el("input.proj-title", { value: p.name });
    title.addEventListener("change", () => guard(async () => {
      if (!title.value.trim()) { title.value = p.name; return toast("name can't be empty", true); }
      await api.projects.update(p.id, { name: title.value.trim() }); toast("renamed"); reload();
    }));

    // "add to the contributions" — drives the outline on the day square
    const contrib = el("input", { type: "checkbox" });
    if (p.contributes !== false) contrib.setAttribute("checked", "");
    contrib.addEventListener("change", () => guard(async () => {
      await api.projects.update(p.id, { contributes: contrib.checked });
      toast(contrib.checked ? "counts toward contributions" : "excluded from contributions");
      reload();
    }));

    card.appendChild(el("div.spread", {}, [
      title,
      el("div.row", { style: "gap:6px" }, [
        // Repo-style "open": dive into this project's workspace. Hidden when
        // the card is already the workspace — it would open itself.
        inWorkspace ? null : el("button.btn-sm", {
          title: "open this project's workspace",
          onclick: () => window.ProjectArea && window.ProjectArea.open(p.id),
          text: "⤢ open",
        }),
        el("label.wl-check", { title: "outline this day's square in the contribution grid" }, [
          contrib, el("span", { text: " add to contributions" }),
        ]),
        // one click records the push; add detail afterwards from sessions or
        // the Database tab (a modal prompt here would block the whole page)
        el("button.btn-sm.proj-push", {
          title: "record a push — puts a ★ on today's square",
          onclick: () => guard(async () => {
            await api.projects.push(p.id, { note: "pushed" });
            toast("pushed ★ — add detail in sessions"); reload();
          }),
          text: "★ pushed",
        }),
        // Log a learning entry against this project without leaving it — same
        // modal, same fields, so it groups with everything else by kind.
        el("button.btn-sm", { title: "log a learning opportunity on this project",
          onclick: () => window.LearningPush && window.LearningPush({
            kind: "", module: "mainframe",
            what: "on “" + p.name + "”: ",
          }), text: "↗ learning" }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete project “" + p.name + "” and its files?", async () => {
          await api.projects.del(p.id);
          if (window.RefPicker) window.RefPicker.invalidate();
          reload();
        }), text: "delete" }),
      ]),
    ]));

    // headline totals — hours spent, at a glance
    card.appendChild(el("div.row", { style: "gap:10px;margin-top:6px;font-size:11px;color:var(--dim);flex-wrap:wrap" }, [
      el("span.pill", { text: "⏱ " + fmtMins(p.total_mins || 0) }),
      el("span.pill", { text: (p.sessions || []).length + " sessions" }),
      p.pass_count ? el("span.pill", { text: "▣ " + p.pass_count + " instance" + (p.pass_count === 1 ? "" : "s") }) : null,
      p.push_count ? el("span.pill", { style: "color:#DE7BA4", text: "★ " + p.push_count + " pushes" }) : null,
      p.last_worked ? el("span.sub", { text: "last worked " + p.last_worked }) : el("span.sub", { text: "not started" }),
      // What this project is about elsewhere in Mainframe. The title is
      // resolved live, so renaming the target shows up here without a sync.
      window.RefPicker ? window.RefPicker.chip(p, { small: true }) : null,
    ]));

    /* ================= what was handed to it, and what it took on =========
       The order is the chain: ideas came in, goals went out, projects sit
       under it. Each section loads itself so the card paints immediately and
       fills in, rather than waiting on four reads to show anything. */
    card.appendChild(chainSections(p, reload));

    /* --- the referenced id: what this project is about ---
       The same pair a Repository entry carries. It saves on change rather than
       behind a button: picking one is a single click, and a save step is how
       it ends up never being set. */
    if (window.RefPicker) {
      card.appendChild(window.RefPicker.editor(p, (patch) => guard(async () => {
        await api.projects.update(p.id, patch);
        toast(patch.link_id ? "reference set" : "reference cleared");
        reload();
      }), { label: "about" }).node);
    }

    // notes — a row per thought, because a project note grows for months and
    // one blob of it is something nothing can count or carry anywhere
    card.appendChild(window.RowBox({ label: "notes", noun: "note",
      placeholder: "note about this project…", parentId: p.id }).node);

    // --- work sessions: log a new visit, see every past one ---
    const sessHost = el("div", { style: "margin-top:10px" });
    const sessBody = el("div");
    let sessOpen = false;
    const toggleSess = el("button.btn-sm", {
      onclick: () => { sessOpen = !sessOpen; drawSessions(); },
      text: "▸ sessions (" + (p.sessions || []).length + ")",
    });
    function drawSessions() {
      clear(sessBody);
      toggleSess.textContent = (sessOpen ? "▾" : "▸") + " sessions (" + (p.sessions || []).length + ")";
      if (!sessOpen) return;
      const list = p.sessions || [];
      if (!list.length) sessBody.appendChild(el("div.sub", { style: "margin-top:6px", text: "No sessions yet — log one above." }));
      list.forEach((s) => sessBody.appendChild(el("div.proj-sess", {}, [
        el("span.mono", { style: "font-size:11px", text: s.date + (s.start ? " " + s.start + (s.end ? "–" + s.end : "") : "") }),
        el("span.pill", { text: fmtMins(s.mins) }),
        el("span", { text: (s.pushed ? "★ " : "") + (s.what || s.notes || "—") }),
        el("span.sub", { style: "font-size:10px", text: s.focus && s.focus !== "none" ? s.focus : "" }),
        el("button.btn-sm.btn-danger", {
          onclick: () => guard(async () => { await api.work.del(s.id); reload(); }), text: "×",
        }),
      ])));
    }
    const addHost = el("div");
    sessHost.appendChild(el("div.row", { style: "gap:6px" }, [
      window.WorkLog.button(
        { mountInto: addHost, ref_kind: "project", ref_id: p.id, ref_title: p.name, lockRef: true },
        reload, "+ log time",
      ),
      toggleSess,
    ]));
    sessHost.appendChild(addHost);
    sessHost.appendChild(sessBody);
    card.appendChild(sessHost);

    // What the project still has to find out, and what it is resting on.
    if (window.QABoxes) card.appendChild(window.QABoxes(p.id, "project"));
    drawSessions();

    // --- master: one document of everything written about this project ---
    const masterHost = el("div");
    let masterOpen = false;
    const masterBtn = el("button.btn-sm", {
      style: "margin-top:8px",
      onclick: () => {
        masterOpen = !masterOpen;
        clear(masterHost);
        masterBtn.textContent = (masterOpen ? "▾" : "▸") + " master";
        if (masterOpen) masterHost.appendChild(masterPanel(p));
      },
      text: "▸ master",
    });
    card.appendChild(masterBtn);
    card.appendChild(masterHost);

    card.appendChild(docsBlock(p));

    window.Images.mount(card, { module: "projects", contextId: p.id, surface: "project", title: "Images" });

    // files
    const list = el("div", { style: "margin-top:10px" });
    (p.files || []).forEach((f) => list.appendChild(fileRow(p, f, reload)));
    if (!(p.files || []).length) list.appendChild(el("div.sub", { text: "No files yet — upload or link one below." }));
    card.appendChild(list);

    // upload + add-link
    const fileIn = el("input", { type: "file" });
    fileIn.addEventListener("change", () => {
      if (!fileIn.files.length) return;
      const form = new FormData(); form.append("file", fileIn.files[0]);
      guard(async () => { await api.projects.uploadFile(p.id, form); toast("uploaded"); reload(); });
    });
    const lname = el("input", { placeholder: "name", style: "width:120px" });
    const ltarget = el("input", { placeholder: "url or /path/to/file", style: "flex:1;min-width:160px" });
    const lnote = el("input", { placeholder: "note", style: "width:120px" });
    card.appendChild(el("div", { style: "margin-top:12px;border-top:1px solid var(--border);padding-top:10px" }, [
      el("div.row", {}, [el("span.sub", { text: "upload:" }), fileIn]),
      el("div.row", { style: "margin-top:8px" }, [
        el("span.sub", { text: "link:" }), lname, ltarget, lnote,
        el("button.btn-sm", { onclick: () => guard(async () => {
          if (!lname.value.trim() || !ltarget.value.trim()) return toast("name + url/path needed", true);
          const isUrl = /^https?:\/\//i.test(ltarget.value.trim());
          await api.projects.addLink(p.id, { name: lname.value.trim(), url: isUrl ? ltarget.value.trim() : null, path: isUrl ? null : ltarget.value.trim(), note: lnote.value.trim() });
          lname.value = ltarget.value = lnote.value = ""; reload();
        }), text: "+ link" }),
      ]),
    ]));
    return card;
  }

  /* ---- starting a project, from the top -------------------------------
     Creating one used to be possible in exactly one place: an input row on the
     Projects sub-tab, below a year of contribution squares. So starting a
     project meant leaving whatever sub-view you were on and scrolling past the
     grid to find it. The button lives in the view head instead, where it is
     reachable from Overview, Instances, References and the map alike — and the
     project you just made becomes the selected one, so you land inside it
     rather than having to go and find it in the list. */
  function newProjectModal(onDone) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const name = el("input.mform-input", { placeholder: "what are you building?" });
    // No project yet: the box holds its rows until create returns the id.
    const notes = window.RowBox({ label: "notes", noun: "note",
      placeholder: "what it's for — a sentence is plenty, and you can change it later" });
    // The same reference a project carries everywhere else: point it at the
    // paper, decomposition node, idea or other project it comes out of, at the
    // moment you know it, rather than having to come back and set it.
    // label: null — the field around it already says "About", and the picker
    // repeating it reads as a stutter.
    const ref = window.RefPicker ? window.RefPicker.editor(null, () => {}, { label: null }) : null;

    const fld = (label, node) => el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);

    const create = () => {
      if (!name.value.trim()) return toast("name the project", true);
      guard(async () => {
        const body = { name: name.value.trim() };
        const r = ref ? ref.get() : {};
        if (r.link_kind && r.link_id) { body.link_kind = r.link_kind; body.link_id = r.link_id; }
        const made = await api.projects.create(body);
        await notes.commit(made.id);
        // A project that didn't exist a second ago has to be selectable and
        // referenceable straight away — both caches are lists, not live reads.
        if (window.RefPicker) window.RefPicker.invalidate();
        if (window.ProjectPicker) {
          await window.ProjectPicker.load(true);
          window.ProjectPicker.id = made.id;
        }
        toast("created " + made.name);
        close();
        onDone();
      });
    };

    const card = el("div.modal", {}, [
      el("div.modal-title", { text: "New project" }),
      el("div.sub", { style: "margin:-8px 0 14px;line-height:1.45",
        text: "A name is all that's required. It becomes the project you're "
            + "looking at, so the next thing you do lands in it." }),
      fld("Name", name),
      el("div.mform-full", {}, [notes.node]),
      ref ? fld("About", ref.node) : null,
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "Create project", onclick: create }),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    name.focus();
    overlay.addEventListener("keydown", (e) => {
      // app.js sends Escape home unless a modal is on screen — it would already
      // be gone by the time the event bubbled that far, so stop it here.
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") create();
    });
  }

  window.Views = window.Views || {};
  /* The Projects tab is a sub-shell, the same shape as Fitness and Nutrition:
     a secondary bar of sub-views registered on window.PROJ_TABS. This file owns
     the first one — the project list, files and contribution grid — and
     project-{overview,instances,ideas}.js push the rest. */
  async function renderProjectList(viewEl) {
      const host = el("div"); viewEl.appendChild(host);

      async function reload() {
        // days=0 → all history, so the week/month/year zooms can scroll past one year
        const [heat, projects] = await guard(() => Promise.all([api.heatmap.get(0), api.projects.list()]));
        // Held for the "sits under" picker, which needs every project rather
        // than the filtered view it is being drawn inside.
        allProjects = projects;
        // The picker caches the list; this view is where it changes.
        if (window.ProjectPicker) await window.ProjectPicker.load(true);
        clear(host);
        host.appendChild(buildHeatmap(heat, reload));

        // create project
        const nameIn = el("input", { placeholder: "new project name", style: "flex:1;min-width:160px" });
        const noteIn = el("input", { placeholder: "note (optional)", style: "flex:1;min-width:160px" });
        host.appendChild(el("div.row", { style: "margin:16px 0 12px" }, [
          nameIn, noteIn,
          el("button.btn-primary", { onclick: () => guard(async () => {
            if (!nameIn.value.trim()) return toast("name the project", true);
            const made = await api.projects.create({ name: nameIn.value.trim() });
            // The note is a row on the project now, not a property of it.
            if (noteIn.value.trim()) await api.post("/api/rows", { text: noteIn.value.trim(), kind: "note", parent_id: made.id });
            // A project that didn't exist a second ago has to be offerable as a
            // reference target straight away.
            if (window.RefPicker) window.RefPicker.invalidate();
            // Same landing as "+ project" at the top: the one you just made is
            // the one you're looking at, so the two entry points don't leave
            // you in different places.
            if (window.ProjectPicker) {
              await window.ProjectPicker.load(true);
              window.ProjectPicker.id = made.id;
            }
            nameIn.value = noteIn.value = ""; reload();
          }), text: "+ project" }),
        ]));

        if (!projects.length) {
          host.appendChild(el("div.empty", { text: "No projects yet. Create one above." }));
          return;
        }
        /* Search the cards. Filtering repaints only the list below it, so the
           box keeps focus while you type. */
        const search = el("input.pp-search", { type: "search", autocomplete: "off",
          placeholder: "search projects by name or note…", style: "margin-bottom:12px" });
        const list = el("div");
        // The notes are + rows now, not p.note: read them all once so the
        // search still finds a project by what you wrote on it.
        const noteText = {};
        api.get("/api/rows?kind=note&parent_ids=" + encodeURIComponent(projects.map((p) => p.id).join(",")))
          .then((rows) => rows.forEach((r) => {
            noteText[r.parent_id] = (noteText[r.parent_id] || "") + " " + r.text.toLowerCase();
          })).catch(() => {});
        const paint = () => {
          const q = search.value.trim().toLowerCase();
          const hits = projects.filter((p) =>
            !q || (p.name || "").toLowerCase().includes(q)
               || (noteText[p.id] || "").includes(q));
          clear(list);
          if (!hits.length) {
            list.appendChild(el("div.empty", { text: "nothing matches “" + search.value.trim() + "”" }));
            return;
          }
          hits.forEach((p) => list.appendChild(projectCard(p, reload)));
        };
        search.addEventListener("input", paint);
        host.appendChild(search);
        host.appendChild(list);
        paint();
      }
      await reload();
  }

  window.PROJ_TABS = window.PROJ_TABS || [];
  window.PROJ_TABS.push({ key: "projects", label: "Projects", render: renderProjectList });

  /* Bumped when Main landed: the stored value from before it existed would
     have pinned everyone to whichever sub-view they last used and hidden the
     one the tab is now for. A fresh key lands on Main once, then remembers the
     choice as before. A stored key naming a sub-view that no longer exists
     (an older "tree") falls through to the first tab below, which is Main. */
  const SUB_KEY = "project.sub.v2";
  let sub = (() => {
    try { return localStorage.getItem(SUB_KEY) || "main"; } catch { return "main"; }
  })();

  /* The workspace sub-view (project-workspace.js) shows one project with the
     same editable card as the list, so the card is shared rather than cloned. */
  window.ProjectCard = projectCard;

  // "Open" from anywhere in the Project area: select it, jump to Workspace.
  let currentDraw = null;
  window.ProjectArea = {
    open(id) {
      if (window.ProjectPicker) window.ProjectPicker.id = id;
      sub = "workspace";
      try { localStorage.setItem(SUB_KEY, sub); } catch { /* ignore */ }
      if (currentDraw) currentDraw();
    },
  };

  window.Views = window.Views || {};
  window.Views.project = {
    id: "project", label: "Project", scoped: false,
    /* Called by the Inbox before it switches tabs. Selects the node in the
       tree and makes sure the tree is the sub-view we land on, so the link
       goes where it says it goes even if you were last on Workspace. */
    focusOn(id) {
      if (window.ProjectTree) window.ProjectTree.focusOn(id);
      sub = "main";
      try { localStorage.setItem(SUB_KEY, sub); } catch { /* ignore */ }
      if (currentDraw) currentDraw();
    },
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Project" }),
          el("div.sub", { text: "Hours logged, the ideas worth looking at, and how they connect." }),
        ]),
        // Sits at the top so a project can be started from any sub-view —
        // `draw` is a hoisted declaration below, so calling it here is safe.
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-primary", {
            title: "start a project — it becomes the one you're looking at",
            onclick: () => newProjectModal(() => draw()),
            text: "+ project",
          }),
        ]),
      ]));

      // Sub-views register themselves in load order; sort to a fixed reading
      // order so the bar doesn't reshuffle if a file moves in index.html.
      const ORDER = ["main", "overview", "workspace", "instances", "references", "database", "graph", "projects"];
      const tabs = (window.PROJ_TABS || []).slice().sort(
        (a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
      if (!tabs.some((t) => t.key === sub)) sub = tabs[0] && tabs[0].key;

      const bar = el("div.fit-subtabs");
      const host = el("div.fit-sub");
      const head = view.querySelector(".view-head");
      function draw() {
        currentDraw = draw;
        // Main brings its own title and its own + project button.
        if (head) head.style.display = sub === "main" ? "none" : "";
        clear(bar);
        tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
          onclick: () => {
            sub = t.key;
            try { localStorage.setItem(SUB_KEY, sub); } catch { /* ignore */ }
            draw();
          },
          text: t.label,
        })));
        clear(host);
        const t = tabs.find((x) => x.key === sub);
        if (t) guard(() => t.render(host));
      }
      view.appendChild(bar);
      view.appendChild(host);
      draw();
    },
  };
})();

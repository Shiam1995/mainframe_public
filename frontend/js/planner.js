/* planner.js — PLANNER_SPEC: long-running study/build items with weekly hour
   budgets. Mainframe-level service; this tab lives in Synapse.

   Two surfaces in one file:
     · Views.planner — ordered item list under a weekly load strip, plus the
       Reports sub-view (frozen WeeklyReport payloads, exportable as markdown)
     · the Focus view — full detail page for one item (numbers, sessions,
       notes timeline, task/paper/video links, 12-week sparkline)
   The top-bar focus selector + quick note were removed 2026-10-28 (top bar
   cleanup); /api/planner/focus/* and the :Session timer model are untouched. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const BASE = "/api/planner";

  const MOD_ACCENT = (k) => ((window.MODULES || []).find((m) => m.key === k) || {}).accent || "#8194a8";
  const MODULES = ["synapse", "vision", "pulse", "vault", "general"];
  const fmtH = (h) => (h == null ? "—" : (Math.round(h * 10) / 10) + "h");
  const fmtDate = (iso) => (iso ? String(iso).slice(0, 10) : "—");

  /* Calendar dates are plain YYYY-MM-DD in the user's own timezone. toISOString
     would convert to UTC first and land a day early anywhere east of Greenwich,
     which would put the finish preview a day off the backend's projection. */
  const localISO = (d) => {
    const x = new Date(d);
    return new Date(x.getTime() - x.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
  };

  /* mode: "list" | "reports" | {item: id} — the tab routes internally */
  let mode = "list";
  let viewHost = null;

  function badge(module) {
    return el("span.pl-badge", { style: "--b:" + MOD_ACCENT(module), text: module || "general" });
  }

  function chip(item) {
    if (item.status === "done") return el("span.pl-chip.done", { text: "done" });
    if (item.status === "queued") return el("span.pl-chip.queued", { text: "queued" });
    if (item.status === "dropped") return el("span.pl-chip.dropped", { text: "dropped" });
    if (item.drift_days != null && item.drift_days > 0)
      return el("span.pl-chip.drift", { title: "projected finish moved " + item.drift_days + "d later since last report", text: "drifting" });
    return el("span.pl-chip.ontrack", { text: "on track" });
  }

  /* ---------------------------------------------------------------- modal */
  function itemModal(existing, onSaved) {
    const f = (v) => existing ? existing[v] : "";
    const name = el("input.mform-input", { value: f("name") || "", placeholder: "e.g. Finish the C textbook" });
    const desc = el("input.mform-input", { placeholder: "optional description" });
    desc.value = f("description") || "";
    const module = el("select.mform-input", {}, MODULES.map((m) => el("option", { value: m, text: m })));
    module.value = f("module") || "general";
    const total = el("input.mform-input", { type: "number", min: "0", step: "0.5", value: f("total_hours") ?? "" , placeholder: "e.g. 40" });
    const low = el("input.mform-input", { type: "number", min: "0", step: "0.5", value: f("hours_low") ?? "", placeholder: "optimistic" });
    const high = el("input.mform-input", { type: "number", min: "0", step: "0.5", value: f("hours_high") ?? "", placeholder: "pessimistic" });
    // a fresh range re-centres the total; the user can still override it
    const recentre = () => {
      const a = parseFloat(low.value), b = parseFloat(high.value);
      if (a > 0 && b >= a) total.value = String(Math.round((a + b) * 2) / 4);
    };
    low.addEventListener("input", recentre);
    high.addEventListener("input", recentre);
    const reasoning = el("input.mform-input", { placeholder: "why this item, and why these hours" });
    reasoning.value = f("reasoning") || "";
    const dayPref = el("select.mform-input", {}, [
      el("option", { value: "any", text: "any day" }),
      el("option", { value: "weekday", text: "weekdays (Mon–Fri)" }),
      el("option", { value: "weekend", text: "weekend (Sat–Sun)" }),
    ]);
    dayPref.value = f("day_pref") || "any";
    const hpw = el("input.mform-input", { type: "number", min: "0", step: "0.5", value: f("hours_per_week") ?? "", placeholder: "e.g. 4" });
    const start = el("input.mform-input", { type: "date", value: (f("start_date") || localISO(new Date())) });
    const category = el("select.mform-input", {},
      Object.keys(CATS).map((c) => el("option", { value: c, text: c })));
    category.value = f("category") || "study";
    const placement = el("select.mform-input", {},
      ["auto", "manual"].map((p) => el("option", { value: p, text: p })));
    placement.value = f("placement") || (AUTO_CATEGORIES.has(category.value) ? "auto" : "manual");
    // category picks the sane default, but the user keeps the last word (spec §2)
    category.addEventListener("change", () => {
      placement.value = AUTO_CATEGORIES.has(category.value) ? "auto" : "manual";
    });
    const marker = el("select.mform-input", {},
      ["none", "priority", "important"].map((m) => el("option", { value: m, text: m })));
    marker.value = f("marker") || "none";
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    window.PULSE.modal(existing ? "Edit plan item" : "New plan item", [
      field("Name", name),
      field("Description", desc),
      el("div.mform-row-3", {}, [field("Category", category), field("Placement", placement), field("Marker", marker)]),
      field("Reasoning", reasoning),
      el("div.mform-row-3", {}, [field("Low estimate (h)", low), field("High estimate (h)", high), field("Total hours", total)]),
      el("div.mform-row-3", {}, [field("Module", module), field("Hours / week", hpw), field("Days", dayPref)]),
      field("Start date", start),
      el("div.sub", { style: "font-size:11px", text: "Auto-placed items are scheduled for you from the budget; hand-placed ones you position yourself on the calendar. Days is optional: weekday/weekend limits auto-placement to those days." }),
    ], [
      { label: existing ? "Save" : "Add", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name is required", true);
        const hours = parseFloat(hpw.value);
        if (!(parseFloat(total.value) > 0) || !start.value)
          return toast("total hours (or a low/high estimate) and start date are required", true);
        const lo = low.value === "" ? null : parseFloat(low.value);
        const hi = high.value === "" ? null : parseFloat(high.value);
        if (lo != null && hi != null && lo > hi)
          return toast("low estimate cannot exceed the high estimate", true);
        if (hpw.value !== "" && !(hours >= 0))
          return toast("hours/week cannot be negative", true);
        const body = { name: name.value.trim(), description: desc.value.trim(), module: module.value,
          category: category.value, placement: placement.value, marker: marker.value,
          total_hours: parseFloat(total.value), hours_low: lo, hours_high: hi,
          reasoning: reasoning.value.trim(), day_pref: dayPref.value,
          hours_per_week: hpw.value === "" ? 0 : hours, start_date: start.value };
        if (existing) await api.patch(BASE + "/items/" + existing.id, body);
        else await api.post(BASE + "/items", body);
        close(); window.PLANNER.notify(); onSaved();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  /* ------------------------------------------------------------ load strip */
  function weekStart(d) {
    const x = new Date(d); const day = (x.getDay() + 6) % 7;
    x.setDate(x.getDate() - day); x.setHours(0, 0, 0, 0);
    return x;
  }
  function loadStrip(items, capacity, onCapacity) {
    const active = items.filter((i) => i.status === "active" || i.status === "queued");
    const wrap = el("div.pl-strip-wrap");
    const head = el("div.spread", {}, [
      el("span.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px", text: "weekly load" }),
      el("label.row", { style: "gap:6px;font-size:11px;color:var(--dim)" }, [
        el("span", { text: "capacity" }),
        (() => {
          const c = el("input", { type: "number", min: "1", step: "1", value: String(capacity),
            style: "width:52px;text-align:center" });
          c.addEventListener("change", () => onCapacity(parseFloat(c.value) || 20));
          return c;
        })(),
        el("span", { text: "h/wk" }),
      ]),
    ]);
    wrap.appendChild(head);
    if (!active.length) { wrap.appendChild(el("div.sub", { style: "font-size:11px", text: "no active items yet" })); return wrap; }

    const starts = active.map((i) => weekStart(i.start_date));
    const finishes = active.map((i) => {
      const f = i.projected_finish_velocity || i.projected_finish_budget;
      return f ? weekStart(f) : weekStart(new Date());
    });
    const lo = new Date(Math.min(...starts));
    const hi = new Date(Math.max(...finishes)); hi.setDate(hi.getDate() + 7 * 8);
    const weeks = [];
    for (let w = new Date(lo); w <= hi; w.setDate(w.getDate() + 7)) weeks.push(new Date(w));
    const totals = weeks.map((w) =>
      active.reduce((sum, i) => {
        const s = weekStart(i.start_date);
        const f = i.projected_finish_velocity || i.projected_finish_budget;
        const fe = f ? weekStart(f) : hi;
        return sum + (s <= w && w <= fe ? (i.hours_per_week || 0) : 0);
      }, 0));
    const max = Math.max(capacity + 4, ...totals, 1);
    const strip = el("div.pl-strip");
    const nowWs = weekStart(new Date()).getTime();
    weeks.forEach((w, k) => {
      const t = totals[k];
      const cls = t > capacity + 3 ? ".over2" : t > capacity ? ".over1" : "";
      const bar = el("div.pl-strip-bar" + cls + (w.getTime() === nowWs ? ".now" : ""), {
        title: localISO(w) + " · " + (Math.round(t * 10) / 10) + "h budgeted",
      });
      bar.style.height = Math.max(2, (t / max) * 100) + "%";
      strip.appendChild(bar);
    });
    // the capacity line sits over the bars at its share of the same scale
    strip.appendChild(el("div.pl-cap-line", {
      style: "bottom:" + (capacity / max) * 100 + "%",
      title: "capacity " + capacity + "h/wk",
    }));
    wrap.appendChild(strip);
    return wrap;
  }

  /* -------------------------------------------------------------- the list */
  async function renderList(host) {
    clear(host);
    const reload = () => renderList(host);
    const [items, settings, inbox] = await guard(() => Promise.all([
      api.get(BASE + "/items"), api.get(BASE + "/settings"), api.get(BASE + "/notes/inbox"),
    ]));

    host.appendChild(el("div.spread", { style: "margin-bottom:10px" }, [
      el("span.sub", { text: "Every item, including finished and dropped ones. Press a name for the full focus view." }),
      el("button.btn-primary", { onclick: () => itemModal(null, reload), text: "+ item" }),
    ]));

    host.appendChild(loadStrip(items, settings.capacity_per_week, (c) => guard(async () => {
      await api.patch(BASE + "/settings", { capacity_per_week: c });
      window.PLANNER.notify();
      reload();
    })));

    // notes inbox — quick notes with no home yet
    if (inbox.length) {
      const box = el("div.pl-inbox");
      box.appendChild(el("div.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px;margin-bottom:6px",
        text: "note inbox (" + inbox.length + ")" }));
      inbox.forEach((n) => {
        const sel = el("select", {}, [el("option", { value: "", text: "attach to…" }),
          ...items.filter((i) => i.status === "active" || i.status === "queued")
            .map((i) => el("option", { value: i.id, text: i.name.slice(0, 40) }))]);
        sel.addEventListener("change", () => guard(async () => {
          if (!sel.value) return;
          await api.post(BASE + "/notes/" + n.id + "/attach/" + sel.value);
          toast("note attached"); reload();
        }));
        box.appendChild(el("div.pl-inbox-row", {}, [
          el("span", { style: "flex:1", text: n.text }),
          sel,
          el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
            await api.del(BASE + "/notes/" + n.id); reload();
          }), text: "×" }),
        ]));
      });
      host.appendChild(box);
    }

    const listed = items.filter((i) => i.status !== "dropped");
    if (!listed.length) {
      host.appendChild(el("div.empty", { text: "No plan items yet. Add the first with + item." }));
      return;
    }
    const listEl = el("div.pl-list");
    const orderable = listed.filter((i) => i.status === "active" || i.status === "queued");
    listed.forEach((item) => {
      const row = el("div.pl-row" + (item.status === "done" ? ".is-done" : ""));
      row.style.borderLeft = "3px solid " + MOD_ACCENT(item.module);

      // ▲▼ manual priority order, written through /items/reorder
      const oi = orderable.indexOf(item);
      const up = el("button.ord-btn", { text: "▲", title: "raise priority" });
      const down = el("button.ord-btn", { text: "▼", title: "lower priority" });
      if (oi < 0 || oi === 0) up.disabled = true;
      if (oi < 0 || oi === orderable.length - 1) down.disabled = true;
      const swap = (dir) => guard(async () => {
        const ids = orderable.map((i) => i.id);
        [ids[oi], ids[oi + dir]] = [ids[oi + dir], ids[oi]];
        await api.post(BASE + "/items/reorder", { ids });
        reload();
      });
      up.addEventListener("click", () => swap(-1));
      down.addEventListener("click", () => swap(1));
      row.appendChild(el("div.ord-col", {}, [up, down]));

      const name = el("div.pl-name", { text: item.name, title: "open focus view" });
      name.addEventListener("click", () => { mode = { item: item.id }; route(); });

      const hpw = el("input.pl-hpw", { type: "number", min: "0", step: "0.5",
        value: String(item.hours_per_week ?? 0), title: "hours per week (budget)" });
      hpw.addEventListener("change", () => guard(async () => {
        await api.patch(BASE + "/items/" + item.id, { hours_per_week: parseFloat(hpw.value) || 0 });
        reload();
      }));

      const pct = item.total_hours ? Math.min(100, (item.hours_logged / item.total_hours) * 100) : 0;
      const prog = el("div.pl-prog", { title: fmtH(item.hours_logged) + " of " + fmtH(item.total_hours) }, [
        el("div.pl-prog-fill", { style: "width:" + pct + "%;background:" + MOD_ACCENT(item.module) }),
      ]);

      row.appendChild(el("div.pl-row-main", {}, [
        el("div.row", { style: "gap:8px;align-items:center;flex-wrap:wrap" }, [
          name, badge(item.module), chip(item),
        ]),
        el("div.row", { style: "gap:12px;align-items:center;margin-top:6px;flex-wrap:wrap" }, [
          el("span.row", { style: "gap:4px;font-size:11px;color:var(--dim)" }, [hpw, el("span", { text: "h/wk" })]),
          prog,
          el("span.sub", { style: "font-size:11px", title: "projected finish" + (item.projected_finish_velocity ? " (at current pace)" : " (budget)"),
            text: "→ " + fmtDate(item.projected_finish_velocity || item.projected_finish_budget) }),
        ]),
      ]));
      listEl.appendChild(row);
    });
    host.appendChild(listEl);
  }

  /* ------------------------------------------------------------- sparkline */
  function sparkline(points) {
    const w = 240, h = 46, max = Math.max(...points.map((p) => p.hours), 1);
    const bw = w / points.length;
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 " + w + " " + h);
    svg.setAttribute("class", "pl-spark");
    points.forEach((p, i) => {
      const bh = Math.max(1, (p.hours / max) * (h - 6));
      const r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      r.setAttribute("x", i * bw + 1); r.setAttribute("width", Math.max(1, bw - 2));
      r.setAttribute("y", h - bh); r.setAttribute("height", bh);
      r.setAttribute("rx", "1");
      r.setAttribute("fill", i === points.length - 1 ? "var(--accent)" : "#3d4c5e");
      const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
      t.textContent = p.week_start + " · " + p.hours + "h";
      r.appendChild(t);
      svg.appendChild(r);
    });
    return svg;
  }

  /* ----------------------------------------------------- item card: plan (§8)
     Sliders with a live finish-date preview. Nothing here touches the server
     until Save, so you can drag through options without the list and calendar
     reflowing under you on every pixel. The preview uses the same arithmetic
     as the backend's projected_finish_budget, so what it promises is what the
     budget will show once saved. */
  function planPanel(item, settings, onSaved) {
    const horizon = settings.horizon_date;
    const logged = item.hours_logged || 0;

    const totalV = el("span.plb-num", { text: fmtH(item.total_hours) });
    const total = el("input", {
      type: "range", min: "1", max: "500", step: "1",
      value: String(Math.max(1, Math.round(item.total_hours || 1))), style: "flex:1",
    });
    const totalN = el("input.plb-total", {
      type: "number", min: "0.5", step: "0.5", value: String(item.total_hours || 0),
    });
    const hpwV = el("span.plb-num", { text: fmtH(item.hours_per_week) + "/wk" });
    const hpw = el("input", {
      type: "range", min: "0", max: "40", step: "0.5",
      value: String(item.hours_per_week || 0), style: "flex:1",
    });
    const hpwN = el("input.plb-total", {
      type: "number", min: "0", step: "0.5", value: String(item.hours_per_week || 0),
    });
    const marker = el("select.mform-input", { style: "width:130px" },
      ["none", "priority", "important"].map((m) => el("option", { value: m, text: m })));
    marker.value = item.marker || "none";
    const preview = el("div.pl-preview");

    function paint() {
      const t = parseFloat(totalN.value) || 0;
      const rate = parseFloat(hpwN.value) || 0;
      totalV.textContent = fmtH(t);
      hpwV.textContent = fmtH(rate) + "/wk";
      if (rate <= 0) {
        preview.textContent = "At 0 h/wk this is unscheduled — it claims no calendar time and never finishes.";
        preview.className = "pl-preview is-never";
        return;
      }
      const remaining = Math.max(0, t - logged);
      const weeks = Math.ceil(remaining / rate);
      const start = new Date((item.start_date || localISO(new Date())) + "T00:00:00");
      start.setDate(start.getDate() + weeks * 7);
      const finish = localISO(start);
      const fits = finish <= horizon;
      preview.textContent = "At " + fmtH(rate) + "/wk that is " + weeks
        + (weeks === 1 ? " week" : " weeks") + ", finishing about " + finish + ". "
        + (fits ? "Fits by " + horizon + "." : "Lands in " + finish.slice(0, 4) + ", past the horizon.");
      preview.className = "pl-preview " + (fits ? "is-fits" : "is-late");
    }

    const link = (range, num) => {
      range.addEventListener("input", () => { num.value = range.value; paint(); });
      num.addEventListener("input", () => {
        const v = parseFloat(num.value);
        if (!isNaN(v)) range.value = String(Math.min(parseFloat(range.max), Math.max(parseFloat(range.min), v)));
        paint();
      });
    };
    link(total, totalN);
    link(hpw, hpwN);
    paint();

    const save = el("button.btn-primary", {
      text: "Save",
      onclick: () => guard(async () => {
        const t = parseFloat(totalN.value), rate = parseFloat(hpwN.value);
        if (!(t > 0)) return toast("total hours must be greater than 0", true);
        if (!(rate >= 0)) return toast("hours/week cannot be negative", true);
        await api.patch(BASE + "/items/" + item.id, {
          total_hours: t, hours_per_week: rate, marker: marker.value,
        });
        toast("saved — budget and calendar reflowed");
        window.PLANNER.notify();
        onSaved();
      }),
    });

    return el("div.pl-plan", {}, [
      el("div.pl-plan-row", {}, [
        el("span.plb-ctl-l", { text: "total" }), total, totalN, totalV,
      ]),
      el("div.pl-plan-row", {}, [
        el("span.plb-ctl-l", { text: "per week" }), hpw, hpwN, hpwV,
      ]),
      preview,
      el("div.row", { style: "gap:8px;align-items:center;margin-top:8px" }, [
        el("span.plb-ctl-l", { text: "marker" }), marker, save,
      ]),
    ]);
  }

  /* ------------------------------------------------------------ focus view */
  async function renderItem(id) {
    clear(viewHost);
    const [item, settings] = await guard(() => Promise.all([
      api.get(BASE + "/items/" + id), api.get(BASE + "/settings"),
    ]));
    const back = el("button.btn-sm", { onclick: () => { mode = "list"; route(); }, text: "← planner" });

    viewHost.appendChild(el("div.view-head", {}, [
      el("div", {}, [
        el("div.row", { style: "gap:10px;align-items:center;flex-wrap:wrap" }, [
          back, el("h1", { style: "margin:0", text: item.name }),
          el("span.plb-swatch", { style: "background:" + CATS[item.category || "study"], title: item.category }),
          markerGlyph(item.marker), badge(item.module), chip(item),
        ].filter(Boolean)),
        item.description ? el("div.sub", { style: "margin-top:4px", text: item.description }) : null,
        item.reasoning ? el("div.sub", { style: "margin-top:4px;white-space:pre-wrap;font-style:italic", text: "Reasoning: " + item.reasoning }) : null,
      ]),
      el("div.row", { style: "gap:6px" }, [
        el("button.btn-sm", { onclick: () => itemModal(item, () => renderItem(id)), text: "edit" }),
        item.status !== "done" ? el("button.btn-sm", { onclick: () => completeModal(item), text: "✓ complete" }) : null,
      ]),
    ]));

    // numbers row
    const stat = (v, l, c) => el("div.prog-box", {}, [
      el("div.prog-val", { style: "font-size:19px" + (c ? ";color:" + c : ""), text: v }),
      el("div.prog-label", { text: l }),
    ]);
    viewHost.appendChild(el("div.prog-grid", { style: "margin-bottom:14px" }, [
      stat(fmtH(item.total_hours), item.hours_low != null && item.hours_high != null
        ? "estimated total (" + fmtH(item.hours_low) + "–" + fmtH(item.hours_high) + ")" : "estimated total"),
      item.day_pref && item.day_pref !== "any" ? stat(item.day_pref === "weekday" ? "Mon–Fri" : "Sat–Sun", "days") : null,
      stat(fmtH(item.hours_logged), "logged", "var(--accent)"),
      stat(fmtH(item.hours_this_week) + " / " + fmtH(item.hours_per_week), "this week",
        item.hours_this_week >= item.hours_per_week ? "var(--green)" : "#D4A017"),
      stat(fmtDate(item.projected_finish_budget), "finish (budget)"),
      stat(fmtDate(item.projected_finish_velocity), "at current pace",
        item.drift_days > 0 ? "var(--red)" : "var(--green)"),
      stat(item.velocity == null ? "—" : fmtH(item.velocity) + "/wk", "velocity"),
    ]));

    viewHost.appendChild(planPanel(item, settings, () => renderItem(id)));

    const grid = el("div.pl-detail-grid");
    viewHost.appendChild(grid);
    const left = el("div"); const right = el("div");
    grid.appendChild(left); grid.appendChild(right);

    // --- sessions ---
    left.appendChild(el("h4.idea-sec", { text: "Sessions" }));
    left.appendChild(el("div.row", { style: "gap:8px;margin-bottom:6px;align-items:center" }, [
      sparkline(item.sparkline), el("span.sub", { style: "font-size:10px", text: "last 12 weeks" }),
    ]));
    const sDate = el("input.mform-input", { type: "date", value: localISO(new Date()), style: "width:140px" });
    const sMins = el("input.mform-input", { type: "number", min: "1", placeholder: "mins", style: "width:80px" });
    const sNote = el("input.mform-input", { placeholder: "note (optional)", style: "flex:1;min-width:120px" });
    left.appendChild(el("div.row", { style: "gap:6px;margin-bottom:8px;flex-wrap:wrap" }, [
      sDate, sMins, sNote,
      el("button.btn-sm", { onclick: () => guard(async () => {
        const m = parseInt(sMins.value);
        if (!m || m <= 0) return toast("minutes required", true);
        await api.post(BASE + "/items/" + id + "/sessions",
          { start: sDate.value + "T12:00:00Z", minutes: m, note: sNote.value.trim() });
        sMins.value = sNote.value = ""; renderItem(id);
      }), text: "+ log" }),
    ]));
    if (!item.sessions.length) left.appendChild(el("div.sub", { style: "font-size:11px", text: "no sessions yet" }));
    item.sessions.forEach((s) => {
      const mins = el("input.pl-hpw", { type: "number", min: "0", value: String(s.minutes ?? "") , title: "minutes" });
      mins.addEventListener("change", () => guard(async () => {
        await api.patch(BASE + "/sessions/" + s.id, { minutes: parseInt(mins.value) || 0 }); renderItem(id);
      }));
      const note = el("input", { value: s.note || "", placeholder: "note", style: "flex:1;background:transparent;border:none;color:var(--text);font-size:12px" });
      note.addEventListener("change", () => guard(async () => {
        await api.patch(BASE + "/sessions/" + s.id, { note: note.value });
      }));
      left.appendChild(el("div.pl-sess", {}, [
        el("span.mono", { style: "font-size:11px;color:var(--dim)", text: fmtDate(s.start) }),
        el("span.pill", { title: s.source, text: s.source === "timer" ? "⏱" : "✎" }),
        s.end === null ? el("span.pill", { style: "color:var(--green)", text: "running" }) : mins,
        note,
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete this session?", async () => {
          await api.del(BASE + "/sessions/" + s.id); renderItem(id);
        }), text: "×" }),
      ]));
    });

    // --- notes timeline ---
    right.appendChild(el("h4.idea-sec", { text: "Notes" }));
    const ORIGIN_ICON = { topbar: "⌨", focus_view: "🗂", session_close: "⏱" };
    const nIn = el("input.mform-input", { placeholder: "add a note to this item…", style: "flex:1" });
    const pushNote = () => guard(async () => {
      if (!nIn.value.trim()) return;
      await api.post(BASE + "/notes", { text: nIn.value.trim(), item_id: id, origin: "focus_view" });
      nIn.value = ""; renderItem(id);
    });
    nIn.addEventListener("keydown", (e) => { if (e.key === "Enter") pushNote(); });
    right.appendChild(el("div.row", { style: "gap:6px;margin-bottom:8px" }, [nIn,
      el("button.btn-sm", { onclick: pushNote, text: "+ note" })]));
    if (!item.notes.length) right.appendChild(el("div.sub", { style: "font-size:11px", text: "no notes yet" }));
    item.notes.forEach((n) => right.appendChild(el("div.pl-note", {}, [
      el("span", { title: n.origin, text: ORIGIN_ICON[n.origin] || "•" }),
      el("span", { style: "flex:1", text: n.text }),
      el("span.sub", { style: "font-size:10px", text: fmtDate(n.created_at) }),
      el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
        await api.del(BASE + "/notes/" + n.id); renderItem(id);
      }), text: "×" }),
    ])));

    // --- links ---
    right.appendChild(el("h4.idea-sec", { text: "Links" }));
    const linkRow = (kind, node, delId) => el("div.pl-note", {}, [
      el("span.pill", { text: kind }), node,
      el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
        await api.del(BASE + "/items/" + id + "/links/" + kind + "/" + delId); renderItem(id);
      }), text: "×" }),
    ]);
    item.links.tasks.forEach((t) => {
      const cb = el("input", { type: "checkbox" });
      cb.checked = !!t.done;
      // read-write through the existing Tasks API — the planner never owns tasks
      cb.addEventListener("change", () => guard(async () => {
        await api.patch("/api/tasks/" + t.id, { done: cb.checked });
      }));
      right.appendChild(linkRow("task", el("label.row", { style: "gap:6px;flex:1;cursor:pointer" }, [cb, el("span", { text: t.title })]), t.id));
    });
    item.links.papers.forEach((p) =>
      right.appendChild(linkRow("paper", el("span", { style: "flex:1", text: p.title }), p.id)));
    item.links.videos.forEach((v) =>
      right.appendChild(linkRow("video", el("span", { style: "flex:1", text: v.title }), v.id)));

    const attachSel = el("select", {}, [el("option", { value: "", text: "attach…" })]);
    guard(async () => {
      const [tasks, videos] = await Promise.all([
        api.get("/api/tasks").catch(() => []),
        api.get("/api/vision/videos").catch(() => []),
      ]);
      const grp = (label, kind, rows, titleOf) => {
        if (!rows.length) return;
        const g = el("optgroup", { label });
        rows.forEach((r) => g.appendChild(el("option", { value: kind + ":" + r.id, text: (titleOf(r) || "").slice(0, 48) })));
        attachSel.appendChild(g);
      };
      grp("tasks", "task", tasks.filter((t) => !t.done), (t) => t.title);
      grp("papers", "paper", window.PM ? window.PM.papers : [], (p) => p.title);
      grp("videos", "video", videos, (v) => v.title);
    });
    attachSel.addEventListener("change", () => guard(async () => {
      if (!attachSel.value) return;
      const [kind, tid] = attachSel.value.split(":");
      await api.post(BASE + "/items/" + id + "/links", { kind, target_id: tid });
      renderItem(id);
    }));
    right.appendChild(el("div.row", { style: "margin-top:6px" }, [attachSel]));
  }

  function completeModal(item) {
    // the single conclusion note (skippable by leaving it empty)
    const note = el("input.mform-input", { placeholder: "conclusion — what came of it? (optional)" });
    window.PULSE.modal("Complete “" + item.name + "”", [
      el("div.mform-full", {}, [el("div.mform-label", { text: "Conclusion note" }), note]),
    ], [
      { label: "Complete", primary: true, onClick: (close) => guard(async () => {
        await api.post(BASE + "/items/" + item.id + "/complete", { note: note.value.trim() });
        close(); toast("completed ✓"); mode = "list"; route();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  /* --------------------------------------------------------------- reports */
  function reportMarkdown(p) {
    const L = ["# Weekly report — " + p.week_start, "", "capacity: " + p.capacity + "h/wk", "",
      "| item | budget | logged | velocity | finish (budget) | finish (pace) | drift |",
      "|---|---|---|---|---|---|---|"];
    p.items.forEach((i) => L.push("| " + i.name + " | " + (i.budget ?? "—") + " | " + (i.logged ?? "—")
      + " | " + (i.velocity ?? "—") + " | " + (i.projected_finish_budget || "—") + " | "
      + (i.projected_finish_velocity || "—") + " | " + (i.drift_days == null ? "—" : i.drift_days + "d") + " |"));
    L.push("", "**totals:** " + p.totals.logged + " / " + p.totals.budget + "h", "");
    if (p.notes.length) {
      L.push("## Notes");
      p.notes.forEach((n) => L.push("- **" + n.item + "** — " + n.text));
    }
    return L.join("\n");
  }

  async function renderReports(host) {
    clear(host);
    const reload = () => renderReports(host);
    host.appendChild(el("div.spread", { style: "margin-bottom:10px" }, [
      el("span.sub", { text: "Frozen snapshots — later edits never rewrite a past report. Generated automatically every Friday 16:00." }),
      el("button.btn-primary", { onclick: () => guard(async () => {
        await api.post(BASE + "/reports/generate"); toast("report generated"); reload();
      }), text: "⚡ generate now" }),
    ]));
    const reports = await guard(() => api.get(BASE + "/reports"));
    if (!reports.length) { host.appendChild(el("div.empty", { text: "No reports yet." })); return; }
    for (const r of reports) {
      const box = el("div.pl-report");
      const body = el("div", { style: "display:none" });
      const head = el("div.spread", { style: "cursor:pointer" }, [
        el("span", { style: "font-weight:600", text: "week of " + r.week_start }),
        el("span.sub", { style: "font-size:10px", text: "generated " + fmtDate(r.generated_at) }),
      ]);
      head.addEventListener("click", () => guard(async () => {
        if (body.dataset.loaded) { body.style.display = body.style.display === "none" ? "" : "none"; return; }
        const full = await api.get(BASE + "/reports/" + r.id);
        const p = full.payload;
        body.dataset.loaded = "1";
        const tbl = el("table.dd-sources");
        tbl.appendChild(el("thead", {}, [el("tr", {}, ["item", "budget", "logged", "velocity", "finish", "drift"].map((h) => el("th", { text: h })))]));
        const tb = el("tbody");
        (p.items || []).forEach((i) => tb.appendChild(el("tr", {}, [
          el("td", { text: i.name }),
          el("td", { text: String(i.budget ?? "—") }),
          el("td", { text: String(i.logged ?? "—") }),
          el("td", { text: String(i.velocity ?? "—") }),
          el("td", { text: i.projected_finish_velocity || i.projected_finish_budget || "—" }),
          el("td", { style: i.drift_days > 0 ? "color:var(--red)" : "color:var(--green)",
            text: i.drift_days == null ? "—" : (i.drift_days > 0 ? "+" : "") + i.drift_days + "d" }),
        ])));
        tbl.appendChild(tb);
        body.appendChild(tbl);
        body.appendChild(el("div.sub", { style: "margin-top:6px",
          text: "totals: " + p.totals.logged + " / " + p.totals.budget + "h · capacity " + p.capacity }));
        if ((p.notes || []).length) {
          body.appendChild(el("h4.idea-sec", { text: "Notes" }));
          p.notes.forEach((n) => body.appendChild(el("div.pl-note", {}, [
            el("span.pill", { text: n.item.slice(0, 22) }), el("span", { style: "flex:1", text: n.text }),
          ])));
        }
        body.appendChild(el("button.btn-sm", { style: "margin-top:8px", onclick: () => {
          const blob = new Blob([reportMarkdown(p)], { type: "text/markdown" });
          const a = el("a", { href: URL.createObjectURL(blob), download: "planner-week-" + p.week_start + ".md" });
          a.click();
        }, text: "⤓ markdown" }));
        body.style.display = "";
      }));
      box.appendChild(head); box.appendChild(body);
      host.appendChild(box);
    }
  }

  /* =================================================================== */
  /* The tab shell: two synced surfaces plus the v1 item list and reports */
  /* =================================================================== */

  /* Sub-views (planner-budget.js, planner-calendar.js) register into
     PLANNER_TABS at load; the shell owns everything they share. Constants live
     here rather than in a sub-view so the two surfaces cannot drift apart on
     what a category colour or a marker glyph means (spec §6). */
  const CATS = {
    study: "#00D4AA", build: "#7AA2F7", paper: "#BB9AF7",
    fixed: "#F7768E", fitness: "#E0AF68", event: "#9ECE6A",
  };
  /* mirrors AUTO_CATEGORIES in routes/planner.py — the categories the
     placement engine schedules for you rather than waiting to be hand-placed */
  const AUTO_CATEGORIES = new Set(["study", "build", "paper"]);

  function markerGlyph(marker) {
    if (marker === "priority") return el("span.pl-mark.is-priority", { title: "priority — do now", text: "!" });
    if (marker === "important") return el("span.pl-mark.is-important", { title: "important, not urgent", text: "★" });
    return null;
  }

  /* Budget and Calendar are one item list seen two ways, so an edit on either
     has to move the other. Whichever sub-view is mounted registers its reload
     here; the other calls notify() after every mutation (spec §1, §11.2). */
  let externalReload = null;

  window.PLANNER = {
    CATS,
    markerGlyph,
    notify() { if (externalReload) externalReload(); },
  };

  let sub = (() => {
    try { return localStorage.getItem("planner.sub") || "budget"; } catch { return "budget"; }
  })();

  function subTabs() {
    return (window.PLANNER_TABS || []).slice()
      .sort((a, b) => (a.order || 999) - (b.order || 999))
      .concat([
        { key: "items", label: "Items", render: (host) => renderList(host) },
        { key: "reports", label: "Reports", render: (host) => renderReports(host) },
      ]);
  }

  function route() {
    if (!viewHost) return;
    if (mode && mode.item) { externalReload = null; renderItem(mode.item); return; }

    clear(viewHost);
    viewHost.appendChild(el("div.view-head", {}, [el("div", {}, [
      el("h1", { text: "Planner" }),
      el("div.sub", {
        text: "One list, two surfaces: Budget decides what fits before the "
            + "horizon and in what order, Calendar decides when it happens.",
      }),
    ])]));

    const tabs = subTabs();
    if (!tabs.some((t) => t.key === sub)) sub = tabs[0].key;
    const bar = el("div.fit-subtabs.pl-subtabs");
    const host = el("div");
    tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
      onclick: () => {
        sub = t.key;
        try { localStorage.setItem("planner.sub", sub); } catch { /* private mode */ }
        route();
      },
      text: t.label,
    })));
    viewHost.appendChild(bar);
    viewHost.appendChild(host);

    externalReload = null;
    const ctx = {
      openItem(id) { mode = { item: id }; route(); },
      goto(key) {
        sub = key;
        try { localStorage.setItem("planner.sub", sub); } catch { /* private mode */ }
        route();
      },
      /* only the mounted sub-view listens, so a stale view is never redrawn */
      onExternalChange(fn) { externalReload = fn; },
    };
    const t = tabs.find((x) => x.key === sub);
    guard(() => t.render(host, ctx));
  }

  window.Views = window.Views || {};
  window.Views.planner = {
    id: "planner", label: "Planner", scoped: false,
    async render(view) { viewHost = view; route(); },
  };

})();

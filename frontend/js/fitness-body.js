/* fitness-body.js — Pulse Fitness Body Map: a snapshot a day.

   An anatomical figure you can turn round (front ↔ back) and look inside
   (muscle ↔ skeleton). Geometry and the region table live in body-atlas.js;
   this file is the view around it.

   v3 — the map is ONE DAY. Pick a day (today by default); the figure shows
   what you logged for it. Click a muscle to log or edit it for that day:
   soreness / pain / tightness / imbalance, severity 1 mild … 5 severe (the
   colour), a note. Nothing carries forward by itself — a new day starts empty
   and "carry over" copies the last logged day, so you only edit what changed.
   The history lists every logged day; each muscle's editor shows its own run
   of days. "All clear" under the date records a day you checked and were fine
   (not the same as a day you didn't log); logging a muscle undoes it. The Day Review opens the same editor on the same data.

   (v2's always-open issues are gone from the view. Any still open show as a
   banner offering to move them into today.)

   `window.FIT.buildBodySvg` keeps its old name and call signature because the
   Day Review builds the same figure to highlight worked muscles. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const A = window.BodyAtlas;

  const KINDS = [
    { id: "soreness", label: "Soreness" },
    { id: "pain", label: "Pain" },
    { id: "tight", label: "Tight" },
    { id: "imbalance", label: "Imbalance" },
  ];
  const SEV = {
    1: { c: "#D9C64B", label: "mild" },
    2: { c: "#F0A030", label: "noticeable" },
    3: { c: "#F07030", label: "moderate" },
    4: { c: "#E05A5A", label: "bad" },
    5: { c: "#C41E1E", label: "severe" },
  };

  // Entries from before the atlas rewrite use the old 19 keys ("l_arm"); name
  // them after the muscle they now stand for, as the figure colours them.
  function regionName(key) {
    const m = A.meta(key);
    if (m.group !== "Other" || m.name !== key) return m.name;
    const t = A.legacyTargets(key);
    return t.length ? A.meta(t[0]).name : key;
  }
  function sevDot(n) {
    return el("span.sevdot", { style: "background:" + (SEV[n] || SEV[3]).c,
      title: "severity " + n + " — " + (SEV[n] || SEV[3]).label });
  }

  /* Build the figure block. `opts`: points, highlight (Set), onRegionClick.
     Unchanged contract — the Day Review calls this too. */
  function buildFigure(points, onRegionClick, highlight) {
    let vi = 0, layer = "muscle";
    const wrap = el("div.bodyfig", { tabIndex: "0" });
    const stage = el("div.bodyfig-stage");
    const readout = el("div.bodyfig-read", { text: " " });

    const viewLabel = el("span.bodyfig-view");
    const layerBtns = A.LAYERS.map((L) =>
      el("button.btn-sm", { onclick: () => { layer = L.id; paint(); }, text: L.label }));

    const ctl = el("div.bodyfig-ctl", {}, [
      el("button.btn-sm.bodyfig-turn", { onclick: () => { vi = (vi + A.VIEWS.length - 1) % A.VIEWS.length; paint(); }, text: "‹" }),
      viewLabel,
      el("button.btn-sm.bodyfig-turn", { onclick: () => { vi = (vi + 1) % A.VIEWS.length; paint(); }, text: "›" }),
      el("span.bodyfig-sep"),
      el("div.row", { style: "gap:2px" }, layerBtns),
    ]);

    function paint() {
      const view = A.VIEWS[vi];
      clear(viewLabel);
      viewLabel.appendChild(el("strong", { text: view.label.toUpperCase() }));
      viewLabel.appendChild(el("span.sub", { text: " " + view.sub }));
      layerBtns.forEach((b, i) => b.classList.toggle("active", A.LAYERS[i].id === layer));
      clear(stage);
      stage.appendChild(A.drawFigure(view, layer, {
        points: A.expand(points),
        highlight,
        onClick: onRegionClick ? (key, state) => onRegionClick(key, state, A.CYCLE[state]) : null,
        onHover: (key) => {
          if (!key) { readout.textContent = " "; return; }
          const m = A.meta(key), st = A.expand(points)[key];
          const sev = /^sev([1-5])$/.exec(st || "");
          readout.textContent = m.name +
            (sev ? "  ·  severity " + sev[1] + " (" + SEV[sev[1]].label + ")" : st ? "  ·  " + st : "");
        },
      }));
    }

    wrap.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { vi = (vi + A.VIEWS.length - 1) % A.VIEWS.length; paint(); }
      else if (e.key === "ArrowRight") { vi = (vi + 1) % A.VIEWS.length; paint(); }
      else if (e.key.toLowerCase() === "l") { layer = layer === "muscle" ? "skeleton" : "muscle"; paint(); }
      else return;
      e.preventDefault();
    });

    wrap.appendChild(ctl);
    wrap.appendChild(stage);
    wrap.appendChild(readout);
    paint();
    return wrap;
  }

  function legend() {
    return el("div.row", { style: "gap:10px;margin-top:8px;font-size:11px;color:var(--dim);flex-wrap:wrap;align-items:center" },
      Object.keys(SEV).map((n) => el("span", { style: "display:inline-flex;align-items:center;gap:4px" },
        [sevDot(+n), SEV[n].label]))
        .concat([el("span", { text: "🩷 worked" }), el("span", { style: "opacity:.7", text: "← → turn · L layer" })]));
  }

  /* Old-format helper kept for the Day Review. */
  async function retireLegacy(points, key, write) {
    const stale = A.legacySources(points, key);
    for (const lk of stale) {
      for (const target of A.legacyTargets(lk)) {
        if (target !== key) await write(target, points[lk]);
      }
      await write(lk, "");
    }
  }

  window.FIT = window.FIT || {};
  window.FIT.buildBodySvg = buildFigure;
  window.FIT.bodyLegend = legend;
  window.FIT.retireLegacy = retireLegacy;

  /* ---------------- severity picker (row of 5 coloured squares) ----------- */
  function sevPicker(initial, onPick) {
    let cur = initial || 0;
    const row = el("div.sevpick");
    const paint = () => [...row.children].forEach((b, i) =>
      b.classList.toggle("on", i + 1 === cur));
    for (let n = 1; n <= 5; n++) {
      const b = el("button.sevbtn", {
        text: n, title: SEV[n].label,
        style: "--sevc:" + SEV[n].c,
        onclick: () => { cur = n; paint(); onPick(n); },
      });
      row.appendChild(b);
    }
    paint();
    return row;
  }

  /* ---------------- one muscle on one day --------------------------------- */
  // Log or edit `region` on day `d`. `entry` is what's there already (or
  // null); `history` is every logged day, for this muscle's run of days.
  function openDayEntry(d, region, entry, history, onSaved) {
    const m = { name: regionName(region) };
    let kind = entry ? entry.kind : "soreness", severity = entry ? entry.severity : 3;
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    const kindRow = el("div.gnew-chips");
    KINDS.forEach((k) => {
      const b = el("button.btn-sm" + (k.id === kind ? ".btn-primary" : ""), { text: k.label });
      b.addEventListener("click", () => {
        kind = k.id;
        [...kindRow.children].forEach((c) => c.classList.remove("btn-primary"));
        b.classList.add("btn-primary");
      });
      kindRow.appendChild(b);
    });
    // One muscle on one day: a single statement, shown inline after the kind.
    const note = el("input.mform-input.gd-note", { placeholder: "how it feels today…" });
    note.value = entry ? entry.note || "" : "";

    // This muscle across days, newest first.
    const run = (history || []).map((h) => ({ date: h.date, e: (h.entries || []).find((x) => x.region === region) }))
      .filter((x) => x.e && x.date !== d).slice(0, 14);
    const tl = el("div.iss-timeline");
    run.forEach((x) => tl.appendChild(el("div.iss-upd", {}, [
      el("span.iss-upd-ts", { text: P.fmtDay(x.date) }), sevDot(x.e.severity),
      el("span.iss-upd-note", { text: x.e.kind + (x.e.note ? " · " + x.e.note : "") }),
    ])));

    const save = () => guard(async () => {
      const day = await api.pulse.fitness.setBodyDayEntry(d, region, { kind, severity, note: note.value.trim() });
      close(); onSaved(day);
    });
    overlay.appendChild(el("div.modal", {}, [
      el("div.modal-title", { text: m.name + " · " + P.fmtDay(d) }),
      el("div.gd-row", {}, [el("span.gd-lbl", { text: "kind" }), kindRow]),
      el("div.gd-row", {}, [el("span.gd-lbl", { text: "severity" }), sevPicker(severity, (n) => { severity = n; })]),
      note,
      el("div.gd-lbl", { style: "margin:6px 0 4px;width:auto", text: run.length ? "other days" : "no other days logged for this muscle" }),
      tl,
      el("div.gd-foot", { style: "margin-top:10px" }, [
        entry ? el("button.btn-sm.btn-danger", { text: "fine today", title: "take it off this day",
          onclick: () => guard(async () => { const day = await api.pulse.fitness.clearBodyDayEntry(d, region); close(); onSaved(day); }) })
          : el("span"),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "cancel", onclick: close }),
          el("button.btn-sm.btn-primary", { text: entry ? "save" : "log it", onclick: save }),
        ]),
      ]),
    ]));
    document.body.appendChild(overlay);
    note.focus();
  }
  window.FIT.openDayEntry = openDayEntry;

  const pointsOf = (entries) => {
    const pts = {};
    (entries || []).forEach((e) => { pts[e.region] = "sev" + e.severity; });
    return pts;
  };
  const shiftDay = (d, n) => { const x = new Date(d + "T00:00:00"); x.setDate(x.getDate() + n); return P.dateStr(x); };

  function entryRow(e, onClick) {
    return el("div.iss-row", { title: "press to edit", onclick: onClick }, [
      sevDot(e.severity),
      el("span.iss-name", { text: regionName(e.region) }),
      el("span.iss-kind", { text: e.kind }),
      el("span.iss-age", { text: e.note || "" }),
    ]);
  }

  /* ---------------- the view ----------------------------------------------- */
  let curDate = null;

  async function render(host) {
    if (!curDate) curDate = P.today();
    const wrap = el("div", { style: "display:grid;grid-template-columns:340px 1fr;gap:24px;align-items:start" });
    const left = el("div"); const right = el("div");
    const banner = el("div");
    const top = el("div");
    host.appendChild(banner);
    host.appendChild(top);
    host.appendChild(wrap);
    wrap.appendChild(left); wrap.appendChild(right);

    async function reload() {
      const [day, history, openIssues, data] = await guard(() => Promise.all([
        api.pulse.fitness.bodyDay(curDate), api.pulse.fitness.bodyDays(),
        api.pulse.fitness.bodyIssues("open"), api.pulse.fitness.body()]));
      const go = (d) => { curDate = d; reload(); };
      const byRegion = {};
      day.entries.forEach((e) => { byRegion[e.region] = e; });
      const edit = (region) => openDayEntry(curDate, region, byRegion[region] || null, history, reload);

      /* old always-on issues, if any are still open */
      clear(banner);
      if (openIssues.length) {
        const names = openIssues.map((i) => regionName(i.region)).join(", ");
        banner.appendChild(el("div.pulse-card", { style: "margin-bottom:14px;border-color:var(--amber)" }, [
          el("div", { style: "margin-bottom:8px", text: openIssues.length + " issue" + (openIssues.length === 1 ? "" : "s")
            + " still open from the old always-on map: " + names + "." }),
          el("div.row", { style: "gap:8px;flex-wrap:wrap" }, [
            el("button.btn-sm.btn-primary", { text: "add to " + (curDate === P.today() ? "today" : P.fmtDay(curDate)) + " and close them",
              onclick: () => guard(async () => { await api.pulse.fitness.issuesToDay({ date: curDate, close: true }); reload(); }) }),
            el("button.btn-sm", { text: "just close them", onclick: () => confirmDo("Close " + openIssues.length + " old issue(s)? Their history is kept.",
              async () => { for (const i of openIssues) await api.pulse.fitness.patchBodyIssue(i.id, { status: "closed" }); reload(); }) }),
          ]),
        ]));
      }

      /* top: day bar, and under it the all-clear for that day */
      clear(top);
      const dateIn = el("input.mform-input", { type: "date", value: curDate, style: "width:150px" });
      dateIn.addEventListener("change", () => dateIn.value && go(dateIn.value));
      top.appendChild(el("div.row", { style: "gap:6px;margin-bottom:10px;align-items:center;flex-wrap:wrap" }, [
        el("button.btn-sm", { text: "‹", title: "day before", onclick: () => go(shiftDay(curDate, -1)) }),
        dateIn,
        el("button.btn-sm", { text: "›", title: "day after", onclick: () => go(shiftDay(curDate, 1)) }),
        el("span.sub", { style: "margin-left:6px", text: curDate === P.today() ? "today" : P.fmtDay(curDate) }),
      ]));
      const setClear = (v) => guard(async () => { await api.pulse.fitness.setBodyAllClear(curDate, v); reload(); });
      if (day.all_clear) {
        top.appendChild(el("div.bodyclear.on", {}, [
          el("span", { text: "✓ All good — body looking fine" }),
          el("button.btn-sm", { text: "undo", onclick: () => setClear(false) }),
        ]));
      } else {
        top.appendChild(el("div.bodyclear", {}, [
          el("button.btn-sm.bodyclear-btn", {
            text: "✓ All clear — body feeling fine",
            title: "checked in, nothing wrong today",
            onclick: () => day.entries.length
              ? confirmDo("Mark " + (curDate === P.today() ? "today" : P.fmtDay(curDate)) + " all clear? This removes the "
                  + day.entries.length + " logged for it.", async () => { await api.pulse.fitness.setBodyAllClear(curDate, true); reload(); })
              : setClear(true),
          }),
          el("span.sub", { style: "font-size:11px", text: day.entries.length ? "" : "or click a muscle if something's off" }),
        ]));
      }

      /* left: the figure for that day */
      clear(left);
      left.appendChild(buildFigure(pointsOf(day.entries), (key) => edit(key)));
      left.appendChild(legend());

      /* right: this day, day note, history */
      clear(right);
      right.appendChild(el("div.spread", {}, [
        el("h3", { style: "margin:0 0 8px", text: (curDate === P.today() ? "Today" : P.fmtDay(curDate)) }),
        el("span.sub", { text: day.entries.length ? day.entries.length + " logged" : "" }),
      ]));
      if (day.all_clear) {
        right.appendChild(el("div.sub", { style: "margin-bottom:8px", text: "Marked all clear. Click a muscle if something comes up — that undoes it." }));
      } else if (!day.entries.length) {
        right.appendChild(el("div.empty", { style: "margin-bottom:8px", text: "Nothing logged for this day. Click a muscle on the figure to log soreness, pain, tightness or an imbalance." }));
      } else {
        day.entries.forEach((e) => right.appendChild(entryRow(e, () => edit(e.region))));
      }
      if (day.prev) {
        const already = new Set(day.entries.map((e) => e.region));
        right.appendChild(el("div.row", { style: "gap:8px;margin:8px 0 4px;align-items:center" }, [
          el("button.btn-sm", { text: "carry over from " + P.fmtDay(day.prev.date) + " (" + day.prev.count + ")",
            title: "copy that day's entries here; ones already logged today are kept",
            onclick: () => guard(async () => { await api.pulse.fitness.carryBodyDay(curDate, day.prev.date); reload(); }) }),
          already.size ? el("span.sub", { style: "font-size:11px", text: "keeps what's already logged" }) : null,
        ]));
      }

      right.appendChild(el("div.mform-label", { style: "margin-top:14px", text: "Day note" }));
      const dn = el("textarea.mform-input", { rows: "2", style: "width:100%", placeholder: "how the body felt today…" });
      dn.value = day.note || "";
      dn.addEventListener("change", () => guard(async () => { await api.pulse.fitness.setDayNote({ date: curDate, text: dn.value }); toast("day note saved"); }));
      right.appendChild(dn);

      right.appendChild(el("h3", { style: "margin:20px 0 8px", text: "History" }));
      const past = history.filter((h) => h.date !== curDate);
      if (!past.length) right.appendChild(el("div.sub", { text: "No other days logged yet." }));
      past.forEach((h) => right.appendChild(el("div.bodyday-row", { title: "open this day", onclick: () => go(h.date) }, [
        el("span.bodyday-date", { text: P.fmtDay(h.date) }),
        el("span.bodyday-chips", {}, h.entries.length ? h.entries.map((e) => el("span.bodyday-chip", {}, [sevDot(e.severity), regionName(e.region)]))
          : [h.all_clear ? el("span.bodyday-clear", { text: "✓ all clear" }) : el("span.sub", { text: "no issues" })]),
        h.note ? el("span.bodyday-note", { text: h.note }) : null,
      ])));

      if ((data.notes || []).length) {
        right.appendChild(el("h3", { style: "margin:20px 0 8px", text: "Older body notes" }));
        data.notes.forEach((n) => right.appendChild(el("div", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
          el("div.sub", { text: P.fmtDay((n.date || "").slice(0, 10)) }), el("div", { text: n.text }),
        ])));
      }
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "body", label: "Body Map", render });
})();

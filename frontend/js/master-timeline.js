/* master-timeline.js — Timeline (topbar): every module on one horizontal axis.

   Replaces the Synapse-only Paper Timeline. One lane per stream — phases,
   projects, hours, calendar, Synapse, Pulse, Vision, Vault — with things that
   last drawn as bars and things that happen on a day drawn as dots. Zoom runs
   week → year; the strip opens on today.

   Reads /api/timeline only. Nothing here writes: click any bar or dot to go to
   the tab that owns it and change it there. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  // px per day at each zoom
  const ZOOMS = [
    { id: "week", label: "Week", px: 40 },
    { id: "month", label: "Month", px: 12 },
    { id: "quarter", label: "Quarter", px: 4 },
    { id: "year", label: "Year", px: 1.2 },
  ];
  const LANE_COLOR = {
    phases: "var(--purple)", projects: "var(--blue)", work: "var(--green)",
    calendar: "var(--gojo)", life: "var(--muted)",
    synapse: "var(--teal)", pulse: "var(--pulse)", vision: "var(--red)", vault: "var(--amber)",
  };
  const ROW_H = 22;          // one row of bars
  const ROW_H_TIGHT = 14;    // …in a lane with more rows than COMPACT_AFTER
  const COMPACT_AFTER = 10;
  const DOT_ROW_H = 26;      // the row of dots
  const PAD_BEFORE = 14, PAD_AFTER = 45;  // days of margin around the data
  const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

  const ZOOM_KEY = "mf.timeline.zoom", HIDDEN_KEY = "mf.timeline.hidden";
  const load = (k, d) => { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private window */ } };

  // Day arithmetic in UTC so a DST change can't shift a bar by a pixel row.
  const toDay = (iso) => Math.round(Date.parse(iso + "T00:00:00Z") / 864e5);
  const fromDay = (n) => new Date(n * 864e5);

  // Greedy row packing: each bar goes in the first row whose last bar ended before it starts.
  function pack(spans) {
    const rowsEnd = [];
    return spans.slice().sort((a, b) => a.s - b.s).map((sp) => {
      let r = rowsEnd.findIndex((end) => end < sp.s - 1);
      if (r < 0) { r = rowsEnd.length; rowsEnd.push(0); }
      rowsEnd[r] = sp.e;
      return Object.assign(sp, { row: r });
    });
  }

  function go(item) {
    if (item.tab === "workspace" && item.id) { window.PM.selectPaper(item.id); return; }
    if (item.tab) window.openTab(item.tab);
  }

  window.Views = window.Views || {};
  window.Views.mtimeline = {
    id: "mtimeline", label: "Timeline", scoped: false,
    async render(view) {
      clear(view);
      const data = await guard(() => api.get("/api/timeline"));
      let zoom = ZOOMS.find((z) => z.id === load(ZOOM_KEY, "month")) || ZOOMS[1];
      const hidden = new Set(load(HIDDEN_KEY, []));

      const t0 = toDay(data.min) - PAD_BEFORE, t1 = toDay(data.max) + PAD_AFTER;
      const today = toDay(data.today);

      const zoomBar = el("div.row", { style: "gap:6px" });
      const laneBar = el("div.row", { style: "gap:6px;flex-wrap:wrap;margin:10px 0 12px" });
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Timeline" }),
          el("div.sub", { text: "Every module on one axis. Bars last, dots happen on a day. Click anything to open it." }),
        ]),
        zoomBar,
      ]));
      view.appendChild(laneBar);

      const labels = el("div.mt-labels");
      const scroller = el("div.mt-scroll");
      view.appendChild(el("div.mt-wrap", {}, [labels, scroller]));

      function drawChips() {
        clear(zoomBar);
        ZOOMS.forEach((z) => zoomBar.appendChild(el("button.filter-chip" + (z === zoom ? ".active" : ""), {
          text: z.label, onclick: () => setZoom(z),
        })));
        zoomBar.appendChild(el("button.filter-chip", { text: "Today", onclick: () => centreOn(today) }));
        clear(laneBar);
        data.lanes.forEach((l) => {
          const on = !hidden.has(l.key);
          laneBar.appendChild(el("button.filter-chip" + (on ? ".active" : ""), {
            style: on ? "border-color:" + LANE_COLOR[l.key] : "",
            title: l.error ? "this lane failed to load: " + l.error : (on ? "hide" : "show") + " " + l.label,
            text: (l.error ? "⚠ " : "") + l.label,
            onclick: () => {
              on ? hidden.add(l.key) : hidden.delete(l.key);
              save(HIDDEN_KEY, [...hidden]);
              const c = centreDay(); drawChips(); draw(); centreOn(c);
            },
          }));
        });
      }

      const centreDay = () => t0 + (scroller.scrollLeft + scroller.clientWidth / 2) / zoom.px;
      const centreOn = (day) => { scroller.scrollLeft = (day - t0) * zoom.px - scroller.clientWidth / 2; };
      function setZoom(z) {
        const c = centreDay();
        zoom = z; save(ZOOM_KEY, z.id);
        drawChips(); draw(); centreOn(c);
      }

      function axis(width) {
        const ax = el("div.mt-axis", { style: "width:" + width + "px" });
        const px = zoom.px;
        // Weeks (Mondays) as faint ticks when there's room for them.
        if (px >= 4) {
          for (let d = t0; d <= t1; d++) {
            if (fromDay(d).getUTCDay() !== 1) continue;
            ax.appendChild(el("div.mt-tick.minor", { style: "left:" + (d - t0) * px + "px" },
              px >= 12 ? [el("span", { text: String(fromDay(d).getUTCDate()) })] : []));
          }
        }
        for (let d = t0; d <= t1; d++) {
          const dt = fromDay(d);
          if (dt.getUTCDate() !== 1) continue;
          const m = dt.getUTCMonth(), y = dt.getUTCFullYear();
          // At year zoom a label per month crowds; keep Jan/Apr/Jul/Oct.
          const label = px < 2 && m % 3 ? "" : (m === 0 || px >= 4 ? MONTHS[m] + " " + y : MONTHS[m]);
          ax.appendChild(el("div.mt-tick" + (m === 0 ? ".year" : ""), { style: "left:" + (d - t0) * px + "px" },
            label ? [el("span", { text: label })] : []));
        }
        return ax;
      }

      function draw() {
        clear(labels); clear(scroller);
        const px = zoom.px, width = (t1 - t0) * px;
        const canvas = el("div.mt-canvas", { style: "width:" + width + "px" });
        canvas.appendChild(axis(width));
        labels.appendChild(el("div.mt-label.axis"));

        data.lanes.filter((l) => !hidden.has(l.key)).forEach((l) => {
          const color = LANE_COLOR[l.key] || "var(--dim)";
          const spans = pack((l.spans || []).filter((s) => s.start).map((s) => Object.assign({}, s, {
            s: toDay(s.start), e: toDay(s.end || s.start),
          })));
          const nRows = spans.length ? Math.max(...spans.map((s) => s.row)) + 1 : 0;
          // Thirty-odd open projects would otherwise fill the screen on their own.
          const tight = nRows > COMPACT_AFTER, rowH = tight ? ROW_H_TIGHT : ROW_H;
          const hasDots = (l.points || []).length || l.days;
          const h = Math.max(nRows * rowH + (hasDots ? DOT_ROW_H : 0), DOT_ROW_H) + 8;

          const lane = el("div.mt-lane", { style: "height:" + h + "px" });
          labels.appendChild(el("div.mt-label", { style: "height:" + h + "px;border-left-color:" + color }, [
            el("span", { text: l.label }),
            el("span.sub", { text: String((l.spans || []).length + (l.points || []).length || Object.keys(l.days || {}).length) }),
          ]));

          spans.forEach((s) => {
            const w = Math.max((s.e - s.s + 1) * px, 3);
            const finished = /^(done|completed|closed)$/.test(s.status || "");
            lane.appendChild(el("div.mt-bar" + (s.open ? ".open" : "") + (finished ? ".done" : "") + (tight ? ".tight" : ""), {
              style: `left:${(s.s - t0) * px}px;width:${w}px;top:${4 + s.row * rowH}px;background:${color}`,
              title: `${s.title}\n${s.start} → ${s.end || "…"}${s.open ? " (open)" : ""}${s.status ? "\n" + s.status : ""}${s.note ? "\n" + s.note : ""}`,
              onclick: () => go(s),
            }, w > 40 ? [el("span", { text: s.title })] : []));
          });

          const dotTop = 4 + nRows * rowH + DOT_ROW_H / 2;
          // Hours: a heat strip, one cell per day, shaded against the busiest day.
          if (l.days) {
            const max = Math.max(1, ...Object.values(l.days));
            Object.entries(l.days).forEach(([d, mins]) => {
              lane.appendChild(el("div.mt-heat", {
                style: `left:${(toDay(d) - t0) * px}px;width:${Math.max(px, 2)}px;top:${dotTop - 8}px;` +
                  `background:${color};opacity:${(0.2 + 0.8 * mins / max).toFixed(2)}`,
                title: `${d} · ${(mins / 60).toFixed(1)} h logged`,
                onclick: () => window.openTab("work"),
              }));
            });
          }
          // Dots: one per day per lane, sized by how much happened that day.
          const byDay = {};
          (l.points || []).forEach((p) => { if (p.date) (byDay[p.date] = byDay[p.date] || []).push(p); });
          Object.entries(byDay).forEach(([d, ps]) => {
            const size = Math.min(6 + (ps.length - 1) * 2, 16);
            const lines = ps.slice(0, 10).map((p) => "• " + (p.kind ? p.kind + ": " : "") + (p.title || ""));
            if (ps.length > 10) lines.push(`… and ${ps.length - 10} more`);
            lane.appendChild(el("div.mt-dot", {
              style: `left:${(toDay(d) - t0 + 0.5) * px - size / 2}px;top:${dotTop - size / 2}px;` +
                `width:${size}px;height:${size}px;background:${color}`,
              title: d + (ps.length > 1 ? ` · ${ps.length} things` : "") + "\n" + lines.join("\n"),
              onclick: () => go(ps[0]),
            }));
          });
          canvas.appendChild(lane);
        });

        if (today >= t0 && today <= t1) {
          canvas.appendChild(el("div.mt-today", { style: "left:" + (today - t0 + 0.5) * px + "px" }, [el("span", { text: "today" })]));
        }
        scroller.appendChild(canvas);
      }

      drawChips();
      draw();
      centreOn(today);
    },
  };
})();

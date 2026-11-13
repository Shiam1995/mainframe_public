/* nutrition-weight.js — weight, body measurements, progress photos
   (NUTRITION_SPEC §6).

   The graph plots every weigh-in AND a smoothed weekly average, because a daily
   weight swings a kilo on water alone — the average is what actually shows the
   direction. Measurement fields you've never used stay hidden, so the form is
   only ever as long as your own history. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const P = window.PULSE;

  const RANGES = [30, 90, 180, 365];
  let range = 90;

  const FIELDS = [
    ["chest", "Chest"], ["waist", "Waist"], ["hips", "Hips"],
    ["left_arm", "L arm"], ["right_arm", "R arm"],
    ["left_thigh", "L thigh"], ["right_thigh", "R thigh"],
    ["left_calf", "L calf"], ["right_calf", "R calf"],
    ["neck", "Neck"], ["shoulders", "Shoulders"], ["body_fat", "Body fat %"],
  ];

  /* Weight graph — points plus the weekly average line. */
  function graph(trend, width) {
    const W = Math.max(560, width || 700), H = 230, M = { l: 42, r: 16, t: 16, b: 26 };
    const SVG = "http://www.w3.org/2000/svg";
    const mk = (t, a) => { const n = document.createElementNS(SVG, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
    const svg = mk("svg", { width: "100%", height: H, viewBox: `0 0 ${W} ${H}` });
    const pts = trend.points || [];
    if (!pts.length) return svg;

    const xs = pts.map((p) => new Date(p.date + "T00:00:00").getTime());
    const ys = pts.map((p) => p.weight).concat(trend.target ? [trend.target] : []);
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = Math.min(...ys), y1 = Math.max(...ys);
    if (y1 - y0 < 2) { y0 -= 1; y1 += 1; }           // a flat line shouldn't fill the panel
    const pad = (y1 - y0) * 0.12; y0 -= pad; y1 += pad;
    const X = (t) => M.l + ((t - x0) / Math.max(1, x1 - x0)) * (W - M.l - M.r);
    const Y = (v) => M.t + (1 - (v - y0) / Math.max(0.001, y1 - y0)) * (H - M.t - M.b);

    // axis labels
    [y0, (y0 + y1) / 2, y1].forEach((v) => {
      const t = mk("text", { x: 6, y: Y(v) + 4, fill: "#5c6b7a", "font-size": "10",
        "font-family": "ui-monospace, Menlo, monospace" });
      t.textContent = v.toFixed(1);
      svg.appendChild(t);
      svg.appendChild(mk("line", { x1: M.l, y1: Y(v), x2: W - M.r, y2: Y(v), stroke: "#18222c" }));
    });

    if (trend.target) {
      svg.appendChild(mk("line", { x1: M.l, y1: Y(trend.target), x2: W - M.r, y2: Y(trend.target),
        stroke: "#7ED957", "stroke-dasharray": "4 4", "stroke-width": 1.2 }));
    }

    // daily points
    pts.forEach((p) => svg.appendChild(mk("circle", {
      cx: X(new Date(p.date + "T00:00:00").getTime()), cy: Y(p.weight), r: 2.6, fill: "#4a5c6b",
    })));

    // weekly average line — the one that shows direction
    const avg = trend.weekly_average || [];
    if (avg.length > 1) {
      const d = avg.map((a, i) => (i ? "L " : "M ")
        + X(new Date(a.week + "T00:00:00").getTime()) + " " + Y(a.weight)).join(" ");
      svg.appendChild(mk("path", { d, fill: "none", stroke: "#7ED957", "stroke-width": 2.2 }));
      avg.forEach((a) => svg.appendChild(mk("circle", {
        cx: X(new Date(a.week + "T00:00:00").getTime()), cy: Y(a.weight), r: 3.4, fill: "#7ED957",
      })));
    }
    return svg;
  }

  function logWeightModal(reload) {
    const { N, field, numInput } = window.NUT;
    const w = numInput("", "kg");
    const d = el("input.mform-input", { type: "date", value: window.NUT.today() });
    const notes = el("input.mform-input", { placeholder: "notes (optional)" });
    P.modal("Log weight", [
      el("div.mform-row", {}, [field("Weight (kg)", w), field("Date", d)]),
      field("Notes", notes),
    ], [
      { label: "Log", primary: true, onClick: (close) => guard(async () => {
        const v = parseFloat(w.value);
        if (!v) return toast("what did it say?", true);
        await N().addWeight({ weight: v, date: d.value, notes: notes.value.trim() });
        toast("logged"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
    w.focus();
  }

  function logBodyModal(used, reload) {
    const { N, field, numInput } = window.NUT;
    const d = el("input.mform-input", { type: "date", value: window.NUT.today() });
    const inputs = {};
    // Show what you've measured before, plus a way to add the rest — the form
    // shouldn't open with twelve empty boxes on day one.
    let showAll = used.length === 0;
    const grid = el("div.bl-grid");
    const drawGrid = () => {
      clear(grid);
      FIELDS.filter(([k]) => showAll || used.includes(k)).forEach(([k, l]) => {
        const i = inputs[k] || (inputs[k] = numInput("", k === "body_fat" ? "%" : "cm"));
        grid.appendChild(el("div", {}, [el("div.mform-label", { text: l }), i]));
      });
    };
    drawGrid();
    const more = el("button.btn-sm", { type: "button", text: "+ all measurements" });
    more.addEventListener("click", () => { showAll = !showAll; more.textContent = showAll ? "− fewer" : "+ all measurements"; drawGrid(); });
    const notes = el("input.mform-input", { placeholder: "notes (optional)" });

    P.modal("Log measurements", [
      field("Date", d), grid,
      el("div.row", { style: "margin-top:6px" }, [more]),
      field("Notes", notes),
    ], [
      { label: "Log", primary: true, onClick: (close) => guard(async () => {
        const body = { date: d.value, notes: notes.value.trim() };
        let any = false;
        Object.keys(inputs).forEach((k) => {
          const v = parseFloat(inputs[k].value);
          if (!isNaN(v)) { body[k] = v; any = true; }
        });
        if (!any) return toast("fill in at least one measurement", true);
        await N().addBody(body);
        toast("logged"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);
    const reload = () => render(host);

    guard(async () => {
      const { N, n1 } = window.NUT;
      const [trend, measures, goals] = await Promise.all([N().weightTrend(range), N().body(), N().goals()]);
      clear(body);

      const bmi = (trend.current && goals.height_cm)
        ? (trend.current / Math.pow(goals.height_cm / 100, 2)) : null;

      body.appendChild(el("div.row", { style: "gap:6px;flex-wrap:wrap;align-items:center" }, [
        ...RANGES.map((r) => el("button.btn-sm" + (r === range ? ".heat-on" : ""), {
          onclick: () => { range = r; reload(); }, text: r + "d" })),
        el("span", { style: "flex:1" }),
        el("button.btn-sm.btn-primary", { onclick: () => logWeightModal(reload), text: "+ log weight" }),
      ]));

      const stat = (v, l, c) => el("div.prog-box", {}, [
        el("div.prog-val", { style: "color:" + c, text: v }), el("div.prog-label", { text: l }),
      ]);
      const goingRight = trend.change != null && goals.weight_goal
        && ((goals.weight_goal === "lose" && trend.change < 0)
          || (goals.weight_goal === "gain" && trend.change > 0)
          || (goals.weight_goal === "maintain" && Math.abs(trend.change) < 0.5));
      body.appendChild(el("div.prog-grid", { style: "margin-top:12px" }, [
        stat(trend.current != null ? n1(trend.current) + "kg" : "—", "current", window.NUT.GREEN),
        stat(trend.start != null ? n1(trend.start) + "kg" : "—", "at start", "var(--dim)"),
        stat(trend.change != null ? (trend.change > 0 ? "+" : "") + n1(trend.change) + "kg" : "—",
          "change", trend.change == null ? "var(--dim)" : goingRight ? window.NUT.GREEN : "var(--amber)"),
        stat(trend.target ? n1(trend.target) + "kg" : "—", "target", "var(--blue)"),
        stat(bmi ? bmi.toFixed(1) : "—", "BMI", "var(--dim)"),
      ]));

      const g = el("div.card", { style: "margin-top:12px" }, [
        el("div.spread", {}, [
          el("h3", { style: "margin:0", text: "Weight" }),
          el("span.sub", { style: "font-size:11px", text: "dots = weigh-ins · line = weekly average" }),
        ]),
      ]);
      if (!trend.points.length) {
        g.appendChild(el("div.empty", { text: "No weigh-ins in this window." }));
      } else {
        g.appendChild(graph(trend, host.clientWidth - 60));
      }
      body.appendChild(g);

      // --- body measurements ---
      const used = [];
      measures.forEach((m) => FIELDS.forEach(([k]) => {
        if (m[k] != null && !used.includes(k)) used.push(k);
      }));
      const mCard = el("div.card", { style: "margin-top:12px" }, [
        el("div.spread", {}, [
          el("h3", { style: "margin:0", text: "Body measurements" }),
          el("button.btn-sm.btn-primary", { onclick: () => logBodyModal(used, reload), text: "+ log" }),
        ]),
      ]);
      if (!measures.length) {
        mCard.appendChild(el("div.empty", { text: "Nothing measured yet." }));
      } else {
        const latest = measures[0], prev = measures[1];
        const table = el("table.wk-table");
        const head = el("tr");
        ["", "latest", "previous", "change"].forEach((h) => head.appendChild(el("th", { text: h })));
        table.appendChild(head);
        used.forEach((k) => {
          const label = (FIELDS.find((f) => f[0] === k) || [k, k])[1];
          const now = latest[k], before = prev ? prev[k] : null;
          const delta = (now != null && before != null) ? now - before : null;
          const tr = el("tr.wk-row");
          tr.appendChild(el("td", { text: label }));
          tr.appendChild(el("td", { text: now != null ? n1(now) : "—" }));
          tr.appendChild(el("td", { text: before != null ? n1(before) : "—" }));
          tr.appendChild(el("td", {
            style: "color:" + (delta == null ? "var(--dim)" : delta < 0 ? window.NUT.GREEN : "var(--amber)"),
            text: delta == null ? "—" : (delta > 0 ? "▲ +" : "▼ ") + n1(delta),
          }));
          table.appendChild(tr);
        });
        mCard.appendChild(el("div.wk-scroll", {}, [table]));
        if (latest.waist_to_height != null || latest.waist_to_hip != null) {
          mCard.appendChild(el("div.sub", { style: "font-size:11px;margin-top:8px",
            text: [latest.waist_to_height != null ? "waist-to-height " + latest.waist_to_height : null,
                   latest.waist_to_hip != null ? "waist-to-hip " + latest.waist_to_hip : null]
              .filter(Boolean).join("  ·  ") }));
        }
        mCard.appendChild(el("div.sub", { style: "font-size:11px;margin-top:6px",
          text: measures.length + " logged · latest " + latest.date }));
      }
      body.appendChild(mCard);

      // --- progress photos, via the shared image service ---
      const photos = el("div.card", { style: "margin-top:12px" }, [
        el("h3", { style: "margin:0 0 4px", text: "Progress photos" }),
        el("div.sub", { style: "margin-bottom:8px", text: "Attached here and stored with the rest of your images." }),
      ]);
      window.Images.mount(photos, { module: "pulse", contextId: "nutrition-progress", surface: "nutrition-progress" });
      body.appendChild(photos);
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "weight", label: "Weight & Body", order: 50, undecided: true, render });
})();

/* nutrition-fasting.js — intermittent fasting (NUTRITION_SPEC §7).

   A large circular timer, not just a log entry — the spec is explicit. The ring
   fills toward the target and keeps going past it, because finishing at 17 of
   16 hours is a success, not an overflow. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const P = window.PULSE;

  const PROTOCOLS = [
    { key: "16:8", hours: 16, label: "16:8 — 8h eating window" },
    { key: "18:6", hours: 18, label: "18:6 — 6h eating window" },
    { key: "20:4", hours: 20, label: "20:4 — 4h eating window" },
    { key: "OMAD", hours: 23, label: "OMAD — one meal a day" },
  ];
  let ticker = null;

  function timerRing(elapsedH, targetH, size) {
    const s = size || 210, r = s / 2 - 15, circ = 2 * Math.PI * r;
    const pct = targetH > 0 ? elapsedH / targetH : 0;
    const done = pct >= 1;
    const colour = done ? window.NUT.GREEN : "#5DA9FF";
    const SVG = "http://www.w3.org/2000/svg";
    const mk = (t, a) => { const n = document.createElementNS(SVG, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
    const svg = mk("svg", { width: s, height: s, viewBox: `0 0 ${s} ${s}` });
    svg.appendChild(mk("circle", { cx: s / 2, cy: s / 2, r, fill: "none", stroke: "#1b2733", "stroke-width": 13 }));
    svg.appendChild(mk("circle", {
      cx: s / 2, cy: s / 2, r, fill: "none", stroke: colour, "stroke-width": 13, "stroke-linecap": "round",
      "stroke-dasharray": `${Math.min(pct, 1) * circ} ${circ}`,
      transform: `rotate(-90 ${s / 2} ${s / 2})`,
    }));
    const h = Math.floor(elapsedH);
    const m = Math.round((elapsedH - h) * 60);
    const big = mk("text", { x: s / 2, y: s / 2 + 2, "text-anchor": "middle", fill: colour,
      "font-size": "32", "font-weight": "600", "font-family": "ui-monospace, Menlo, monospace" });
    big.textContent = h + "h " + String(m).padStart(2, "0") + "m";
    svg.appendChild(big);
    const sub = mk("text", { x: s / 2, y: s / 2 + 26, "text-anchor": "middle", fill: "#7b8b9a",
      "font-size": "12", "font-family": "ui-monospace, Menlo, monospace" });
    sub.textContent = done ? "target " + targetH + "h reached" : "of " + targetH + "h";
    svg.appendChild(sub);
    return svg;
  }

  function startModal(reload) {
    const { N, field } = window.NUT;
    const proto = el("select.mform-input", {}, [
      ...PROTOCOLS.map((p) => el("option", { value: String(p.hours), text: p.label })),
      el("option", { value: "custom", text: "Custom…" }),
    ]);
    const custom = el("input.mform-input", { type: "number", min: "1", step: "any", value: "16", style: "display:none" });
    proto.addEventListener("change", () => {
      custom.style.display = proto.value === "custom" ? "block" : "none";
    });
    const start = el("input.mform-input", { type: "datetime-local" });
    const notes = el("input.mform-input", { placeholder: "notes (optional)" });
    P.modal("Start a fast", [
      field("Protocol", proto),
      field("Custom hours", custom),
      field("Started at (blank = now)", start),
      field("Notes", notes),
    ], [
      { label: "Start", primary: true, onClick: (close) => guard(async () => {
        const hours = proto.value === "custom" ? (parseFloat(custom.value) || 16) : parseFloat(proto.value);
        await N().startFast({
          target_hours: hours,
          start_time: start.value ? new Date(start.value).toISOString() : null,
          notes: notes.value.trim(),
        });
        toast("fast started"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function render(host) {
    clear(host);
    if (ticker) { clearInterval(ticker); ticker = null; }
    const body = el("div");
    host.appendChild(body);
    const reload = () => render(host);

    guard(async () => {
      const { N, n1 } = window.NUT;
      const data = await N().fasting();
      clear(body);

      const active = data.active;
      const card = el("div.card");
      if (active) {
        const started = new Date(active.start_time);
        const ringHost = el("div");
        const tick = () => {
          const elapsed = (Date.now() - started.getTime()) / 3600000;
          clear(ringHost);
          ringHost.appendChild(timerRing(Math.max(0, elapsed), Number(active.target_hours) || 16));
        };
        tick();
        // one second is enough — the display only shows minutes
        ticker = setInterval(tick, 1000);
        card.appendChild(el("div.row", { style: "gap:22px;flex-wrap:wrap;align-items:center" }, [
          ringHost,
          el("div", { style: "flex:1;min-width:200px;display:flex;flex-direction:column;gap:8px" }, [
            el("div", { style: "font-size:15px;color:" + window.NUT.GREEN, text: "Fasting" }),
            el("div.sub", { style: "font-size:11px",
              text: "since " + active.start_time.slice(0, 16).replace("T", " ") + " · target " + active.target_hours + "h" }),
            el("div.row", { style: "gap:6px;flex-wrap:wrap" }, [
              el("button.btn-sm.btn-primary", { text: "■ end fast", onclick: () => guard(async () => {
                const r = await N().endFast(active.id);
                toast(r.completed ? "completed — " + n1(r.actual_hours) + "h" : "broken at " + n1(r.actual_hours) + "h",
                  !r.completed);
                reload();
              }) }),
              el("button.btn-sm.btn-danger", { text: "discard", onclick: () =>
                confirmDo("Discard this fast without recording it?", async () => {
                  await window.NUT.N().delFast(active.id); reload();
                }) }),
            ]),
          ]),
        ]));
      } else {
        card.appendChild(el("div.row", { style: "gap:22px;flex-wrap:wrap;align-items:center" }, [
          timerRing(0, 16),
          el("div", { style: "flex:1;min-width:200px" }, [
            el("div", { style: "font-size:15px", text: "Eating window" }),
            el("div.sub", { style: "font-size:11px;margin-bottom:8px", text: "No fast running." }),
            el("button.btn-sm.btn-primary", { onclick: () => startModal(reload), text: "▶ start a fast" }),
          ]),
        ]));
      }
      body.appendChild(card);

      const done = (data.sessions || []).filter((s) => s.end_time);
      const stat = (v, l, c) => el("div.prog-box", {}, [
        el("div.prog-val", { style: "color:" + c, text: String(v) }), el("div.prog-label", { text: l }),
      ]);
      body.appendChild(el("div.prog-grid", { style: "margin-top:12px" }, [
        stat(done.length, "fasts logged", "var(--dim)"),
        stat(data.completed_count, "hit the target", window.NUT.GREEN),
        stat(data.average_hours != null ? data.average_hours + "h" : "—", "average length", "var(--blue)"),
      ]));

      if (!done.length) return;
      const list = el("div.card", { style: "margin-top:12px" }, [
        el("h3", { style: "margin:0 0 8px", text: "History" }),
      ]);
      done.forEach((s) => list.appendChild(el("div.nt-entry", {}, [
        el("span.mono", { style: "font-size:11px;color:var(--dim);min-width:104px",
          text: (s.start_time || "").slice(0, 10) }),
        el("div", { style: "flex:1" }, [
          el("div", { text: n1(s.actual_hours) + "h of " + s.target_hours + "h" }),
          s.notes ? el("div.sub", { style: "font-size:10.5px", text: s.notes }) : null,
        ]),
        el("span.pill", { style: "color:" + (s.completed ? window.NUT.GREEN : "var(--amber)"),
          text: s.completed ? "completed" : "broken" }),
        el("button.btn-sm.btn-danger", { text: "×", onclick: () =>
          confirmDo("Delete this fast?", async () => { await window.NUT.N().delFast(s.id); reload(); }) }),
      ])));
      body.appendChild(list);
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "fasting", label: "Fasting", order: 60, undecided: true, render });
})();

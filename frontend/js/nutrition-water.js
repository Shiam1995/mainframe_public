/* nutrition-water.js — hydration (NUTRITION_SPEC §5).

   A bottle that fills as you drink, quick-add buttons for the amounts you
   actually pour, and the day's entries with their times. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;

  const QUICK = [250, 500, 750, 1000];
  let day = null;

  const shift = (base, n) => { const d = new Date(base + "T00:00:00"); d.setDate(d.getDate() + n); return window.ui.todayISO(d); };

  /* The bottle. SVG so the fill can be a clean clipped rectangle rather than a
     percentage-height div — those collapse inside flex parents. */
  function bottle(total, target) {
    const W = 92, H = 190, pct = target > 0 ? Math.min(total / target, 1) : 0;
    const SVG = "http://www.w3.org/2000/svg";
    const mk = (t, a) => { const n = document.createElementNS(SVG, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
    const svg = mk("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}` });
    const body = "M26 34 h40 a14 14 0 0 1 14 14 v112 a14 14 0 0 1 -14 14 h-40 a14 14 0 0 1 -14 -14 v-112 a14 14 0 0 1 14 -14 z";
    const clip = mk("clipPath", { id: "nt-bottle-clip" });
    clip.appendChild(mk("path", { d: body }));
    const defs = mk("defs", {}); defs.appendChild(clip); svg.appendChild(defs);
    svg.appendChild(mk("rect", { x: 34, y: 14, width: 24, height: 22, rx: 4, fill: "#22303c" }));
    svg.appendChild(mk("path", { d: body, fill: "#111a22", stroke: "#22303c", "stroke-width": 2 }));
    const fillH = (H - 34 - 6) * pct;
    svg.appendChild(mk("rect", {
      x: 12, y: H - 6 - fillH, width: W - 24, height: fillH,
      fill: pct >= 1 ? "#5DA9FF" : "#3E86D6", "clip-path": "url(#nt-bottle-clip)",
    }));
    const t = mk("text", { x: W / 2, y: H / 2 + 4, "text-anchor": "middle", fill: "#e8eef4",
      "font-size": "15", "font-weight": "600", "font-family": "ui-monospace, Menlo, monospace" });
    t.textContent = Math.round(pct * 100) + "%";
    svg.appendChild(t);
    return svg;
  }

  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);
    const date = day || window.NUT.today();
    const reload = () => render(host);

    guard(async () => {
      const { N, n0 } = window.NUT;
      const w = await N().water(date);
      clear(body);

      body.appendChild(el("div.row", { style: "gap:8px;align-items:center;flex-wrap:wrap" }, [
        el("button.btn-sm", { onclick: () => { day = shift(date, -1); reload(); }, text: "◀" }),
        el("input.mform-input", { type: "date", value: date, style: "width:auto",
          onchange: (e) => { day = e.target.value; reload(); } }),
        el("button.btn-sm", { onclick: () => { day = shift(date, 1); reload(); }, text: "▶" }),
        date !== window.NUT.today() ? el("button.btn-sm", { onclick: () => { day = null; reload(); }, text: "today" }) : null,
      ]));

      const custom = el("input.mform-input", { type: "number", min: "0", step: "any",
        placeholder: "ml", style: "width:90px" });
      const addCustom = () => guard(async () => {
        const v = parseFloat(custom.value);
        if (!v) return toast("how much?", true);
        await N().addWater({ date, amount: v, time: window.ui.nowHM() });
        custom.value = ""; toast("logged"); reload();
      });
      custom.addEventListener("keydown", (e) => { if (e.key === "Enter") addCustom(); });

      body.appendChild(el("div.card", { style: "margin-top:12px" }, [
        el("div.row", { style: "gap:22px;flex-wrap:wrap;align-items:center" }, [
          bottle(w.total_ml, w.target_ml),
          el("div", { style: "flex:1;min-width:220px;display:flex;flex-direction:column;gap:10px" }, [
            el("div.mono", { style: "font-size:20px;color:#5DA9FF",
              text: n0(w.total_ml) + " / " + n0(w.target_ml) + " ml" }),
            el("div.sub", { style: "font-size:11px", text: w.total_ml >= w.target_ml
              ? "target met"
              : n0(w.target_ml - w.total_ml) + " ml to go" }),
            el("div.row", { style: "gap:6px;flex-wrap:wrap" }, QUICK.map((ml) =>
              el("button.btn-sm", { text: "+" + (ml >= 1000 ? ml / 1000 + "L" : ml + "ml"),
                onclick: () => guard(async () => {
                  await N().addWater({ date, amount: ml, time: window.ui.nowHM() });
                  reload();
                }) }))),
            el("div.row", { style: "gap:6px" }, [custom, el("button.btn-sm", { onclick: addCustom, text: "+ add" })]),
          ]),
        ]),
      ]));

      if (!w.entries.length) {
        body.appendChild(el("div.empty", { style: "margin-top:12px", text: "Nothing logged for this day." }));
        return;
      }
      const list = el("div.card", { style: "margin-top:12px" }, [
        el("h3", { style: "margin:0 0 8px", text: "Today's entries" }),
      ]);
      w.entries.forEach((e) => list.appendChild(el("div.nt-entry", {}, [
        el("span.mono", { style: "font-size:11px;color:var(--dim);min-width:52px", text: e.time || "—" }),
        el("div", { style: "flex:1", text: n0(e.amount) + " ml" }),
        el("button.btn-sm.btn-danger", { text: "×",
          onclick: () => confirmDo("Remove " + n0(e.amount) + "ml?", async () => {
            await window.NUT.N().delWater(e.id); reload();
          }) }),
      ])));
      body.appendChild(list);
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "water", label: "Drinks", order: 20, render });
})();

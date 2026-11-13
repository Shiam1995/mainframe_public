/* refs.js — citation cross-reference matrix. Row cites column.
   Click a cell to cycle: · (none) → ✓ (cites) → ★ (highlighted) → · */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const NEXT = { none: "cites", cites: "highlighted", highlighted: "none" };
  const GLYPH = { none: "·", cites: "✓", highlighted: "★" };

  window.Views = window.Views || {};
  window.Views.refs = {
    id: "refs", label: "References", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [ el("h1", { text: "Reference Matrix" }), el("div.sub", { text: "Row cites column. Click to cycle · → ✓ → ★." }) ]),
      ]));
      const statsBox = el("div.sub", { style: "margin-bottom:12px" });
      view.appendChild(statsBox);
      const box = el("div.matrix"); view.appendChild(box);

      async function reload() {
        const { papers, edges } = await guard(() => api.get("/api/synapse/refs"));
        const state = {}; // "src|tgt" -> "cites"|"highlighted"
        edges.forEach((e) => { state[e.source + "|" + e.target] = e.highlighted ? "highlighted" : "cites"; });
        clear(box);
        if (papers.length < 2) { box.appendChild(el("div.empty", { text: "Add at least 2 papers to build a matrix." })); return; }
        const table = el("table");
        const head = el("tr"); head.appendChild(el("th.rowhead", { text: "row cites ↓ →" }));
        papers.forEach((p) => head.appendChild(el("th.colhead", { title: p.title, text: p.title.slice(0, 22) })));
        table.appendChild(head);
        papers.forEach((rp) => {
          const tr = el("tr");
          tr.appendChild(el("td.rowhead", { title: rp.title, text: rp.title.slice(0, 22) }));
          papers.forEach((cp) => {
            if (rp.id === cp.id) { tr.appendChild(el("td.cell.diag", { text: "" })); return; }
            const key = rp.id + "|" + cp.id;
            const st = state[key] || "none";
            const cell = el("td.cell." + st, { text: GLYPH[st] });
            cell.addEventListener("click", () => guard(async () => {
              const ns = NEXT[state[key] || "none"];
              await api.post("/api/synapse/refs/toggle", { source_id: rp.id, target_id: cp.id, state: ns });
              state[key] = ns === "none" ? undefined : ns;
              cell.className = "cell " + ns; cell.textContent = GLYPH[ns];
              loadStats();
            }));
            tr.appendChild(cell);
          });
          table.appendChild(tr);
        });
        box.appendChild(table);
      }
      async function loadStats() {
        const s = await guard(() => api.get("/api/synapse/refs/stats"));
        const mc = s.most_cited[0]; const mg = s.most_citing[0];
        statsBox.textContent = `${s.total_edges} citation links · most cited: ${mc && mc.cited_by ? mc.title.slice(0,30)+" ("+mc.cited_by+")" : "—"} · most citing: ${mg && mg.cites ? mg.title.slice(0,30)+" ("+mg.cites+")" : "—"}`;
      }
      await reload(); await loadStats();
    },
  };
})();

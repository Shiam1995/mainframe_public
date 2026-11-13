/* benchmark-snapshots.js — Benchmark ▸ Snapshots. The point-in-time history:
   log a full snapshot (baseline + metrics + blood), a period-over-period
   comparison table with coloured deltas, the list of saved snapshots (each with
   its next-due date, expandable, deletable), and the tracked-metrics config. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const BM = () => api.pulse.benchmarks;

  function num(s) {
    if (s == null || s === "") return null;
    const m = String(s).match(/-?\d+(\.\d+)?/);
    return m ? parseFloat(m[0]) : null;
  }
  function delta(cur, prev, hib) {
    if (prev == null || cur == null) return el("span.bm-delta", { text: "" });
    const diff = Math.round((cur - prev) * 100) / 100;
    if (diff === 0) return el("span.bm-delta", { text: "—" });
    const improved = hib ? diff > 0 : diff < 0;
    return el("span.bm-delta." + (improved ? "up" : "down"), { text: (diff > 0 ? "↑ +" : "↓ ") + Math.abs(diff) });
  }

  // ---- comparison table (baseline rows + tracked metric rows) ----
  function comparisonTable(metrics, assessments) {
    if (!assessments.length) return el("div.sub", { text: "No snapshots yet — save your first below." });
    const tracked = metrics.filter((m) => m.tracked);
    const head = el("tr", {}, [
      el("th", { text: "" }),
      ...assessments.map((a) => el("th", {}, [
        el("div", { text: a.label || (a.date || "").slice(0, 10) }),
        el("div.sub", { style: "font-weight:400", text: (a.date || "").slice(0, 10) }),
      ])),
    ]);
    const body = el("tbody");
    const section = (title) => body.appendChild(el("tr", {}, [el("td.bm-section", { colSpan: assessments.length + 1, text: title })]));
    const row = (label, icon, getVal, hib) => {
      const tr = el("tr", {}, [el("td", {}, [el("span", { text: (icon || "") + " " }), el("span", { text: label })])]);
      assessments.forEach((a, i) => {
        const cur = getVal(a);
        const prevA = assessments[i + 1];
        const prev = prevA ? getVal(prevA) : null;
        tr.appendChild(el("td", {}, [
          el("div", { text: cur == null || cur === "" ? "·" : String(cur) }),
          delta(num(cur), num(prev), hib),
        ]));
      });
      body.appendChild(tr);
    };
    section("Baseline");
    (window.BENCH.BASELINE_FIELDS).forEach(([k, l]) => row(l, "", (a) => a["bl_" + k], false));
    ["fitness", "blood", "custom"].forEach((cat) => {
      const ms = tracked.filter((m) => m.category === cat);
      if (!ms.length) return;
      section(cat[0].toUpperCase() + cat.slice(1));
      ms.forEach((m) => row(m.name, m.icon, (a) => (a.values[m.key] ? a.values[m.key].value : null), m.higher_is_better));
    });
    return el("table.bm-table", {}, [el("thead", {}, [head]), body]);
  }

  // ---- full log-snapshot modal (baseline + metrics) ----
  function logModal(metrics, latest, baseline, reload) {
    const tracked = metrics.filter((m) => m.tracked);
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const labelI = el("input.mform-input", { placeholder: "e.g. Q3 2026" });
    // + rows, held until the snapshot exists and then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "how you felt, context" });
    const blInputs = {};
    const blNodes = window.BENCH.BASELINE_FIELDS.map(([k, l, ph]) => {
      const inp = el("input.mform-input", { placeholder: ph, value: baseline[k] || "" });
      blInputs[k] = inp;
      return el("div.mform-full", {}, [el("div.mform-label", { text: l }), inp]);
    });
    const inputs = {};
    const groupNodes = [];
    ["fitness", "blood", "custom"].forEach((cat) => {
      const ms = tracked.filter((m) => m.category === cat);
      if (!ms.length) return;
      groupNodes.push(el("div.mform-label", { style: "margin-top:10px;color:" + (cat === "blood" ? "var(--red)" : cat === "custom" ? "var(--dim)" : "#DE7BA4"), text: "── " + cat + " ──" }));
      ms.forEach((m) => {
        const pre = latest && latest.values[m.key] ? latest.values[m.key].value : "";
        const inp = el("input.mform-input", { type: "number", step: "any", placeholder: m.unit, value: pre });
        inputs[m.key] = inp;
        groupNodes.push(el("div.mform-full", {}, [el("div.mform-label", { text: m.icon + " " + m.name + " (" + m.unit + ")" }), inp]));
      });
    });
    P.modal("Save snapshot", [
      el("div.mform-row", {}, [
        el("div", {}, [el("div.mform-label", { text: "Date" }), date]),
        el("div", {}, [el("div.mform-label", { text: "Label" }), labelI]),
      ]),
      el("div.mform-label", { style: "margin-top:10px;color:var(--accent)", text: "── baseline (frozen into this snapshot) ──" }),
      ...blNodes,
      ...groupNodes,
      notes.node,
    ], [
      { label: "Save snapshot", primary: true, onClick: (close) => guard(async () => {
        const values = {};
        Object.keys(inputs).forEach((k) => { if (inputs[k].value !== "") values[k] = { value: parseFloat(inputs[k].value) }; });
        const bl = {};
        Object.keys(blInputs).forEach((k) => { bl[k] = blInputs[k].value.trim(); });
        const made = await BM().create({ date: date.value, label: labelI.value.trim(), type: "combined", values, baseline: bl });
        await notes.commit(made.id);
        toast("snapshot saved");
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  // ---- saved-snapshot history cards ----
  const open = new Set();
  function snapCard(a, metrics, reload) {
    const isOpen = open.has(a.id);
    const card = el("div.pulse-card", {}, [
      el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(a.id) : open.add(a.id); reload(); } }, [
        el("div.row", { style: "gap:8px" }, [
          el("span", { text: "📸" }),
          el("span", { style: "font-weight:600", text: a.label || (a.date || "").slice(0, 10) }),
          el("span.sub", { text: (a.date || "").slice(0, 10) }),
        ]),
        a.next_due ? el("span.pulse-tag", { text: "next due " + a.next_due }) : null,
      ]),
    ]);
    if (isOpen) {
      const body = el("div", { style: "margin-top:10px;border-top:1px solid var(--border);padding-top:10px" });
      const blLine = window.BENCH.BASELINE_FIELDS.filter(([k]) => a["bl_" + k]).map(([k, l]) => l + ": " + a["bl_" + k]).join("  ·  ");
      if (blLine) body.appendChild(el("div.sub", { style: "margin-bottom:6px", text: "Baseline — " + blLine }));
      if (a.bl_goals) body.appendChild(el("div.sub", { style: "margin-bottom:6px", text: "Goals — " + a.bl_goals }));
      if (a.bl_notes) body.appendChild(el("div.sub", { style: "margin-bottom:6px", text: "Notes — " + a.bl_notes }));
      const mvals = metrics.filter((m) => a.values[m.key]).map((m) => m.icon + " " + m.name + ": " + a.values[m.key].value + " " + m.unit);
      if (mvals.length) body.appendChild(el("div", { style: "display:flex;flex-wrap:wrap;gap:6px;margin:6px 0" }, mvals.map((t) => el("span.pulse-tag", { text: t }))));
      body.appendChild(window.RowBox({ label: "notes", parentId: a.id }).node);
      window.Images.mount(body, { module: "pulse", contextId: a.id, surface: "pulse-snapshot", title: "Images" });
      body.appendChild(el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete this snapshot?", async () => { await BM().del(a.id); reload(); }), text: "× delete" }));
      card.appendChild(body);
    }
    return card;
  }

  // ---- metric config toggles ----
  function metricConfig(metrics, reload) {
    const wrap = el("div");
    ["fitness", "blood", "custom"].forEach((cat) => {
      const ms = metrics.filter((m) => m.category === cat);
      const color = cat === "blood" ? "var(--red)" : cat === "custom" ? "var(--dim)" : "#DE7BA4";
      wrap.appendChild(el("div.mform-label", { style: "margin:10px 0 6px;color:" + color, text: cat + " metrics" }));
      const row = el("div.row", { style: "gap:5px;flex-wrap:wrap" });
      ms.forEach((m) => row.appendChild(el("button.fit-toggle" + (m.tracked ? ".on" : ""), {
        onclick: () => guard(async () => { await BM().toggleMetric(m.key, { tracked: !m.tracked }); reload(); }), text: m.icon + " " + m.name,
      })));
      if (cat === "custom") row.appendChild(el("button.btn-sm", { onclick: () => addCustomModal(reload), text: "＋ custom metric" }));
      wrap.appendChild(row);
    });
    return wrap;
  }
  function addCustomModal(reload) {
    const name = el("input.mform-input", { placeholder: "metric name" });
    const unit = el("input.mform-input", { placeholder: "unit, e.g. kg" });
    P.modal("Add custom metric", [el("div.mform-row", {}, [el("div", {}, [el("div.mform-label", { text: "Name" }), name]), el("div", {}, [el("div.mform-label", { text: "Unit" }), unit])])], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!name.value.trim()) return toast("name it", true); await BM().addMetric({ name: name.value.trim(), unit: unit.value.trim() }); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    async function reload() {
      const [cmp, sched, bl] = await guard(() => Promise.all([BM().compare(), BM().schedule(), BM().baseline()]));
      clear(host);
      const logBtn = el("button.btn-primary", { onclick: () => logModal(cmp.metrics, cmp.assessments[0], bl, reload), text: "＋ Log snapshot" });
      host.appendChild(window.BENCH.scheduleBanner(sched, reload, logBtn));
      host.appendChild(el("div.pulse-card", { style: "overflow-x:auto" }, [el("h3", { style: "margin:0 0 10px", text: "Comparison" }), comparisonTable(cmp.metrics, cmp.assessments)]));
      const hist = el("div");
      hist.appendChild(el("div.mform-label", { style: "margin:16px 0 8px", text: "Saved snapshots" }));
      if (!cmp.assessments.length) hist.appendChild(el("div.empty", { text: "No snapshots yet." }));
      else cmp.assessments.forEach((a) => hist.appendChild(snapCard(a, cmp.metrics.filter((m) => m.tracked), reload)));
      host.appendChild(hist);
      host.appendChild(el("div.pulse-card", { style: "margin-top:12px" }, [el("h3", { style: "margin:0", text: "Metrics tracked" }), metricConfig(cmp.metrics, reload)]));
    }
    reload();
  }

  window.BENCH_TABS = window.BENCH_TABS || [];
  window.BENCH_TABS.push({ key: "snapshots", label: "Snapshots", render });
})();

/* benchmark-baseline.js — Benchmark ▸ Baseline. The "where I am now" card
   (editable, autosaves), the next-snapshot-due banner, and a one-click
   "📸 Save snapshot" that freezes the current baseline as a point in time.
   Also defines the shared window.BENCH helpers used by the other sub-views. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const BM = () => api.pulse.benchmarks;
  const FREQS = ["monthly", "quarterly", "6-monthly", "yearly"];

  // ---- shared helpers (used by snapshots + trends sub-views) ----
  const BENCH = window.BENCH = window.BENCH || {};
  BENCH.FREQS = FREQS;
  BENCH.BASELINE_FIELDS = [
    ["age", "Age", "age"], ["height", "Height", "e.g. 170cm"], ["weight", "Weight", "e.g. 70kg"],
    ["body_fat", "Body fat", "body fat %"], ["resting_hr", "Resting HR", "resting HR"],
  ];
  BENCH.scheduleBanner = function (sched, reload, actionNode) {
    const st = sched.status;
    const stColor = st === "overdue" ? "var(--red)" : st === "due-soon" ? "var(--amber)" : "var(--green)";
    const line = sched.next_due
      ? (st === "overdue" ? "⚠ Snapshot OVERDUE" : "Next snapshot due") + ": " + sched.next_due +
        (sched.days != null ? " (" + (sched.days < 0 ? Math.abs(sched.days) + " days ago" : "in " + sched.days + " days") + ")" : "")
      : "No snapshots yet — save your first.";
    const freq = el("select.mform-input", { style: "width:auto" }, FREQS.map((x) => el("option", { value: x, text: x })));
    freq.value = sched.frequency;
    freq.addEventListener("change", () => guard(async () => { await BM().setSchedule({ frequency: freq.value }); reload(); }));
    return el("div.pulse-card", { style: "border-left-color:" + stColor }, [
      el("div.spread", {}, [
        el("div", {}, [
          el("div", { style: "font-weight:600;color:" + stColor, text: line }),
          sched.last_assessment ? el("div.sub", { text: "Last snapshot: " + sched.last_assessment }) : null,
        ]),
        el("div.row", { style: "gap:8px" }, [el("span.sub", { text: "cadence" }), freq, actionNode || null]),
      ]),
    ]);
  };

  function baselineCard(bl) {
    const inp = {};
    const field = (key, label, ph) => {
      const i = el("input.mform-input", { placeholder: ph, value: bl[key] || "", style: "width:100%" });
      inp[key] = i;
      return el("div", {}, [el("div.mform-label", { text: label }), i]);
    };
    // Goals and notes are + rows on the one Baseline node (id "me"); they save
    // on Enter, and a snapshot freezes their text.
    const goals = window.RowBox({ label: "current goals", kind: "goal", noun: "goal", placeholder: "a current goal", parentId: bl.id || "me" });
    const notes = window.RowBox({ label: "notes", placeholder: "context, symptoms, how you feel…", parentId: bl.id || "me" });
    const save = () => guard(async () => {
      const body = {};
      BENCH.BASELINE_FIELDS.forEach(([k]) => { body[k] = inp[k].value.trim(); });
      await BM().setBaseline(body);
      toast("baseline saved");
    });
    const grid = el("div.bl-grid", {}, BENCH.BASELINE_FIELDS.map(([k, l, ph]) => field(k, l, ph)));
    Object.values(inp).forEach((i) => i.addEventListener("change", save));
    return el("div.pulse-card", {}, [
      el("h3", { style: "margin:0 0 4px", text: "Baseline — where I am now" }),
      grid,
      goals.node, notes.node,
    ]);
  }

  // ---- current blood work / biomarker readings (stored on the baseline as
  //      mv_<key>; frozen into snapshots so they trend over time) ----
  function biomarkerCard(bl, metrics, reload) {
    const cats = [["blood", "Blood work & biomarkers", "var(--red)"], ["fitness", "Fitness metrics", "#DE7BA4"], ["custom", "Custom", "var(--dim)"]];
    const card = el("div.pulse-card", {}, [
      el("div.spread", {}, [
        el("h3", { style: "margin:0", text: "Current readings" }),
        el("button.btn-sm", { onclick: () => addBiomarkerModal(reload), text: "＋ add biomarker" }),
      ]),
      el("div.sub", { style: "margin:2px 0 8px", text: "Your latest values. “Save snapshot” freezes these into the timeline." }),
    ]);
    let any = false;
    const saveVal = (key, i) => guard(async () => { await BM().setBaseline({ ["mv_" + key]: i.value.trim() }); toast("saved"); });
    cats.forEach(([cat, label, color]) => {
      const ms = metrics.filter((m) => m.tracked && m.category === cat);
      if (!ms.length) return;
      any = true;
      card.appendChild(el("div.mform-label", { style: "margin:10px 0 6px;color:" + color, text: label }));
      const grid = el("div.bl-grid");
      ms.forEach((m) => {
        const i = el("input.mform-input", { type: "number", step: "any", placeholder: m.unit, value: bl["mv_" + m.key] || "", style: "width:100%" });
        i.addEventListener("change", () => saveVal(m.key, i));
        grid.appendChild(el("div", {}, [el("div.mform-label", { text: m.icon + " " + m.name + (m.unit ? " (" + m.unit + ")" : "") }), i]));
      });
      card.appendChild(grid);
    });
    if (!any) card.appendChild(el("div.sub", { text: "No tracked metrics yet — add a biomarker, or enable metrics in Snapshots → Metrics tracked." }));
    return card;
  }

  function addBiomarkerModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Magnesium" });
    const unit = el("input.mform-input", { placeholder: "unit, e.g. mmol/L" });
    const hib = el("select.mform-input", {}, [el("option", { value: "true", text: "higher is better" }), el("option", { value: "false", text: "lower is better" })]);
    P.modal("Add biomarker", [
      el("div.mform-row", {}, [el("div", {}, [el("div.mform-label", { text: "Name" }), name]), el("div", {}, [el("div.mform-label", { text: "Unit" }), unit])]),
      el("div.mform-full", {}, [el("div.mform-label", { text: "Direction" }), hib]),
    ], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        await BM().addMetric({ name: name.value.trim(), unit: unit.value.trim(), category: "blood", higher_is_better: hib.value === "true" });
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    async function reload() {
      const [bl, sched, metrics] = await guard(() => Promise.all([BM().baseline(), BM().schedule(), BM().metrics()]));
      clear(host);
      const snapBtn = el("button.btn-primary", {
        onclick: () => guard(async () => {
          const s = await BM().quickSnapshot({});
          toast("snapshot saved — " + (s.label || s.date));
          reload();
        }),
        text: "📸 Save snapshot",
      });
      host.appendChild(BENCH.scheduleBanner(sched, reload, snapBtn));
      host.appendChild(baselineCard(bl));
      host.appendChild(biomarkerCard(bl, metrics, reload));
      host.appendChild(el("div.sub", { style: "margin-top:8px", text: "“Save snapshot” freezes the baseline + these current readings at today’s date. Loose thoughts → the shared Mind Dump." }));
    }
    reload();
  }

  window.BENCH_TABS = window.BENCH_TABS || [];
  window.BENCH_TABS.push({ key: "baseline", label: "Baseline", render });
})();

/* benchmark-fitness-test.js — the fitness baseline test.

   The fixed reference point every later assessment is measured against.
   Exactly one test carries the reference flag; recording a new one moves it,
   so Benchmark always has a single origin.

   Comparison is direction-aware: a faster 5k and a lower resting heart rate are
   improvements, not regressions. Weight and girths are reported as neutral —
   cutting and bulking pull opposite ways, so the change is shown without being
   judged. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const MEASURE = [
    ["weight_kg", "weight", "kg"], ["height_cm", "height", "cm"],
    ["body_fat_pct", "body fat", "%"], ["resting_hr", "resting HR", "bpm"],
    ["waist_cm", "waist", "cm"], ["chest_cm", "chest", "cm"],
    ["arm_cm", "arm", "cm"], ["thigh_cm", "thigh", "cm"],
  ];
  const PERFORM = [
    ["push_ups", "push-ups", "reps"], ["pull_ups", "pull-ups", "reps"],
    ["squat_kg", "squat", "kg"], ["bench_kg", "bench", "kg"],
    ["deadlift_kg", "deadlift", "kg"], ["plank_secs", "plank", "secs"],
    ["run_5k_mins", "5k run", "mins"], ["vo2max", "VO₂max", ""],
  ];
  const LABEL = Object.fromEntries([...MEASURE, ...PERFORM].map(([k, l, u]) => [k, l + (u ? " (" + u + ")" : "")]));

  async function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);

    async function reload() {
      const [data, cmp] = await guard(() => Promise.all([
        api.get("/api/pulse/fitness/baseline-test"),
        api.get("/api/pulse/fitness/baseline-test/compare"),
      ]));
      clear(body);
      const ref = data.reference;

      body.appendChild(el("div.sub", {
        text: ref
          ? "Reference point recorded " + ref.date + " — every assessment below is measured against it."
          : "No baseline yet. Record one and it becomes the reference every future assessment compares against.",
      }));

      // --- the comparison, when there's something later to compare ---
      if (cmp.metrics && cmp.metrics.some((m) => m.current != null)) {
        const t = el("table.wk-table");
        t.appendChild(el("tr", {}, ["metric", "baseline", "latest", "change", ""].map((h) => el("th", { text: h }))));
        cmp.metrics.filter((m) => m.current != null).forEach((m) => {
          const col = m.neutral ? "var(--dim)" : (m.improved ? "var(--teal)" : "var(--red)");
          const verdict = m.neutral ? "—" : (m.improved ? "✓ better" : "✗ worse");
          t.appendChild(el("tr.wk-row", {}, [
            el("td", { text: LABEL[m.metric] || m.metric }),
            el("td", { class: "mono", style: "font-size:11px", text: String(m.baseline) }),
            el("td", { class: "mono", style: "font-size:11px", text: String(m.current) }),
            el("td", { class: "mono", style: "font-size:11px;color:" + col, text: (m.delta > 0 ? "+" : "") + m.delta }),
            el("td", { style: "font-size:11px;color:" + col, text: verdict + (m.lower_is_better ? "  (lower is better)" : "") }),
          ]));
        });
        body.appendChild(el("div.card", { style: "margin-top:12px" }, [
          el("div.spread", {}, [
            el("h3", { style: "margin:0", text: "Against the baseline" }),
            el("span.sub", { text: (cmp.compared_to || {}).date ? "latest test " + cmp.compared_to.date : "" }),
          ]),
          el("div.wk-scroll", { style: "margin-top:10px" }, [t]),
        ]));
      }

      // --- record a test ---
      const inputs = {};
      const group = (title, spec) => {
        const rows = spec.map(([key, label, unit]) => {
          const n = el("input", { type: "number", step: "0.1", min: "0", style: "width:92px",
            value: ref && ref[key] != null ? String(ref[key]) : "" });
          inputs[key] = n;
          return el("label.wl-field", {}, [el("span.wl-label", { text: label + (unit ? " · " + unit : "") }), n]);
        });
        return el("div", { style: "margin-top:10px" }, [
          el("div.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px", text: title }),
          el("div.row", { style: "gap:10px;margin-top:6px;flex-wrap:wrap" }, rows),
        ]);
      };
      const date = el("input", { type: "date", value: new Date().toISOString().slice(0, 10) });
      const notes = el("input", { placeholder: "notes", style: "flex:1;min-width:200px" });

      body.appendChild(el("div.card", { style: "margin-top:12px" }, [
        el("div.spread", {}, [
          el("h3", { style: "margin:0", text: ref ? "Record a new test" : "Record the baseline test" }),
          el("span.sub", { text: "saving marks this one as the reference" }),
        ]),
        el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap" }, [
          el("label.wl-field", {}, [el("span.wl-label", { text: "date" }), date]), notes,
        ]),
        group("Measurements", MEASURE),
        group("Performance", PERFORM),
        el("div.row", { style: "margin-top:12px" }, [
          el("button.btn-primary", {
            onclick: () => guard(async () => {
              const payload = { date: date.value, notes: notes.value.trim() };
              let any = false;
              Object.entries(inputs).forEach(([k, n]) => {
                if (n.value !== "") { payload[k] = Number(n.value); any = true; }
              });
              if (!any) return toast("fill in at least one measurement", true);
              await api.put("/api/pulse/fitness/baseline-test", payload);
              toast("baseline recorded — this is now the reference");
              reload();
            }),
            text: ref ? "save as the new reference" : "set the baseline",
          }),
        ]),
      ]));

      // --- history ---
      if ((data.all || []).length > 1) {
        const list = el("div", { style: "margin-top:10px;display:flex;flex-direction:column;gap:4px" });
        data.all.forEach((t) => list.appendChild(el("div.row", { style: "gap:8px" }, [
          el("span.mono", { style: "font-size:11px", text: t.date }),
          t.is_reference ? el("span.pill", { style: "color:var(--teal)", text: "reference" }) : el("span.sub", { style: "font-size:11px", text: "assessment" }),
          el("span.sub", { style: "font-size:11px", text: t.notes || "" }),
        ])));
        body.appendChild(el("div.card", { style: "margin-top:12px" }, [
          el("div.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px", text: "History" }), list,
        ]));
      }
    }
    await reload();
  }

  window.BENCH_TABS = window.BENCH_TABS || [];
  window.BENCH_TABS.push({ key: "fitness-test", label: "Fitness Test", render });
})();

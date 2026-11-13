/* nutrition-goals.js — targets and preferences (NUTRITION_SPEC §8).

   Macros can be set in grams or as percentages of the calorie target. The two
   are kept in step: type a percentage and the grams follow, using 4/4/9 kcal
   per gram, so the split always adds up to the calories you set. */
(function () {
  const { el, clear, toast, guard } = window.ui;

  const KCAL_PER_G = { protein: 4, carbs: 4, fat: 9 };
  const PRESETS = [
    { key: "balanced", label: "Balanced", split: { protein: 30, carbs: 40, fat: 30 } },
    { key: "high_protein", label: "High protein", split: { protein: 40, carbs: 30, fat: 30 } },
    { key: "keto", label: "Keto", split: { protein: 25, carbs: 5, fat: 70 } },
  ];

  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);
    const reload = () => render(host);

    guard(async () => {
      const { N, field, numInput, MACRO, n0 } = window.NUT;
      const g = await N().goals();
      clear(body);

      const mode = el("select.mform-input", {}, [
        el("option", { value: "grams", text: "grams" }),
        el("option", { value: "percentage", text: "percentage of calories" }),
      ]);
      mode.value = g.macro_mode || "grams";

      const cals = numInput(g.daily_calories);
      const gram = {
        protein: numInput(g.protein_g), carbs: numInput(g.carbs_g), fat: numInput(g.fat_g),
      };
      const pctIn = { protein: numInput(), carbs: numInput(), fat: numInput() };
      const split = el("div.sub", { style: "font-size:11px" });

      const gramsFromPct = () => {
        const c = parseFloat(cals.value) || 0;
        MACRO.forEach((m) => {
          const p = parseFloat(pctIn[m.key].value) || 0;
          gram[m.key].value = Math.round((c * (p / 100)) / KCAL_PER_G[m.key]);
        });
      };
      const pctFromGrams = () => {
        const c = parseFloat(cals.value) || 0;
        MACRO.forEach((m) => {
          const grams = parseFloat(gram[m.key].value) || 0;
          pctIn[m.key].value = c ? Math.round(((grams * KCAL_PER_G[m.key]) / c) * 100) : 0;
        });
      };
      const showSplit = () => {
        const c = parseFloat(cals.value) || 0;
        const kcal = MACRO.reduce((s, m) => s + (parseFloat(gram[m.key].value) || 0) * KCAL_PER_G[m.key], 0);
        const pctSum = MACRO.reduce((s, m) => s + (parseFloat(pctIn[m.key].value) || 0), 0);
        // A split that doesn't add up is the classic way targets end up wrong —
        // say so rather than silently accepting it.
        split.textContent = "macros come to " + n0(kcal) + " kcal of " + n0(c)
          + (Math.abs(kcal - c) > 50 ? "  ⚠ that's " + n0(Math.abs(kcal - c)) + " " + (kcal > c ? "over" : "under") : "  ✓")
          + "   ·   " + pctSum + "% assigned";
        split.style.color = Math.abs(kcal - c) > 50 ? "var(--amber)" : "var(--dim)";
      };

      pctFromGrams(); showSplit();
      MACRO.forEach((m) => {
        gram[m.key].addEventListener("input", () => { pctFromGrams(); showSplit(); });
        pctIn[m.key].addEventListener("input", () => { gramsFromPct(); showSplit(); });
      });
      cals.addEventListener("input", () => {
        if (mode.value === "percentage") gramsFromPct(); else pctFromGrams();
        showSplit();
      });

      const gramRow = el("div.bl-grid", {}, MACRO.map((m) =>
        el("div", {}, [el("div.mform-label", { style: "color:" + m.colour, text: m.label + " (g)" }), gram[m.key]])));
      const pctRow = el("div.bl-grid", {}, MACRO.map((m) =>
        el("div", {}, [el("div.mform-label", { style: "color:" + m.colour, text: m.label + " (%)" }), pctIn[m.key]])));
      const applyMode = () => {
        gramRow.style.display = mode.value === "grams" ? "grid" : "none";
        pctRow.style.display = mode.value === "percentage" ? "grid" : "none";
      };
      mode.addEventListener("change", applyMode);
      applyMode();

      const presets = el("div.row", { style: "gap:6px;flex-wrap:wrap" }, PRESETS.map((p) =>
        el("button.btn-sm", { text: p.label, onclick: () => {
          mode.value = "percentage"; applyMode();
          MACRO.forEach((m) => { pctIn[m.key].value = p.split[m.key]; });
          gramsFromPct(); showSplit();
        } })));

      const fibre = numInput(g.fibre_g);
      const water = numInput(g.water_ml);
      const height = numInput(g.height_cm, "cm");
      const wTarget = numInput(g.weight_target, "kg");
      const wGoal = el("select.mform-input", {}, ["lose", "maintain", "gain"].map((x) =>
        el("option", { value: x, text: x })));
      wGoal.value = g.weight_goal || "maintain";
      const fast = el("input.mform-input", { value: g.fasting_protocol || "", placeholder: "e.g. 16:8 (optional)" });

      body.appendChild(el("div.card", {}, [
        el("h3", { style: "margin:0 0 10px", text: "Daily targets" }),
        el("div.mform-row", {}, [field("Calories", cals), field("Macros as", mode)]),
        el("div.mform-label", { style: "margin-top:6px", text: "Presets" }), presets,
        el("div", { style: "margin-top:10px" }, [gramRow, pctRow]),
        split,
        el("div.mform-row", { style: "margin-top:10px" }, [field("Fibre (g)", fibre), field("Water (ml)", water)]),
      ]));

      body.appendChild(el("div.card", { style: "margin-top:12px" }, [
        el("h3", { style: "margin:0 0 10px", text: "Body" }),
        el("div.sub", { style: "font-size:11px;margin-bottom:8px",
          text: "Height is used for BMI and waist-to-height — set it once." }),
        el("div.mform-row", {}, [field("Height (cm)", height), field("Target weight (kg)", wTarget)]),
        el("div.mform-row", {}, [field("Goal", wGoal), field("Fasting protocol", fast)]),
      ]));

      body.appendChild(el("div.row", { style: "gap:8px;margin-top:12px" }, [
        el("button.btn-primary", { text: "Save targets", onclick: () => guard(async () => {
          await N().setGoals({
            daily_calories: parseInt(cals.value) || 0,
            protein_g: parseInt(gram.protein.value) || 0,
            carbs_g: parseInt(gram.carbs.value) || 0,
            fat_g: parseInt(gram.fat.value) || 0,
            fibre_g: parseInt(fibre.value) || 0,
            water_ml: parseInt(water.value) || 0,
            height_cm: parseFloat(height.value) || null,
            weight_target: parseFloat(wTarget.value) || null,
            weight_goal: wGoal.value,
            fasting_protocol: fast.value.trim(),
            macro_mode: mode.value,
          });
          toast("targets saved"); reload();
        }) }),
      ]));
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "goals", label: "Goals", order: 70, undecided: true, render });
})();

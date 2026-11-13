/* nutrition-common.js — shared bits for the eight Nutrition tabs (NUTRITION_SPEC).

   Loaded before every nutrition-*.js. Holds the vocabulary the spec fixes —
   meal slots, food categories, serving units, macro colours — so the tabs can't
   drift apart on naming or colour. */
(function () {
  const { el } = window.ui;

  const N = () => window.api.pulse.nutrition;

  // Spec's slots. Custom slots are allowed; these are the ones that always exist.
  const SLOTS = [
    { key: "breakfast", icon: "🌅", label: "Breakfast" },
    { key: "lunch", icon: "🌞", label: "Lunch" },
    { key: "dinner", icon: "🌙", label: "Dinner" },
    { key: "snacks", icon: "🍎", label: "Snacks" },
    { key: "pre_workout", icon: "☕", label: "Pre-workout" },
    { key: "post_workout", icon: "🥤", label: "Post-workout" },
  ];
  const SLOT = (k) => SLOTS.find((s) => s.key === k) || { key: k, icon: "🍽", label: k };

  const CATEGORIES = [
    { key: "protein", icon: "🥩", label: "Protein" },
    { key: "grains", icon: "🍚", label: "Grains & carbs" },
    { key: "vegetables", icon: "🥬", label: "Vegetables" },
    { key: "fruit", icon: "🍎", label: "Fruit" },
    { key: "dairy", icon: "🥛", label: "Dairy" },
    { key: "nuts_seeds", icon: "🥜", label: "Nuts & seeds" },
    { key: "oils_fats", icon: "🫒", label: "Oils & fats" },
    { key: "bread_bakery", icon: "🍞", label: "Bread & bakery" },
    { key: "drinks", icon: "🥤", label: "Drinks" },
    { key: "snacks", icon: "🍫", label: "Snacks" },
    { key: "condiments", icon: "🧂", label: "Condiments" },
    { key: "prepared_meals", icon: "🍽", label: "Prepared meals" },
    { key: "other", icon: "📌", label: "Other" },
  ];
  const CAT = (k) => CATEGORIES.find((c) => c.key === k) || CATEGORIES[CATEGORIES.length - 1];

  const UNITS = ["g", "ml", "piece", "slice", "cup", "tbsp", "tsp", "scoop", "bowl", "can", "bottle", "serving"];

  // Spec's macro colours — protein blue, carbs amber, fat pink. Consistent everywhere.
  const MACRO = [
    { key: "protein", label: "Protein", colour: "#5DA9FF", unit: "g", goal: "protein_g" },
    { key: "carbs", label: "Carbs", colour: "#F4B43C", unit: "g", goal: "carbs_g" },
    { key: "fat", label: "Fat", colour: "#DE7BA4", unit: "g", goal: "fat_g" },
  ];
  const GREEN = "#7ED957";          // nutrition accent
  const today = () => window.ui.todayISO();
  const n1 = (v) => Math.round((Number(v) || 0) * 10) / 10;
  const n0 = (v) => Math.round(Number(v) || 0);

  /* Calorie ring — the dashboard's hero visual. Green on track, amber from 80%,
     red once over. Inline SVG, no libraries. */
  function calorieRing(consumed, target, size) {
    const s = size || 190;
    const r = s / 2 - 14;
    const circ = 2 * Math.PI * r;
    const pct = target > 0 ? consumed / target : 0;
    const colour = pct > 1 ? "#FF4757" : pct >= 0.8 ? "#F4B43C" : GREEN;
    const SVG = "http://www.w3.org/2000/svg";
    const mk = (t, a) => { const n = document.createElementNS(SVG, t); for (const k in a) n.setAttribute(k, a[k]); return n; };
    const svg = mk("svg", { width: s, height: s, viewBox: `0 0 ${s} ${s}` });
    svg.appendChild(mk("circle", { cx: s / 2, cy: s / 2, r, fill: "none", stroke: "#1b2733", "stroke-width": 12 }));
    svg.appendChild(mk("circle", {
      cx: s / 2, cy: s / 2, r, fill: "none", stroke: colour, "stroke-width": 12,
      "stroke-linecap": "round",
      // clamp the arc at a full turn — 3,000 calories over target shouldn't
      // wrap the ring round twice and read as "nearly done"
      "stroke-dasharray": `${Math.min(pct, 1) * circ} ${circ}`,
      transform: `rotate(-90 ${s / 2} ${s / 2})`,
    }));
    const big = mk("text", { x: s / 2, y: s / 2 - 2, "text-anchor": "middle", fill: colour,
      "font-size": "30", "font-weight": "600", "font-family": "ui-monospace, Menlo, monospace" });
    big.textContent = n0(consumed);
    svg.appendChild(big);
    const sub = mk("text", { x: s / 2, y: s / 2 + 20, "text-anchor": "middle", fill: "#7b8b9a",
      "font-size": "12", "font-family": "ui-monospace, Menlo, monospace" });
    sub.textContent = "of " + n0(target) + " kcal";
    svg.appendChild(sub);
    const rem = mk("text", { x: s / 2, y: s / 2 + 38, "text-anchor": "middle",
      fill: pct > 1 ? "#FF4757" : "#5c6b7a", "font-size": "11",
      "font-family": "ui-monospace, Menlo, monospace" });
    rem.textContent = pct > 1 ? n0(consumed - target) + " over" : n0(target - consumed) + " left";
    svg.appendChild(rem);
    return svg;
  }

  /* One macro bar: consumed vs target with a percentage. */
  function macroBar(m, consumed, target) {
    const pct = target > 0 ? Math.min(consumed / target, 1) * 100 : 0;
    const over = target > 0 && consumed > target;
    return el("div.nt-macro", {}, [
      el("div.row", { style: "justify-content:space-between;font-size:11px" }, [
        el("span", { style: "color:" + m.colour, text: m.label }),
        el("span.mono", { style: "color:var(--dim)",
          text: n1(consumed) + " / " + n0(target) + m.unit
            + (target > 0 ? "  ·  " + Math.round((consumed / target) * 100) + "%" : "") }),
      ]),
      el("div.nt-bar", {}, [
        el("div.nt-bar-fill", { style: "width:" + pct + "%;background:" + (over ? "#FF4757" : m.colour) }),
      ]),
    ]);
  }

  function slotSelect(value) {
    const s = el("select.mform-input", {}, SLOTS.map((x) =>
      el("option", { value: x.key, text: x.icon + "  " + x.label })));
    s.value = value || "snacks";
    return s;
  }

  function unitSelect(value) {
    const s = el("select.mform-input", {}, UNITS.map((u) => el("option", { value: u, text: u })));
    s.value = value || "g";
    return s;
  }

  function categorySelect(value) {
    const s = el("select.mform-input", {}, CATEGORIES.map((c) =>
      el("option", { value: c.key, text: c.icon + "  " + c.label })));
    s.value = value || "other";
    return s;
  }

  function field(label, node) {
    return el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);
  }
  function numInput(value, placeholder) {
    return el("input.mform-input", { type: "number", min: "0", step: "any",
      value: value == null ? "" : String(value), placeholder: placeholder || "" });
  }

  window.NUT = { N, SLOTS, SLOT, CATEGORIES, CAT, UNITS, MACRO, GREEN, today, n0, n1,
                 calorieRing, macroBar, slotSelect, unitSelect, categorySelect, field, numInput };
})();

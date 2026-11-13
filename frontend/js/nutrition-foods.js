/* nutrition-foods.js — My Foods, your personal food database (NUTRITION_SPEC §3).

   Starts empty and grows only from foods you actually eat. Sorted most-used
   first, because repeat logging is the common case and the spec says search must
   put your usual foods at the top.

   Only name, serving and the four macros are required. Everything else — fibre,
   sugar, sodium, vitamins — is optional and tucked behind a toggle, per the
   spec's explicit DO-NOT about demanding micronutrients. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const P = window.PULSE;

  let query = "", category = "";

  const OPTIONAL = [
    ["fibre", "Fibre (g)"], ["sugar", "Sugar (g)"], ["saturated_fat", "Saturated fat (g)"],
    ["sodium", "Sodium (mg)"], ["potassium", "Potassium (mg)"], ["cholesterol", "Cholesterol (mg)"],
    ["vitamin_a", "Vitamin A (%)"], ["vitamin_c", "Vitamin C (%)"],
    ["calcium", "Calcium (%)"], ["iron", "Iron (%)"],
  ];

  /* `prefill` fills the form without making it an edit — the barcode scanner
     uses it to hand over a code it read off a packet the catalogue doesn't
     know, so the next scan of that packet finds your own entry. */
  function foodModal(existing, reload, prefill) {
    const { N, field, numInput, unitSelect, categorySelect } = window.NUT;
    const f = existing || prefill || {};
    const name = el("input.mform-input", { value: f.name || "", placeholder: "e.g. Chicken breast, grilled" });
    const brand = el("input.mform-input", { value: f.brand || "", placeholder: "Tesco, homemade… (optional)" });
    const cat = categorySelect(f.category);
    const size = numInput(f.serving_size != null ? f.serving_size : 100);
    const unit = unitSelect(f.serving_unit || "g");
    const cal = numInput(f.calories), pro = numInput(f.protein), carb = numInput(f.carbs), fat = numInput(f.fat);

    const optInputs = {};
    const optBox = el("div", { style: "display:none" }, [
      el("div.bl-grid", {}, OPTIONAL.map(([k, l]) => {
        const i = numInput(f[k]);
        optInputs[k] = i;
        return el("div", {}, [el("div.mform-label", { text: l }), i]);
      })),
    ]);
    const optBtn = el("button.btn-sm", { type: "button", text: "+ optional nutrients" });
    optBtn.addEventListener("click", () => {
      const on = optBox.style.display === "none";
      optBox.style.display = on ? "block" : "none";
      optBtn.textContent = on ? "− optional nutrients" : "+ optional nutrients";
    });

    const barcode = el("input.mform-input", { value: f.barcode || "",
      placeholder: "barcode — scan it, or type it off the packet" });

    P.modal(existing ? "Edit food" : "Add a food", [
      field("Name", name),
      el("div.mform-row", {}, [field("Brand", brand), field("Category", cat)]),
      el("div.sub", { style: "font-size:11px",
        text: "Everything below is PER SERVING — a slice, a scoop, 150g. Logging is then “one of those”." }),
      el("div.mform-row", {}, [field("Serving size", size), field("Unit", unit)]),
      el("div.bl-grid", {}, [
        el("div", {}, [el("div.mform-label", { text: "Calories" }), cal]),
        el("div", {}, [el("div.mform-label", { text: "Protein (g)" }), pro]),
        el("div", {}, [el("div.mform-label", { text: "Carbs (g)" }), carb]),
        el("div", {}, [el("div.mform-label", { text: "Fat (g)" }), fat]),
      ]),
      el("div.row", { style: "margin-top:8px" }, [optBtn]),
      optBox,
      el("div.row", { style: "gap:8px;align-items:flex-end" }, [
        el("div", { style: "flex:1" }, [field("Barcode", barcode)]),
        window.NUT.scanButton
          ? window.NUT.scanButton(null, "📷 scan",
              { onCode: (code) => { barcode.value = code; } })
          : null,
      ]),
    ], [
      { label: existing ? "Save" : "Add", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("a food needs a name", true);
        const body = {
          name: name.value.trim(), brand: brand.value.trim(), category: cat.value,
          serving_size: parseFloat(size.value) || 100, serving_unit: unit.value,
          calories: parseFloat(cal.value) || 0, protein: parseFloat(pro.value) || 0,
          carbs: parseFloat(carb.value) || 0, fat: parseFloat(fat.value) || 0,
          barcode: barcode.value.trim(),
        };
        // only send optional values that were actually filled in
        OPTIONAL.forEach(([k]) => {
          const v = parseFloat(optInputs[k].value);
          if (!isNaN(v)) body[k] = v;
        });
        if (existing) await N().updateFood(existing.id, body);
        else await N().addFood(body);
        toast(existing ? "saved" : "added"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
    name.focus();
  }

  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);
    const reload = () => render(host);

    guard(async () => {
      const { N, CAT, CATEGORIES, n0, n1 } = window.NUT;
      const qs = [];
      if (query) qs.push("q=" + encodeURIComponent(query));
      if (category) qs.push("category=" + encodeURIComponent(category));
      const foods = await N().foods(qs.length ? "?" + qs.join("&") : "");
      clear(body);

      const search = el("input.mform-input", { value: query, placeholder: "search your foods…", style: "flex:1;min-width:160px" });
      let t = null;
      search.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(() => { query = search.value.trim(); reload(); }, 200);
      });
      const catSel = el("select.mform-input", { style: "width:auto" }, [
        el("option", { value: "", text: "all categories" }),
        ...CATEGORIES.map((c) => el("option", { value: c.key, text: c.icon + "  " + c.label })),
      ]);
      catSel.value = category;
      catSel.addEventListener("change", () => { category = catSel.value; reload(); });

      body.appendChild(el("div.row", { style: "gap:8px;flex-wrap:wrap;align-items:center" }, [
        search, catSel,
        // The catalogue lives in its own tab, but reaching it from here is the
        // natural move — this is where you notice a food is missing.
        window.NUT.catalogPicker
          ? el("button.btn-sm", { title: "search the USDA food database",
              onclick: () => window.NUT.catalogPicker(() => reload()), text: "🔍 food database" })
          : null,
        // The fastest route of all for anything packaged: hold it up to the camera.
        window.NUT.scanButton ? window.NUT.scanButton(() => reload(), "📷 scan a packet") : null,
        el("button.btn-sm.btn-primary", { onclick: () => foodModal(null, reload), text: "+ add a food" }),
      ]));

      if (!foods.length) {
        body.appendChild(el("div.empty", { style: "margin-top:14px" }, query || category
          ? [el("div", { text: "Nothing matches." })]
          : [
              el("div", { text: "Your food library is empty — and that's deliberate. It fills with the foods you actually eat, so search stays fast and the numbers stay yours." }),
              el("div.sub", { style: "font-size:11px;margin-top:10px",
                text: "You don't have to type them in, though — pull them from the USDA food database." }),
              el("div.row", { style: "margin-top:10px;gap:8px;justify-content:center" }, [
                window.NUT.catalogPicker
                  ? el("button.btn-sm.btn-primary", { text: "🔍 search the food database",
                      onclick: () => window.NUT.catalogPicker(() => reload()) })
                  : null,
                window.NUT.scanButton ? window.NUT.scanButton(() => reload(), "📷 scan a packet") : null,
              ]),
            ]));
        return;
      }

      body.appendChild(el("div.sub", { style: "margin:12px 0 6px;font-size:11px",
        text: foods.length + " food" + (foods.length === 1 ? "" : "s") + " · most-used first" }));

      foods.forEach((f) => {
        const c = CAT(f.category);
        body.appendChild(el("div.nt-food", {}, [
          el("span", { title: c.label, text: c.icon }),
          el("div", { style: "flex:1;min-width:0" }, [
            el("div", { text: f.name + (f.brand ? "  ·  " + f.brand : "") }),
            el("div.sub", { style: "font-size:10.5px",
              text: n0(f.calories) + " cal · P" + n1(f.protein) + " C" + n1(f.carbs) + " F" + n1(f.fat)
                + "   per " + n1(f.serving_size) + " " + (f.serving_unit || "") }),
          ]),
          f.use_count ? el("span.sub", { style: "font-size:10px", title: "times logged", text: "×" + f.use_count }) : null,
          el("button.btn-sm", { title: f.favourite ? "unstar" : "star for quick access",
            text: f.favourite ? "★" : "☆",
            onclick: () => guard(async () => {
              await window.NUT.N().updateFood(f.id, { favourite: !f.favourite }); reload();
            }) }),
          el("button.btn-sm", { text: "✎", onclick: () => foodModal(f, reload) }),
          el("button.btn-sm.btn-danger", { text: "×",
            onclick: () => confirmDo(
              "Delete “" + f.name + "”?\n\nEntries you've already logged keep their numbers — deleting a food doesn't rewrite what you ate.",
              async () => { await window.NUT.N().delFood(f.id); toast("deleted"); reload(); }) }),
        ]));
      });
    });
  }

  window.NUT = window.NUT || {};
  window.NUT.foodModal = foodModal;

  window.NUT_TABS = window.NUT_TABS || [];
  // Dropped from the Nutrition tab bar 2026-08-18 (user: "the rest i dont think need to stay").
  // The view still works — uncomment to bring it back. Data is untouched either way.
  // window.NUT_TABS.push({ key: "foods", label: "My Foods", order: 30, render });
})();

/* nutrition-recipes.js — saved meals (NUTRITION_SPEC §4).

   A recipe's totals and per-serving figures are always DERIVED from its
   ingredients — never typed — so they can't drift from what's in it. Change the
   servings and everything rescales. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const P = window.PULSE;

  const CATS = ["breakfast", "lunch", "dinner", "snack", "other"];
  const open = new Set();

  function recipeModal(existing, reload) {
    const { N, field, numInput, unitSelect, n1, n0 } = window.NUT;
    const r = existing || {};
    const name = el("input.mform-input", { value: r.name || "", placeholder: "e.g. Protein omelette" });
    const servings = numInput(r.servings || 1);
    const cat = el("select.mform-input", {}, CATS.map((c) => el("option", { value: c, text: c })));
    cat.value = r.category || "other";
    const prep = numInput(r.prep_time, "min"), cook = numInput(r.cook_time, "min");
    // Steps as + rows: saved straight onto an existing recipe, held for a new
    // one until it has an id.
    const steps = window.RowBox({ label: "steps", kind: "step", noun: "step", placeholder: "the next step",
      parentId: existing ? existing.id : undefined });

    let ingredients = (r.ingredients || []).map((i) => ({ ...i }));
    const list = el("div");
    const totals = el("div.sub", { style: "font-size:11px;margin-top:6px" });

    const recalc = () => {
      const t = ["calories", "protein", "carbs", "fat"].reduce((a, k) => {
        a[k] = ingredients.reduce((s, i) => s + (Number(i[k]) || 0), 0); return a;
      }, {});
      const n = Math.max(1, parseInt(servings.value) || 1);
      totals.textContent = "total " + n0(t.calories) + " cal · P" + n1(t.protein) + " C" + n1(t.carbs) + " F" + n1(t.fat)
        + "   →   per serving " + n0(t.calories / n) + " cal · P" + n1(t.protein / n)
        + " C" + n1(t.carbs / n) + " F" + n1(t.fat / n);
    };
    servings.addEventListener("input", recalc);

    const drawList = () => {
      clear(list);
      if (!ingredients.length) list.appendChild(el("div.sub", { style: "font-size:11px", text: "No ingredients yet." }));
      ingredients.forEach((ing, idx) => {
        list.appendChild(el("div.nt-entry", {}, [
          el("div", { style: "flex:1;min-width:0" }, [
            el("div", { text: ing.food_name }),
            el("div.sub", { style: "font-size:10.5px",
              text: n1(ing.serving_size) + " " + (ing.serving_unit || "") + " · " + n0(ing.calories)
                + " cal · P" + n1(ing.protein) + " C" + n1(ing.carbs) + " F" + n1(ing.fat) }),
          ]),
          el("button.btn-sm.btn-danger", { text: "×", onclick: () => {
            ingredients.splice(idx, 1); drawList(); recalc();
          } }),
        ]));
      });
      recalc();
    };

    /* Add an ingredient: pick from My Foods, or type one that isn't in the
       library — a recipe mustn't demand every ingredient already exists. */
    const pickName = el("input.mform-input", { placeholder: "search My Foods, or just type a name" });
    const pickSize = numInput(1);
    const pickUnit = unitSelect("serving");
    const pickCal = numInput("", "cal"), pickP = numInput("", "P"), pickC = numInput("", "C"), pickF = numInput("", "F");
    const hits = el("div.nt-results");
    let chosen = null;
    let t = null;
    pickName.addEventListener("input", () => {
      chosen = null;
      clearTimeout(t);
      t = setTimeout(() => guard(async () => {
        const q = pickName.value.trim();
        if (!q) { clear(hits); return; }
        const found = await N().foods("?q=" + encodeURIComponent(q));
        clear(hits);
        found.slice(0, 6).forEach((f) => hits.appendChild(el("div.nt-result", {
          onclick: () => {
            chosen = f;
            pickName.value = f.name;
            pickCal.value = f.calories; pickP.value = f.protein;
            pickC.value = f.carbs; pickF.value = f.fat;
            pickSize.value = 1; pickUnit.value = "serving";
            clear(hits);
          },
        }, [el("div", { style: "flex:1" }, [
          el("div", { text: f.name }),
          el("div.sub", { style: "font-size:10.5px", text: n0(f.calories) + " cal per " + n1(f.serving_size) + f.serving_unit }),
        ])])));
      }), 200);
    });

    const addIng = () => {
      const nm = pickName.value.trim();
      if (!nm) return toast("name the ingredient", true);
      const mult = parseFloat(pickSize.value) || 1;
      // A library food's macros are per serving, so scale by the amount; a
      // typed ingredient's numbers are taken as entered.
      const base = { calories: parseFloat(pickCal.value) || 0, protein: parseFloat(pickP.value) || 0,
                     carbs: parseFloat(pickC.value) || 0, fat: parseFloat(pickF.value) || 0 };
      ingredients.push({
        food_id: chosen ? chosen.id : null, food_name: nm,
        serving_size: mult, serving_unit: pickUnit.value,
        calories: chosen ? base.calories * mult : base.calories,
        protein: chosen ? base.protein * mult : base.protein,
        carbs: chosen ? base.carbs * mult : base.carbs,
        fat: chosen ? base.fat * mult : base.fat,
      });
      chosen = null;
      pickName.value = ""; [pickCal, pickP, pickC, pickF].forEach((i) => { i.value = ""; });
      pickSize.value = 1;
      drawList();
    };

    P.modal(existing ? "Edit recipe" : "New recipe", [
      field("Name", name),
      el("div.mform-row", {}, [field("Servings it makes", servings), field("Category", cat)]),
      el("div.mform-row", {}, [field("Prep (min)", prep), field("Cook (min)", cook)]),
      el("div.mform-label", { text: "Ingredients" }), list, totals,
      el("div.row", { style: "gap:6px;margin-top:8px;flex-wrap:wrap;align-items:flex-start" }, [
        el("div", { style: "flex:2;min-width:170px" }, [pickName, hits]),
        pickSize, pickUnit, pickCal, pickP, pickC, pickF,
        el("button.btn-sm", { onclick: addIng, text: "+ ingredient" }),
      ]),
      steps.node,
    ], [
      { label: existing ? "Save" : "Create", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("a recipe needs a name", true);
        const body = {
          name: name.value.trim(), servings: Math.max(1, parseInt(servings.value) || 1),
          category: cat.value,
          prep_time: parseInt(prep.value) || null, cook_time: parseInt(cook.value) || null,
          ingredients,
        };
        if (existing) await N().updateRecipe(existing.id, body);
        else { const made = await N().addRecipe(body); await steps.commit(made.id); }
        toast(existing ? "saved" : "created"); close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
    drawList();
    name.focus();
  }

  function logModal(r, reload) {
    const { N, field, numInput, slotSelect, n0 } = window.NUT;
    const servings = numInput(1);
    const slot = slotSelect("dinner");
    const out = el("div.sub", { style: "font-size:11px" });
    const show = () => {
      const s = parseFloat(servings.value) || 0;
      out.textContent = n0((r.per_serving.calories || 0) * s) + " cal · P"
        + window.NUT.n1((r.per_serving.protein || 0) * s)
        + " C" + window.NUT.n1((r.per_serving.carbs || 0) * s)
        + " F" + window.NUT.n1((r.per_serving.fat || 0) * s);
    };
    servings.addEventListener("input", show); show();
    P.modal("Log “" + r.name + "”", [
      el("div.mform-row", {}, [field("Servings", servings), field("Meal", slot)]), out,
    ], [
      { label: "Log it", primary: true, onClick: (close) => guard(async () => {
        await N().logRecipe(r.id, "?servings=" + (parseFloat(servings.value) || 1) + "&meal_slot=" + slot.value);
        toast("logged to today"); close(); reload();
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
      const { N, n0, n1 } = window.NUT;
      const recipes = await N().recipes();
      clear(body);
      body.appendChild(el("div.row", { style: "gap:8px" }, [
        el("button.btn-sm.btn-primary", { onclick: () => recipeModal(null, reload), text: "+ new recipe" }),
      ]));
      if (!recipes.length) {
        body.appendChild(el("div.empty", { style: "margin-top:14px",
          text: "No recipes yet. A recipe is a meal you make often — build it once from your foods and log it in one click." }));
        return;
      }
      recipes.forEach((r) => {
        const isOpen = open.has(r.id);
        const card = el("div.card", { style: "margin-top:10px" });
        card.appendChild(el("div.spread", { style: "cursor:pointer",
          onclick: () => { isOpen ? open.delete(r.id) : open.add(r.id); reload(); } }, [
          el("div.row", { style: "gap:8px;align-items:baseline;flex-wrap:wrap" }, [
            el("span.dd-caret", { text: isOpen ? "▾" : "▸" }),
            el("strong", { text: r.name }),
            el("span.pill", { text: r.category || "other" }),
            el("span.sub", { style: "font-size:11px", text: r.servings + " serving" + (r.servings === 1 ? "" : "s") }),
            r.use_count ? el("span.sub", { style: "font-size:10px", text: "×" + r.use_count }) : null,
          ]),
          el("span.mono", { style: "font-size:12px;color:" + window.NUT.GREEN,
            text: n0(r.per_serving.calories) + " cal / serving" }),
        ]));
        if (isOpen) {
          const detail = el("div", { style: "margin-top:8px" });
          (r.ingredients || []).forEach((i) => detail.appendChild(el("div.nt-entry", {}, [
            el("div", { style: "flex:1" }, [
              el("div", { text: i.food_name }),
              el("div.sub", { style: "font-size:10.5px",
                text: n1(i.serving_size) + " " + (i.serving_unit || "") + " · " + n0(i.calories) + " cal" }),
            ]),
          ])));
          detail.appendChild(el("div.sub", { style: "font-size:11px;margin-top:6px",
            text: "total " + n0(r.totals.calories) + " cal · P" + n1(r.totals.protein)
              + " C" + n1(r.totals.carbs) + " F" + n1(r.totals.fat)
              + "   →   per serving P" + n1(r.per_serving.protein)
              + " C" + n1(r.per_serving.carbs) + " F" + n1(r.per_serving.fat) }));
          detail.appendChild(window.RowBox({ label: "steps", kind: "step", noun: "step", parentId: r.id }).node);
          detail.appendChild(el("div.row", { style: "gap:6px;margin-top:10px;flex-wrap:wrap" }, [
            el("button.btn-sm.btn-primary", { onclick: () => logModal(r, reload), text: "＋ log this recipe" }),
            el("button.btn-sm", { onclick: () => recipeModal(r, reload), text: "✎ edit" }),
            el("button.btn-sm.btn-danger", { style: "margin-left:auto", text: "delete",
              onclick: () => confirmDo("Delete “" + r.name + "”?", async () => {
                await window.NUT.N().delRecipe(r.id); open.delete(r.id); toast("deleted"); reload();
              }) }),
          ]));
          card.appendChild(detail);
        }
        body.appendChild(card);
      });
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "recipes", label: "Food Advisor", order: 40, render });
})();

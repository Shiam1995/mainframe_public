/* nutrition-catalog.js — the Food Database tab.

   The reference catalogue imported from USDA FoodData Central (see
   backend/foodcatalog.py). This is the answer to "my library starts empty, so I
   have to type in everything I eat".

   Two rules shape the whole tab:

   1. **The catalogue is not your library.** `:CatalogFood` is read-only
      reference data; `:Food` is yours. Searching here never changes My Foods —
      adopting does, and adopting copies a snapshot. So the spec's "starts empty"
      rule survives, and 13,000 rows never drown the list of things you actually
      eat.
   2. **USDA states everything per 100 g; this app states food per serving.** The
      portion picker is where those meet, and it shows you the converted numbers
      *before* you commit, so "1 banana" is never a guess.

   Zero libraries, like the rest of the app. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const P = window.PULSE;

  let query = "";
  let source = "";
  let lastResults = [];

  // Proper attribution, used wherever there's room for it. The badge on each
  // row uses the short label from the API; this is the full name.
  const SOURCE_FULL = {
    sr_legacy: "USDA SR Legacy",
    foundation: "USDA Foundation Foods",
    survey: "USDA FNDDS",
    branded: "USDA Branded",
    off: "Open Food Facts",
    cofid: "UK CoFID (McCance & Widdowson)",
  };

  const SOURCE_NOTE = {
    sr_legacy: "USDA Standard Reference — the classic whole-food tables",
    foundation: "USDA Foundation — newest lab analyses, fewest foods",
    survey: "USDA FNDDS — foods as actually eaten, best portion data",
    branded: "USDA Branded — packaged US products, with barcodes",
    off: "Open Food Facts — crowd-sourced packaged products worldwide, with barcodes. "
       + "Anyone can edit it, so treat a single entry with more caution than the lab-measured sources.",
    cofid: "UK CoFID — McCance & Widdowson, the UK government's own food tables",
  };

  /* ---------------------------------------------------------------- portions */
  /* Adopting is a conversion, and the conversion is the part worth showing.
     Pick a portion, watch the numbers change, then commit. */
  function adoptModal(food, onDone) {
    const { N, field, n1, n0 } = window.NUT;
    const portions = food.portions || [];

    const name = el("input.mform-input", { value: food.name });
    const custom = el("input.mform-input", {
      type: "number", min: "0", step: "any", style: "width:110px",
      value: portions.length ? String(portions[0].grams) : "100",
    });

    const sel = el("select.mform-input", {}, [
      ...portions.map((p, i) => el("option", { value: String(i), text: p.label + "  ·  " + n1(p.grams) + " g" })),
      el("option", { value: "custom", text: portions.length ? "custom weight…" : "weight in grams" }),
    ]);
    sel.value = portions.length ? "0" : "custom";

    const customRow = el("div.row", { style: "gap:8px;align-items:center" }, [
      custom, el("span.sub", { style: "font-size:11px", text: "grams" }),
    ]);

    // Live preview of what will actually be stored.
    const preview = el("div", { style: "margin-top:10px" });

    function grams() {
      if (sel.value === "custom") return parseFloat(custom.value) || 0;
      const p = portions[parseInt(sel.value, 10)];
      return p ? p.grams : 0;
    }
    function label() {
      if (sel.value === "custom") return n1(grams()) + " g";
      const p = portions[parseInt(sel.value, 10)];
      return p ? p.label : n1(grams()) + " g";
    }

    const ROWS = [
      ["calories", "kcal", n0], ["protein", "g protein", n1],
      ["carbs", "g carbs", n1], ["fat", "g fat", n1],
      ["fibre", "g fibre", n1], ["sugar", "g sugar", n1],
      ["sodium", "mg sodium", n0], ["potassium", "mg potassium", n0],
    ];

    function refresh() {
      customRow.style.display = sel.value === "custom" ? "flex" : "none";
      const g = grams();
      const f = g / 100;
      clear(preview);
      preview.appendChild(el("div.sub", { style: "font-size:11px;margin-bottom:6px",
        text: g > 0 ? "Stored as one serving of “" + label() + "” = " + n1(g) + " g"
                    : "Set a weight to see the numbers." }));
      if (g <= 0) return;
      preview.appendChild(el("div.nt-cat-preview", {}, ROWS
        .filter(([k]) => food[k] != null)
        .map(([k, unit, fmt]) => el("div", {}, [
          el("div.mono", { style: "font-size:15px;color:var(--accent)", text: String(fmt(food[k] * f)) }),
          el("div.sub", { style: "font-size:10px", text: unit }),
        ]))));
    }
    sel.addEventListener("change", refresh);
    custom.addEventListener("input", refresh);
    refresh();

    P.modal("Add to my foods", [
      el("div.sub", { style: "font-size:11px" }, [
        // No "USDA" prefix here — the catalogue also holds Open Food Facts and
        // CoFID, and attributing those to the USDA would be plainly wrong.
        el("span", { text: (SOURCE_FULL[food.source] || food.source_label || food.source)
          + " · per 100 g: " }),
        el("span.mono", { text: n0(food.calories) + " kcal  P" + n1(food.protein)
          + "  C" + n1(food.carbs) + "  F" + n1(food.fat) }),
      ]),
      field("Name", name),
      field("Serving", sel),
      customRow,
      preview,
    ], [
      { label: "Add to my foods", primary: true, onClick: (close) => guard(async () => {
        const g = grams();
        if (!(g > 0)) return toast("a serving needs a weight", true);
        const created = await window.NUT.N().adoptFood(food.fdc_id, {
          serving_g: g, serving_label: label(), name: name.value.trim() || food.name,
        });
        toast("added to my foods");
        close();
        if (onDone) onDone(created);
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  /* --------------------------------------------------------------- searching */
  function resultRow(f, onDone) {
    const { n0, n1 } = window.NUT;
    const portions = f.portions || [];
    return el("div.nt-food", {}, [
      el("span.nt-cat-src", { title: SOURCE_NOTE[f.source] || "", text: f.source_label || f.source }),
      el("div", { style: "flex:1;min-width:0" }, [
        el("div", {}, [
          el("span", { text: f.name }),
          // Brand matters for packaged food — two products called "Granola" are
          // not the same food, and the brand is what tells them apart.
          f.brand ? el("span.sub", { style: "font-size:11px", text: "  ·  " + f.brand }) : null,
        ]),
        el("div.sub", { style: "font-size:10.5px",
          text: "per 100 g · " + n0(f.calories) + " cal · P" + n1(f.protein)
            + " C" + n1(f.carbs) + " F" + n1(f.fat)
            + (portions.length ? "   ·   " + portions.length + " portion"
                + (portions.length === 1 ? "" : "s") : "")
            + (f.barcode ? "   ·   ▮▯▮ " + f.barcode : "") }),
      ]),
      el("button.btn-sm.btn-primary", { text: "+ add", title: "choose a serving and copy it into My Foods",
        onclick: () => adoptModal(f, onDone) }),
    ]);
  }

  /* A standalone picker so other tabs (My Foods) can search the catalogue
     without navigating away. Same modal, same conversion — one code path. */
  function catalogPicker(onDone) {
    const { n0 } = window.NUT;
    const input = el("input.mform-input", { placeholder: "search the food database, or type a barcode…" });
    const results = el("div", { style: "margin-top:10px;max-height:46vh;overflow:auto" });
    let t = null;

    const run = () => guard(async () => {
      const q = input.value.trim();
      clear(results);
      if (q.length < 2) {
        results.appendChild(el("div.sub", { style: "font-size:11px", text: "Type at least two letters." }));
        return;
      }
      const rows = await window.NUT.N().catalog(q);
      clear(results);
      if (!rows.length) {
        results.appendChild(el("div.empty", { text: "Nothing matches “" + q + "”." }));
        return;
      }
      rows.forEach((f) => results.appendChild(resultRow(f, onDone)));
    });
    input.addEventListener("input", () => { clearTimeout(t); t = setTimeout(run, 220); });

    P.modal("Food database", [
      el("div.sub", { style: "font-size:11px",
        text: "USDA FoodData Central + Open Food Facts, held in your own graph. Adding copies a snapshot into My Foods." }),
      input,
      window.NUT.scanButton
        ? el("div.row", { style: "margin-top:8px" },
             [window.NUT.scanButton(onDone, "📷 scan a barcode instead")])
        : null,
      results,
    ], [{ label: "Done", onClick: (close) => close() }]);
    input.focus();
    run();
  }

  /* ------------------------------------------------------------------- view */
  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);
    const reload = () => render(host);

    guard(async () => {
      const status = await window.NUT.N().catalogStatus();
      clear(body);

      // What's actually in the graph, stated plainly.
      const strip = el("div.nt-cat-status", {}, [
        el("div", {}, [
          el("span.mono", { style: "font-size:19px;color:var(--accent)",
            text: status.total.toLocaleString() }),
          el("span.sub", { style: "font-size:11px", text: "  foods in the catalogue" }),
        ]),
        el("div.sub", { style: "font-size:11px",
          text: status.sources.map((s) => s.label + " " + s.foods.toLocaleString()).join("  ·  ") }),
      ]);
      body.appendChild(strip);

      if (!status.total) {
        body.appendChild(el("div.empty", { style: "margin-top:14px" }, [
          el("div", { text: "The catalogue is empty." }),
          el("div.sub", { style: "font-size:11px;margin-top:6px",
            text: status.archives.length
              ? "Archives are on disk — import them to fill it."
              : "No USDA archives found in " + status.source_dir + "." }),
          status.archives.length
            ? el("button.btn-sm.btn-primary", { style: "margin-top:10px", text: "import now",
                onclick: () => guard(async () => {
                  toast("importing — this takes about a minute…");
                  const r = await window.NUT.N().catalogImport();
                  toast(r.total.toLocaleString() + " foods imported"); reload();
                }) })
            : null,
        ]));
        return;
      }

      const search = el("input.mform-input", { value: query,
        placeholder: "search the food database — “chicken breast”, “hobnobs”, or type a barcode…",
        style: "flex:1;min-width:200px" });
      let t = null;
      const doSearch = () => guard(async () => {
        query = search.value.trim();
        if (query.length < 2) { lastResults = []; paint(); return; }
        lastResults = await window.NUT.N().catalog(query, source || undefined);
        paint();
      });
      search.addEventListener("input", () => { clearTimeout(t); t = setTimeout(doSearch, 220); });

      const srcSel = el("select.mform-input", { style: "width:auto" }, [
        el("option", { value: "", text: "all sources" }),
        ...status.sources.map((s) => el("option", { value: s.key, text: s.label })),
      ]);
      srcSel.value = source;
      srcSel.addEventListener("change", () => { source = srcSel.value; doSearch(); });

      // Scanning is the same search by another route: the camera types the
      // barcode for you, and lands in the same portion picker.
      const scanBtn = window.NUT.scanButton
        ? window.NUT.scanButton(() => toast("in My Foods now"), "📷 scan a packet")
        : null;
      body.appendChild(el("div.row", { style: "gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px" }, [
        search, srcSel, scanBtn,
      ]));

      const out = el("div", { style: "margin-top:12px" });
      body.appendChild(out);

      function paint() {
        clear(out);
        if (query.length < 2) {
          out.appendChild(el("div.empty", {}, [
            el("div", { text: "Search the catalogue to add a food." }),
            el("div.sub", { style: "font-size:11px;margin-top:8px;line-height:1.6",
              text: "USDA FoodData Central and Open Food Facts, imported into your own graph — "
                + "open data, no account, no API, works offline. Whole foods rank above packaged "
                + "ones, and a barcode — scanned with the camera or typed in full — jumps straight "
                + "to the product. Nothing here "
                + "counts as one of your foods until you add it, and adding stores a snapshot, so a "
                + "future re-import can never rewrite what you've been logging." }),
          ]));
          return;
        }
        if (!lastResults.length) {
          out.appendChild(el("div.empty", { text: "Nothing matches “" + query + "”." }));
          return;
        }
        out.appendChild(el("div.sub", { style: "font-size:11px;margin-bottom:6px",
          text: lastResults.length + " result" + (lastResults.length === 1 ? "" : "s") }));
        lastResults.forEach((f) => out.appendChild(resultRow(f, () => toast("in My Foods now"))));
      }
      paint();
      if (query.length >= 2) doSearch();
    });
  }

  window.NUT = window.NUT || {};
  window.NUT.catalogPicker = catalogPicker;
  // The scanner shows its hits with exactly this row, portion picker included —
  // a scanned product and a searched one are the same thing found two ways.
  window.NUT.catalogRow = resultRow;

  window.NUT_TABS = window.NUT_TABS || [];
  // Dropped from the Nutrition tab bar 2026-08-18 (user: "the rest i dont think need to stay").
  // The view still works — uncomment to bring it back. Data is untouched either way.
  // window.NUT_TABS.push({ key: "catalog", label: "Food Database", order: 35, render });
})();

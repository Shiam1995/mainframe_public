/* scanner.js — Dictionary · Scanner (MASTER_SPEC, Dictionary §PDF SCANNER).

   Paste paper text, get candidate terms ranked by frequency, pick the ones
   worth keeping, add them to the Dictionary as stubs.

   Extraction is frequency-based, NOT LLM-powered — the spec is explicit that
   the prototype uses the deterministic algorithm (LLM extraction is a future
   enhancement). The backend does the counting; this file is selection + display.

   Two views, same click-to-cycle behaviour in both:
     unselected → selected (teal) → dismissed (faded, struck) → unselected
   Terms already in the dictionary are green ✓ and can't be picked. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  let candidates = [];
  let view = "cloud";                 // cloud | list
  const state = {};                   // term → "sel" | "dis"

  const cycle = (t) => (state[t] === "sel" ? "dis" : state[t] === "dis" ? undefined : "sel");
  const selected = () => candidates.filter((c) => !c.in_dict && state[c.term] === "sel");

  function termClasses(c) {
    if (c.in_dict) return ".in-dict";
    if (state[c.term] === "sel") return ".sel";
    if (state[c.term] === "dis") return ".dis";
    return "";
  }

  function cloudView(rerender) {
    if (!candidates.length) return el("div.sub", { style: "font-style:italic", text: "Nothing scanned yet." });
    const max = candidates[0].count, min = candidates[candidates.length - 1].count;
    const wrap = el("div.scan-cloud");
    candidates.forEach((c) => {
      // size proportional to frequency, 11–36px per spec
      const t = max === min ? 1 : (c.count - min) / (max - min);
      const size = 11 + t * 25;
      const node = el("span.scan-term" + termClasses(c), {
        style: "font-size:" + size.toFixed(1) + "px",
        title: c.count + "× " + (c.in_dict ? "· already in the dictionary" : ""),
        text: (c.in_dict ? "✓ " : "") + c.term,
      });
      if (!c.in_dict) node.addEventListener("click", () => {
        const n = cycle(c.term);
        if (n) state[c.term] = n; else delete state[c.term];
        rerender();
      });
      wrap.appendChild(node);
    });
    return wrap;
  }

  function listView(rerender) {
    if (!candidates.length) return el("div.sub", { style: "font-style:italic", text: "Nothing scanned yet." });
    const max = candidates[0].count;
    const wrap = el("div");
    candidates.forEach((c) => {
      const row = el("div.scan-row" + termClasses(c), {}, [
        el("span.scan-row-name", { text: (c.in_dict ? "✓ " : "") + c.term }),
        el("div.scan-row-bar", {}, [
          el("div.scan-row-fill", { style: "width:" + (100 * c.count / max) + "%" }),
        ]),
        el("span.sub", { style: "width:44px;text-align:right", text: c.count + "×" }),
        el("span.scan-tag", { text: c.in_dict ? "in dict" : state[c.term] === "sel" ? "selected"
          : state[c.term] === "dis" ? "dismissed" : "—" }),
      ]);
      if (!c.in_dict) row.addEventListener("click", () => {
        const n = cycle(c.term);
        if (n) state[c.term] = n; else delete state[c.term];
        rerender();
      });
      wrap.appendChild(row);
    });
    return wrap;
  }

  window.Views = window.Views || {};
  window.Views.scanner = {
    id: "scanner", label: "Scanner", scoped: false,
    async render(v) {
      clear(v);
      v.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Scanner" }),
        el("div.sub", { text: "Paste a paper. Pick out the terms worth learning. They land in the Dictionary as stubs to fill in." }),
      ])]));

      const ta = el("textarea", { rows: "7", placeholder: "paste paper text here…",
        style: "width:100%;font-family:var(--mono);font-size:12px" });
      const controls = el("div"); const results = el("div");

      const doScan = () => guard(async () => {
        if (!ta.value.trim()) return toast("paste some text first", true);
        const r = await api.dictionary.scan(ta.value);
        candidates = r.candidates;
        Object.keys(state).forEach((k) => delete state[k]);
        if (!candidates.length) toast("no candidate terms found", true);
        else toast(candidates.length + " candidates from " + r.total_words + " words");
        rerender();
      });

      v.appendChild(el("div.card", {}, [ta,
        el("div.row", { style: "margin-top:10px" }, [
          el("button.btn-primary", { onclick: doScan, text: "scan for terms" }),
          el("button.btn-sm", { onclick: () => {
            ta.value = ""; candidates = [];
            Object.keys(state).forEach((k) => delete state[k]);
            rerender();
          }, text: "clear" }),
        ]),
      ]));
      v.appendChild(controls);
      v.appendChild(results);

      function rerender() {
        clear(controls); clear(results);
        if (!candidates.length) return;

        const seg = (label, val) => el("button.btn-sm" + (view === val ? ".scan-on" : ""), {
          onclick: () => { view = val; rerender(); }, text: label });
        const n = selected().length;
        controls.appendChild(el("div.row", { style: "margin:14px 0 10px;gap:8px" }, [
          el("div.row", { style: "gap:4px" }, [seg("cloud", "cloud"), seg("ranked list", "list")]),
          el("span.sub", { text: candidates.length + " candidates · click to select, again to dismiss" }),
          el("button.btn-primary", { style: "margin-left:auto", disabled: !n,
            onclick: () => guard(async () => {
              const terms = selected().map((c) => c.term);
              const r = await api.dictionary.bulkAdd(terms);
              toast("added " + r.added + " term" + (r.added === 1 ? "" : "s")
                + (r.skipped ? " · " + r.skipped + " already there" : "") + " — go fill in their ELI5s");
              // re-flag the added ones as in-dict without re-scanning
              candidates = candidates.map((c) => terms.includes(c.term) ? { ...c, in_dict: true } : c);
              terms.forEach((t) => delete state[t]);
              rerender();
            }),
            text: n ? "add " + n + " to dictionary" : "add selected to dictionary" }),
        ]));
        results.appendChild(el("div.card", {}, [view === "cloud" ? cloudView(rerender) : listView(rerender)]));
      }
      rerender();
    },
  };
})();

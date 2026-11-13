/* log.js — activity log: every mutation as a ChangeEvent, grouped by day,
   filterable by category / module / trigger, exportable. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const CAT_COLOR = {
    paper: "#5A9DE0", highlight: "#00D4AA", term: "#F0A030", task: "#8B7EC8",
    ref: "#E05A5A", kg: "#8B7EC8", status: "#5A9DE0", deepdive: "#00D4AA",
    idea: "#F0A030", header: "#5A9DE0", instance: "#00D4AA", question: "#E05A5A",
    dictionary: "#F0A030",
  };
  const MODULE_COLOR = {
    synapse: "#2DE2FF", vitality: "#00D4AA", cortex: "#8B7EC8", inventory: "#F0A030",
  };
  // trigger → glyph + color: who caused the change.
  const TRIGGER = {
    manual: { glyph: "✋", color: "#8194a8" },
    llm: { glyph: "✦", color: "#2DE2FF" },
    system: { glyph: "⚙", color: "#5A9DE0" },
  };

  const filters = { category: "", module: "", trigger: "" };
  // Two things belong in a log: what the machine did, and what you got wrong.
  // They're the same kind of record — timestamped, read back later — but you
  // never want both at once, so they're modes rather than two stacked lists.
  let mode = "activity";

  function dropdown(label, key, opts, onChange) {
    const sel = el("select", {}, [
      el("option", { value: "", text: "all " + label }),
      ...opts.map((o) =>
        el("option", { value: o.value, text: o.value + " (" + o.n + ")" })),
    ]);
    sel.value = filters[key];
    sel.addEventListener("change", () => { filters[key] = sel.value; onChange(); });
    return sel;
  }

  window.Views = window.Views || {};
  window.Views.log = {
    id: "log", label: "Log", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Activity Log" }),
          el("div.sub", { text: "The spine — every change as a ChangeEvent, and every mistake logged, both timestamped." }),
        ]),
        el("button.btn-sm", {
          onclick: () => guard(async () => {
            const r = await api.get("/api/log/export");
            toast("exported " + r.count + " entries → " + r.saved_to);
          }),
          text: "⤓ export JSON",
        }),
      ]));

      const facets = await guard(() => api.get("/api/log/facets"));
      const host = el("div");

      const bar = el("div.row", { style: "margin-bottom:14px; gap:8px; flex-wrap:wrap" }, [
        dropdown("categories", "category", facets.category || [], reload),
        dropdown("modules", "module", facets.module || [], reload),
        dropdown("triggers", "trigger", facets.trigger || [], reload),
      ]);

      const modeBar = el("div.row", { style: "margin-bottom:12px;gap:6px" },
        [["activity", "activity"], ["mistakes", "mistakes"]].map(([id, label]) =>
          el("button.btn-sm" + (mode === id ? ".heat-on" : ""), {
            text: label,
            onclick: () => { mode = id; draw(); },
          })));
      view.appendChild(modeBar);
      view.appendChild(bar);
      view.appendChild(host);

      /* Swap between the two halves. The activity filters only mean anything to
         the stream, so they're hidden in the other mode rather than sitting
         there doing nothing. */
      function draw() {
        [...modeBar.children].forEach((b, n) => b.className =
          "btn-sm" + ((n === 0 ? "activity" : "mistakes") === mode ? " heat-on" : ""));
        bar.style.display = mode === "activity" ? "" : "none";
        if (mode === "mistakes") { clear(host); return window.LogMistakes.render(host); }
        return reload();
      }

      async function reload() {
        const qs = Object.entries(filters)
          .filter(([, v]) => v)
          .map(([k, v]) => k + "=" + encodeURIComponent(v))
          .join("&");
        const byDay = await guard(() => api.get("/api/log/by-day" + (qs ? "?" + qs : "")));
        clear(host);
        const days = Object.keys(byDay).sort().reverse();
        if (!days.length) { host.appendChild(el("div.empty", { text: "No activity yet." })); return; }
        days.forEach((day) => {
          const box = el("div.logday");
          box.appendChild(el("h3", { text: day }));
          byDay[day].forEach((e) => {
            const trig = TRIGGER[e.trigger] || TRIGGER.manual;
            const mod = e.module || "synapse";
            box.appendChild(el("div.logentry", {}, [
              el("span.lt", { text: (e.ts || "").slice(11, 19) }),
              el("span.lc", { style: "color:" + (CAT_COLOR[e.category] || "#8194a8"), text: e.category }),
              el("span.lmod", {
                style: "color:" + (MODULE_COLOR[mod] || "#8194a8") + "; opacity:.85",
                title: "module", text: mod,
              }),
              el("span.ltrig", {
                style: "color:" + trig.color, title: "trigger: " + (e.trigger || "manual"),
                text: trig.glyph,
              }),
              el("span", {}, [
                el("span", { text: e.action + (e.detail ? " — " + e.detail : "") }),
                e.paper_title ? el("span.sub", { text: "  · " + e.paper_title.slice(0, 40) }) : null,
              ]),
            ]));
          });
          host.appendChild(box);
        });
      }
      draw();
    },
  };
})();

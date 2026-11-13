/* timeline.js — Paper Timeline: everything in the library, oldest first, as a
   scroll.

   Deliberately NOT a graph. The lineage-as-a-picture view lives in the
   Reference Map, which has the room for it; here the job is to see the whole
   library in order and get to any of it quickly. Each entry still carries what
   it cites and what cites it, because that's the part of the connection story
   that reads fine as a number. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const KIND_ICON = {
    paper: "📄", book: "📕", video: "🎬", course: "🎓", article: "📰", note: "🗒️", event: "🎟️",
  };

  window.Views = window.Views || {};
  window.Views.timeline = {
    id: "timeline", label: "Paper Timeline", scoped: false,
    async render(view) {
      clear(view);

      const [papers, kg] = await guard(() => Promise.all([
        api.papers.list(),
        api.get("/api/synapse/kg/papers?shared_only=true"),
      ]));

      // paper→paper citations. The KG endpoint calls the relationship `type`
      // (the reference-map payload calls it `kind` — not the same shape).
      const ids = new Set(papers.map((p) => p.id));
      const cites = {}, citedBy = {};
      (kg.edges || [])
        .filter((e) => /^cites/.test(e.type || "") && ids.has(e.source) && ids.has(e.target))
        .forEach((e) => {
          cites[e.source] = (cites[e.source] || 0) + 1;
          citedBy[e.target] = (citedBy[e.target] || 0) + 1;
        });

      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Paper Timeline" }),
          el("div.sub", { text: papers.length
            ? "Everything in the library, oldest first. " + papers.length + " entries."
            : "Everything in the library, oldest first." }),
        ]),
      ]));

      if (!papers.length) {
        view.appendChild(el("div.empty", { text: "No papers yet." }));
        return;
      }

      const byYear = {};
      papers.forEach((p) => { const y = p.year || "undated"; (byYear[y] = byYear[y] || []).push(p); });
      // undated last; everything else oldest first
      const years = Object.keys(byYear).sort((a, b) =>
        (a === "undated" ? 1 : b === "undated" ? -1 : Number(a) - Number(b)));

      years.forEach((y) => {
        const group = byYear[y];
        view.appendChild(el("div.row", { style: "gap:10px;align-items:baseline;margin:18px 0 8px" }, [
          el("h3", { style: "font-family:var(--mono);color:var(--teal);margin:0", text: String(y) }),
          el("span.sub", { style: "font-size:11px",
            text: group.length + (group.length === 1 ? " entry" : " entries") }),
        ]));
        group.forEach((p) => {
          const c = cites[p.id] || 0, cb = citedBy[p.id] || 0;
          view.appendChild(el("div.card", { style: "margin-bottom:8px" }, [
            el("div.spread", {}, [
              el("div", { style: "min-width:0" }, [
                el("div.row", { style: "gap:8px;align-items:baseline;flex-wrap:wrap" }, [
                  el("span", { title: p.kind || "paper", text: KIND_ICON[p.kind || "paper"] || "📄" }),
                  el("span", { style: "cursor:pointer;font-weight:600",
                    onclick: () => window.PM.selectPaper(p.id), text: p.title }),
                ]),
                el("div.sub", { text: (p.authors || []).join(", ") || "unknown authors" }),
                p.venue ? el("div.sub", { style: "font-size:11px;opacity:.75", text: p.venue }) : null,
              ]),
              el("div.row", { style: "gap:6px;flex-wrap:wrap;justify-content:flex-end" }, [
                el("span.pill." + (p.status || "unread"), { text: p.status || "unread" }),
                // only shown when non-zero — a wall of "0" is noise
                c ? el("span.mono", { style: "font-size:11px;color:var(--teal)", text: "cites " + c }) : null,
                cb ? el("span.mono", { style: "font-size:11px;color:var(--amber)", text: "cited by " + cb }) : null,
                p.original_path ? null : el("span.sub", { style: "font-size:10.5px", text: "no file" }),
              ]),
            ]),
          ]));
        });
      });
    },
  };
})();

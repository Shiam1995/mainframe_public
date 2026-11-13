/* reasoning.js — every "why" you have ever written, in one place.

   Read only, deliberately. Reasons are written where the decision is made: the
   moment you give an idea to a project, raise a goal, pull one into a phase,
   or set a habit. That is when the reasoning exists and when it is cheapest to
   write down. A tab where you could sit and type reasons in the abstract would
   fill up with reasons invented after the fact, which is the one thing this
   view is for catching.

   It reads the same (:Note {kind: 'why'}) every other tab writes. Because a
   note attaches either to a node or to a :Hop standing in for an edge, one
   query covers reasons about things and reasons about the links between them:
   "why this habit" and "why this habit went into this phase" both turn up.

   TWO VIEWS, because there are two ways of asking:
     by time   newest first, which is how you re-read a month
     by area   module, then the thing, which is how you audit a project
   FILTERS: the phase it was written in, and one thing in particular.

   Superseded reasons are shown, marked. An append-only store you cannot read
   the history of would be pointless, and what you used to think is usually the
   interesting half. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  // Module of origin, and the colour it reads as. Anything the backend cannot
  // place lands in "other" rather than being dropped.
  const AREA = {
    mainframe: { label: "Mainframe", c: "var(--teal)" },
    synapse: { label: "Synapse", c: "var(--teal)" },
    pulse: { label: "Pulse", c: "#DE7BA4" },
    vision: { label: "Vision", c: "#FF4757" },
    vault: { label: "Vault", c: "#D4A017" },
    other: { label: "Other", c: "var(--dim)" },
  };
  const areaOf = (k) => AREA[k] || AREA.other;

  function whyRow(n) {
    const a = areaOf(n.about.area);
    return el("div.rs-row" + (n.current ? "" : ".old"), {}, [
      el("div.rs-meta", {}, [
        el("span.rs-date", { text: window.Notes.fmtDate(n.date) }),
        el("span.rs-kind", { style: "color:" + a.c + ";border-color:" + a.c,
          text: n.about.kind }),
        el("span.rs-about", { title: n.about.title, text: n.about.title }),
        n.phase ? el("span.rs-phase", { text: n.phase }) : null,
        n.current ? null : el("span.nt-replaced", { text: "replaced" }),
      ]),
      el("div.rs-text", { text: n.text }),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.reasoning = {
    id: "reasoning", label: "Reasoning", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      let view = "time";                 // time | area
      let phaseId = "";
      let thingId = "";
      let notes = [];

      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Reasoning" }),
        el("div.sub", { text: "every why you have written, and what it was about. "
          + "written where the decision was made, read here." }),
      ])]));

      const controls = el("div.rs-controls");
      const body = el("div");
      viewEl.appendChild(controls);
      viewEl.appendChild(body);

      /* --- by time: one flat list, newest first --- */
      function paintTime() {
        if (!notes.length) return paintEmpty();
        let lastMonth = "";
        notes.forEach((n) => {
          const m = String(n.date).slice(0, 7);
          if (m !== lastMonth) {
            lastMonth = m;
            body.appendChild(el("div.wl-label", { style: "display:block;margin:16px 0 8px",
              text: new Date(m + "-01T12:00:00").toLocaleDateString("en-GB",
                { month: "long", year: "numeric" }).toLowerCase() }));
          }
          body.appendChild(whyRow(n));
        });
      }

      /* --- by area: module, then the thing inside it --- */
      function paintArea() {
        if (!notes.length) return paintEmpty();
        const byArea = {};
        notes.forEach((n) => {
          const a = n.about.area || "other";
          (byArea[a] = byArea[a] || {});
          const key = n.about.id || n.about.title;
          (byArea[a][key] = byArea[a][key] || { about: n.about, notes: [] }).notes.push(n);
        });
        Object.keys(byArea).sort().forEach((areaKey) => {
          const a = areaOf(areaKey);
          body.appendChild(el("div.rs-areahead", { style: "border-color:" + a.c },
            [el("span", { style: "color:" + a.c, text: a.label })]));
          const things = Object.values(byArea[areaKey])
            .sort((x, y) => y.notes.length - x.notes.length);
          things.forEach((t) => {
            body.appendChild(el("div.rs-thing", {}, [
              el("span.rs-kind", { style: "color:" + a.c + ";border-color:" + a.c,
                text: t.about.kind }),
              el("span", { text: t.about.title }),
              el("span.ph-meta", { text: t.notes.length
                + (t.notes.length === 1 ? " why" : " whys") }),
            ]));
            t.notes.forEach((n) => body.appendChild(whyRow(n)));
          });
        });
      }

      function paintEmpty() {
        body.appendChild(el("div.card", {}, [
          el("div.sub", { style: "line-height:1.6", text: (phaseId || thingId)
            ? "no reasons match that filter."
            : "nothing written yet. a why is written at the moment you decide something: "
              + "giving an idea to a project, raising a goal, pulling one into a phase, "
              + "or setting a habit. they all land here." }),
        ]));
      }

      async function load() {
        clear(body);
        body.appendChild(el("div.ph-meta", { text: "…" }));
        const q = [];
        if (phaseId) q.push("phase_id=" + encodeURIComponent(phaseId));
        if (thingId) q.push("target_id=" + encodeURIComponent(thingId));
        notes = await guard(() => api.get("/api/notes/why" + (q.length ? "?" + q.join("&") : "")));
        clear(body);
        (view === "time" ? paintTime : paintArea)();
      }

      /* --- the controls --- */
      const seg = el("div.ph-hz");
      [["time", "by time"], ["area", "by area"]].forEach(([k, label]) => {
        seg.appendChild(el("button" + (k === view ? ".on" : ""), {
          text: label,
          onclick: () => {
            view = k;
            [...seg.children].forEach((b, i) => b.classList.toggle("on", ["time", "area"][i] === k));
            clear(body);
            (view === "time" ? paintTime : paintArea)();
          },
        }));
      });

      const phaseSel = el("select.mform-input", { style: "width:auto" },
        [el("option", { value: "", text: "any phase" })]);
      phaseSel.addEventListener("change", () => { phaseId = phaseSel.value; load(); });

      const thingSel = el("select.mform-input", { style: "width:auto;max-width:280px" },
        [el("option", { value: "", text: "anything" })]);
      thingSel.addEventListener("change", () => { thingId = thingSel.value; load(); });

      controls.appendChild(el("div.row", { style: "gap:10px;flex-wrap:wrap" }, [
        seg,
        el("span.ph-meta", { text: "phase" }), phaseSel,
        el("span.ph-meta", { text: "about" }), thingSel,
      ]));

      guard(async () => {
        const [phases, things] = await Promise.all([
          api.get("/api/phases"),
          api.get("/api/notes/why/things"),
        ]);
        (phases || []).forEach((p) => phaseSel.appendChild(
          el("option", { value: p.id, text: "phase " + String(p.number).padStart(2, "0")
            + " · " + p.name })));
        // Grouped by area so the list of things reads the way the tab does.
        const byArea = {};
        (things || []).forEach((t) => (byArea[t.area] = byArea[t.area] || []).push(t));
        Object.keys(byArea).sort().forEach((k) => {
          const og = el("optgroup", { label: areaOf(k).label });
          byArea[k].forEach((t) => og.appendChild(el("option", {
            value: t.id, text: t.kind + ": " + t.title.slice(0, 44) })));
          thingSel.appendChild(og);
        });
      });

      load();
    },
  };
})();

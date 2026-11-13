/* project-attach.js — attachments on the project page, and the attach picker.

   One master: the Project tree. A paper, a doc, a sheet or a video stays where
   it was made; attaching writes (:X)-[:PART_OF]->(:Project), and optionally
   (:X)-[:SOURCE_OF]->(:Document) for a doc in the project. Nothing moves, and
   detaching removes PART_OF only.

   window.ProjectAttach.block(project, rollup, claims, onChange)
       the Attachments card on a project page (its "+ attach" is in the page header)
   window.ProjectAttach.strip(item, { sources })
       a doc's or a video's line: hours, projects, attach, (sources)
   window.ProjectAttach.open({ project, item, onDone })
       the picker. From a project page `project` is set and you pick the item;
       from a Repository card, a doc or a video `item` is set and you pick the
       project. Hours shown are the shared roll-up (backend hours.py). */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;
  const B = "/api/synapse";

  const ICON = { project: "◆", paper: "📑", book: "📕", article: "📰", video: "🎬", doc: "📄", sheet: "▦", writing: "✍" };
  const icon = (x) => ICON[x.chip] || ICON[x.kind] || "•";
  const hrs = (mins) => (Math.round((mins || 0) / 6) / 10) + "h";
  const KIND_TABS = [["", "all"], ["project", "projects"], ["paper", "repository"], ["doc", "docs"], ["sheet", "sheets"], ["video", "vision"]];

  /* Open the node where it lives. */
  async function openNode(x) {
    switch (x.kind) {
      case "project":
        window.openTab("project");
        location.hash = "#project/" + encodeURIComponent(x.id);
        return;
      case "doc":
        if (window.Docs) window.Docs.open(x.id);
        window.openTab("docs");
        return;
      case "sheet":
        if (window.SheetsTab) window.SheetsTab.open(x.id);
        window.openTab("sheets");
        return;
      case "video":
        if (window.VisionVideos) window.VisionVideos.open(x.id);
        window.openTab("youtube");
        return;
      case "writing":
        window.openTab("writing");
        return;
      case "paper":
        await guard(async () => {
          window.PM.paper = await api.papers.get(x.id);
          if (window.PM.renderContext) window.PM.renderContext();
          window.openTab("repo");
        });
    }
  }

  function row(x, opts) {
    const acts = [el("button.btn-sm", { text: "↗", title: "open where it lives", onclick: () => openNode(x) })];
    if (opts.detach) acts.push(el("button.btn-sm", { text: "detach", title: "take it out of this project (it is not deleted)", onclick: opts.detach }));
    return el("div.pj-at-r" + (opts.root ? ".proj" : ""), {}, [
      el("span.ic", { text: icon(x) }),
      el("div.nm", {}, [
        el("span", { text: x.title }),
        opts.root ? null : el("span.pj-kind.k-" + x.chip, { text: x.chip }),
        el("span.meta", { text: opts.meta || x.where }),
      ]),
      el("div.h", {}, [el("span", { text: hrs(x.mins) }), el("small", { text: " · " + x.sessions + (opts.root ? " session" + (x.sessions === 1 ? "" : "s") : "") })]),
      el("span.acts", {}, acts),
    ]);
  }

  function block(project, rollup, claims, onChange) {
    const host = el("div");
    const card = el("section.card.pj-attach", {}, [
      el("div.spread", { style: "margin-bottom:6px" }, [
        el("div", {}, [
          el("h2", { style: "font-size:14px;margin:0;font-weight:600", text: "Attachments" }),
          el("div.pj-note", { style: "margin:2px 0 0", text: "everything that belongs to this project, from wherever it was made. hours are the thing's own sessions plus everything under it." }),
        ]),
      ]),
      host,
    ]);

    async function paint() {
      const d = await guard(() => api.get(B + "/projects/" + project.id + "/attachments"));
      if (!d) return;
      clear(host);
      const tree = el("div.pj-at-node.root");
      tree.appendChild(row({ kind: "project", chip: "project", id: project.id, title: d.name, mins: d.mins, sessions: d.sessions },
        { root: true, meta: d.items.length ? d.items.length + " attached" : "nothing attached yet" }));
      const est = rollup && rollup.high;
      if (est) {
        const frac = Math.min(1, d.mins / 60 / est);
        tree.appendChild(el("div.pj-at-bar", { title: hrs(d.mins) + " of " + est + "h estimated" }, [
          el("i" + (d.mins / 60 > est ? ".over" : ""), { style: "width:" + Math.round(frac * 100) + "%" })]));
      }
      if (d.items.length) {
        const kids = el("div.pj-at-node");
        d.items.forEach((x) => {
          kids.appendChild(row(x, {
            detach: () => guard(async () => {
              await api.del(B + "/projects/" + project.id + "/attachments/" + encodeURIComponent(x.id));
              toast("detached"); paint(); if (onChange) onChange();
            }),
            meta: x.where + (x.sources.length ? " · built on " + x.sources.length + " source" + (x.sources.length === 1 ? "" : "s") : ""),
          }));
          if (x.sources.length) {
            kids.appendChild(el("div.pj-at-node", {}, x.sources.map((s) => row(s, {}))));
          }
        });
        tree.appendChild(kids);
      } else {
        tree.appendChild(el("div.pj-empty", { text: "attach a paper, doc, sheet or video made anywhere in Mainframe. it stays where it is." }));
      }
      (claims || []).forEach((c) => tree.appendChild(el("div.pj-at-auto", {}, [
        el("span", { text: "pulled into " + c.phase + " · " + hrs(c.logged_mins) + " counted there · " }),
        el("a", { text: "↗ phase", onclick: () => window.openTab("phases") }),
      ])));
      host.appendChild(tree);
    }
    paint();
    return card;
  }

  /* ---- the picker ------------------------------------------------------- */
  function open(opts) {
    let project = opts.project || null;      // {id, name}
    let item = opts.item || null;            // {kind, id, title}
    let kind = "", q = "";
    let docs = [];

    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const tabs = el("div.pj-pick-tabs");
    const search = el("input.mform-input", { placeholder: item ? "search projects" : "search everything you have made" });
    const hits = el("div.pj-pick-hits");
    const partOf = el("input", { type: "checkbox" }); partOf.checked = true;
    const partLbl = el("b");
    const srcOn = el("input", { type: "checkbox" });
    const srcSel = el("select.mform-input", { style: "width:auto;flex:1" });
    const why = el("input.mform-input", { placeholder: "why this belongs here" });

    const pickingProject = !!item;          // the item is fixed; choose a project
    const chosenLine = el("div.pj-note", { style: "margin:4px 0 0" });

    function paintChosen() {
      partLbl.textContent = project ? project.name : "the project";
      chosenLine.textContent = pickingProject
        ? (item.title ? "attaching " + item.title : "")
        : (project ? "into " + project.name : "");
      clear(srcSel);
      srcSel.appendChild(el("option", { value: "", text: docs.length ? "pick a doc…" : "no docs in this project yet" }));
      docs.filter((d) => !item || d.id !== item.id).forEach((d) => srcSel.appendChild(el("option", { value: d.id, text: d.title })));
      srcOn.disabled = !docs.length;
    }
    async function loadDocs() {
      docs = project ? ((await guard(() => api.get(B + "/projects/" + project.id + "/attachments"))) || {}).docs || [] : [];
      paintChosen();
    }

    function paintTabs() {
      clear(tabs);
      if (pickingProject) return;
      KIND_TABS.forEach(([k, l]) => tabs.appendChild(el("span" + (k === kind ? ".on" : ""), {
        text: l, onclick: () => { kind = k; paintTabs(); runSearch(); } })));
    }

    let timer = null, seq = 0;
    async function runSearch() {
      const my = ++seq;
      const qs = "?q=" + encodeURIComponent(q) + "&kind=" + (pickingProject ? "project" : kind)
        + (project && !pickingProject ? "&project_id=" + encodeURIComponent(project.id) : "");
      const res = await guard(() => api.get(B + "/attach/search" + qs));
      if (my !== seq || !res) return;
      clear(hits);
      if (!res.length) hits.appendChild(el("div.pj-empty", { text: "nothing matches." }));
      res.forEach((x) => {
        const sel = pickingProject ? project && project.id === x.id : item && item.id === x.id;
        hits.appendChild(el("div.pj-pick-hit" + (sel ? ".sel" : ""), {
          onclick: () => {
            if (pickingProject) { project = { id: x.id, name: x.title }; loadDocs(); }
            else item = { kind: x.kind, id: x.id, title: x.title };
            paintChosen(); runSearch();
          },
        }, [
          el("span", { text: icon(x) }),
          el("span", { text: x.title }),
          el("span.pj-kind.k-" + x.chip, { text: x.chip }),
          el("span.meta", { text: x.attached ? "already attached" : x.where }),
        ]));
      });
    }
    search.addEventListener("input", () => { q = search.value.trim(); clearTimeout(timer); timer = setTimeout(runSearch, 180); });

    async function submit() {
      if (!project) return toast("pick a project", true);
      if (!item) return toast("pick something to attach", true);
      const source_of = srcOn.checked ? srcSel.value : "";
      if (srcOn.checked && !source_of) return toast("pick the doc it is a source of", true);
      if (!partOf.checked && !source_of) return toast("tick part of the project, or a doc it is a source of", true);
      await guard(async () => {
        await api.post(B + "/projects/" + project.id + "/attach", {
          kind: item.kind, id: item.id, part_of: partOf.checked, source_of: source_of || null, why: why.value.trim(),
        });
        toast("attached to " + project.name);
        close();
        if (opts.onDone) opts.onDone(project);
      });
    }

    const card = el("div.modal.pj-pick", {}, [
      el("div.spread", {}, [el("div.modal-title", { style: "margin:0", text: "Attach" }), el("span.meta", { text: "nothing moves, an edge is written" })]),
      chosenLine,
      tabs, search, hits,
      el("div.pj-pick-where", {}, [
        el("label", {}, [partOf, el("span", { text: "part of " }), partLbl]),
        el("label", {}, [srcOn, el("span", { text: "source of" }), srcSel]),
        el("div.meta", { style: "margin:6px 0 4px", text: "reason, optional, becomes a dated why" }),
        why,
        el("div.row", { style: "margin-top:12px;gap:8px;justify-content:flex-end" }, [
          el("button.tk-btn", { text: "cancel", onclick: close }),
          el("button.tk-btn.teal", { text: "attach", onclick: submit }),
        ]),
      ]),
    ]);
    srcSel.addEventListener("change", () => { if (srcSel.value) srcOn.checked = true; });
    overlay.appendChild(card);
    overlay.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    document.body.appendChild(overlay);
    paintTabs(); loadDocs(); runSearch();
    search.focus();
  }

  /* ---- lenses ------------------------------------------------------------
     The same tree read from the node's side. `chips` names the projects a
     node sits in (click to open the project). `strip` is the line Docs and
     Vision show: hours, projects, "attach to project", and for a doc the
     sources it is built on. */
  function chips(projects) {
    return (projects || []).map((m) => el("a.pj-in", {
      title: m.via ? "source of " + m.via + " in this project" : "part of this project",
      text: "◆ " + m.name + (m.via ? " (via " + m.via + ")" : ""),
      onclick: (e) => { e.stopPropagation(); openNode({ kind: "project", id: m.id }); },
    }));
  }

  function strip(item, opts) {
    const host = el("div.pj-lens");
    async function paint() {
      const d = await guard(() => api.get(B + "/attach/of/" + encodeURIComponent(item.id)));
      if (!d) return;
      clear(host);
      const line = el("div.pj-lens-row", {}, [
        el("span.meta", { text: (d.sessions ? hrs(d.mins) + " · " + d.sessions + " session" + (d.sessions === 1 ? "" : "s") : "no hours yet") }),
        ...(d.projects.length ? chips(d.projects) : [el("span.meta", { text: "not in a project yet" })]),
        el("button.btn-sm", { text: "attach to project", onclick: () => open({ item, onDone: paint }) }),
      ]);
      host.appendChild(line);
      if (opts && opts.sources) {
        host.appendChild(el("div.pj-lens-row", {}, [el("span.meta", { text: "sources" })].concat(
          d.sources.length
            ? d.sources.map((x) => el("a.pj-src", { title: x.where + " · " + hrs(x.mins), onclick: () => openNode(x) },
                [el("span", { text: icon(x) + " " + x.title }), el("span.pj-kind.k-" + x.chip, { text: x.chip })]))
            : [el("span.meta", { text: d.projects.length
                ? "none yet. attach a paper from its project page and tick source of this doc."
                : "none yet. attach this doc to a project, then add its sources there." })])));
      }
    }
    paint();
    return host;
  }

  window.ProjectAttach = { block, open, openNode, chips, strip };
})();

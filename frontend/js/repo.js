/* repo.js — the Repository: everything you read, watch or work through.

   Papers arrive as PDFs; books, video series and courses are typed in by hand.
   Both are the same :Paper node underneath, so an entry with no file still gets
   the workspace, its own instances, references and knowledge-graph nodes — a
   PDF is a thing an entry *can* have, not what it *is*. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;

  let filters = { q: "", status: "", year: "", kind: "" };

  /* Finished reading is still part of the library, but it isn't what you're
     looking at day to day. Hidden by default, remembered across reloads —
     "read" is the finished state; "revisit" deliberately is not. "shelved"
     hides with it: put down on purpose, out of the way until picked up. */
  /* Two readings of the same entries. "by project" is the Project tree seen
     from here: papers, books and courses grouped under the projects they are
     attached to (notes/ui/mainframe_project_attach.html). "everything" is the
     flat library of every kind. The cards are the same in both. */
  const LENS_KEY = "mf.repo.lens";
  // Every kind you read or watch. Articles, videos and notes used to be left
  // out, so one added from this (default) lens seemed never to land and got
  // added again; only the work kinds (project/decomp/idea/topic) stay out.
  const LENS_KINDS = ["paper", "book", "course", "article", "video", "note", "event"];
  const lens = () => { try { return localStorage.getItem(LENS_KEY) || "project"; } catch { return "project"; } };
  const setLens = (v) => { try { localStorage.setItem(LENS_KEY, v); } catch { /* */ } };
  let members = {};                     // paper id → {mins, sessions, projects}

  const SHOW_READ_KEY = "mf.repo.showRead";
  const showRead = () => localStorage.getItem(SHOW_READ_KEY) !== "0";
  const setShowRead = (v) => localStorage.setItem(SHOW_READ_KEY, v ? "1" : "0");

  // Icon + label per kind. Order is the order they appear in the pickers.
  const KINDS = [
    { key: "topic",   icon: "🌀", label: "General idea" },
    { key: "paper",   icon: "📄", label: "Paper" },
    { key: "book",    icon: "📕", label: "Book" },
    { key: "video",   icon: "🎬", label: "Video series" },
    { key: "course",  icon: "🎓", label: "Course" },
    { key: "article", icon: "📰", label: "Article" },
    { key: "note",    icon: "🗒️", label: "Note" },
    { key: "event",   icon: "🎟️", label: "Event" },
    { key: "project", icon: "🧱", label: "Project",       link: "project" },
    { key: "decomp",  icon: "🌳", label: "Decomposition", link: "decomp" },
    { key: "idea",    icon: "💡", label: "Idea",          link: "idea" },
  ];
  const KIND = (k) => KINDS.find((x) => x.key === k) || KINDS.find((x) => x.key === "paper");
  // The three kinds that can point at something that already exists elsewhere
  // in Mainframe. Everything else is just a title you typed.
  const LINKABLE = (k) => (KIND(k) || {}).link || null;

  function statusPill(s) { return el("span.pill." + s, { text: s }); }

  /* ★ — this entry has hours in the work database.

     "Pushed" is what the button in the workspace does, so the star means a
     :WorkSession exists on this entry, not that anything was ticked finished.
     The count is the point: a repository is a wall of things you *meant* to
     read, and the only honest way to tell those from the ones you actually sat
     with is how many times you pushed. No star at all where the answer is
     none — a greyed-out zero on every card says nothing and costs a row. */
  function pushStar(p) {
    const n = p.push_count || 0;
    if (!n) return null;
    const mins = p.push_mins || 0;
    return el("span.repo-push", {
      title: n + " session" + (n === 1 ? "" : "s") + " pushed to the database"
           + (mins && window.WorkLog ? " · " + window.WorkLog.fmtMins(mins) : ""),
      text: n > 1 ? "★ " + n : "★",
    });
  }

  function kindTag(p) {
    const k = KIND(p.kind || "paper");
    return el("span.repo-kind", {
      title: k.label + (p.original_path ? " · has a PDF" : " · no file"),
      text: k.icon + " " + k.label.toLowerCase(),
    });
  }

  /* ---- form helpers ----
     Extraction only ever produces a starting point — for a book it may produce
     nothing at all — so every field it can fill is editable by hand, and a
     blank field clears the property rather than being ignored. */
  function field(label, value, opts) {
    const input = el((opts && opts.area) ? "textarea.mform-input" : "input.mform-input", {
      placeholder: (opts && opts.ph) || "", value: value == null ? "" : String(value),
    });
    return {
      node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), input]),
      get: () => input.value.trim(),
      input,
    };
  }

  function kindField(label, value) {
    const input = el("select.mform-input", {}, KINDS.map((k) =>
      el("option", { value: k.key, text: k.icon + "  " + k.label })));
    input.value = value || "topic";
    return {
      node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), input]),
      get: () => input.value,
      input,
    };
  }

  // Shared shell so the add and edit modals can't drift apart.
  function modal(titleText, note, fields, submitLabel, onSubmit) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const card = el("div.modal", {}, [
      el("div.modal-title", { text: titleText }),
      note.text
        ? el("div.sub", {
            style: "margin:-8px 0 14px;line-height:1.45" + (note.warn ? ";color:var(--red)" : ""),
            text: note.text })
        : null,
      ...fields.map((f) => (f && f.node) || f),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: submitLabel, onclick: () => onSubmit(close) }),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        // app.js sends Escape home unless a .modal-overlay is on screen — it would
        // still be gone by the time the event bubbled up, so stop it here.
        e.stopPropagation();
        close();
      }
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") onSubmit(close);
    });
    return { overlay, card, close };
  }

  const authorList = (s) => (s ? s.split(",").map((a) => a.trim()).filter(Boolean) : []);
  const badYear = (y) => y && !/^\d{1,4}$/.test(y);

  /* ---- bring something in / add a source by hand ----
     No file: a book you own on paper, a video series, a course — or a project,
     a decomposition node, an idea, or a subject that is none of those and just
     needs somewhere to be thought about. It lands in the same library as the
     PDFs and behaves the same everywhere afterwards, workspace included.

     The title comes first and the type second, because in practice you know
     what you want to call the thing long before you know what it is — and
     often it never becomes any one of them. Leave the type alone and it stays
     a general idea. */

  /* The optional "…which one?" row. Appears only once a kind that can point at
     something real is chosen, and fills an empty title from the pick so
     bringing in an existing project is two clicks and no typing. */
  function linkField(titleField) {
    let cache = null;                 // {project:[], decomp:[], idea:[]}
    const select = el("select.mform-input");
    const node = el("div.mform-full", { style: "display:none" }, [
      el("div.mform-label", { text: "Which one?" }), select,
    ]);
    let kind = null;

    select.addEventListener("change", () => {
      const opt = (cache && cache[kind] || []).find((x) => x.id === select.value);
      if (opt && !titleField.get()) { titleField.input.value = opt.title; }
    });

    let pending = Promise.resolve();   // the in-flight show(), so select() can wait for it

    async function show(linkKind) {
      kind = linkKind;
      if (!linkKind) { node.style.display = "none"; return; }
      node.style.display = "";
      clear(select);
      select.appendChild(el("option", { value: "", text: "— don't link, just the title —" }));
      if (!cache) {
        select.appendChild(el("option", { value: "", text: "loading…" }));
        cache = await guard(() => window.api.papers.linkable()) || { project: [], decomp: [], idea: [] };
        clear(select);
        select.appendChild(el("option", { value: "", text: "— don't link, just the title —" }));
      }
      const rows = cache[linkKind] || [];
      if (!rows.length) {
        select.appendChild(el("option", { value: "", text: "(nothing to link yet)" }));
        return;
      }
      rows.forEach((r) => select.appendChild(el("option", {
        value: r.id, text: r.title + (r.note ? "  ·  " + r.note : ""),
      })));
    }

    return {
      node,
      show: (k) => { pending = show(k); return pending; },
      // preselect an already-linked target once its options have landed
      select: (id) => pending.then(() => { select.value = id || ""; }),
      get: () => select.value || null,
    };
  }

  function addModal() {
    const title = field("What do you want to call it?", "", {
      ph: "say it in a sentence if that's what it takes — you can rename it later",
    });
    const kind = kindField("What is it? (optional)", "topic");
    const link = linkField(title);
    const authors = field("Authors / creator", "", { ph: "comma-separated" });
    const year = field("Year", "", { ph: "e.g. 1978" });
    const venue = field("Publisher / channel", "", { ph: "publisher, channel, platform" });
    const url = field("Link", "", { ph: "playlist, course page, anywhere it lives" });
    const about = field("What it's about", "", { area: true, ph: "your own blurb — notes come later, on the entry itself" });

    // Authors/year/venue are source metadata; on a project or a loose idea they
    // are just four empty boxes in the way. Hidden until the type asks for them.
    const sourceOnly = el("div", {}, [
      authors.node, el("div.mform-row", {}, [year.node, venue.node]), url.node,
    ]);
    const syncKind = () => {
      const k = kind.get();
      link.show(LINKABLE(k));
      sourceOnly.style.display = (k === "topic" || LINKABLE(k)) ? "none" : "";
    };
    kind.input.addEventListener("change", syncKind);

    const m = modal("Bring something in", {
      text: "A title is all that's required. Say what it is only if you want to — "
          + "untyped, it lands as a general idea with a workspace of its own." },
      [title, kind, link, sourceOnly, about],
      "Add", (close) => {
        if (!title.get()) return toast("give it a title — the rest is optional", true);
        if (badYear(year.get())) return toast("year must be a number", true);
        guard(async () => {
          const p = await window.api.papers.create({
            kind: kind.get(), title: title.get(), authors: authorList(authors.get()),
            year: year.get() ? parseInt(year.get(), 10) : null,
            venue: venue.get() || null, url: url.get() || null,
            abstract: about.get() || null,
            link_kind: LINKABLE(kind.get()) && link.get() ? LINKABLE(kind.get()) : null,
            link_id: LINKABLE(kind.get()) ? link.get() : null,
          });
          toast("added: " + p.title);
          close();
          load();
        });
      });
    syncKind();
    title.input.focus();
    return m;
  }

  function editModal(p, note) {
    const kind = kindField("Kind", p.kind || "paper");
    const title = field("Title", p.title, { ph: "the real title" });
    // Same optional reference as the add modal — a subject that started as a
    // loose idea can be pointed at the project it turned into.
    const link = linkField(title);
    const syncKind = () => link.show(LINKABLE(kind.get()));
    kind.input.addEventListener("change", syncKind);
    const authors = field("Authors", (p.authors || []).join(", "), { ph: "comma-separated" });
    const year = field("Year", p.year, { ph: "e.g. 1979" });
    const venue = field("Venue / publisher", p.venue, { ph: "journal, conference, publisher or channel" });
    const url = field("Link", p.url, { ph: "where it lives" });
    const doi = field("DOI", p.doi);
    const arxiv = field("arXiv id", p.arxiv_id);
    const abstract = field("Abstract / blurb", p.abstract, { area: true });

    const m = modal("Edit details",
      note
        ? { text: note, warn: true }
        : { text: "Correct anything the scan got wrong — or anything you typed." },
      [kind, title, link, authors,
       el("div.mform-row", {}, [year.node, venue.node]),
       url,
       el("div.mform-row", {}, [doi.node, arxiv.node]),
       abstract],
      "Save", (close) => {
        if (!title.get()) return toast("a title is required", true);
        if (badYear(year.get())) return toast("year must be a number", true);
        guard(async () => {
          await window.api.papers.update(p.id, {
            // null (not "") clears — the backend patches on exclude_unset, and Neo4j
            // drops null properties, so an emptied field really does go away.
            kind: kind.get(),
            title: title.get(),
            authors: authorList(authors.get()),
            year: year.get() ? parseInt(year.get(), 10) : null,
            venue: venue.get() || null,
            url: url.get() || null,
            doi: doi.get() || null,
            arxiv_id: arxiv.get() || null,
            abstract: abstract.get() || null,
            link_kind: LINKABLE(kind.get()) && link.get() ? LINKABLE(kind.get()) : null,
            link_id: LINKABLE(kind.get()) ? link.get() : null,
          });
          toast("saved");
          close();
          // PM.paper is the cached copy the Workspace/KG header reads. Refresh it in
          // place (not via selectPaper, which would navigate away from the repo).
          if (window.PM && window.PM.paper && window.PM.paper.id === p.id) {
            window.PM.paper = await window.api.papers.get(p.id);
          }
          load();
        });
      });
    syncKind();
    if (p.link_id) link.select(p.link_id);
    title.input.focus();
    title.input.select();
    return m;
  }

  /* ◀ ▶ swap a card with its neighbour in the list as currently shown, so a
     move means what you see rather than what's behind a filter. */
  function move(list, idx, dir) {
    const a = list[idx], b = list[idx + dir];
    if (!a || !b) return;
    guard(async () => {
      // reorder() gives the listed ids the slots those same nodes already hold,
      // in the order listed — so the pair must be passed in the order you want
      // them to end up. Moving `a` earlier means a first; later means b first.
      await window.api.papers.reorder(dir < 0 ? [a.id, b.id] : [b.id, a.id]);
      load();
    });
  }

  /* ---- layered card colours ------------------------------------------- */
  const MAX_LAYERS = 4;
  const paperColors = (v) => String(v || "").split(",").map((x) => x.trim()).filter(Boolean).slice(0, MAX_LAYERS);

  // The palette's hex values live in main.css (the `.wide` swatch rules); read
  // them back from a hidden probe rather than keep a second copy here.
  const hexCache = {};
  function colorHex(name) {
    if (hexCache[name]) return hexCache[name];
    const probe = el("span.ui-swatch.wide", { "data-color": name, style: "position:absolute;visibility:hidden" });
    document.body.appendChild(probe);
    const v = getComputedStyle(probe).getPropertyValue("--uic").trim() || "transparent";
    probe.remove();
    return (hexCache[name] = v);
  }

  /* The card's dot: shows every layer as slices; click opens the palette.
     In the palette a click ADDS that colour as the next layer (or removes it
     if it's already on), numbered in layer order. It stays open so you can
     build up all four; the dashed one clears them. */
  function layerSwatch(p, onSaved) {
    const layers = paperColors(p.color);
    const dot = el("button.ui-swatch.wide", { "data-color": layers[0] || "",
      title: "card colours" + (layers.length ? ": " + layers.join(" → ") : "") + " — click to pick up to " + MAX_LAYERS });
    if (layers.length > 1) {
      const step = 100 / layers.length;
      dot.style.background = "conic-gradient(" + layers.map((c, i) =>
        `${colorHex(c)} ${i * step}% ${(i + 1) * step}%`).join(", ") + ")";
    }
    async function save(next) {
      await guard(() => window.api.papers.update(p.id, { color: next.join(",") }));
      p.color = next.join(",");
      onSaved();
    }
    function openPalette() {
      document.querySelector(".ui-palette")?.remove();
      const pal = el("div.ui-palette.wide.repo-layers");
      function drawPal() {
        clear(pal);
        const cur = paperColors(p.color);
        pal.appendChild(el("div.repo-layers-head", { text: cur.length
          ? cur.length + " of " + MAX_LAYERS + " layers" : "pick up to " + MAX_LAYERS + " colours, in order" }));
        window.ui.SWATCH_COLORS_WIDE.forEach((c) => {
          const at = cur.indexOf(c);
          const b = el("button.ui-swatch" + (at >= 0 ? ".on" : ""), {
            "data-color": c, title: c ? (at >= 0 ? "remove " + c : "add " + c) : "clear all colours" },
            at >= 0 ? [el("span.repo-layer-n", { text: String(at + 1) })] : []);
          b.addEventListener("click", async (ev) => {
            ev.stopPropagation();
            let next;
            if (!c) next = [];
            else if (at >= 0) next = cur.filter((x) => x !== c);
            else if (cur.length >= MAX_LAYERS) { toast("four layers max — remove one first", true); return; }
            else next = cur.concat(c);
            await save(next);
            drawPal();
          });
          pal.appendChild(b);
        });
      }
      drawPal();
      const r = dot.getBoundingClientRect();
      pal.style.left = (r.left + window.scrollX) + "px";
      pal.style.top = (r.bottom + window.scrollY + 4) + "px";
      document.body.appendChild(pal);
      const away = (ev) => {
        if (pal.contains(ev.target)) return;
        pal.remove(); document.removeEventListener("mousedown", away);
      };
      setTimeout(() => document.addEventListener("mousedown", away), 0);
    }
    dot.addEventListener("click", (e) => { e.stopPropagation(); e.preventDefault(); openPalette(); });
    dot.addEventListener("contextmenu", (e) => { e.stopPropagation(); e.preventDefault(); openPalette(); });
    return dot;
  }

  function paperCard(p, list, idx) {
    const authors = (p.authors || []).join(", ") || "unknown authors";
    const meta = [p.year, p.venue].filter(Boolean).join(" · ");
    /* The library is a wall of near-identical cards, and the one thing that
       makes yours findable in it is that you painted it. Same seven names as
       the Projects tree and the workspace boxes, so a purple entry here and a
       purple project there mean the same thing. */
    const card = el("div.card.repo-card", { "data-nav": p.id });

    /* Up to four colours, layered (2026-11-10). `color` stays one string —
       "red,blue,green" — so a single-colour paper is exactly what it was. The
       first colour is the card's border and tint as before; each later one is
       a ring just inside the one before it. */
    const slot = el("span", { style: "display:flex" });
    function paint() {
      const layers = paperColors(p.color);
      card.setAttribute("data-color", layers[0] || "");
      card.classList.remove("layers-2", "layers-3", "layers-4");
      if (layers.length > 1) card.classList.add("layers-" + layers.length);
      layers.slice(1).forEach((c, i) => card.style.setProperty("--uic" + (i + 2), colorHex(c)));
    }
    function drawSwatch() {
      clear(slot);
      slot.appendChild(layerSwatch(p, () => { paint(); drawSwatch(); }));
    }
    paint();
    drawSwatch();

    [
      // Year/venue used to lead the card, which put a publication detail above
      // the title. It's now a footnote just above the buttons, and it's simply
      // absent when there's nothing to say rather than showing an em-dash.
      el("div.spread", {}, [
        el("div.row", { style: "gap:2px" }, [
          el("button.btn-sm.repo-move", { title: "move earlier", disabled: idx === 0,
            onclick: () => move(list, idx, -1), text: "◀" }),
          el("button.btn-sm.repo-move", { title: "move later", disabled: idx === list.length - 1,
            onclick: () => move(list, idx, 1), text: "▶" }),
        ]),
        el("div.row", { style: "gap:8px;align-items:center" }, [
          slot, pushStar(p), statusPill(p.status || "unread"),
        ]),
      ]),
      el("h3", { style: "margin:8px 0 4px;cursor:pointer",
        onclick: () => window.PM.selectPaper(p.id) , text: p.title }),
      el("div.sub", { text: authors }),
      el("div.row", { style: "margin-top:6px;gap:6px;flex-wrap:wrap" }, [
        kindTag(p),
        checkPill(p),
        p.url ? el("a.repo-link", { href: p.url, target: "_blank", rel: "noopener noreferrer",
          title: p.url, onclick: (e) => e.stopPropagation(), text: "↗ link" }) : null,
      ]),
      p.arxiv_id ? el("div.mono", { style: "font-size:10.5px;color:var(--muted);margin-top:6px", text: "arXiv:" + p.arxiv_id }) : null,
      memberLine(p),
      meta ? el("div.mono", { style: "font-size:11px;color:var(--muted);margin-top:10px", text: meta }) : null,
      el("div.row", { style: "margin-top:8px;flex-wrap:wrap;gap:6px" }, [
        el("button.btn-sm", { onclick: () => window.PM.selectPaper(p.id), text: "open" }),
        el("button.btn-sm", { onclick: () => guard(async () => {
          const up = await window.api.papers.cycle(p.id);
          toast("status → " + up.status); load();
        }), text: "cycle status" }),
        // The shelf's three moves, straight from the card (same moveTo the
        // shelf's info panel uses, so the six-slot cap and the takeaway
        // prompt apply here too). The section it is already in has no button.
        tabOf(p) !== "main" ? el("button.btn-sm", { title: "put it in the Current section (six at most)",
          onclick: () => moveTo(p, "main"), text: "→ Current" }) : null,
        tabOf(p) !== "later" ? el("button.btn-sm", { title: "put it in the Come back later section",
          onclick: () => moveTo(p, "later"), text: "→ Later" }) : null,
        tabOf(p) !== "done" ? el("button.btn-sm", { title: "put it in the Finished section",
          onclick: () => moveTo(p, "done"), text: "✓ Finished" }) : null,
        // Already in Later: shelve / unshelve still tells "put down on purpose"
        // from plain unread. From anywhere else, → Later is the same move.
        p.status === "shelved"
          ? el("button.btn-sm", { title: "take it off the shelf — back to unread", onclick: () => setStatus(p, "unread", "off the shelf"), text: "unshelve" })
          : tabOf(p) === "later"
            ? el("button.btn-sm", { title: "put it down on purpose — hidden with finished ones until you pick it back up",
                onclick: () => setStatus(p, "shelved", "shelved"), text: "shelve" })
            : null,
        el("button.btn-sm", { title: "edit title and details by hand", onclick: () => editModal(p), text: "✎ edit" }),
        el("button.btn-sm", { title: "put this in a project. It stays here too.",
          onclick: () => window.ProjectAttach.open({ item: { kind: "paper", id: p.id, title: p.title }, onDone: () => load() }),
          text: "attach to project" }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + p.title + "” and its data?", async () => {
          await window.api.papers.del(p.id); toast("deleted"); load();
        }), text: "×" }),
      ]),
    ].forEach((n) => n && card.appendChild(n));
    return card;
  }

  function setStatus(p, status, msg) {
    guard(async () => {
      await window.api.papers.update(p.id, { status });
      toast(msg + ": " + p.title);
      load();
    });
  }

  /* Hours from the shared roll-up (backend hours.py), the same number the
     project and the phase show, and the projects this entry sits in. */
  // paper id → open to-do rows on it (load() fills it)
  let toCheck = {};
  function checkPill(p) {
    const n = toCheck[p.id];
    return n ? el("span.pill.repo-check", { text: n + " to check",
      title: "open “look into” rows on this paper — tick them off inside the paper" }) : null;
  }

  function memberLine(p) {
    const m = members[p.id];
    if (!m || (!m.sessions && !m.projects.length)) return null;
    return el("div.row.pj-lens-row", { style: "margin-top:8px" }, [
      m.sessions ? el("span.meta", { text: (Math.round(m.mins / 6) / 10) + "h · " + m.sessions + " session" + (m.sessions === 1 ? "" : "s") }) : null,
      ...window.ProjectAttach.chips(m.projects),
    ]);
  }

  /* ==== the bookshelf (notes/ui/mainframe_shelf.html) =====================
     A shelf of spines above the list. It is a view of the same :Paper nodes,
     no new node type and no copied data. Its four tabs are the existing
     status read four ways:
       Master           every entry, whatever the "show read" toggle says
       Current          reading (six at most)
       Come back later  shelved, revisit, unread
       Finished         read
     Hours are the membership roll-up (hours.py) that load() already fetches,
     never summed a second way here. */
  const SHELF_KEY = "mf.repo.shelf.";
  const sget = (k, d) => { try { const v = localStorage.getItem(SHELF_KEY + k); return v == null ? d : JSON.parse(v); } catch { return d; } };
  const sset = (k, v) => { try { localStorage.setItem(SHELF_KEY + k, JSON.stringify(v)); } catch { /* */ } };

  const SHELF_MAX_MAIN = 6;
  const SHELF_TABS = [
    { key: "master", label: "Master" },
    { key: "main",   label: "Current" },
    { key: "later",  label: "Come back later" },
    { key: "done",   label: "Finished" },
  ];
  const SHELF_NAME = { master: "Master", main: "Current", later: "Come back later", done: "Finished" };
  const TAB_STATUS = { main: "reading", later: "shelved", done: "read" };
  const tabOf = (p) => {
    const s = p.status || "unread";
    return s === "reading" ? "main" : s === "read" ? "done" : "later";
  };

  // Module accents from modules.js; Bare Metal has no module yet, so it keeps
  // the mockup's purple.
  const AREAS = [
    { key: "synapse",   label: "Synapse",    color: "#00D4AA" },
    { key: "pulse",     label: "Pulse",      color: "#DE7BA4" },
    { key: "vision",    label: "Vision",     color: "#FF4757" },
    { key: "vault",     label: "Vault",      color: "#D4A017" },
    { key: "baremetal", label: "Bare Metal", color: "#9B7BFF" },
  ];
  const AREA_BY = Object.fromEntries(AREAS.map((a) => [a.key, a]));
  const normArea = (v) => {
    const k = String(v || "").toLowerCase().replace(/[\s_-]+/g, "");
    if (k === "glass" || k === "glassbox") return "baremetal";
    return AREA_BY[k] ? k : null;
  };
  const SPINE_GLYPH = { paper: "Pp", book: "Bk", course: "Cr", video: "Vd", article: "Ar", note: "Nt",
    event: "Ev", topic: "Tp", project: "Pj", decomp: "Dc", idea: "Id" };

  let shelfTab = sget("tab", "master");
  if (!SHELF_NAME[shelfTab]) shelfTab = "master";
  let shelfSort = sget("sort", "num");
  const SF = { area: new Set(sget("area", [])), kind: new Set(sget("kind", [])) };
  let shelfOpen = null;                 // id of the entry whose panel is open
  let shelfAll = [];                    // every entry, in the reorder order
  let shelfNum = {};                    // id -> its number in that order
  let sessByRef = {};                   // paper id -> its :WorkSession rows, newest first
  let projModule = {};                  // project id -> module/area, where one is set
  const upToCache = {};                 // paper id -> "ch 3 · p 41" | ""

  const saveFilters = () => { sset("area", [...SF.area]); sset("kind", [...SF.kind]); };
  const filtersOn = () => SF.area.size > 0 || SF.kind.size > 0;

  /* Area: the entry's own module (or area) field, else that of a project it
     is attached to, else Synapse. `own` says whether one was actually set, so
     the colour band knows whether to fall back to the entry's own colour. */
  function areaOf(p) {
    const mine = normArea(p.module) || normArea(p.area);
    if (mine) return { key: mine, own: true };
    for (const pr of ((members[p.id] || {}).projects || [])) {
      const k = normArea(projModule[pr.id]);
      if (k) return { key: k, own: true };
    }
    return { key: "synapse", own: false };
  }
  function spineColor(p) {
    const a = areaOf(p);
    if (a.own) return AREA_BY[a.key].color;
    const first = paperColors(p.color)[0];
    const hex = first ? colorHex(first) : "";
    return hex && hex !== "transparent" ? hex : AREA_BY.synapse.color;
  }
  const hoursOf = (p) => Math.round(((members[p.id] || {}).mins || 0) / 6) / 10;
  const sessionsOf = (p) => (members[p.id] || {}).sessions || 0;
  const progressOf = (p) => {
    if ((p.status || "unread") === "read") return 100;
    const v = Number(p.progress);
    return Number.isFinite(v) ? Math.max(0, Math.min(100, Math.round(v))) : 0;
  };
  const isoDay = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const dayNum = (s) => { const [y, m, d] = String(s).slice(0, 10).split("-").map(Number); return Date.UTC(y, m - 1, d) / 86400000; };
  const todayNum = () => dayNum(isoDay(new Date()));
  // Days since the newest :WorkSession on the entry; added_at when there is none.
  function untouched(p) {
    const last = ((sessByRef[p.id] || [])[0] || {}).date || p.added_at;
    if (!last) return null;
    return Math.max(0, todayNum() - dayNum(last));
  }
  const agoText = (d) => d == null ? "never" : d === 0 ? "today" : d === 1 ? "yesterday" : d + "d ago";
  const fmtH = (h) => (h >= 10 ? Math.round(h) : h);

  const passArea = (p) => !SF.area.size || SF.area.has(areaOf(p).key);
  const passKind = (p) => !SF.kind.size || SF.kind.has(p.kind || "paper");
  const passShelf = (p) => passArea(p) && passKind(p);
  const onTab = (p) => shelfTab === "master" || tabOf(p) === shelfTab;

  function shelfList() {
    const by = {
      num: (a, b) => shelfNum[a.id] - shelfNum[b.id],
      hours: (a, b) => hoursOf(b) - hoursOf(a) || shelfNum[a.id] - shelfNum[b.id],
      area: (a, b) => areaOf(a).key.localeCompare(areaOf(b).key) || shelfNum[a.id] - shelfNum[b.id],
      kind: (a, b) => (a.kind || "paper").localeCompare(b.kind || "paper") || shelfNum[a.id] - shelfNum[b.id],
      prog: (a, b) => progressOf(b) - progressOf(a) || shelfNum[a.id] - shelfNum[b.id],
      touched: (a, b) => (untouched(a) ?? 1e9) - (untouched(b) ?? 1e9) || shelfNum[a.id] - shelfNum[b.id],
    };
    return shelfAll.filter((p) => onTab(p) && passShelf(p)).sort(by[shelfSort] || by.num);
  }

  function moveTo(p, tab) {
    if (!TAB_STATUS[tab] || tabOf(p) === tab) return;
    if (tab === "main" && shelfAll.filter((x) => tabOf(x) === "main").length >= SHELF_MAX_MAIN) {
      toast("Current is full (6). Send one to Later first.", true);
      return;
    }
    const send = (extra) => guard(async () => {
      await window.api.papers.update(p.id, { status: TAB_STATUS[tab], ...extra });
      toast(p.title + " → " + SHELF_NAME[tab]);
      load();
    });
    if (tab !== "done") return send({});
    const take = field("One-line takeaway", p.takeaway || "", { ph: "what you are taking away from it" });
    modal("Onto the Finished shelf", { text: p.title }, [take], "Finish", (close) => {
      close();
      send({ takeaway: take.get() || null });
    });
    take.input.focus();
  }

  function startSession(p) {
    if (!window.Timers || !window.Timers.start) return toast("the timer is not loaded", true);
    window.Timers.start({ kind: "paper", ref_id: p.id, label: p.title, module: "synapse" });
    toast("timer started on " + p.title);
  }

  function shelfFilters() {
    const row = el("div.rs-filters");
    const base = shelfAll.filter(onTab);
    const box = (group, key, label, color, glyph) => {
      // a box's count honours the OTHER group, so it says what pressing it would show
      const n = base.filter((p) => group === "area"
        ? areaOf(p).key === key && passKind(p)
        : (p.kind || "paper") === key && passArea(p)).length;
      const on = SF[group].has(key);
      const b = el("button.rs-fb" + (on ? ".on" : "") + (n ? "" : ".zero"), {
        style: on ? "color:" + color : null,
        title: (on ? "stop filtering by " : "show only ") + label,
        onclick: () => { on ? SF[group].delete(key) : SF[group].add(key); saveFilters(); load(); },
      }, [el("span.rs-sq", { style: "background:" + color, text: glyph }), label + " ", el("b", { text: String(n) })]);
      row.appendChild(b);
    };
    AREAS.forEach((a) => box("area", a.key, a.label, a.color, a.label[0]));
    row.appendChild(el("span.rs-sep"));
    LENS_KINDS.forEach((k) => box("kind", k, KIND(k).label, "#8194a8", SPINE_GLYPH[k]));
    if (filtersOn()) {
      row.appendChild(el("button.rs-fclear", { text: "clear filters ✕",
        onclick: () => { SF.area.clear(); SF.kind.clear(); saveFilters(); load(); } }));
    }
    return row;
  }

  function spine(p) {
    const c = spineColor(p), t = tabOf(p), d = untouched(p);
    const s = el("div.rs-spine" + (t === "done" ? ".done" : t === "later" ? ".later" : "") + (p.id === shelfOpen ? ".sel" : ""), {
      draggable: "true", "data-id": p.id, title: p.title,
      onclick: () => { shelfOpen = shelfOpen === p.id ? null : p.id; renderShelf(); },
      ondragstart: (e) => e.dataTransfer.setData("text/plain", p.id),
    }, [
      el("i.rs-band.t", { style: "background:" + c }),
      el("div.rs-ico", { style: "background:" + c, text: SPINE_GLYPH[p.kind || "paper"] || "Pp" }),
      el("div.rs-ttl", { text: p.title }),
      el("div.rs-hrs", {}, [String(fmtH(hoursOf(p))), el("small", { text: "h" })]),
      el("div.rs-prog", {}, [el("i", { style: "width:" + progressOf(p) + "%;background:" + c })]),
      el("i.rs-band.b", { style: "background:" + c }),
      el("div.rs-num", { text: String(shelfNum[p.id]) }),
      t === "done" ? el("div.rs-seal", { text: "★" }) : null,
      t === "later" && d != null && d >= 14 ? el("div.rs-dust", { text: "since " + d + "d" }) : null,
    ]);
    return s;
  }

  function weekBars(p, color) {
    const wk = [0, 0, 0, 0, 0, 0, 0, 0];      // oldest first, last one is this week
    const today = todayNum();
    (sessByRef[p.id] || []).forEach((w) => {
      const ago = Math.floor((today - dayNum(w.date)) / 7);
      if (ago >= 0 && ago < 8) wk[7 - ago] += (w.mins || 0) / 60;
    });
    const mx = Math.max(1, ...wk);
    return [
      el("div.rs-week", {}, wk.map((h) => el("span", {
        style: "height:" + (h / mx * 100) + "%;background:" + (h ? color : "var(--raised)"),
        title: (Math.round(h * 10) / 10) + " h" }))),
      el("div.rs-wl", {}, wk.map((_, i) => el("span", { text: i === 7 ? "now" : "-" + (7 - i) }))),
    ];
  }

  function shelfInfo(p) {
    const c = spineColor(p), t = tabOf(p), a = areaOf(p), k = KIND(p.kind || "paper");
    const recent = (sessByRef[p.id] || []).slice(0, 8);
    const btn = (label, fn, title) => el("button.btn-sm", { text: label, title: title || null, onclick: fn });
    const upTile = el("div.rs-st", { style: "display:none" }, [
      el("div.rs-k", { text: "up to" }), el("div.rs-v", { style: "font-size:16px" })]);
    const fillUp = (txt) => { if (txt) { upTile.lastChild.textContent = txt; upTile.style.display = ""; } };
    if (p.id in upToCache) fillUp(upToCache[p.id]);
    else {
      // the latest pass that says where it got to: a chapter, or a page
      window.api.get("/api/synapse/instances?paper_id=" + encodeURIComponent(p.id)).then((insts) => {
        const at = (insts || []).filter((i) => i.chapter || i.pages_to)
          .sort((x, y) => String(y.read_date || y.created_at || "").localeCompare(String(x.read_date || x.created_at || "")))[0];
        upToCache[p.id] = at ? [at.chapter ? "ch " + at.chapter : "", at.pages_to ? "p " + at.pages_to : ""].filter(Boolean).join(" · ") : "";
        fillUp(upToCache[p.id]);
      }).catch(() => { upToCache[p.id] = ""; });
    }
    const pct = progressOf(p);
    const next = p.next_action || p.next || "";
    return el("div.rs-info", {}, [
      el("div.rs-ih", {}, [
        el("div.rs-big", { style: "background:" + c, text: SPINE_GLYPH[p.kind || "paper"] || "Pp" }),
        el("div", {}, [
          el("div.rs-it", { text: p.title }),
          el("div.rs-im", { text: "#" + shelfNum[p.id] + " · " + k.label.toLowerCase() + " · " + AREA_BY[a.key].label + " · on " + SHELF_NAME[t] }),
        ]),
        el("div.rs-acts", {}, [
          btn("▶ start session", () => startSession(p), "start a timer on this entry"),
          t !== "main" ? btn("→ Current", () => moveTo(p, "main")) : null,
          t !== "later" ? btn("→ Later", () => moveTo(p, "later")) : null,
          t !== "done" ? btn("✓ Finished", () => moveTo(p, "done")) : null,
          el("button.rs-close", { text: "✕", title: "close (Esc)", onclick: () => { shelfOpen = null; renderShelf(); } }),
        ]),
      ]),
      el("div.rs-stats", {}, [
        el("div.rs-st", {}, [el("div.rs-k", { text: "hours" }), el("div.rs-v", { text: hoursOf(p) + " h" })]),
        el("div.rs-st", {}, [el("div.rs-k", { text: "progress" }), el("div.rs-v", { text: pct + "%" }),
          el("div.rs-pbar", {}, [el("i", { style: "width:" + pct + "%;background:" + c })])]),
        upTile,
        el("div.rs-st", {}, [el("div.rs-k", { text: "sessions" }), el("div.rs-v", { text: String(sessionsOf(p)) })]),
        el("div.rs-st", {}, [el("div.rs-k", { text: "last touched" }), el("div.rs-v", { style: "font-size:16px", text: agoText(untouched(p)) })]),
      ]),
      el("div.rs-cols", {}, [
        el("div.rs-box", {}, [
          el("h4", { text: "recent sessions" }),
          el("ul.rs-ses", {}, recent.length
            ? recent.map((w) => el("li", {}, [
                el("span.d", { text: new Date(w.date + "T12:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" }) }),
                el("span", { text: w.what || w.notes || "session" }),
                el("span.h", { text: (Math.round((w.mins || 0) / 6) / 10) + " h" }),
              ]))
            : [el("li", {}, [el("span"), el("span", { style: "color:var(--dim)", text: "no sessions yet" }), el("span")])]),
        ]),
        el("div.rs-box", {}, [
          el("h4", { text: "hours per week, last 8 weeks" }),
          ...weekBars(p, c),
          p.takeaway
            ? el("div.rs-take", {}, [el("h4", { text: "takeaway" }), el("div.q", { text: p.takeaway })])
            : next ? el("div.rs-next", {}, ["next: ", el("b", { text: next })]) : null,
          el("a.rs-open", { href: "#", text: "open the full workspace ↗",
            onclick: (e) => { e.preventDefault(); window.PM.selectPaper(p.id); } }),
        ]),
      ]),
    ]);
  }

  function renderShelf() {
    const host = document.getElementById("repo-shelf");
    if (!host) return;
    const oldWrap = host.querySelector(".rs-wrap");
    const keepScroll = oldWrap ? oldWrap.scrollLeft : 0;
    const list = shelfList();
    if (shelfOpen && !list.some((p) => p.id === shelfOpen)) shelfOpen = null;
    clear(host);

    const totalH = Math.round(shelfAll.reduce((s, p) => s + ((members[p.id] || {}).mins || 0), 0) / 6) / 10;
    const counts = el("div.rs-counts", {}, [
      el("span", { title: "entries" }, [el("i", { style: "border-color:var(--teal)" }), el("b", { text: String(shelfAll.length) })]),
      el("span", { title: "finished", style: "color:var(--rs-gold)" }, [el("i", { style: "border-color:var(--rs-gold);background:var(--rs-gold)" }),
        el("b", { text: String(shelfAll.filter((p) => tabOf(p) === "done").length) })]),
      el("span", { title: "hours across every entry", style: "color:var(--muted)" }, ["⏱ ", el("b", { style: "color:var(--text)", text: String(fmtH(totalH)) }), "h"]),
    ]);
    const tabs = el("div.rs-tabs", {}, SHELF_TABS.map((t) => {
      const n = t.key === "master" ? shelfAll.length : shelfAll.filter((p) => tabOf(p) === t.key).length;
      const b = el("button.rs-tab" + (t.key === shelfTab ? ".on" : ""), {
        title: t.key === "master" ? null : "drop a book here to move it",
        onclick: () => { shelfTab = t.key; sset("tab", shelfTab); shelfOpen = null; load(); },
        ondragover: (e) => { if (t.key !== "master") { e.preventDefault(); b.classList.add("drop"); } },
        ondragleave: () => b.classList.remove("drop"),
        ondrop: (e) => {
          e.preventDefault(); b.classList.remove("drop");
          const p = shelfAll.find((x) => x.id === e.dataTransfer.getData("text/plain"));
          if (p) moveTo(p, t.key);
        },
      }, [t.label + " ", el("b", { text: String(n) })]);
      return b;
    }));
    const sort = el("select.rs-sort", { title: "sort the shelf" }, [
      ["num", "numerical order"], ["hours", "most hours"], ["area", "by area"],
      ["kind", "by kind"], ["prog", "by progress"], ["touched", "last touched"],
    ].map(([v, l]) => el("option", { value: v, text: l })));
    sort.value = shelfSort;
    sort.addEventListener("change", () => { shelfSort = sort.value; sset("sort", shelfSort); renderShelf(); });

    const marker = el("div.rs-marker", { style: "display:none" });
    const shelf = el("div.rs-shelf", {}, list.map(spine));
    if (shelfTab === "main" && !filtersOn()) {
      for (let i = list.length; i < SHELF_MAX_MAIN; i++) shelf.appendChild(el("div.rs-empty", { text: "+", title: "drag a book onto Current to fill this slot" }));
    }
    if (!list.length && shelfTab !== "main") {
      shelf.appendChild(el("div.rs-none", { text: filtersOn() ? "nothing on this shelf matches the filters" : "nothing on this shelf yet" }));
    }
    const wrap = el("div.rs-wrap", {}, [marker, shelf]);
    const open = list.find((p) => p.id === shelfOpen);

    host.appendChild(el("div.rs-frame", {}, [
      el("div.rs-top", {}, [counts, tabs, sort]),
      shelfFilters(),
      wrap,
      el("div.rs-ledge"),
      open ? shelfInfo(open) : el("div.rs-hint", { text: "press a book to see its info" }),
    ]));
    wrap.scrollLeft = keepScroll;
    requestAnimationFrame(() => {
      const sel = shelf.querySelector(".rs-spine.sel");
      if (!sel) return;
      marker.style.display = "";
      marker.style.left = (sel.offsetLeft + 28) + "px";
      const info = host.querySelector(".rs-info");
      if (info) info.scrollIntoView({ behavior: "smooth", block: "nearest" });
    });
  }

  // Esc closes the panel. Captured ahead of app.js, which sends Escape home.
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !shelfOpen) return;
    if (!document.querySelector("#repo-shelf .rs-info") || document.querySelector(".modal-overlay")) return;
    e.stopPropagation();
    e.preventDefault();
    shelfOpen = null;
    renderShelf();
  }, true);

  /* Everything the shelf needs beyond what load() already has: the whole
     library (the list may be cut by its search box), each entry's sessions
     (for last touched, recent sessions and the week bars), and the projects'
     module where one is set. */
  async function loadShelfData(filteredAll, listWasFiltered) {
    const [all, sess, projs] = await Promise.all([
      listWasFiltered ? window.api.papers.list("") : Promise.resolve(filteredAll),
      window.api.get("/api/work?ref_kind=paper&limit=10000").catch(() => []),
      window.api.get("/api/synapse/projects").catch(() => null),
    ]);
    shelfAll = all || [];
    shelfNum = {};
    shelfAll.forEach((p, i) => { shelfNum[p.id] = i + 1; });
    sessByRef = {};
    (sess || []).forEach((w) => { if (w.ref_id) (sessByRef[w.ref_id] = sessByRef[w.ref_id] || []).push(w); });
    projModule = {};
    ((projs && projs.projects) || []).forEach((pr) => { const m = pr.module || pr.area; if (m) projModule[pr.id] = m; });
  }

  async function load() {
    const view = document.getElementById("view-body-repo");
    if (!view) return;
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.status) params.set("status", filters.status);
    if (filters.year) params.set("year", filters.year);
    if (filters.kind) params.set("kind", filters.kind);
    const qs = params.toString() ? "?" + params.toString() : "";
    const [all, mem, plist, todos] = await guard(() => Promise.all([
      window.api.papers.list(qs),
      window.api.get("/api/synapse/attach/membership?kind=paper"),
      lens() === "project" ? window.api.get("/api/synapse/projects") : Promise.resolve(null),
      // open "look into" rows per paper — the "2 to check" on each card
      window.api.get("/api/rows/todo-counts").catch(() => ({})),
    ]));
    members = mem || {};
    toCheck = todos || {};
    await guard(() => loadShelfData(all, !!qs));
    renderShelf();
    // The "read" and "shelved" filters ask for exactly those entries, so they
    // ignore the toggle; everywhere else the toggle decides.
    const AWAY = ["read", "shelved"];
    // The shelf's area and kind boxes cut the list too.
    const shown = (all || []).filter(passShelf);
    const papers = (AWAY.includes(filters.status) || showRead())
      ? shown : shown.filter((p) => !AWAY.includes(p.status || "unread"));
    const hidden = shown.length - papers.length;
    clear(view);

    if (!papers.length) {
      const filtered = filters.q || filters.status || filters.year || filters.kind || filtersOn();
      view.appendChild(el("div.empty", { text: hidden
        ? "Everything here is finished or shelved — " + hidden + " hidden."
        : filtered
          ? "Nothing matches those filters."
          : "Nothing here yet — upload a PDF, or add a book or video series by hand." }));
      return;
    }
    if (hidden) {
      view.appendChild(el("div.sub", { style: "margin-bottom:8px;font-size:11px",
        text: hidden + " finished or shelved entr" + (hidden === 1 ? "y" : "ies") + " hidden" }));
    }
    if (lens() !== "project") {
      const grid = el("div.cards");
      papers.forEach((p, i) => grid.appendChild(paperCard(p, papers, i)));
      view.appendChild(grid);
      return;
    }

    // by project: the tree's order, each project with the entries in it
    const inLens = papers.filter((p) => LENS_KINDS.includes(p.kind || "paper"));
    const placed = new Set();
    (plist ? plist.projects : []).forEach((pr) => {
      const here = inLens.filter((p) => ((members[p.id] || {}).projects || []).some((m) => m.id === pr.id));
      if (!here.length) return;
      here.forEach((p) => placed.add(p.id));
      view.appendChild(el("div.pj-lens-grp", {}, [
        el("a.pj-lens-h", { text: "◆ " + pr.path, title: "open the project",
          onclick: () => window.ProjectAttach.openNode({ kind: "project", id: pr.id }) }),
        el("span.meta", { text: (Math.round(pr.rollup.logged_mins / 6) / 10) + "h in the project · " + here.length + " here" }),
      ]));
      const grid = el("div.cards");
      here.forEach((p, i) => grid.appendChild(paperCard(p, here, i)));
      view.appendChild(grid);
    });
    const loose = inLens.filter((p) => !placed.has(p.id));
    if (loose.length) {
      view.appendChild(el("div.pj-lens-grp", {}, [
        el("span.pj-lens-h", { text: "not in a project yet" }),
        el("span.meta", { text: loose.length + " · attach to project puts one in the tree" }),
      ]));
      const grid = el("div.cards");
      loose.forEach((p, i) => grid.appendChild(paperCard(p, loose, i)));
      view.appendChild(grid);
    }
    const other = papers.length - inLens.length;
    if (other) {
      view.appendChild(el("div.sub", { style: "margin-top:14px;font-size:11px",
        text: other + " other entr" + (other === 1 ? "y" : "ies") + " (videos, articles, notes…) show under everything." }));
    }
  }

  /* ---- upload ----
     The scan is a choice, not a step. A book whose opening pages are a cover —
     or a scanned one with no text at all — is better typed in, so untick it and
     the local LLM is never called. */
  function uploadBar() {
    const fileInput = el("input", { type: "file", accept: "application/pdf", style: "display:none" });
    // You are uploading a PDF, so the work kinds (project / decomposition /
    // idea / general) aren't on offer here, and "paper" leads rather than
    // whatever happens to sit first in KINDS.
    const kind = el("select.repo-mini", {}, KINDS.filter((k) => !k.link && k.key !== "topic").map((k) =>
      el("option", { value: k.key, text: k.icon + " " + k.label })));
    kind.value = "paper";
    const scan = el("input", { type: "checkbox", id: "repo-scan" });
    scan.checked = true;

    fileInput.addEventListener("change", async () => {
      if (!fileInput.files.length) return;
      const doScan = scan.checked;
      const form = new FormData();
      form.append("file", fileInput.files[0]);
      form.append("kind", kind.value);
      form.append("scan", doScan ? "true" : "false");
      toast(doScan ? "uploading + reading it (local LLM)…" : "uploading…");
      await guard(async () => {
        const p = await window.api.papers.upload(form);
        fileInput.value = "";
        load();
        if (p._warning) {
          // A scan has no text to read, so the title is a filename guess. Open
          // the editor with the reason stated in it — a toast would fade while
          // they're still reading, and the guess would then look like a reading.
          editModal(p, p._warning);
          return;
        }
        if (!doScan) {
          // Nothing was read, so the title is only the filename. Open the editor
          // rather than leaving it sitting there looking finished.
          toast("added — now name it");
          editModal(p, "Not scanned, as you asked. The title is just the filename — set it here.");
          return;
        }
        toast("added: " + p.title + "  [" + (p._extraction_source || "?") + "]");
      });
    });

    return el("div.row", { style: "gap:8px;align-items:center" }, [
      kind,
      el("label.repo-scan-lbl", { title: "Read the first pages with the local LLM to fill in the details. Untick for books and scans." },
        [scan, el("span", { text: "read it" })]),
      el("button.btn-primary", { onclick: () => fileInput.click(), text: "+ Upload PDF" }),
      el("button.btn-primary", { onclick: () => addModal(), title: "a project, a decomposition, an idea, a book, a video series — or just a subject. No file needed.", text: "+ Bring something in" }),
      fileInput,
    ]);
  }

  function filterBar() {
    const q = el("input", { placeholder: "search title / author", value: filters.q, style: "width:200px" });
    q.addEventListener("input", () => { filters.q = q.value; load(); });
    const status = el("select", {}, [
      el("option", { value: "", text: "all status" }),
      el("option", { value: "unread", text: "unread" }),
      el("option", { value: "reading", text: "reading" }),
      el("option", { value: "read", text: "read" }),
      el("option", { value: "revisit", text: "revisit" }),
      el("option", { value: "shelved", text: "shelved" }),
    ]);
    status.value = filters.status;
    status.addEventListener("change", () => { filters.status = status.value; load(); });
    const year = el("input", { placeholder: "year", value: filters.year, style: "width:80px" });
    year.addEventListener("input", () => { filters.year = year.value.trim(); load(); });
    const kind = el("select", {}, [
      el("option", { value: "", text: "all kinds" }),
      ...KINDS.map((k) => el("option", { value: k.key, text: k.icon + " " + k.label })),
    ]);
    kind.value = filters.kind;
    kind.addEventListener("change", () => { filters.kind = kind.value; load(); });

    // Cuts across the other filters, so it's a toggle rather than another
    // dropdown value — "all kinds" should still mean unfinished unless you say.
    const readToggle = el("button.btn-sm");
    const paint = () => {
      const on = showRead();
      readToggle.classList.toggle("heat-on", on);
      readToggle.textContent = on ? "✓ finished + shelved shown" : "finished + shelved hidden";
      readToggle.title = on ? "hide what you've finished or shelved" : "show finished and shelved entries too";
    };
    readToggle.addEventListener("click", () => { setShowRead(!showRead()); paint(); load(); });
    paint();

    const lensChips = el("span.row", { style: "gap:4px" }, [["project", "by project"], ["all", "everything"]].map(([k, l]) =>
      el("span.pj-chip-lens" + (lens() === k ? ".on" : ""), { text: l, title: k === "project"
        ? "papers, books and courses, grouped by the project they are in" : "every entry, every kind",
        onclick: (e) => {
          setLens(k);
          e.target.parentNode.querySelectorAll(".pj-chip-lens").forEach((c) => c.classList.toggle("on", c.textContent === l));
          load();
        } })));

    return el("div.row", {}, [lensChips, q, kind, status, year, readToggle]);
  }

  window.Views = window.Views || {};
  window.Views.repo = {
    id: "repo", label: "Repository", scoped: false,
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [ el("h1", { text: "Repository" }),
          el("div.sub", { text: "Everything you read, watch or work through — papers, books, video series, courses. A PDF is optional." }) ]),
        uploadBar(),
      ]));
      view.appendChild(el("div", { id: "repo-shelf" }));
      view.appendChild(filterBar());
      view.appendChild(el("div", { id: "view-body-repo", style: "margin-top:16px" }));
      load();
    },
  };
})();

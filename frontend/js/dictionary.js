/* dictionary.js — the global Mainframe Dictionary.
   A rich term store: ELI5, technical definition, video embed, questions,
   notes (with images), related links, 0-10 familiarity, a star/type tag
   (term/concept/method/person), and an optional header image on each card.
   Grid ⇄ detail (detail replaces the grid, with a Back button). Zero libs. */
(function () {
  const { el, clear, toast, guard, confirmDo, famClass } = window.ui;
  const api = window.api;
  const dict = api.dictionary;

  // ---- classification tag (the "star" tag the user asked for) ----
  const TYPES = {
    term:    { c: "var(--teal)",   bg: "var(--teal-d)",   l: "term" },
    concept: { c: "var(--purple)", bg: "var(--purple-d)", l: "concept" },
    method:  { c: "var(--amber)",  bg: "var(--amber-d)",  l: "method" },
    person:  { c: "var(--blue)",   bg: "var(--blue-d)",   l: "person" },
  };
  const TYPE_OPTS = Object.keys(TYPES).map((k) => ({ v: k, t: TYPES[k].l }));
  const famColor = (v) => (v <= 3 ? "var(--red)" : v <= 6 ? "var(--amber)" : "var(--teal)");

  // ---- view state (session only) ----
  let host = null;
  let detailId = null;
  let query = "", famFilter = "all", typeFilter = "all", starOnly = false;

  // =======================================================================
  //  small modal + field helpers (reuse the app's .modal / .mform-* CSS)
  // =======================================================================
  function openModal(titleText, fields, submitLabel, onSubmit, submitClass) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const card = el("div.modal", {}, [
      el("div.modal-title", { text: titleText }),
      ...fields.map((f) => f.node || f),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button" + (submitClass || ".btn-primary"), { text: submitLabel, onclick: () => onSubmit(close) }),
        el("button", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const first = card.querySelector("input,select,textarea");
    if (first) first.focus();
  }
  function fText(label, ph, val) {
    const input = el("input.mform-input", { placeholder: ph || "", value: val || "" });
    return { node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), input]), get: () => input.value.trim() };
  }
  function fSelect(label, options, val) {
    const input = el("select.mform-input", {}, options.map((o) => el("option", { value: o.v, text: o.t })));
    if (val) input.value = val;
    return { node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), input]), get: () => input.value };
  }
  function fNumber(label, val, min, max) {
    const input = el("input.mform-input", { type: "number", min: String(min), max: String(max), value: String(val) });
    return { node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), input]), get: () => Math.max(min, Math.min(max, parseInt(input.value) || 0)) };
  }

  // =======================================================================
  //  LIST VIEW
  // =======================================================================
  function buildQuery() {
    const parts = [];
    if (query) parts.push("q=" + encodeURIComponent(query));
    if (famFilter !== "all") parts.push("fam=" + famFilter);
    if (typeFilter !== "all") parts.push("type=" + typeFilter);
    if (starOnly) parts.push("starred=true");
    return parts.length ? "?" + parts.join("&") : "";
  }

  async function renderList(view) {
    clear(view);
    host = view;
    detailId = null;

    view.appendChild(el("div.view-head", {}, [
      el("div", {}, [
        el("h1", { text: "Dictionary" }),
        el("div.sub", { text: "Every term you've learned — ELI5s, videos, questions, notes. Global across Mainframe." }),
      ]),
      el("button.btn-primary", { onclick: openAddTerm, text: "+ Add term" }),
    ]));

    // search
    const search = el("input", {
      placeholder: "Search terms, ELI5, domain…",
      value: query,
      style: "width:100%;margin-bottom:12px",
    });
    let searchTimer = null;
    search.addEventListener("input", () => {
      query = search.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => refreshGrid(grid), 200);
    });
    view.appendChild(search);

    // familiarity filter chips
    view.appendChild(el("div.row", { style: "margin-bottom:8px" }, [
      chip("all", "All", "var(--muted)", () => famFilter === "all", () => { famFilter = "all"; }),
      chip("0-3", "0–3", "var(--red)", () => famFilter === "0-3", () => { famFilter = "0-3"; }),
      chip("4-6", "4–6", "var(--amber)", () => famFilter === "4-6", () => { famFilter = "4-6"; }),
      chip("7-10", "7–10", "var(--teal)", () => famFilter === "7-10", () => { famFilter = "7-10"; }),
    ]));

    // type filter chips + star-only toggle
    const typeRow = el("div.row", { style: "margin-bottom:16px" }, [
      chip("t-all", "All types", "var(--muted)", () => typeFilter === "all", () => { typeFilter = "all"; }),
      ...Object.keys(TYPES).map((k) =>
        chip("t-" + k, TYPES[k].l, TYPES[k].c, () => typeFilter === k, () => { typeFilter = k; })),
      starToggle(),
    ]);
    view.appendChild(typeRow);

    const grid = el("div.cards");
    view.appendChild(grid);
    await refreshGrid(grid);

    // Re-bind the filter chips now that `grid` exists (chips created above
    // reference it via closure over this same variable).
    function chip(id, label, color, isActive, onPick) {
      const b = el("button.btn-sm", {
        text: label,
        onclick: async () => { onPick(); reflectChips(view); await refreshGrid(grid); },
      });
      styleChip(b, isActive(), color);
      b.dataset.chip = id;
      return b;
    }
    function starToggle() {
      const b = el("button.btn-sm", {
        text: "★ starred",
        onclick: async () => { starOnly = !starOnly; reflectChips(view); await refreshGrid(grid); },
      });
      styleChip(b, starOnly, "var(--amber)");
      b.dataset.chip = "star";
      return b;
    }
    reflectChips(view);
  }

  function styleChip(b, active, color) {
    b.style.borderColor = active ? color : "var(--border)";
    b.style.color = active ? color : "var(--muted)";
    b.style.background = active ? "var(--raised)" : "transparent";
  }

  // Re-apply active styling to all chips after a state change.
  function reflectChips(view) {
    const map = {
      all: famFilter === "all", "0-3": famFilter === "0-3", "4-6": famFilter === "4-6", "7-10": famFilter === "7-10",
      "t-all": typeFilter === "all", star: starOnly,
    };
    Object.keys(TYPES).forEach((k) => (map["t-" + k] = typeFilter === k));
    const colors = {
      all: "var(--muted)", "0-3": "var(--red)", "4-6": "var(--amber)", "7-10": "var(--teal)",
      "t-all": "var(--muted)", star: "var(--amber)",
    };
    Object.keys(TYPES).forEach((k) => (colors["t-" + k] = TYPES[k].c));
    view.querySelectorAll("[data-chip]").forEach((b) => styleChip(b, !!map[b.dataset.chip], colors[b.dataset.chip] || "var(--muted)"));
  }

  async function refreshGrid(grid) {
    const terms = await guard(() => dict.list(buildQuery()));
    clear(grid);
    if (!terms.length) {
      grid.appendChild(el("div.empty", {
        style: "grid-column:1/-1",
        text: query || famFilter !== "all" || typeFilter !== "all" || starOnly
          ? "No terms match these filters."
          : 'No terms yet. Click "+ Add term", or use the → Dict button on any Workspace term.',
      }));
      return;
    }
    terms.forEach((t) => grid.appendChild(termCard(t)));
  }

  function termCard(t) {
    const ty = TYPES[t.type] || TYPES.term;
    const fc = famColor(t.familiarity);
    const kids = [];

    // optional header image (banner)
    if (t.image) {
      kids.push(el("img", {
        src: t.image, alt: "",
        style: "width:100%;height:120px;object-fit:cover;display:block;border-bottom:1px solid var(--border)",
        onerror: function () { this.style.display = "none"; },
      }));
    }

    // top: name + star + familiarity mini bar
    kids.push(el("div", { style: "padding:14px 16px;display:flex;justify-content:space-between;align-items:flex-start;gap:8px" }, [
      el("div", { style: "font-size:15px;font-weight:600;line-height:1.3" }, [
        t.starred ? el("span", { style: "color:var(--amber);margin-right:5px", text: "★" }) : null,
        document.createTextNode(t.name),
      ]),
      el("div", { style: "display:flex;align-items:center;gap:6px;flex-shrink:0" }, [
        el("div", { style: "width:44px;height:4px;background:var(--raised);border-radius:2px;overflow:hidden" }, [
          el("div", { style: `height:100%;width:${t.familiarity * 10}%;background:${fc}` }),
        ]),
        el("span.mono", { style: `font-size:11px;color:${fc}`, text: String(t.familiarity) }),
      ]),
    ]));

    // eli5 preview
    const eli5 = (t.eli5 || "").trim();
    kids.push(el("div", {
      style: "padding:0 16px 12px;font-size:12.5px;color:var(--muted);line-height:1.5" + (eli5 ? "" : ";font-style:italic"),
      text: eli5 ? (eli5.length > 120 ? eli5.slice(0, 120) + "…" : eli5) : "No ELI5 yet",
    }));

    // footer tags
    const foot = el("div", { style: "display:flex;gap:6px;flex-wrap:wrap;padding:10px 16px;border-top:1px solid var(--border)" });
    foot.appendChild(el("span.tag", { style: `background:${ty.bg};color:${ty.c}`, text: "★ " + ty.l }));
    if (t.domain) foot.appendChild(el("span.tag", { style: "background:var(--purple-d);color:var(--purple)", text: t.domain }));
    if (t.n_questions) foot.appendChild(el("span.tag", { style: "background:var(--amber-d);color:var(--amber)", text: t.n_questions + " Q" }));
    if (t.n_notes) foot.appendChild(el("span.tag", { style: "background:var(--blue-d);color:var(--blue)", text: t.n_notes + " notes" }));
    if (t.video) foot.appendChild(el("span.tag", { style: "background:var(--red-d);color:var(--red)", text: "🎥" }));
    if (t.n_related) foot.appendChild(el("span.tag", { style: "background:var(--teal-d);color:var(--teal)", text: t.n_related + " linked" }));
    kids.push(foot);

    return el("div.card", {
      style: "padding:0;overflow:hidden;cursor:pointer",
      onclick: () => openDetail(t.id),
    }, kids);
  }

  // =======================================================================
  //  DETAIL VIEW
  // =======================================================================
  function openDetail(id) { detailId = id; renderDetail(host, id); }
  function backToList() { detailId = null; renderList(host); }

  async function renderDetail(view, id) {
    clear(view);
    const t = await guard(() => dict.get(id));
    const ty = TYPES[t.type] || TYPES.term;
    const fc = famColor(t.familiarity);
    const reload = () => renderDetail(view, id);

    view.appendChild(el("button.btn-sm", { onclick: backToList, text: "← Back to dictionary", style: "margin-bottom:14px" }));

    // header image with controls
    view.appendChild(imageBlock(t, reload));

    // header row: name/tags + familiarity slider
    const nameWrap = el("div", {}, [
      el("div", { style: "font-size:26px;font-weight:700", text: t.name }),
      el("div.row", { style: "margin-top:8px;gap:8px" }, [
        el("span.tag", { style: `background:${ty.bg};color:${ty.c}`, text: "★ " + ty.l }),
        t.domain ? el("span.tag", { style: "background:var(--purple-d);color:var(--purple)", text: t.domain }) : null,
        t.source ? el("span.tag", { style: "background:var(--raised);color:var(--muted)", text: "src: " + t.source }) : null,
        el("span.tag", { style: "background:var(--raised);color:var(--muted)", text: "added " + window.ui.fmtDate(t.created_at) }),
      ]),
    ]);

    const famVal = el("span.mono", { style: `font-size:26px;font-weight:700;color:${fc}`, text: String(t.familiarity) });
    const slider = el("input", { type: "range", min: "0", max: "10", value: String(t.familiarity) });
    let famTimer = null;
    slider.addEventListener("input", () => {
      const v = +slider.value;
      famVal.textContent = String(v); famVal.style.color = famColor(v);
      clearTimeout(famTimer);
      famTimer = setTimeout(() => guard(() => dict.update(id, { familiarity: v })), 300);
    });
    const famBox = el("div", { style: "display:flex;align-items:center;gap:12px" }, [
      el("div", { style: "text-align:center" }, [
        famVal,
        el("div.mono", { style: "font-size:9px;color:var(--muted);letter-spacing:1px", text: "FAMILIARITY" }),
      ]),
      slider,
    ]);

    view.appendChild(el("div", {
      style: "display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin:14px 0 18px",
    }, [nameWrap, famBox]));

    // quick controls: type + star + edit name
    view.appendChild(el("div.card", { style: "margin-bottom:14px" }, [
      el("div.row", {}, [
        el("span.sub", { text: "Tag:" }),
        typeSelect(t, reload),
        starButton(t, reload),
        el("button.btn-sm", { onclick: () => editField(t, "name", "Term name", false, reload), text: "✎ rename" }),
        el("span", { style: "flex:1" }),
        el("button.btn-sm", { onclick: () => editField(t, "domain", "Domain (e.g. NLP, RL, maths)", false, reload), text: "domain" }),
        el("button.btn-sm", { onclick: () => editField(t, "source", "Source (e.g. Vaswani et al. 2017)", false, reload), text: "source" }),
      ]),
    ]));

    // ELI5
    view.appendChild(section("🧒 ELI5", [
      t.eli5
        ? el("div", { style: "font-size:14px;line-height:1.7", text: t.eli5 })
        : el("div.sub", { style: "font-style:italic", text: "No ELI5 yet. Add a simple, plain-language explanation." }),
      editBtn(() => editField(t, "eli5", "ELI5 — explain like I'm five", true, reload)),
    ]));

    // Technical definition
    view.appendChild(section("📐 Technical Definition", [
      t.definition
        ? el("div", { style: "font-size:13px;line-height:1.7", text: t.definition })
        : el("div.sub", { style: "font-style:italic", text: "No definition yet." }),
      editBtn(() => editField(t, "definition", "Technical definition", true, reload)),
    ]));

    // Video
    view.appendChild(section("🎥 Video", videoBody(t, reload)));

    // Questions
    view.appendChild(questionsSection(t, reload));

    // Notes
    view.appendChild(notesSection(t, reload));

    // Related
    view.appendChild(await relatedSection(t, reload));

    // delete
    view.appendChild(el("div", { style: "margin-top:18px;text-align:right" }, [
      el("button.btn-sm.btn-danger", {
        onclick: () => confirmDo(`Delete "${t.name}" from the dictionary?`, async () => {
          await dict.del(id); toast("deleted"); backToList();
        }),
        text: "Delete term",
      }),
    ]));
  }

  function section(title, bodyNodes) {
    return el("div.card", { style: "margin-bottom:14px" }, [
      el("div.mono", { style: "font-size:10px;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted);margin-bottom:10px", text: title }),
      ...bodyNodes.filter(Boolean),
    ]);
  }
  function editBtn(fn) {
    return el("div", { style: "margin-top:10px" }, [el("button.btn-sm", { onclick: fn, text: "✎ edit" })]);
  }

  function typeSelect(t, reload) {
    const sel = el("select", {}, TYPE_OPTS.map((o) => el("option", { value: o.v, text: o.t })));
    sel.value = t.type;
    sel.style.width = "120px";
    sel.addEventListener("change", () => guard(async () => { await dict.update(t.id, { type: sel.value }); reload(); }));
    return sel;
  }
  function starButton(t, reload) {
    return el("button.btn-sm", {
      style: t.starred ? "border-color:var(--amber);color:var(--amber)" : "",
      onclick: () => guard(async () => { await dict.update(t.id, { starred: !t.starred }); reload(); }),
      text: t.starred ? "★ starred" : "☆ star",
    });
  }

  function videoBody(t, reload) {
    const out = [];
    if (t.video) {
      let vid = t.video.replace("watch?v=", "embed/").replace("youtu.be/", "youtube.com/embed/");
      if (vid.includes("youtube.com/embed/")) {
        out.push(el("iframe", { width: "100%", height: "300", src: vid, frameborder: "0", allowfullscreen: true, style: "border-radius:8px;margin-bottom:8px;border:1px solid var(--border)" }));
      }
      out.push(el("a", { href: t.video, target: "_blank", style: "color:var(--teal);font-size:12px;word-break:break-all", text: t.video }));
    } else {
      out.push(el("div.sub", { style: "font-style:italic", text: "No video linked yet." }));
    }
    out.push(editBtn(() => editField(t, "video", "Video URL (YouTube embeds automatically)", false, reload)));
    return out;
  }

  function questionsSection(t, reload) {
    const body = [];
    (t.questions || []).forEach((q) => {
      body.push(el("div", { style: "padding:10px 0;border-bottom:1px solid var(--border)" }, [
        el("div.spread", {}, [
          el("div", { style: "font-size:13px;font-weight:500;display:flex;gap:8px;align-items:flex-start" }, [
            el("span.mono", { style: "font-size:10px;background:var(--amber-d);color:var(--amber);padding:2px 6px;border-radius:3px", text: "Q" }),
            document.createTextNode(q.question),
          ]),
          el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await dict.delQuestion(t.id, q.id); reload(); }), text: "×" }),
        ]),
        q.answer
          ? el("div", { style: "font-size:13px;color:var(--muted);padding-left:26px;margin-top:4px;line-height:1.6", text: q.answer })
          : el("div", { style: "padding-left:26px;margin-top:4px" }, [
              el("span.sub", { style: "font-style:italic", text: "No answer yet — " }),
              el("span", { style: "color:var(--amber);cursor:pointer;font-size:12px", text: "add one", onclick: () => editAnswer(t, q, reload) }),
            ]),
      ]));
    });
    body.push(el("div", { style: "margin-top:10px" }, [
      el("button.btn-sm", { style: "border-color:var(--amber);color:var(--amber)", onclick: () => openAddQuestion(t, reload), text: "+ Add question" }),
    ]));
    return section(`❓ Questions (${(t.questions || []).length})`, body);
  }

  function notesSection(t, reload) {
    const body = [];
    (t.notes || []).forEach((n) => {
      body.push(el("div", { style: "padding:10px 12px;border:1px solid var(--border);border-radius:6px;margin-bottom:8px;background:var(--raised)" }, [
        el("div.spread", {}, [
          el("div.mono", { style: "font-size:10px;color:var(--muted)", text: window.ui.fmtDate(n.date) }),
          el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await dict.delNote(t.id, n.id); reload(); }), text: "×" }),
        ]),
        el("div", { style: "font-size:13px;line-height:1.6;margin-top:4px", text: n.text }),
        n.image ? el("img", { src: n.image, style: "max-width:100%;border-radius:6px;margin-top:8px;border:1px solid var(--border)", onerror: function () { this.style.display = "none"; } }) : null,
      ].filter(Boolean)));
    });
    body.push(el("div", { style: "margin-top:6px" }, [
      el("button.btn-sm", { style: "border-color:var(--blue);color:var(--blue)", onclick: () => openAddNote(t, reload), text: "+ Add note" }),
    ]));
    return section(`📝 Notes (${(t.notes || []).length})`, body);
  }

  async function relatedSection(t, reload) {
    const chips = el("div.row", { style: "margin-bottom:10px" });
    (t.related || []).forEach((r) => {
      chips.appendChild(el("span.tag", {
        style: "background:var(--teal-d);color:var(--teal);cursor:pointer;padding:5px 10px;font-size:11px",
        text: r.name,
        onclick: () => openDetail(r.id),
      }));
      chips.appendChild(el("span", {
        style: "color:var(--muted);cursor:pointer;font-size:11px;margin:-4px 8px 0 -4px", text: "×",
        title: "unlink",
        onclick: () => guard(async () => { await dict.unlink(t.id, r.id); reload(); }),
      }));
    });
    if (!(t.related || []).length) chips.appendChild(el("div.sub", { style: "font-style:italic", text: "No related terms linked." }));
    return section(`🔗 Related Terms (${(t.related || []).length})`, [
      chips,
      el("button.btn-sm", { style: "border-color:var(--blue);color:var(--blue)", onclick: () => openLinkTerm(t, reload), text: "+ Link term" }),
    ]);
  }

  // ---- header image block ----
  function imageBlock(t, reload) {
    const wrap = el("div", { style: "margin-bottom:8px" });
    if (t.image) {
      wrap.appendChild(el("img", {
        src: t.image, alt: "",
        style: "width:100%;max-height:260px;object-fit:cover;border-radius:10px;border:1px solid var(--border);display:block",
        onerror: function () { this.style.display = "none"; },
      }));
    }
    const fileIn = el("input", { type: "file", accept: "image/*", style: "display:none" });
    fileIn.addEventListener("change", () => {
      if (!fileIn.files || !fileIn.files[0]) return;
      const form = new FormData();
      form.append("file", fileIn.files[0]);
      guard(async () => { await dict.uploadImage(t.id, form); toast("image set"); reload(); });
    });
    const controls = el("div.row", { style: "margin-top:8px" }, [
      fileIn,
      el("button.btn-sm", { onclick: () => fileIn.click(), text: t.image ? "⤢ replace picture" : "🖼 add picture" }),
      t.image ? el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await dict.delImage(t.id); reload(); }), text: "remove picture" }) : null,
    ].filter(Boolean));
    wrap.appendChild(controls);
    // gallery alongside the single hero picture above
    window.Images.mount(wrap, { module: "dictionary", contextId: t.id, surface: "dictionary-term", title: "More images" });
    return wrap;
  }

  // =======================================================================
  //  edit helpers + modals
  // =======================================================================
  function editField(t, field, label, multiline, reload) {
    const val = window.prompt(label + ":", t[field] || "");
    if (val === null) return;
    guard(async () => { await dict.update(t.id, { [field]: val }); reload(); });
  }
  function editAnswer(t, q, reload) {
    const val = window.prompt("Answer:", q.answer || "");
    if (val === null) return;
    guard(async () => { await dict.updateQuestion(t.id, q.id, { answer: val }); reload(); });
  }

  function openAddTerm() {
    const name = fText("Term", "e.g. self-attention");
    const type = fSelect("Tag", TYPE_OPTS, "term");
    const eli5 = fText("ELI5 — explain like I'm five", "Simple explanation anyone could understand…");
    const def = fText("Technical definition", "Precise definition…");
    const fam = fNumber("Familiarity (0–10)", 3, 0, 10);
    const video = fText("Video URL (optional)", "YouTube link…");
    const domain = fText("Domain (optional)", "e.g. NLP, RL, maths");
    const source = fText("Source (optional)", "e.g. Vaswani et al. 2017");
    openModal("Add Dictionary Term", [name, type, eli5, def, fam, video, domain, source], "Add term", (close) => {
      if (!name.get()) return toast("enter a term", true);
      guard(async () => {
        await dict.create({
          name: name.get(), type: type.get(), eli5: eli5.get() || null, definition: def.get() || null,
          familiarity: fam.get(), video: video.get() || null, domain: domain.get() || null, source: source.get() || null,
        });
        close(); toast("term added"); refreshCurrent();
      });
    });
  }

  function openAddQuestion(t, reload) {
    const q = fText("Question", "What don't you understand?");
    const a = fText("Answer (optional — fill in later)", "");
    openModal("Add question — " + t.name, [q, a], "Add question", (close) => {
      if (!q.get()) return toast("enter a question", true);
      guard(async () => { await dict.addQuestion(t.id, { question: q.get(), answer: a.get() || null }); close(); reload(); });
    });
  }

  function openAddNote(t, reload) {
    const text = fText("Note", "Your thoughts, observations, connections…");
    const image = fText("Image URL (optional)", "Paste an image URL…");
    openModal("Add note — " + t.name, [text, image], "Add note", (close) => {
      if (!text.get()) return toast("write something", true);
      guard(async () => { await dict.addNote(t.id, { text: text.get(), image: image.get() || null }); close(); reload(); });
    });
  }

  async function openLinkTerm(t, reload) {
    const all = await guard(() => dict.list());
    const linked = new Set((t.related || []).map((r) => r.id));
    const opts = all.filter((x) => x.id !== t.id && !linked.has(x.id)).map((x) => ({ v: x.id, t: x.name }));
    if (!opts.length) return toast("no other terms to link", true);
    const sel = fSelect("Select a term", opts, opts[0].v);
    openModal("Link related term — " + t.name, [sel], "Link term", (close) => {
      guard(async () => { await dict.link(t.id, sel.get()); close(); reload(); });
    });
  }

  // Re-render whichever view is currently showing.
  function refreshCurrent() {
    if (detailId) renderDetail(host, detailId);
    else renderList(host);
  }

  // =======================================================================
  //  register
  // =======================================================================
  window.Views = window.Views || {};
  window.Views.dictionary = {
    id: "dictionary", label: "Dictionary", scoped: false,
    render(view) {
      host = view;
      if (detailId) return renderDetail(view, detailId);
      return renderList(view);
    },
  };
})();

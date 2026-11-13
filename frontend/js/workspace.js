/* workspace.js — per-paper reading workspace: instances (v1/v2…), highlights
   tagged knew/new/rethink/implement, and terms with 0-10 familiarity sliders. */
(function () {
  const { el, clear, toast, guard, confirmDo, famClass, inlineRename, colorSwatch } = window.ui;
  const api = window.api;

  // image widget for one row/entity, returned as a child node
  function imgHost(id, surface) {
    const host = el("div");
    window.Images.mount(host, { module: "synapse", contextId: id, surface, title: "Images" });
    return host;
  }


  /* ---- colouring the boxes ----------------------------------------------
     Eight section boxes is more than you can hold as a shape, and every
     workspace lays them out identically — so the one thing that can make YOUR
     terms box findable is that you painted it. The colour is per workspace and
     per section, stored as a JSON object on the :Paper whose shape this file
     owns (section_colors), so adding a section here costs no backend change.

     Applied by decorating a finished card rather than by threading a colour
     argument through eight builders: each of those functions already knows
     enough, and none of them should have to know about this. */
  function sectionColors(paper) {
    try { return JSON.parse(paper.section_colors || "{}") || {}; }
    catch (e) { return {}; }
  }

  /* Adds the class, the current colour, and the dot that changes it. Returns
     the same node so it can wrap a builder call inline. The dot is rebuilt
     after each pick rather than mutated: it was built knowing the old colour,
     and one expression that reads the current value is easier to trust than
     three that update it. */
  function colorable(wrap, key, paper) {
    wrap.classList.add("ws-card");
    const h = wrap.querySelector("h3");

    function paint() {
      wrap.setAttribute("data-color", sectionColors(paper)[key] || "");
      if (!h) return;
      const old = h.querySelector(".ws-dot");
      const dot = colorSwatch(sectionColors(paper)[key] || "", pick, { title: "box border" });
      dot.classList.add("ws-dot");
      if (old) old.replaceWith(dot); else h.appendChild(dot);
    }

    const pick = (c) => guard(async () => {
      const next = sectionColors(paper);
      if (c) next[key] = c; else delete next[key];
      const saved = await api.patch("/api/synapse/papers/" + paper.id,
        { section_colors: JSON.stringify(next) });
      // Keep the cached subject in step, or the next rerender undoes the choice.
      paper.section_colors = saved.section_colors;
      if (window.PM.paper && window.PM.paper.id === paper.id) {
        window.PM.paper.section_colors = saved.section_colors;
      }
      paint();
    });

    paint();
    return wrap;
  }

  /* ---- panes you can size -----------------------------------------------
     The S/M/L/XL toggle began on "to look into later" (now + rows) and lives
     in ui.js, shared; only the read-back pane below is workspace-specific. */
  const { sizeButtons, sizePref } = window.ui;

  /* The read-back half of the same problem. The Master Instance is where every
     pass is read as one document, and a 460px window onto a paper you may have
     written pages about is the reading equivalent of a three-row textarea. Same
     toggle, same remembered choice — here it sets how tall the pane is *and*
     how big the text is, because reading back wants both. XL drops the cap and
     lets the page scroll instead of the pane. */
  const PANE_SIZES = [
    { key: "s",  label: "S",  max: "260px", font: "12px" },
    { key: "m",  label: "M",  max: "460px", font: "13px" },
    { key: "l",  label: "L",  max: "820px", font: "14.5px" },
    { key: "xl", label: "XL", max: "none",  font: "16px" },
  ];
  const PANE_DEFAULT = "l";

  function paneSizeBar(pane, prefKey, label) {
    const btns = sizeButtons(PANE_SIZES, prefKey, PANE_DEFAULT,
      (s) => { pane.style.maxHeight = s.max; pane.style.fontSize = s.font; },
      (s) => (s.key === "xl" ? "no height limit — the page scrolls instead"
                             : "pane about " + s.max + " tall, text " + s.font));
    return el("div.wl-sizebar", {}, [el("span.wl-label", { text: label || "" }), btns]);
  }

  let activeInstance = null;

  /* ---- nothing open yet ----------------------------------------------
     The workspace used to be a dead end until a paper was picked in the left
     panel. But most of what you want to work on isn't a paper — it's a project,
     a decomposition node, an idea, or a subject that hasn't decided what it is.
     So the empty state is a starting line instead: name the thing, and it opens.
     Saying what it is comes after, or never. */

  const SUBJECT_ICON = {
    topic: "🌀", paper: "📄", book: "📕", video: "🎬", course: "🎓",
    article: "📰", note: "🗒️", event: "🎟️", project: "🧱", decomp: "🌳", idea: "💡",
  };
  const subjectIcon = (p) => SUBJECT_ICON[p && p.kind] || SUBJECT_ICON.paper;

  // Where a linked subject's real home is, for the chip in the header.
  const LINK_TAB = { project: "project", decomp: "decomposition", idea: "ideas" };

  async function openSubject(id) {
    // The left-panel picker reads a cached list; a subject created a second ago
    // isn't in it, and the panel would show "— none —" over an open workspace.
    if (window.PM.refreshPapers) await window.PM.refreshPapers();
    await window.PM.selectPaper(id);      // selectPaper already lands on the workspace
  }

  function needPaper(view) {
    const wrap = el("div", { style: "max-width:640px;margin:40px auto" });
    wrap.appendChild(el("h1", { text: "Open a workspace" }));
    wrap.appendChild(el("div.sub", {
      style: "margin-bottom:18px;line-height:1.5",
      text: "On anything: a project, a decomposition, an idea, a paper — or a "
          + "general idea that is none of those yet. Passes, highlights, terms "
          + "and images all work the same either way.",
    }));

    // Start one from nothing: a title is the whole form.
    const input = el("input.mform-input", {
      placeholder: "what are you working on? (a sentence is fine)",
      style: "flex:1",
    });
    const start = () => {
      const title = input.value.trim();
      if (!title) return toast("give it a title — that's all it needs", true);
      guard(async () => {
        // kind "topic" = untyped on purpose. Say what it is later in the
        // repository, or leave it a general idea forever.
        const p = await api.papers.create({ kind: "topic", title });
        toast("workspace open: " + p.title);
        await openSubject(p.id);
      });
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") start(); });
    wrap.appendChild(el("div.row", { style: "gap:8px;margin-bottom:22px" }, [
      input, el("button.btn-primary", { onclick: start, text: "Start" }),
    ]));

    // Or pick up something already in the library, newest work first.
    const recent = el("div");
    wrap.appendChild(recent);
    guard(async () => {
      const all = await api.papers.list();
      if (!all.length) return;
      recent.appendChild(el("div.mform-label", { text: "OR PICK UP WHERE YOU LEFT OFF" }));
      const list = el("div", { style: "display:flex;flex-direction:column;gap:6px;margin-top:8px" });
      all.slice(0, 12).forEach((p) => list.appendChild(el("button.tk-btn", {
        style: "text-align:left;justify-content:flex-start",
        onclick: () => openSubject(p.id),
        text: subjectIcon(p) + "  " + p.title,
      })));
      recent.appendChild(list);
    });

    view.appendChild(wrap);
  }

  // ---- dictionary quick-check / quick-add (any word → entry, exists-check) ----
  /* The last word checked, so the card's bottom line can say so. Per browser,
     a convenience only. */
  const DICT_LAST_KEY = "workspace.dict.last";
  function dictLast() {
    try { return JSON.parse(localStorage.getItem(DICT_LAST_KEY) || "null"); } catch (_) { return null; }
  }
  function dictLastText(v) {
    if (!v || !v.word) return "nothing checked yet";
    const d = new Date(v.at);
    const day = isNaN(d) ? "" : " · " + d.getDate() + " "
      + d.toLocaleDateString("en-GB", { month: "short" }).toLowerCase();
    return "last checked: " + v.word + day;
  }

  function dictWidget() {
    const wrap = el("div.card");
    wrap.appendChild(el("h3", { text: "Dictionary · check or add a word" }));
    wrap.appendChild(el("div.sub", { style: "margin-top:2px", text: "type any word to see if it's in your Dictionary, or add it." }));
    const nameIn = el("input", { placeholder: "a word or term…", style: "flex:1;min-width:160px" });
    const result = el("div", { style: "margin-top:10px" });

    async function check() {
      const name = nameIn.value.trim();
      if (!name) return;
      const r = await guard(() => api.dictionary.lookup(name));
      const v = { word: name, at: new Date().toISOString() };
      try { localStorage.setItem(DICT_LAST_KEY, JSON.stringify(v)); } catch (_) {}
      last.textContent = dictLastText(v);
      clear(result);
      if (r.exists) {
        const t = r.term;
        result.appendChild(el("div", { style: "padding:8px 0" }, [
          el("div.row", {}, [ el("span.tag.knew", { text: "✓ in dictionary" }), el("span", { style: "font-weight:600", text: t.name }) ]),
          el("div.sub", { style: "margin-top:4px", text: t.definition || t.eli5 || "(no definition saved yet)" }),
        ]));
      } else {
        const defIn = el("input", { placeholder: "definition (optional, leave blank to fill later)", style: "width:100%;margin-top:8px" });
        result.appendChild(el("div", { style: "padding:6px 0" }, [
          el("div.sub", { text: "“" + name + "” isn't in the Dictionary yet." }),
          defIn,
          el("div.row", { style: "margin-top:8px" }, [
            el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
              await api.dictionary.create({ name, definition: defIn.value.trim() || null });
              toast("added “" + name + "” to Dictionary");
              nameIn.value = ""; clear(result);
            }), text: "+ add to Dictionary" }),
          ]),
        ]));
      }
    }
    nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") check(); });
    const last = el("div.ws-meta", { text: dictLastText(dictLast()) });
    wrap.appendChild(el("div.row", { style: "margin-top:10px;flex-wrap:nowrap" }, [ nameIn, el("button.btn-sm", { onclick: check, text: "check" }) ]));
    wrap.appendChild(result);
    // The spacer pushes the bottom line down so both cards in the row end level.
    wrap.appendChild(el("div.ws-grow"));
    wrap.appendChild(last);
    return wrap;
  }

  // ---- screenshots / figures / annotations attached to this paper ----
  function imagesWidget(paper) {
    const wrap = el("div.card");
    wrap.appendChild(el("h3", { text: "📷 Images" }));
    wrap.appendChild(el("div.sub", { style: "margin-top:2px", text: "screenshots, figures, annotations attached to this subject." }));
    window.Images.mount(wrap, { module: "synapse", contextId: paper.id, surface: "synapse-paper" });
    return wrap;
  }

  // ---- terms ----
  async function termsSection(paperId) {
    const wrap = el("div.card");
    let hideOptional = false;
    wrap.appendChild(el("div.spread", {}, [
      el("h3", { text: "Terms and familiarity, 0 to 10" }),
      el("button.btn-sm", { onclick: () => suggestTerms(paperId), text: "✦ suggest (local LLM)" }),
    ]));
    const filterCb = el("input", { type: "checkbox" });
    filterCb.addEventListener("change", () => { hideOptional = filterCb.checked; reload(); });
    wrap.appendChild(el("label.sub", { style: "display:flex;gap:6px;align-items:center;cursor:pointer;margin-top:6px" }, [
      filterCb, document.createTextNode("hide optional / review-later"),
    ]));
    const list = el("div", { style: "margin-top:10px" });
    wrap.appendChild(list);

    async function reload() {
      let terms = await guard(() => api.get("/api/synapse/terms?paper_id=" + paperId));
      if (hideOptional) terms = terms.filter((t) => !t.optional);
      clear(list);
      if (!terms.length) list.appendChild(el("div.sub", { text: "No terms yet." }));
      terms.forEach((t) => list.appendChild(termRow(t, paperId, reload)));
    }
    // add-term form
    const nameIn = el("input", { placeholder: "term", style: "width:130px" });
    const defIn = el("input", { placeholder: "definition (optional)", style: "flex:1;min-width:130px" });
    const famIn = el("input", { type: "number", min: "0", max: "10", value: "0", style: "width:56px" });
    const optCb = el("input", { type: "checkbox", title: "mark optional / review later" });
    wrap.appendChild(el("div.ws-grow"));
    wrap.appendChild(el("div.row", { style: "margin-top:12px" }, [
      nameIn, defIn, famIn,
      el("label.sub", { style: "display:flex;gap:4px;align-items:center", title: "optional / review later" }, [optCb, document.createTextNode("opt")]),
      el("button.btn-sm", { onclick: () => guard(async () => {
        if (!nameIn.value.trim()) return;
        await api.post("/api/synapse/terms?paper_id=" + paperId, { name: nameIn.value.trim(), definition: defIn.value.trim() || null, familiarity: +famIn.value, optional: optCb.checked });
        nameIn.value = ""; defIn.value = ""; famIn.value = "0"; optCb.checked = false; reload();
      }), text: "+ add" }),
    ]));
    await reload();
    return wrap;
  }

  function termRow(t, paperId, reload) {
    const val = el("span.fam." + famClass(t.familiarity), { text: String(t.familiarity) });
    const slider = el("input", { type: "range", min: "0", max: "10", value: String(t.familiarity) });
    let timer = null;
    slider.addEventListener("input", () => {
      val.textContent = slider.value; val.className = "fam " + famClass(+slider.value);
      clearTimeout(timer);
      timer = setTimeout(() => guard(() => api.patch("/api/synapse/terms/" + t.id, { familiarity: +slider.value })), 350);
    });
    const optBtn = el("button.btn-sm" + (t.optional ? ".opt-on" : ""), {
      title: "toggle optional / review-later",
      onclick: () => guard(async () => { await api.patch("/api/synapse/terms/" + t.id, { optional: !t.optional }); reload(); }),
      text: t.optional ? "★ opt" : "☆ opt",
    });
    return el("div", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
      el("div.spread", {}, [
        el("div", {}, [
          el("span", { text: t.name }),
          t.optional ? el("span.tk-tag", { style: "background:var(--amber-d);color:var(--amber);margin-left:6px", text: "optional" }) : null,
          t.domain ? el("span.sub", { text: "  · " + t.domain }) : null,
        ]),
        el("div.row", {}, [ slider, val, optBtn,
          el("button.btn-sm", { title: "add to Dictionary", onclick: () => guard(async () => {
            const r = await api.dictionary.fromConcept({
              name: t.name, definition: t.definition || null, domain: t.domain || null,
              familiarity: t.familiarity, type: "term",
            });
            toast(r && r._already ? t.name + " already in dictionary" : "→ added " + t.name + " to Dictionary");
          }), text: "→ Dict" }),
          el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
            await api.del("/api/synapse/terms/" + t.id + "?paper_id=" + paperId); reload();
          }), text: "×" }) ]),
      ]),
      t.definition ? el("div.sub", { style: "margin-top:2px", text: t.definition }) : null,
      imgHost(t.id, "synapse-term"),
    ]);
  }

  async function suggestTerms(paperId) {
    toast("asking local LLM…");
    const form = new FormData();
    const cands = await guard(() => api.postForm("/api/synapse/terms/suggest?paper_id=" + paperId, form));
    if (!cands.length) { toast("no suggestions (LLM offline?)", true); return; }
    for (const c of cands) {
      await api.post("/api/synapse/terms?paper_id=" + paperId, { name: c.name, definition: c.definition, domain: c.domain, familiarity: 0 });
    }
    toast("added " + cands.length + " candidate terms");
    window.Views.workspace.render(document.getElementById("view"), window.PM);
  }

  // ---- highlights ----
  function highlightRow(h, reload) {
    return el("div", { style: "padding:8px 0;border-bottom:1px solid var(--border)" }, [
      el("div.spread", {}, [
        el("div.row", {}, [ el("span.tag." + h.tag, { text: h.tag }), h.section ? el("span.sub", { text: h.section }) : null, h.page ? el("span.sub", { text: "p." + h.page }) : null ]),
        el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.del("/api/synapse/highlights/" + h.id); reload(); }), text: "×" }),
      ]),
      h.excerpt ? el("div", { style: "margin-top:4px", text: h.excerpt }) : null,
      h.my_note ? el("div.sub", { style: "margin-top:2px", text: "▸ " + h.my_note }) : null,
      imgHost(h.id, "synapse-highlight"),
    ]);
  }

  async function highlightsSection(instanceId) {
    const wrap = el("div.card", { style: "margin-top:14px" });
    wrap.appendChild(el("h3", { text: "Highlights" }));
    const list = el("div"); wrap.appendChild(list);
    async function reload() {
      const hs = await guard(() => api.get("/api/synapse/highlights?instance_id=" + instanceId));
      clear(list);
      if (!hs.length) list.appendChild(el("div.sub", { text: "No highlights yet." }));
      hs.forEach((h) => list.appendChild(highlightRow(h, reload)));
    }
    const excerpt = el("input", { placeholder: "excerpt", style: "flex:1;min-width:160px" });
    const note = el("input", { placeholder: "your note", style: "flex:1;min-width:120px" });
    const section = el("input", { placeholder: "§", style: "width:60px" });
    const page = el("input", { type: "number", placeholder: "pg", style: "width:56px" });
    const tag = el("select", {}, ["knew","new","rethink","implement"].map((t) => el("option", { value: t, text: t })));
    tag.value = "new";
    wrap.appendChild(el("div.row", { style: "margin-top:10px" }, [ tag, section, page, excerpt, note,
      el("button.btn-sm", { onclick: () => guard(async () => {
        await api.post("/api/synapse/highlights?instance_id=" + instanceId, {
          tag: tag.value, section: section.value, page: page.value ? +page.value : null,
          excerpt: excerpt.value, my_note: note.value });
        excerpt.value = note.value = section.value = page.value = ""; reload();
      }), text: "+ add" }) ]));
    await reload();
    return wrap;
  }

  /* Whether the active pass's form is showing. Kept outside the function so it
     survives the re-render that follows a save, and in localStorage so a paper
     you're only reading — not logging — stays uncluttered between visits. */
  const LOG_OPEN_KEY = "mf.workspace.sessionOpen";
  const logOpen = () => localStorage.getItem(LOG_OPEN_KEY) !== "0";
  const setLogOpen = (v) => localStorage.setItem(LOG_OPEN_KEY, v ? "1" : "0");

  // ---- reading-session log for the active instance ----
  function sessionLog(inst, view, instCount, paper) {
    const box = el("div", { style: "margin-top:14px;padding-top:12px;border-top:1px solid var(--border)" });
    window.Images.mount(box, { module: "synapse", contextId: inst.id, surface: "synapse-instance", title: "Session images" });
    box.appendChild(el("div.sub", { style: "margin-bottom:8px", text: "Session log — v" + inst.version + (inst.created_at ? " · started " + (inst.created_at || "").slice(0, 10) : "") }));
    const purpose = el("input", { value: inst.purpose || "", placeholder: "purpose (e.g. revisit)", style: "flex:1;min-width:120px" });
    const readDate = el("input", { type: "date", value: (inst.read_date || "").slice(0, 10) });

    // --- structured timing: started / ended / spent, split active vs passive,
    // and how many times you got pulled away. Blank or 0 where it doesn't fit.
    const num = (v, w) => el("input", { type: "number", min: "0", value: v || 0, style: "width:" + (w || 68) + "px" });
    const start = el("input", { type: "time", value: inst.start || "" });
    const end = el("input", { type: "time", value: inst.end || "" });
    const mins = num(inst.mins, 76);
    const activeMins = num(inst.active_mins);
    const passiveMins = num(inst.passive_mins);
    const distractions = num(inst.distractions);

    // clock times fill the duration in, until you type one yourself
    let minsTouched = !!(inst.mins && !(inst.start && inst.end));
    mins.addEventListener("input", () => { minsTouched = true; splitNote(); });
    const syncMins = () => {
      if (!minsTouched && start.value && end.value) {
        const p = (t) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
        let d = p(end.value) - p(start.value);
        if (d < 0) d += 1440;                        // ran past midnight
        mins.value = d;
      }
      splitNote();
    };
    start.addEventListener("change", syncMins);
    end.addEventListener("change", syncMins);
    [activeMins, passiveMins].forEach((n) => n.addEventListener("input", splitNote));

    /* --- where in the book -------------------------------------------
       Books only. A paper is read front to back and "chapter 3, pp.44-49" is
       not a thing you can say about it; a book is worked through, and where
       you got to is the one fact the master record cannot reconstruct from
       anything else.

       Chapter is a TEXT box, not a number: a session that ran across a
       boundary is honestly "1 to 2". Both page boxes may be left empty — an
       end page you did not note stays unknown rather than being invented,
       which is why the master record prints "pp.22 →" for those. */
    const isBook = !!paper && paper.kind === "book";
    const chapter = el("input", {
      value: inst.chapter || "", placeholder: "3, or 1 to 2", style: "width:96px" });
    const pageNum = (v) => el("input", {
      type: "number", min: "0", value: (v === null || v === undefined) ? "" : v,
      placeholder: "—", style: "width:72px" });
    const pagesFrom = pageNum(inst.pages_from);
    const pagesTo = pageNum(inst.pages_to);
    const MODES = [["", "— mode —"], ["read", "read"], ["exercises", "exercises"],
                   ["code", "code"], ["review", "review"]];
    const mode = el("select", { style: "min-width:104px" },
      MODES.map(([v, t]) => el("option", { value: v, text: t })));
    mode.value = inst.mode || "";

    // a quiet nudge when active+passive doesn't line up with the total
    const note = el("span.sub", { style: "font-size:10px" });
    function splitNote() {
      const total = Number(mins.value) || 0;
      const split = (Number(activeMins.value) || 0) + (Number(passiveMins.value) || 0);
      if (!total && !split) { note.textContent = ""; return; }
      if (split === total) { note.textContent = "✓ splits add up"; note.style.color = "var(--teal)"; return; }
      note.textContent = split > total ? "split is " + (split - total) + "m over the total"
        : (total - split) + "m unaccounted";
      note.style.color = "var(--muted)";
    }
    splitNote();

    /* Distractions as a list — one row per interruption, each saying what it
       was. A count says the session went badly; the entries say what to change.

       EVERY ENTRY GOES TO LESSONS ON SAVE — no button, nothing to remember.
       Lessons groups them and reports the gaps between occurrences, and
       that only answers "is this getting better or worse" if the record is
       complete; gaps computed from the ones you thought to push are worse than
       no answer. The server matches what you type against the kinds already in
       use, so "phone", "my phone" and "phone buzzing" stay one pattern rather
       than becoming three that never repeat. Saving twice does not log twice. */
    const distList = el("div.dist-list");
    const distRows = [];
    function addDist(value, focus) {
      const input = el("input", { placeholder: "what pulled you away — phone, noise, hunger…",
        style: "flex:1;min-width:180px", value: value || "" });
      const row = el("div.row", { style: "gap:6px;margin-top:6px" }, [
        el("span.dist-n", { text: String(distRows.length + 1) }),
        input,
        // Push THIS distraction on its own. The whole-set button below sends
        // them together as one entry; this one keeps a single recurring
        // interruption as its own kind, which is what repeat detection needs.
        el("button.btn-sm", { title: "file this one now, in your own words. It goes to Lessons on save either way", text: "↗", onclick: () => guard(async () => {
          const v = input.value.trim();
          if (!v) return toast("write what it was first", true);
          await api.post("/api/lessons", {
            wrong: "distracted by " + v + " while reading v" + inst.version
              + (window.PM && window.PM.paper ? " (" + window.PM.paper.title + ")" : ""),
            instead: "",
            pattern: v,
            source: "distraction",
            date: (readDate.value || "").slice(0, 10) || undefined,
            about_id: inst.id,
          });
          toast("filed under " + v);
        }) }),
        el("button.btn-sm.btn-danger", { title: "remove", text: "×", onclick: () => {
          const i = distRows.findIndex((r) => r.input === input);
          if (i >= 0) distRows.splice(i, 1);
          row.remove(); renumber(); syncCount();
        } }),
      ]);
      distRows.push({ input, row });
      distList.appendChild(row);
      renumber(); syncCount();
      if (focus) input.focus();
    }
    const renumber = () => distRows.forEach((r, i) => { r.row.querySelector(".dist-n").textContent = String(i + 1); });
    // The count is still yours to set — you might be pulled away five times and
    // only bother describing three — but it can never sit below what you've
    // actually listed.
    const syncCount = () => {
      if ((Number(distractions.value) || 0) < distRows.length) distractions.value = distRows.length;
    };
    const distValues = () => distRows.map((r) => r.input.value.trim()).filter(Boolean);
    (inst.distraction_items || []).forEach((d) => addDist(d));
    const addDistBtn = el("button.btn-sm", { text: "+ add distraction", onclick: () => addDist("", true) });
    /* The write-up, in the order the questions actually get asked after a read:
       what you understood, what you're still asking, what to come back to —
       which is a to-do rather than a finding — and last the general notes, for
       whatever none of the four asked for. ("What you took away" opened this
       list until it was dropped as a duplicate of "what did I understand".
       :Instance.notes, the property it filled, is what "general notes" writes
       to now, so a pass that already carries one opens with it in the box.)
       Each is a + rows box on the pass: one thing understood, one thing to come
       back to, one note per row, saved on Enter — not with "save session".
       "understood" is its own kind so it never mixes with the general notes
       on the same pass; it wears the note colour. */
    const understoodBox = window.RowBox({
      label: "what did I understand", kind: "understood", noun: "point", parentId: inst.id,
      placeholder: "in your own words, the part you could now explain",
    });

    /* The main question is a list, not a paragraph. One pass rarely leaves you
       with exactly one question, and three of them in a textarea are one string
       that the Questions tab cannot count, answer or carry anywhere. Each row
       saves on Enter as its own :Question and lands in the Inbox as an idea, so
       a question you wrote and then walked away from is still a question you
       asked. See listbox.js. */
    const mainQBox = window.ListBox({
      label: "main question", kind: "main question", parentId: inst.id,
      noun: "question",
      placeholder: "the question this leaves you with, one per row",
      note: "each one goes to the Questions tab and the Inbox",
    });

    /* What the pass took for granted, beside what it left you asking. Same
       list box, its own store: each row is a numbered :Assumption (A7) that
       the Assumptions tab gathers. See assumptions.js. */
    const assumpBox = window.ListBox({
      label: "assumptions", kind: "assumption", parentId: inst.id,
      endpoint: "/api/assumptions", noun: "assumption",
      placeholder: "something this pass takes for granted, one per row",
      note: "numbered in the Assumptions tab",
      onChange: () => window.refreshAssumptionBadge && window.refreshAssumptionBadge(),
    });

    /* Passes written before the change still hold their question as one string.
       Rather than drop it or silently rewrite it, show it and let one click
       make it a row. */
    const legacyQ = el("div");
    if ((inst.main_question || "").trim()) {
      const text = inst.main_question.trim();
      legacyQ.appendChild(el("div.row", { style: "gap:8px;align-items:flex-start;margin-top:6px" }, [
        el("span.sub", { style: "font-size:10px;min-width:58px", text: "written as" }),
        el("div", { style: "flex:1;font-size:12px;color:var(--dim)", text: text }),
        el("button.btn-sm", { text: "keep as question", onclick: () => guard(async () => {
          await api.post("/api/questions", { text: text, kind: "main question", parent_id: inst.id });
          await api.patch("/api/synapse/instances/" + inst.id, { main_question: "" });
          toast("kept"); rerender(view);
        }) }),
      ]));
    }

    const lookIntoBox = window.RowBox({
      label: "to look into later", kind: "look into", noun: "thing to look into", parentId: inst.id,
      placeholder: "a section to reread, a term to check…",
    });

    /* Whatever the four questions above didn't ask for. It writes to
       :Instance.notes — the property the dropped "what you took away" box used
       to fill — so a pass that already carries one opens with it in the box
       instead of only showing it in the Master Instance. */
    const notesBox = window.RowBox({
      label: "general notes", kind: "note", noun: "note", parentId: inst.id,
      placeholder: "anything else from this session…",
    });
    const save = el("button.btn-sm.btn-primary", { text: "save session", onclick: () => guard(async () => {
      await api.patch("/api/synapse/instances/" + inst.id, {
        purpose: purpose.value.trim() || inst.purpose || "revisit",
        read_date: readDate.value || null,
        start: start.value || "",
        end: end.value || "",
        mins: Number(mins.value) || 0,
        active_mins: Number(activeMins.value) || 0,
        passive_mins: Number(passiveMins.value) || 0,
        distractions: Number(distractions.value) || 0,
        distraction_items: distValues(),
        // Books only, and "" / null where a value was not given: the master
        // record distinguishes "page 49" from "not written down", and sending
        // 0 for an empty page box would destroy that distinction.
        ...(isBook ? {
          chapter: chapter.value.trim(),
          pages_from: pagesFrom.value === "" ? null : Number(pagesFrom.value),
          pages_to: pagesTo.value === "" ? null : Number(pagesTo.value),
          mode: mode.value || null,
        } : {}),
      });
      toast("session saved"); rerender(view);
    }) });

    /* The whole-set "push to learning" button is gone: saving the session is
       the push now, so a button that did it again would either duplicate the
       occurrences or do nothing, and both are worse than no button. The
       per-entry ↗ stays — see addDist — for wording one yourself. */
    const learnNote = el("span.sub", { style: "font-size:10px",
      text: "↗ each one goes to Lessons when you save" });

    const field = (label, node) => el("label.wl-field", {}, [el("span.wl-label", { text: label }), node]);
    box.appendChild(el("div.row", { style: "gap:10px;flex-wrap:wrap" }, [
      field("purpose", purpose), field("read on", readDate),
    ]));
    // One button walks started → ended, so a session can be bracketed without
    // typing a clock time at all. syncMins turns that into the duration.
    const stamp = window.ui.stampPair(start, end, { onChange: syncMins });
    box.appendChild(el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap;align-items:flex-end" }, [
      field("started", start), field("ended", end), stamp,
      field("time spent (m)", mins),
      field("active (m)", activeMins), field("passive (m)", passiveMins),
      field("distractions", distractions),
      note,
    ]));
    if (isBook) {
      box.appendChild(el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap;align-items:flex-end" }, [
        field("chapter", chapter),
        field("pages from", pagesFrom), field("to", pagesTo),
        field("mode", mode),
        el("span.sub", { style: "font-size:10px",
          text: "a chapter counts as done once it has a read AND an exercises session" }),
      ]));
    }
    box.appendChild(understoodBox.node);
    box.appendChild(mainQBox.node);
    box.appendChild(legacyQ);
    box.appendChild(assumpBox.node);
    box.appendChild(lookIntoBox.node);
    box.appendChild(notesBox.node);
    // Distractions sit after the write-up: what you understood is the point of
    // the session, what interrupted it is the postscript.
    box.appendChild(el("div", { style: "margin-top:10px" }, [
      el("div.row", { style: "gap:8px;align-items:center" }, [
        el("span.wl-label", { text: "what the distractions were" }), addDistBtn, learnNote,
      ]),
      distList,
    ]));

    /* Push this reading session into the work database.
       The shapes don't map one-to-one — a work row carries a single `focus`
       while a reading instance splits its minutes across active and passive,
       and it counts distractions rather than timing them. So this pre-fills
       the form (focus = whichever side dominates, the split and the count
       carried into the notes) and lets you adjust before saving, instead of
       guessing silently. */
    const pushHost = el("div");
    const pushBtn = window.WorkLog.button({
      mountInto: pushHost,
      module: "synapse",
      ref_kind: "paper",
      ref_id: (window.PM && window.PM.paper) ? window.PM.paper.id : null,
      ref_title: (window.PM && window.PM.paper) ? window.PM.paper.title : "",
      lockRef: true,
      // Which pass these hours were read in. The session is still ON the paper
      // — that's where the time counts — this only says which sitting it came
      // out of, so the chip can wear its own ★.
      instance_id: inst.id,
      session: {
        date: (inst.read_date || "").slice(0, 10) || undefined,
        start: inst.start || "",
        end: inst.end || "",
        mins: inst.mins || 0,
        focus: (inst.active_mins || 0) >= (inst.passive_mins || 0)
          ? ((inst.active_mins || 0) > 0 ? "active" : "none")
          : "passive",
        what: "read v" + inst.version + (inst.purpose ? " — " + inst.purpose : ""),
        notes: [
          (inst.active_mins || inst.passive_mins)
            ? "active " + (inst.active_mins || 0) + "m · passive " + (inst.passive_mins || 0) + "m" : "",
          inst.distractions ? inst.distractions + " distractions" : "",
          ...(((inst.row_text || {}).note) || []),
        ].filter(Boolean).join(" · "),
      },
    }, () => {
      toast("pushed to database");
      // Redraw so the pass wears its ★ straight away. Without this the star
      // is right in the database and absent on screen until the next reload,
      // which reads as the push not having landed.
      rerender(view);
    }, "⤴ push to database");

    const del = el("button.btn-sm.btn-danger", {
      title: "delete this pass — annotations and notes only; the original paper and the auto-KG are untouched",
      onclick: () => deletePass(inst, instCount, view),
      text: "delete pass",
    });

    box.appendChild(el("div.row", { style: "margin-top:8px;gap:6px" }, [save, pushBtn, del]));
    box.appendChild(pushHost);
    return box;
  }

  /* Pre-filled learning entry. Same shape the Learning tab writes, so a
     distraction logged from here is grouped with the same kind logged there.
     Exposed as window.LearningPush so the project cards and deep dives log the
     same way — one modal, one wording, one set of fields. */
  window.LearningPush = learningPushModal;
  function learningPushModal(seed) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const kind = el("input.mform-input", { value: seed.kind || "" });
    const what = el("input.mform-input", { value: seed.what || "" });
    const action = el("input.mform-input", { placeholder: "what will you do about it? (optional)" });
    const when = el("input.mform-input", { type: "date", value: seed.when || window.ui.todayISO() });
    const fld = (label, node) => el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);

    const save = () => guard(async () => {
      if (!what.value.trim()) return toast("describe what happened", true);
      await api.post("/api/learning", {
        kind: kind.value.trim(), what_happened: what.value.trim(),
        detail: (seed.detail || "").trim(),
        occurred_at: when.value || null, module: seed.module || "synapse",
        action: action.value.trim(), status: "open",
      });
      toast("logged to Learning");
      close();
    });

    const card = el("div.modal", {}, [
      el("div.modal-title", { text: "Log to Learning" }),
      el("div.sub", { style: "margin:-8px 0 14px", text: "Repeats are grouped by kind — keep the wording consistent and Learning can show whether the gaps are widening." }),
      fld("Kind (what groups repeats)", kind),
      fld("What happened", what),
      fld("Action", action),
      fld("When", when),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "Log it", onclick: save }),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    kind.focus(); kind.select();
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") save();
    });
  }

  /* A pass starts with intent: what it's for, and what you already know you
     want to come back to. Written up front rather than remembered afterwards —
     it lands in the Master Instance as its own block. */
  function newInstanceModal(paper, view) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const purpose = el("input.mform-input", { value: "revisit", placeholder: "e.g. first read, revisit, implement" });
    // No pass yet, so the rows are held and posted once create returns its id.
    const look = window.RowBox({
      label: "to look into later", kind: "look into", noun: "thing to look into",
      placeholder: "a section to reread, a proof to check, a term to look up" });
    const fld = (label, node) => el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);

    const create = () => guard(async () => {
      const inst = await api.post("/api/synapse/instances?paper_id=" + paper.id, {
        purpose: purpose.value.trim() || "revisit",
        coverage_pre: 0,
      });
      await look.commit(inst.id);
      activeInstance = inst.id;
      toast("created v" + inst.version);
      close();
      rerender(view);
    });

    const card = el("div.modal", {}, [
      el("div.modal-title", { text: "New reading pass" }),
      fld("Purpose", purpose),
      look.node,
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "Create pass", onclick: create }),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    purpose.focus(); purpose.select();
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(); }   // else app.js goes home
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") create();
    });
  }

  /* Delete one reading pass. Its highlights and notes go with it; the original
     PDF in the vault and the frozen auto-KG do not. Shared by the chip's × and
     the button inside the session form so the warning can't drift between them. */
  function deletePass(inst, total, view) {
    return confirmDo(
      "Delete reading pass v" + inst.version + (inst.purpose ? " (" + inst.purpose + ")" : "") + "?\n\n"
      + "This removes that pass's highlights and notes"
      + (total === 1 ? ", leaving this paper with no passes" : "") + ".\n"
      + "The original paper in your vault and the frozen auto-KG are NOT touched.",
      async () => {
        await api.del("/api/synapse/instances/" + inst.id);
        // Selecting a deleted pass would render an empty form; let the next
        // render pick the newest one instead.
        if (activeInstance === inst.id) activeInstance = null;
        toast("v" + inst.version + " deleted");
        rerender(view);
      });
  }

  // A pass's "to look into later" rows, as the list endpoint carries them.
  const lookRows = (i) => ((i.row_text || {})["look into"]) || [];

  // ---- instances ----
  async function instancesSection(paper, view) {
    const wrap = el("div.card");
    wrap.appendChild(el("div.spread", {}, [
      el("h3", { text: "Reading instances" }),
      el("button.btn-sm.btn-primary", { onclick: () => newInstanceModal(paper, view), text: "+ new instance" }),
    ]));
    const insts = await guard(() => api.get("/api/synapse/instances?paper_id=" + paper.id));
    if (!activeInstance && insts.length) activeInstance = insts[insts.length - 1].id;
    const chips = el("div.row", { style: "margin-top:10px;flex-wrap:wrap" });
    // ◀ ▶ swap a pass with its neighbour. `version` never moves — it records
    // which read came first — only the on-screen order does.
    const move = (idx, dir) => guard(async () => {
      const a = insts[idx], b = insts[idx + dir];
      if (!a || !b) return;
      // The pair must be listed in the order you want them to end up — reorder()
      // assigns the slots these nodes already hold, in the order given. Passing
      // [b, a] to move `a` EARLIER just restates the existing order: a no-op.
      await api.post("/api/synapse/instances/reorder",
        { ids: dir < 0 ? [a.id, b.id] : [b.id, a.id] });
      rerender(view);
    });
    /* Renaming a pass and colouring it are edits to the pass you're working
       on, so they live on the active chip only. Eight passes each carrying a
       pencil and a dot would bury the one thing the row is for — telling you
       which pass you're in. The colour itself still shows on every chip. */
    const patchInstance = (i, body) => guard(async () => {
      await api.patch("/api/synapse/instances/" + i.id, body);
      rerender(view);
    });

    insts.forEach((i, idx) => {
      const isActive = i.id === activeInstance;
      const grp = el("div.row", { style: "gap:0;align-items:stretch" }, [
        el("button.btn-sm.ins-move", { title: "move earlier", disabled: idx === 0,
          onclick: (e) => { e.stopPropagation(); move(idx, -1); }, text: "◀" }),
        el("button.btn-sm.ws-chip" + (isActive ? ".btn-primary" : ""), {
          "data-color": i.color || "",
          // Clicking the pass you're already on folds its form away — the boxes
          // are for logging, and you don't want them in the way while reading.
          onclick: () => {
            if (isActive) setLogOpen(!logOpen());
            else activeInstance = i.id;
            rerender(view);
          },
          title: isActive
            ? (logOpen() ? "hide this pass's boxes" : "show this pass's boxes")
            : (lookRows(i).length ? "look into: " + lookRows(i).join(" · ") : "open this pass"),
          text: "v" + i.version + " · " + i.purpose + (lookRows(i).length ? " ⌛" : "")
              + (isActive ? (logOpen() ? "  ▾" : "  ▸") : ""),
        }),
        // A pass you've already pushed from. Sits outside the chip so the
        // chip's label stays the thing it has always been, and so the star
        // isn't swallowed by the active-state restyling.
        i.push_count ? el("span.ins-push", {
          title: i.push_count + " session" + (i.push_count === 1 ? "" : "s")
               + " pushed from this pass"
               + (i.push_mins ? " · " + window.WorkLog.fmtMins(i.push_mins) : ""),
          text: i.push_count > 1 ? "★" + i.push_count : "★",
        }) : null,
        // Rename lives outside the chip, not on its label: the chip's own click
        // selects and folds, and a label you can click for two different things
        // is a label you stop clicking.
        isActive ? el("button.btn-sm.ins-move", {
          title: "rename this pass",
          onclick: (e) => {
            e.stopPropagation();
            const span = inlineRename(i.purpose || "", (v) =>
              api.patch("/api/synapse/instances/" + i.id, { purpose: v })
                .then(() => rerender(view)),
              { placeholder: "purpose", title: "rename this pass",
                // Backing out puts the ✎ back rather than leaving the label
                // stranded beside the chip that already says the same thing.
                onCancel: () => rerender(view) });
            e.currentTarget.replaceWith(span);
            span.click();
          },
          text: "✎",
        }) : null,
        isActive ? (() => {
          const dot = colorSwatch(i.color || "", (c) => patchInstance(i, { color: c }),
            { title: "pass colour" });
          return el("span.ins-swatch", {}, [dot]);
        })() : null,
        el("button.btn-sm.ins-move", { title: "move later", disabled: idx === insts.length - 1,
          onclick: (e) => { e.stopPropagation(); move(idx, 1); }, text: "▶" }),
        // Delete lives on the chip as well as inside the form — the form can be
        // folded away, and you shouldn't have to open a pass to get rid of it.
        el("button.btn-sm.btn-danger.ins-del", {
          title: "delete pass v" + i.version + " — its highlights and notes only",
          onclick: (e) => { e.stopPropagation(); deletePass(i, insts.length, view); },
          text: "×",
        }),
      ]);
      chips.appendChild(grp);
    });
    if (!insts.length) chips.appendChild(el("div.sub", { text: "No instances — create one to start annotating." }));
    wrap.appendChild(chips);
    const active = insts.find((i) => i.id === activeInstance);
    // Folded away, the pass is still selected — highlights below still belong to
    // it. Only the logging form is hidden.
    if (active && logOpen()) wrap.appendChild(sessionLog(active, view, insts.length, paper));
    else if (active) wrap.appendChild(el("div.sub", { style: "margin-top:10px",
      text: "Session boxes hidden — click v" + active.version + " again to show them." }));
    return { wrap, hasInstance: !!activeInstance };
  }

  /* The "N things done here since you last logged time" banner used to sit
     here, and it asked its question about one paper only — whichever you had
     open. It's now the ⏱ chip beside the reminders bell (unlogged.js), which
     asks it of everything at once and stays quiet until you go looking. The
     endpoint behind it, /api/work/gap, is unchanged. */

  /* ---- Master Instance ------------------------------------------------
     Read-only and auto-generated: everything written about this paper across
     every reading pass, in one scrollable document. You never author it — it
     assembles itself from the passes, so deleting a pass removes its blocks. */
  const MI_COLOR = {
    highlight: "var(--teal)", "session note": "var(--blue)", concept: "var(--amber)",
    idea: "var(--purple)", question: "var(--red)",
    // The write-up's other two answers: understanding reads with the session
    // note it sits beside, an open question with the questions.
    understood: "var(--blue)", "main question": "var(--red)",
    "look into": "var(--amber)", distractions: "var(--red)",
  };

  function masterInstanceSection(paper) {
    const wrap = el("div.card");
    let open = false;
    const body = el("div");
    const btn = el("button.btn-sm", { onclick: () => { open = !open; draw(); }, text: "▸ open" });
    /* A book's passes are chapters, not re-reads, so behind the same "open" it
       gets the book master record instead — the same document its Project page
       shows. One record, two doors. See book-master.js. */
    const isBook = paper.kind === "book";
    wrap.appendChild(el("div.spread", {}, [
      el("div", {}, [
        el("h3", { style: "margin:0", text: isBook ? "Master record" : "Master Instance" }),
        el("div.sub", { text: isBook
          ? "Auto-generated · read-only · every session, by chapter"
          : "Auto-generated · read-only · every pass merged into one document" }),
      ]),
      btn,
    ]));
    wrap.appendChild(body);

    function draw() {
      clear(body);
      btn.textContent = open ? "▾ close" : "▸ open";
      if (!open) return;
      if (isBook) {
        const host = el("div", { style: "margin-top:10px" });
        body.appendChild(host);
        window.BookMaster.render(host, paper.id, { compact: true });
        return;
      }
      body.appendChild(el("div.sub", { style: "margin-top:10px", text: "building…" }));
      guard(async () => {
        const m = await api.get("/api/synapse/instances/master?paper_id=" + paper.id);
        clear(body);
        const stat = (v, l, c) => el("div.prog-box", {}, [
          el("div.prog-val", { style: "color:" + c + ";font-size:18px", text: String(v) }),
          el("div.prog-label", { text: l }),
        ]);
        body.appendChild(el("div.prog-grid", { style: "margin:10px 0" }, [
          stat(m.counts.passes, "passes", "var(--blue)"),
          stat(m.counts.highlights, "highlights", "var(--teal)"),
          stat(m.counts.concepts, "concepts", "var(--amber)"),
          stat(m.counts.ideas + m.counts.dumps, "ideas & notes", "var(--purple)"),
          stat(window.WorkLog.fmtMins(m.totals.mins), "time spent", "#2de2ff"),
          stat(m.totals.distractions, "distractions", "var(--red)"),
        ]));

        // per-pass strip so you can see what each read contributed
        if (m.passes.length) {
          const strip = el("div.row", { style: "gap:6px;flex-wrap:wrap;margin-bottom:10px" });
          m.passes.forEach((p) => strip.appendChild(el("span.tk-tag", {
            style: "background:var(--raised);color:var(--blue)",
            title: (p.purpose || "") + " · " + (p.date || "no date") + " · " + p.highlight_count + " highlights",
            text: "v" + p.version + " · " + window.WorkLog.fmtMins(p.mins),
          })));
          body.appendChild(strip);
        }

        if (!m.blocks.length && !(m.log || []).length) {
          body.appendChild(el("div.empty", { text: "Nothing written yet. Highlights, session notes, concepts and ideas all flow in here." }));
          return;
        }
        const doc = el("div.mi-doc");
        m.blocks.forEach((b) => {
          const tags = [
            b.instance ? "instance " + b.instance : null,
            b.date || null,
            b.section ? "§ " + b.section : null,
            b.page ? "p." + b.page : null,
            b.mins ? window.WorkLog.fmtMins(b.mins) : null,
            b.tag || null,
          ].filter(Boolean).join("  ·  ");
          doc.appendChild(el("div.mi-block", { style: "border-left-color:" + (MI_COLOR[b.kind] || "var(--border)") }, [
            el("div.mi-meta", { text: b.kind.toUpperCase() + (tags ? "  ·  " + tags : "") }),
            b.title ? el("div.mi-title", { text: b.title }) : null,
            b.body ? el("div", { style: "white-space:pre-wrap", text: b.body }) : null,
          ]));
        });
        body.appendChild(paneSizeBar(doc, "masterDoc", "the document"));
        body.appendChild(doc);

        /* The log — what HAPPENED to this paper, as opposed to what you wrote
           about it. Kept as its own collapsed section rather than merged into
           the document above, or a single highlight would sit buried under
           twenty "updated" rows. */
        const logRows = m.log || [];
        if (logRows.length) {
          let logOpen = false;
          const logBody = el("div");
          const logBtn = el("button.btn-sm", { text: "▸ log (" + logRows.length + ")" });
          logBtn.addEventListener("click", () => {
            logOpen = !logOpen;
            logBtn.textContent = (logOpen ? "▾" : "▸") + " log (" + logRows.length + ")";
            clear(logBody);
            if (!logOpen) return;
            logRows.forEach((r) => logBody.appendChild(el("div.mi-log-row", {}, [
              el("span.mono.mi-log-when", { text: (r.timestamp || "").slice(0, 16).replace("T", " ") }),
              el("span.tk-tag", { style: "background:var(--raised);color:var(--dim)", text: r.category || "—" }),
              el("span", { text: r.action || "" }),
              r.detail ? el("span.sub", { style: "opacity:.7", text: "· " + r.detail }) : null,
            ])));
          });
          body.appendChild(el("div", { style: "margin-top:14px;padding-top:10px;border-top:1px solid var(--border)" }, [
            el("div.spread", {}, [
              el("div.sub", { text: "Everything that has happened to this subject" }), logBtn,
            ]),
            logBody,
          ]));
        }
      });
    }
    draw();
    return wrap;
  }

  // ---- references (scan → name + link, citation-map ready) ----
  // Reading state cycles as you work down a bibliography.
  // Same yellow the Reference Map draws a starred edge in — the button and the
  // edge have to read as the same mark.
  const STAR_COLOR = "#FFD426";
  const REF_STATES = ["unread", "read", "in_library", "dismissed"];
  const REF_LABEL = { unread: "unread", read: "read", in_library: "in library", dismissed: "dismissed" };
  const REF_STYLE = {
    unread: "",
    read: "text-decoration:line-through;opacity:.72",
    in_library: "color:var(--teal)",
    dismissed: "text-decoration:line-through;opacity:.4;color:var(--red)",
  };

  function refRow(r, reload) {
    const state = REF_STATES.includes(r.state) ? r.state : "unread";
    const titleEl = r.link
      ? el("a", { href: r.link, target: "_blank", rel: "noopener noreferrer", style: "color:var(--blue);" + REF_STYLE[state], text: r.title })
      : el("span", { style: REF_STYLE[state], text: r.title });

    const cycle = el("button.btn-sm", {
      title: "cycle: unread → read → in library → dismissed",
      style: state === "in_library" ? "color:var(--teal);border-color:var(--teal)"
        : state === "dismissed" ? "color:var(--red);border-color:var(--red)" : "",
      onclick: () => guard(async () => {
        const next = REF_STATES[(REF_STATES.indexOf(state) + 1) % REF_STATES.length];
        await api.patch("/api/synapse/refs/stored/" + r.id + "/state", { state: next });
        reload();
      }),
      text: REF_LABEL[state],
    });

    /* The star is "come back to this one". It's stored on this paper's copy of
       the reference, so it means "read this after THIS paper" — and that pair
       is exactly the edge the Reference Map draws yellow. */
    const starred = !!r.starred;
    const star = el("button.btn-sm", {
      title: starred
        ? "starred — its edge is yellow on the Reference Map; click to unstar"
        : "star it: the edge from this paper turns yellow on the Reference Map, and you can pin a note to it",
      style: starred ? "color:" + STAR_COLOR + ";border-color:" + STAR_COLOR : "",
      onclick: () => guard(async () => {
        await api.patch("/api/synapse/refs/stored/" + r.id + "/flag", { starred: !starred });
        reload();
      }),
      text: starred ? "★" : "☆",
    });

    const row = el("div.spread", { style: "padding:6px 0" }, [
      el("div", { style: "min-width:0" }, [
        titleEl,
        r.year ? el("span.sub", { text: "  · " + r.year }) : null,
        r.matched_paper_id ? el("span.tk-tag", { style: "background:var(--teal-d);color:var(--teal);margin-left:6px", text: "in repo" }) : null,
        r.kg_node_id ? el("span.tk-tag", { style: "background:var(--raised);color:var(--purple);margin-left:6px", text: "on KG" }) : null,
        !r.link ? el("span.sub", { style: "margin-left:6px", text: "· no link" }) : null,
      ]),
      el("div.row", { style: "gap:6px;flex-wrap:nowrap" }, [
        star,
        cycle,
        el("button.btn-sm", {
          title: r.matched_paper_id
            ? "add to the knowledge graph and link to the matching paper"
            : "add to the knowledge graph as a cited work",
          onclick: () => guard(async () => {
            const res = await api.post("/api/synapse/refs/stored/" + r.id + "/kg");
            toast(res.linked_paper_id ? "on KG · linked to the paper in your library" : "added to KG");
            reload();
          }),
          text: "+ KG",
        }),
        el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.del("/api/synapse/refs/stored/" + r.id); reload(); }), text: "×" }),
      ]),
    ]);

    const wrap = el("div", { style: "border-bottom:1px solid var(--border)" }, [row]);
    // The note field appears with the star, and stays visible for a note left
    // behind by an unstar — the thought outlives the urgency.
    if (starred || r.note) {
      const noteIn = el("input", {
        value: r.note || "",
        placeholder: "note — e.g. read this after, for the method in §3",
        style: "flex:1;font-size:12px",
      });
      // Saved on blur rather than per keystroke, and without a reload: a redraw
      // mid-sentence would take the cursor with it.
      const save = () => guard(async () => {
        const v = noteIn.value.trim();
        if (v === (r.note || "")) return;
        await api.patch("/api/synapse/refs/stored/" + r.id + "/flag", { note: v });
        r.note = v;
        toast(v ? "note saved — it shows on the Reference Map" : "note cleared");
      });
      noteIn.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); noteIn.blur(); } });
      noteIn.addEventListener("blur", save);
      wrap.appendChild(el("div.row", { style: "gap:6px;padding:0 0 8px 2px" }, [
        el("span", { style: "color:" + STAR_COLOR + ";font-size:12px", text: "★" }), noteIn,
      ]));
    }
    return wrap;
  }

  /* Paste a bibliography as text. No LLM touches this path, so a link can only
     ever be one that literally appears in what you pasted. Preview first —
     nothing is written until you press add. */
  function bulkPasteBox(paper, reload) {
    const box = el("div", { style: "margin-top:12px;border-top:1px solid var(--border);padding-top:10px" });
    box.appendChild(el("div.spread", {}, [
      el("span.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px", text: "Paste a reference list" }),
      el("span.sub", { style: "font-size:10px", text: "no LLM · links only if they appear in your text" }),
    ]));
    const ta = el("textarea.mform-input", {
      rows: "5", style: "width:100%;margin-top:6px;font-family:var(--mono);font-size:11px",
      placeholder: "Paste the whole bibliography — [1] A. Author. Title. Venue, 2007.  …or one per line, or blank-line separated.",
    });
    box.appendChild(ta);
    const preview = el("div");
    const replace = el("input", { type: "checkbox" });

    box.appendChild(el("div.row", { style: "gap:8px;margin-top:6px;flex-wrap:wrap" }, [
      el("button.btn-sm", {
        onclick: () => guard(async () => {
          if (!ta.value.trim()) return toast("paste something first", true);
          const res = await api.post("/api/synapse/refs/bulk?paper_id=" + paper.id, { text: ta.value, commit: false });
          clear(preview);
          if (!res.parsed) { preview.appendChild(el("div.sub", { text: "Couldn't find any references in that." })); return; }
          preview.appendChild(el("div.sub", { style: "margin:8px 0 4px", text: "Parsed " + res.parsed + " — check before adding:" }));
          const t = el("table.dd-sources");
          t.appendChild(el("tr", {}, [el("th", { text: "#" }), el("th", { text: "title" }), el("th", { text: "year" }), el("th", { text: "link" })]));
          res.entries.forEach((e, i) => t.appendChild(el("tr", {}, [
            el("td", { class: "mono", style: "font-size:10px;color:var(--dim)", text: String(i + 1) }),
            el("td", { text: e.title }),
            el("td", { class: "mono", style: "font-size:11px", text: e.year == null ? "—" : String(e.year) }),
            el("td", { class: "mono", style: "font-size:10px;color:var(--dim)", text: e.link || "" }),
          ])));
          preview.appendChild(el("div.grid", {}, [t]));
          preview.appendChild(el("div.row", { style: "gap:8px;margin-top:8px" }, [
            el("label.wl-check", {}, [replace, el("span", { text: " replace the existing list" })]),
            el("button.btn-primary", {
              onclick: () => guard(async () => {
                const done = await api.post("/api/synapse/refs/bulk?paper_id=" + paper.id,
                  { text: ta.value, commit: true, replace: replace.checked });
                toast((replace.checked ? "replaced with " : "added ") + done.stored + " references");
                ta.value = ""; clear(preview); reload();
              }),
              text: "add " + res.parsed + " references",
            }),
          ]));
        }),
        text: "preview",
      }),
      el("span.sub", { style: "font-size:10px", text: "parses [1] markers, numbered lists, or blank-line blocks" }),
    ]));
    box.appendChild(preview);
    return box;
  }

  async function referencesSection(paper) {
    const wrap = el("div.card", { style: "margin-top:14px" });
    wrap.appendChild(el("div.spread", {}, [
      el("h3", { text: "References" }),
      el("button.btn-sm", { onclick: () => scan(), text: "✦ scan references (local LLM)" }),
    ]));
    wrap.appendChild(el("div.sub", { style: "margin-top:2px", text: "Extract each cited work's name + link — the seed for a citation map." }));
    const list = el("div", { style: "margin-top:10px" });
    wrap.appendChild(list);

    async function reload() {
      const refs = await guard(() => api.get("/api/synapse/refs/stored?paper_id=" + paper.id));
      clear(list);
      if (!refs.length) { list.appendChild(el("div.sub", { text: "No references yet — scan the PDF or add one below." })); return; }
      const nStar = refs.filter((x) => x.starred).length;
      list.appendChild(el("div.sub", { style: "margin-bottom:6px" }, [
        el("span", { text: refs.length + " references" }),
        nStar ? el("span", { style: "color:" + STAR_COLOR + ";margin-left:8px",
          title: "starred works draw a yellow edge from this paper on the Reference Map",
          text: "★ " + nStar + " to read after" }) : null,
      ]));
      refs.forEach((r) => list.appendChild(refRow(r, reload)));
    }
    async function scan() {
      toast("scanning references (local LLM)…");
      const res = await guard(() => api.postForm("/api/synapse/refs/scan?paper_id=" + paper.id, new FormData()));
      toast("stored " + res.count + " references"); reload();
    }
    // manual add
    const titleIn = el("input", { placeholder: "reference title / name", style: "flex:2;min-width:180px" });
    const linkIn = el("input", { placeholder: "link (URL/DOI, optional)", style: "flex:1;min-width:120px" });
    wrap.appendChild(el("div.row", { style: "margin-top:12px" }, [
      titleIn, linkIn,
      el("button.btn-sm", { onclick: () => guard(async () => {
        if (!titleIn.value.trim()) return;
        await api.post("/api/synapse/refs/stored?paper_id=" + paper.id, { title: titleIn.value.trim(), link: linkIn.value.trim() || null });
        titleIn.value = ""; linkIn.value = ""; reload();
      }), text: "+ add" }),
    ]));
    wrap.appendChild(bulkPasteBox(paper, reload));
    await reload();
    return wrap;
  }

  // A redraw rebuilds the view head, so the shell's log-time button has to be
  // put back — otherwise it disappears the first time you save a session.
  function rerender(view) {
    const p = window.Views.workspace.render(view, window.PM);
    Promise.resolve(p).then(() => window.remountWorkLog && window.remountWorkLog());
  }

  window.Views = window.Views || {};
  window.Views.workspace = {
    id: "workspace", label: "Workspace", scoped: true,
    async render(view, PM) {
      clear(view);
      if (!PM.paper) return needPaper(view);
      const p = PM.paper;
      // Subtitle carries what the subject IS as well as what it's called, and
      // — when it was brought in from elsewhere — a way back to the real thing.
      const sub = el("div.sub", {}, [
        el("span", { text: subjectIcon(p) + "  " }),
        // The title is the one piece of a workspace you get wrong on the way in
        // — you name the thing before you've read it. Click it and type over it.
        inlineRename(p.title, async (v) => {
          const saved = await api.patch("/api/synapse/papers/" + p.id, { title: v });
          p.title = saved.title;
          // The left panel and the repo list both read a cached list, and a
          // rename that only lands here reads as a bug the next time you look.
          if (window.PM.paper && window.PM.paper.id === p.id) window.PM.paper.title = saved.title;
          if (window.PM.refreshPapers) await window.PM.refreshPapers();
          if (window.PM.renderContext) window.PM.renderContext();
          toast("renamed");
          rerender(view);
        }, { title: "click to rename this workspace" }),
      ]);
      if (p.link_kind && p.link_id) {
        sub.appendChild(el("button.btn-sm", {
          style: "margin-left:10px",
          title: "open the " + p.link_kind + " this workspace is about",
          onclick: () => window.openTab(LINK_TAB[p.link_kind]),
          text: "↪ " + (p.link_title || p.link_kind),
        }));
      }
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [ el("h1", { text: "Workspace" }), sub ]),
        // Only a PDF has anything for the reader to read.
        p.original_path ? el("button.btn-sm", {
          title: "read this PDF with the local LLM and build the frozen auto layer of the Knowledge Graph",
          onclick: () => guard(async () => {
            await api.post("/api/synapse/kg/generate?paper_id=" + p.id); toast("auto KG generated — see Knowledge Graph tab");
          }), text: "✦ generate auto KG" }) : null,
      ]));
      // Master first: it's the whole paper in one place, so it reads as the
      // summary the passes below feed into rather than an afterthought.
      view.appendChild(colorable(masterInstanceSection(p), "master", p));
      const inst = await instancesSection(p, view);
      colorable(inst.wrap, "instances", p);
      inst.wrap.style.marginTop = "14px";
      view.appendChild(inst.wrap);
      /* Dictionary left, Terms right, stretched to one height; Images full
         width under them (mainframe_workspace_no_minddump.html). No Mind dump:
         a quick thought goes to the Inbox through + idea, which links it to
         this subject. */
      view.appendChild(el("div.ws-two", {}, [
        colorable(dictWidget(), "dict", p),
        colorable(await termsSection(p.id), "terms", p),
      ]));
      const images = colorable(imagesWidget(p), "images", p);
      images.style.marginTop = "14px";
      view.appendChild(images);
      /* Highlights card removed from the workspace (user, 2026-10-28). The
         data and highlightsSection() stay, so existing highlights still count
         in the master view and can come back by restoring this block.
      if (inst.hasInstance) {
        const hl = colorable(await highlightsSection(activeInstance), "highlights", p);
        hl.style.marginTop = "14px";
        view.appendChild(hl);
      } */
      view.appendChild(colorable(await referencesSection(p), "refs", p));
      view.appendChild(el("div.ws-meta", { style: "margin-top:14px",
        text: "quick thoughts go to Inbox: press i or the + idea button, with this paper set as the source." }));
    },
  };
})();

/* docs.js — Documents: the Mainframe word processor (Mainframe-level, /api/docs).

   Left rail lists every document, grouped by folder, with full-text search.
   Right side is the editor: a source pane, a live preview, and a toolbar whose
   buttons change with the format (markdown gets **bold**, LaTeX gets \textbf).

   Two rules this view lives by:
     · The preview HTML comes from the SERVER (/api/docs/render), the same
       renderer that produces every export — so what you see is what you get.
     · Autosave writes the body through its own endpoint, debounced, and always
       flushes before you navigate away from a document.

   A document can also be bound to a project — (:Document)-[:FOR]->(:Project),
   set from the "for …" chip or Ctrl+P. Once it is, the header grows a clock:
   start it when you sit down, end it when you stop, then push. The push opens
   the ordinary session form with the bracket already in it, and writes ONE
   :WorkSession — :ON the project, :WORKED_ON this document. The hours show up
   on the project page and against the title in the rail, in both cases as the
   same hours the project already counts, never as extra ones. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const AUTOSAVE_MS = 900;
  const PREVIEW_MS = 250;

  const FORMATS = [
    { v: "markdown", t: "Markdown" },
    { v: "latex", t: "LaTeX" },
    { v: "plain", t: "Plain text" },
  ];

  // View state survives tab switches so you come back to the doc you were in.
  let docs = [], query = "", currentId = null, current = null;
  // Projects a document can say it is part of. Loaded once per view mount —
  // the list is short and changes far less often than the documents do.
  let projects = [];
  let listHost = null, paneHost = null;
  let saveTimer = null, previewTimer = null, dirty = false, saving = false;
  /* The doc clock, per document, so switching documents (or tabs) doesn't lose
     one that's running. `timerId` points at a real timer in the shared dock —
     this view draws its own chip for it, it doesn't own it. `bracket` is what a
     finished clock left behind, waiting to be pushed. */
  const clocks = {};                     // docId → { timerId, bracket }
  let clockTick = null;
  let layout = "split";                  // split | write | read
  const collapsed = new Set();           // folder names collapsed in the rail

  /* ------------------------------------------------------------------ *
   * Small helpers
   * ------------------------------------------------------------------ */
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso), now = new Date();
    const mins = Math.round((now - d) / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return mins + "m ago";
    if (mins < 60 * 24 && d.toDateString() === now.toDateString())
      return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }

  const folderLabel = (f) => f || "Unfiled";

  // Local YYYY-MM-DD. toISOString() would give UTC, which puts a late-evening
  // push on tomorrow's square.
  function today() {
    const d = new Date();
    return [d.getFullYear(),
            String(d.getMonth() + 1).padStart(2, "0"),
            String(d.getDate()).padStart(2, "0")].join("-");
  }

  // "2.5h", or "" when nothing has been logged — a zero reads as noise in a
  // rail of titles, and "no hours yet" is what a blank already says.
  function hours(mins) {
    mins = Number(mins) || 0;
    if (!mins) return "";
    const h = mins / 60;
    return (h >= 10 ? h.toFixed(0) : h.toFixed(1)) + "h";
  }

  // "7:56 pm" — the clock the way the header reads it out.
  function clockTime(d) {
    return d.toLocaleTimeString("en-GB", { hour: "numeric", minute: "2-digit", hour12: true })
            .toLowerCase().replace(/\s+/g, " ");
  }

  // "HH:MM" (what a session stores) → "7:56 pm".
  function hmPretty(hm) {
    if (!hm) return "";
    const [h, m] = String(hm).split(":").map(Number);
    if (isNaN(h) || isNaN(m)) return hm;
    const d = new Date();
    d.setHours(h, m, 0, 0);
    return clockTime(d);
  }

  const clockOf = (id) => (clocks[id] = clocks[id] || { timerId: null, bracket: null });

  /* The live timer behind this doc's chip, or null. Read back from the shared
     dock rather than cached here: the dock is where it can also be paused,
     stopped or discarded, and this view must not show a clock that isn't
     running any more. */
  function liveTimer(docId) {
    const c = clockOf(docId);
    if (!c.timerId || !window.Timers) return null;
    const t = window.Timers.list().find((x) => x.id === c.timerId);
    if (!t) { c.timerId = null; return null; }
    return t;
  }

  /* PATCH /api/docs/{id} returns the metadata node, which carries no body —
     assigning it straight to `current` would blank `current.content`, and the
     next render would put an empty textarea in front of you and autosave it
     over your file. Metadata always merges; the body only ever comes from
     GET /{id} or from what you typed. */
  function applyMeta(node) {
    const body = current ? current.content : "";
    current = Object.assign({}, current, node);
    if (current.content === undefined) current.content = body;
    // Renaming or moving rewrites the file's path — the footer says where the
    // file actually is, so it has to follow.
    const foot = document.getElementById("doc-path");
    if (foot) foot.textContent = current.path ? "~/.mainframe/documents/" + current.path : "";
    return current;
  }

  /* Editing a <textarea> without losing the user's place. Every toolbar button
     routes through one of these two so undo history and cursor stay sane. */
  function surround(ta, before, after, placeholder) {
    const { selectionStart: s, selectionEnd: e, value } = ta;
    const sel = value.slice(s, e) || placeholder || "";
    ta.setRangeText(before + sel + after, s, e, "end");
    if (!value.slice(s, e) && placeholder) {
      ta.selectionStart = s + before.length;
      ta.selectionEnd = s + before.length + placeholder.length;
    }
    ta.focus();
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function prefixLines(ta, prefix, opts) {
    opts = opts || {};
    const { selectionStart: s, selectionEnd: e, value } = ta;
    const start = value.lastIndexOf("\n", s - 1) + 1;
    const end = value.indexOf("\n", e) === -1 ? value.length : value.indexOf("\n", e);
    const lines = value.slice(start, end).split("\n");
    // Pressing the same button again lifts the prefix back off.
    const has = lines.every((l) => !l.trim() || l.startsWith(prefix));
    const out = lines.map((l, i) => {
      const p = opts.numbered ? (i + 1) + ". " : prefix;
      if (has) return l.startsWith(prefix) ? l.slice(prefix.length) : l;
      return l.trim() || !opts.skipBlank ? p + l : l;
    }).join("\n");
    ta.setRangeText(out, start, end, "end");
    ta.focus();
    ta.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /* ------------------------------------------------------------------ *
   * Saving
   * ------------------------------------------------------------------ */
  function setStatus(text, cls) {
    const s = document.getElementById("doc-status");
    if (s) { s.textContent = text; s.className = "doc-status" + (cls ? " " + cls : ""); }
  }

  async function flushSave() {
    clearTimeout(saveTimer);
    saveTimer = null;
    if (!dirty || !current || saving) return;
    const ta = document.getElementById("doc-body");
    if (!ta) return;
    saving = true;
    setStatus("saving…");
    try {
      const res = await api.docs.saveContent(current.id, ta.value);
      dirty = false;
      current.words = res.stats.words;
      current.updated_at = res.updated_at || current.updated_at;
      setStatus("saved " + when(current.updated_at), "ok");
      const row = docs.find((d) => d.id === current.id);
      if (row) { row.words = current.words; row.updated_at = current.updated_at; }
    } catch (err) {
      // Never silently swallow this — an editor that says nothing after a
      // failed save is how work disappears.
      setStatus("NOT SAVED — " + (err.message || "error"), "err");
      toast("save failed: " + (err.message || err), true);
    } finally {
      saving = false;
    }
  }
  // Leaving the tab, closing the browser, or switching module must not drop
  // the last few keystrokes.
  window.addEventListener("beforeunload", () => { if (dirty) flushSave(); });

  function queueSave() {
    dirty = true;
    setStatus("unsaved…");
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => flushSave(), AUTOSAVE_MS);
  }

  /* ------------------------------------------------------------------ *
   * Preview
   * ------------------------------------------------------------------ */
  function queuePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => renderPreview(), PREVIEW_MS);
  }

  async function renderPreview() {
    const ta = document.getElementById("doc-body");
    const host = document.getElementById("doc-preview");
    const counts = document.getElementById("doc-counts");
    if (!ta) return;
    if (current && current.format !== "markdown") {
      // No TeX toolchain is installed, so LaTeX and plain text preview as their
      // own source rather than pretending to typeset.
      if (host) { clear(host); host.appendChild(el("pre.doc-raw", { text: ta.value })); }
    } else if (host) {
      try {
        const res = await api.docs.render(ta.value);
        host.innerHTML = res.html;
        renderOutline(res.outline);
        if (counts) counts.textContent =
          `${res.stats.words} words · ${res.stats.chars} chars · ${res.stats.read_mins} min read`;
        return;
      } catch { /* preview is cosmetic; a failure must not block typing */ }
    }
    if (counts) {
      const words = (ta.value.match(/\b[\w'-]+\b/g) || []).length;
      counts.textContent = `${words} words · ${ta.value.length} chars`;
    }
  }

  function renderOutline(items) {
    const host = document.getElementById("doc-outline");
    if (!host) return;
    clear(host);
    if (!items || !items.length) return;
    host.appendChild(el("div.doc-outline-h", { text: "OUTLINE" }));
    items.forEach((h) => {
      host.appendChild(el("button.doc-outline-i", {
        style: "padding-left:" + (2 + (h.level - 1) * 10) + "px",
        text: h.text,
        onclick: () => {
          const t = document.getElementById("doc-preview");
          const target = t && t.querySelector("#" + CSS.escape(h.id));
          if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
        },
      }));
    });
  }

  /* ------------------------------------------------------------------ *
   * Toolbars — per format, because "bold" is not the same keystroke in LaTeX
   * ------------------------------------------------------------------ */
  function toolbarFor(fmt, ta) {
    const btn = (label, title, fn) =>
      el("button.doc-tool", { title, onclick: () => fn(ta) }, [
        typeof label === "string" ? document.createTextNode(label) : label]);
    const sep = () => el("span.doc-tool-sep");

    if (fmt === "latex") {
      return [
        btn("§", "section", (t) => surround(t, "\\section{", "}", "Introduction")),
        btn("§§", "subsection", (t) => surround(t, "\\subsection{", "}", "Background")),
        btn("B", "textbf", (t) => surround(t, "\\textbf{", "}", "bold")),
        btn("I", "emph", (t) => surround(t, "\\emph{", "}", "italic")),
        btn("⌨", "texttt", (t) => surround(t, "\\texttt{", "}", "code")),
        sep(),
        btn("x²", "superscript / math", (t) => surround(t, "$", "$", "x^2")),
        btn("∑", "display equation", (t) =>
          surround(t, "\\begin{equation}\n  ", "\n\\end{equation}", "E = mc^2")),
        sep(),
        btn("•", "itemize", (t) =>
          surround(t, "\\begin{itemize}\n  \\item ", "\n\\end{itemize}", "first item")),
        btn("1.", "enumerate", (t) =>
          surround(t, "\\begin{enumerate}\n  \\item ", "\n\\end{enumerate}", "first item")),
        btn("⊞", "table", (t) =>
          surround(t, "\\begin{tabular}{ll}\n  ", " & b \\\\\n  c & d \\\\\n\\end{tabular}", "a")),
        btn("🔗", "href", (t) => surround(t, "\\href{https://}{", "}", "link text")),
        btn("🖼", "figure", (t) =>
          surround(t, "\\begin{figure}[h]\n  \\centering\n  \\includegraphics{", "}\n\\end{figure}", "image.png")),
      ];
    }
    if (fmt === "plain") return [];
    return [
      btn("H1", "heading 1", (t) => prefixLines(t, "# ")),
      btn("H2", "heading 2", (t) => prefixLines(t, "## ")),
      btn("H3", "heading 3", (t) => prefixLines(t, "### ")),
      sep(),
      btn(el("strong", { text: "B" }), "bold  (Ctrl+B)", (t) => surround(t, "**", "**", "bold")),
      btn(el("em", { text: "I" }), "italic  (Ctrl+I)", (t) => surround(t, "*", "*", "italic")),
      btn(el("del", { text: "S" }), "strikethrough", (t) => surround(t, "~~", "~~", "struck")),
      btn("⌨", "inline code", (t) => surround(t, "`", "`", "code")),
      sep(),
      btn("•", "bullet list", (t) => prefixLines(t, "- ")),
      btn("1.", "numbered list", (t) => prefixLines(t, "1. ", { numbered: true })),
      btn("☑", "task", (t) => prefixLines(t, "- [ ] ")),
      btn("❝", "quote", (t) => prefixLines(t, "> ")),
      sep(),
      btn("🔗", "link  (Ctrl+K)", (t) => surround(t, "[", "](https://)", "link text")),
      btn("🖼", "image", (t) => surround(t, "![", "](https://)", "alt text")),
      btn("⊞", "table", (t) => surround(t,
        "\n| Column | Column |\n| --- | --- |\n| ", " |  |\n", "value")),
      btn("{ }", "code block", (t) => surround(t, "\n```\n", "\n```\n", "code")),
      btn("—", "divider", (t) => surround(t, "\n---\n", "", "")),
    ];
  }

  /* ------------------------------------------------------------------ *
   * The document list (left rail)
   * ------------------------------------------------------------------ */
  async function reloadList(keepSelection) {
    docs = await api.docs.list(query || undefined);
    renderList();
    if (!keepSelection && !currentId && docs.length) openDoc(docs[0].id);
  }

  function renderList() {
    if (!listHost) return;
    clear(listHost);
    if (!docs.length) {
      listHost.appendChild(el("div.sub", {
        style: "padding:14px 4px",
        text: query ? "nothing matches “" + query + "”" : "no documents yet",
      }));
      return;
    }
    const groups = new Map();
    docs.forEach((d) => {
      const k = d.folder || "";
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(d);
    });
    [...groups.keys()].sort().forEach((folder) => {
      const items = groups.get(folder);
      const isShut = collapsed.has(folder);
      listHost.appendChild(el("button.doc-folder", {
        onclick: () => { isShut ? collapsed.delete(folder) : collapsed.add(folder); renderList(); },
      }, [
        el("span", { text: (isShut ? "▸ " : "▾ ") + folderLabel(folder) }),
        el("span.sub", { text: String(items.length) }),
      ]));
      if (isShut) return;
      items.forEach((d) => {
        const row = el("button.doc-item" + (d.id === currentId ? ".active" : ""), {
          "data-eid": d.id,
          onclick: () => openDoc(d.id),
        }, [
          el("div.doc-item-t", {}, [
            d.starred ? el("span.doc-star", { text: "★" }) : null,
            el("span", { text: d.title || "Untitled" }),
            // Hours worked inside this document — the sessions pushed from it.
            el("span.doc-hours", { title: d.mins ? d.session_count + " session"
                                     + (d.session_count === 1 ? "" : "s") + " worked in this doc" : "",
                                   text: hours(d.mins) }),
          ]),
          el("div.doc-item-m", {
            text: [d.format === "latex" ? "TeX" : d.format === "plain" ? "txt" : "md",
                   (d.words || 0) + "w", when(d.updated_at)].join(" · "),
          }),
          d.excerpt ? el("div.doc-item-x", { text: d.excerpt }) : null,
        ]);
        listHost.appendChild(row);
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * The project binding — what this document's hours are for
   * ------------------------------------------------------------------ */

  /* Search over every project, not the handful this document already knows
     about: binding a doc is exactly the moment you reach for one you haven't
     touched in months. Type to filter, Enter takes the first match, Escape
     leaves the binding alone. */
  function projectSearch(onPick) {
    const overlay = el("div.modal-overlay");
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };

    const input = el("input.doc-pick-search", {
      type: "search", placeholder: "search projects…", autocomplete: "off",
    });
    const list = el("div.doc-pick-list");
    let shown = [];

    function draw() {
      const q = input.value.trim().toLowerCase();
      shown = projects.filter((p) => !q || (p.name || "").toLowerCase().includes(q));
      clear(list);
      if (!shown.length) {
        list.appendChild(el("div.sub", { style: "padding:10px 2px",
          text: projects.length ? "no project matches that" : "no projects yet" }));
        return;
      }
      shown.slice(0, 40).forEach((p, i) => list.appendChild(el(
        "button.doc-pick-row" + (i === 0 ? ".first" : ""), {
          onclick: () => { close(); onPick(p); },
        }, [
          el("span.doc-pick-name", { text: p.name }),
          el("span.doc-pick-meta", { text: hours(p.total_mins) || "no hours yet" }),
        ])));
    }

    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); close(); return; }
      if (e.key === "Enter" && shown.length) { e.preventDefault(); close(); onPick(shown[0]); }
    }
    input.addEventListener("input", draw);
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

    overlay.appendChild(el("div.modal.doc-pick", {}, [
      el("div.modal-title", { text: "This document is for…" }),
      input,
      list,
      el("div.doc-hint", { text: "enter takes the first match · esc cancels" }),
    ]));
    document.body.appendChild(overlay);
    draw();
    input.focus();
    // The list this view loaded on mount can be minutes old, and a project
    // started since then is exactly the one you're reaching for. Refresh behind
    // the open picker rather than making you wait for it.
    api.projects.list()
      .then((ps) => { projects = ps; if (overlay.isConnected) draw(); })
      .catch(() => { /* keep what we have */ });
  }

  // Bind (or unbind) the open document, then repaint: the chip, the clock and
  // the rail's hour column all read the binding.
  function bindProject(projectId) {
    return guard(async () => {
      applyMeta(await api.docs.setProject(current.id, projectId));
      await reloadList(true);
      renderEditor();
      toast(current.project_id ? "for " + (current.project_name || "project")
                               : "not for a project");
    });
  }

  /* The "for …" chip. Click to search, × to clear. Reads the project's name
     back through the relationship, so a rename over there shows up here. */
  function forChip() {
    const set = !!current.project_id;
    const chip = el("span.doc-for" + (set ? ".set" : ""), {
      title: set ? "the project this document's hours go to — click to change, Ctrl+P"
                 : "bind this document to a project (Ctrl+P)",
      onclick: () => projectSearch((p) => bindProject(p.id)),
    }, set
      ? [el("span", { text: "for " }), el("b", { text: current.project_name || "project" })]
      : [el("span", { text: "for a project…" })]);
    if (set) {
      const x = el("span.x", { title: "clear the binding", text: "×" });
      x.addEventListener("click", (e) => { e.stopPropagation(); bindProject(null); });
      chip.appendChild(x);
    }
    return chip;
  }

  /* ------------------------------------------------------------------ *
   * The clock — only once the document is for something
   * ------------------------------------------------------------------ */
  function startClock() {
    if (!window.Timers) return toast("timers unavailable", true);
    const c = clockOf(current.id);
    c.bracket = null;                     // a new stretch replaces an unpushed one
    const t = window.Timers.start({
      kind: "project",
      ref_id: current.project_id,
      label: current.project_name || current.title || "project",
      module: "mainframe",
    });
    c.timerId = t.id;
    renderEditor();
  }

  /* End the clock WITHOUT logging: the push writes the session, and doing it
     here as well would put the same stretch in the database twice. */
  function endClock() {
    const c = clockOf(current.id);
    if (!c.timerId) return;
    c.bracket = window.Timers.release(c.timerId);
    c.timerId = null;
    renderEditor();
  }

  function clockCluster() {
    const c = clockOf(current.id);
    const live = liveTimer(current.id);
    const row = [];

    if (live) {
      row.push(el("span.doc-timer.live", { id: "doc-clock" }, [
        el("span.dot"),
        el("span", { text: live.clock + " · started " + hmPretty(live.startHM) }),
      ]));
      row.push(el("button.btn-sm", { title: "stop the clock — nothing is logged until you push",
                                     text: "◼ end", onclick: endClock }));
    } else {
      const b = c.bracket;
      row.push(el("span.doc-timer" + (b ? ".done" : ""), { id: "doc-clock" }, [
        el("span", { text: b
          ? b.mins + "m · " + hmPretty(b.start) + "–" + hmPretty(b.end)
          : "not running" }),
      ]));
      row.push(el("button.btn-sm", { title: "start a clock on " + (current.project_name || "this project"),
                                     text: "▶ start", onclick: startClock }));
    }
    row.push(el("button.btn-sm.btn-primary", {
      title: "log this stretch as a session on " + (current.project_name || "the project"),
      text: "+ push", onclick: () => guard(async () => { await flushSave(); showSessionPush(); }),
    }));
    return row;
  }

  /* Repaint just the running clock, once a second — redrawing the whole editor
     would take the caret out of the textarea you are typing in, and would throw
     away whatever has taken over the preview pane (the push form, a snapshot
     list). Nothing to animate means no interval at all: a chip showing a
     finished bracket is a fixed string. */
  function stopClockTick() { clearInterval(clockTick); clockTick = null; }

  function startClockTick() {
    stopClockTick();
    if (!current || !liveTimer(current.id)) return;
    clockTick = setInterval(() => {
      const chip = document.getElementById("doc-clock");
      if (!chip || !chip.isConnected || !current) return stopClockTick();
      const live = liveTimer(current.id);
      // Stopped from the dock rather than from here: the chip has to stop
      // claiming a clock that no longer exists. Once, then stand down — this
      // ran every second before, which redrew the editor in a loop.
      if (!live) { stopClockTick(); renderEditor(); return; }
      const label = chip.querySelector("span:last-child");
      if (label) label.textContent = live.clock + " · started " + hmPretty(live.startHM);
    }, 1000);
  }

  /* The push. The existing session form, in the preview pane, prefilled from
     the clock — one session, on the project, worked on this document. The
     document's TEXT is never copied into it: the session links to the doc, and
     the doc is where the writing already lives. */
  function showSessionPush() {
    const host = document.getElementById("doc-preview");
    if (!host) return;
    const c = clockOf(current.id);
    const b = c.bracket || (liveTimer(current.id) ? null : null);

    clear(host);
    host.appendChild(el("div.doc-attached", {}, [
      el("span", { text: "📄 " + (current.title || "Untitled") }),
      el("span.doc-attached-m", { text: "attached to this session · WORKED_ON" }),
    ]));
    const done = () => {
      c.bracket = null;
      guard(async () => { await reloadList(true); renderEditor(); });
    };
    host.appendChild(window.WorkLog.form({
      module: "mainframe",
      ref_kind: "project",
      ref_id: current.project_id,
      ref_title: current.project_name || "",
      lockRef: true,
      doc_id: current.id,
      session: {
        date: b ? b.date : null,
        start: b ? b.start : "",
        end: b ? b.end : "",
        mins: b ? b.mins : 0,
        what: current.title || "",
      },
    }, done));
    host.appendChild(el("div.doc-hint", { style: "margin-top:10px",
      text: "the document body is not copied into notes — the session links to the doc, "
          + "and opens from the project page." }));
    host.appendChild(el("div.doc-push-row", {}, [
      el("button.doc-act", { text: "back to doc", onclick: () => queuePreview() }),
    ]));
  }

  /* ------------------------------------------------------------------ *
   * The editor (right pane)
   * ------------------------------------------------------------------ */
  async function openDoc(id) {
    await flushSave();
    currentId = id;
    current = await api.docs.get(id);
    renderList();
    renderEditor();
  }

  function renderEditor() {
    if (!paneHost) return;
    clear(paneHost);
    if (!current) {
      paneHost.appendChild(el("div.doc-empty", {}, [
        el("div", { style: "font-size:15px;margin-bottom:6px", text: "No document open" }),
        el("div.sub", { text: "Pick one on the left, or press “+ New document”." }),
      ]));
      return;
    }

    /* --- header: title, format, folder, actions --- */
    const titleIn = el("input.doc-title", { value: current.title || "", placeholder: "Untitled" });
    titleIn.addEventListener("change", () => guard(async () => {
      const t = titleIn.value.trim() || "Untitled";
      applyMeta(await api.docs.update(current.id, { title: t }));
      await reloadList(true);
      toast("renamed");
    }));

    const fmtSel = el("select.doc-mini", {}, FORMATS.map((f) =>
      el("option", { value: f.v, text: f.t })));
    fmtSel.value = current.format;
    fmtSel.addEventListener("change", () => guard(async () => {
      await flushSave();
      applyMeta(await api.docs.update(current.id, { format: fmtSel.value }));
      await reloadList(true);
      renderEditor();
      toast("format → " + fmtSel.value);
    }));

    const folderIn = el("input.doc-mini", {
      value: current.folder || "", placeholder: "folder", title: "folder (a real directory on disk)",
    });
    folderIn.addEventListener("change", () => guard(async () => {
      applyMeta(await api.docs.update(current.id, { folder: folderIn.value.trim() }));
      folderIn.value = current.folder || "";
      await reloadList(true);
      toast(current.folder ? "moved to " + current.folder : "moved to Unfiled");
    }));

    const star = el("button.doc-icon" + (current.starred ? ".on" : ""), {
      title: "star", text: current.starred ? "★" : "☆",
      onclick: () => guard(async () => {
        applyMeta(await api.docs.update(current.id, { starred: !current.starred }));
        await reloadList(true);
        renderEditor();
      }),
    });

    const header = el("div.doc-head", {}, [
      el("div.doc-head-l", {}, [titleIn]),
      el("div.doc-head-r", {}, [
        star, fmtSel, folderIn, forChip(),
        // The clock and the push only mean anything once the hours have
        // somewhere to go, so they appear with the binding.
        ...(current.project_id ? clockCluster() : []),
        el("span.doc-status", { id: "doc-status", text: "saved " + when(current.updated_at) }),
      ]),
    ]);

    /* --- actions: export, print, duplicate, history, delete --- */
    const ext = current.format === "latex" ? ".tex" : current.format === "plain" ? ".txt" : ".md";
    const actions = el("div.doc-actions", {}, [
      el("a.doc-act", { href: api.docs.exportUrl(current.id), download: "",
                        title: "download the source file", text: "↓ " + ext }),
      el("a.doc-act", { href: api.docs.exportUrl(current.id, "html"), download: "",
                        title: "download as HTML", text: "↓ html" }),
      el("a.doc-act", { href: api.docs.printUrl(current.id), target: "_blank", rel: "noopener",
                        title: "opens a clean page — Ctrl+P from there gives a PDF",
                        text: "🖨 print / PDF" }),
      el("button.doc-act", { text: "⧉ duplicate", onclick: () => guard(async () => {
        await flushSave();
        const copy = await api.docs.duplicate(current.id);
        await reloadList(true);
        openDoc(copy.id);
        toast("duplicated");
      }) }),
      el("button.doc-act", { text: "★ push",
        title: "record a timestamped push — puts a ★ on that day's square",
        onclick: () => guard(async () => { await flushSave(); showPush(); }) }),
      el("button.doc-act", { text: "⏱ history", onclick: () => guard(() => showHistory()) }),
      deleteControl(),
    ]);

    /* --- toolbar + panes --- */
    const ta = el("textarea.doc-body" + (current.format === "markdown" ? "" : ".mono"), {
      id: "doc-body",
      spellcheck: current.format !== "latex",
      placeholder: current.format === "latex"
        ? "\\section{Introduction}\n\nStart writing…"
        : "Start writing…",
    });
    ta.value = current.content || "";
    ta.addEventListener("input", () => { queueSave(); queuePreview(); });
    ta.addEventListener("blur", () => flushSave());
    ta.addEventListener("keydown", (e) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); flushSave(); return; }
      if (current.format === "markdown" && mod && e.key.toLowerCase() === "b") {
        e.preventDefault(); surround(ta, "**", "**", "bold"); return;
      }
      if (current.format === "markdown" && mod && e.key.toLowerCase() === "i") {
        e.preventDefault(); surround(ta, "*", "*", "italic"); return;
      }
      if (current.format === "markdown" && mod && e.key.toLowerCase() === "k") {
        e.preventDefault(); surround(ta, "[", "](https://)", "link text"); return;
      }
      // Tab indents instead of leaping to the next control — this is an editor.
      if (e.key === "Tab") {
        e.preventDefault();
        const { selectionStart: s, selectionEnd: en } = ta;
        if (s !== en || e.shiftKey) prefixLines(ta, "  ");
        else { ta.setRangeText("  ", s, en, "end"); ta.dispatchEvent(new Event("input", { bubbles: true })); }
      }
    });

    const tools = el("div.doc-toolbar", {}, toolbarFor(current.format, ta));
    const modes = el("div.doc-modes", {}, ["write", "split", "read"].map((m) =>
      el("button.doc-mode" + (layout === m ? ".active" : ""), {
        text: m, onclick: () => { layout = m; renderEditor(); },
      })));
    tools.appendChild(el("div", { style: "flex:1" }));
    tools.appendChild(modes);

    const preview = el("div.doc-preview", { id: "doc-preview" });
    const panes = el("div.doc-panes", { "data-layout": layout }, [
      el("div.doc-pane-src", {}, [ta]),
      el("div.doc-pane-prev", {}, [preview]),
    ]);

    const status = el("div.doc-foot", {}, [
      el("span.sub", { id: "doc-counts", text: "" }),
      el("span.doc-hint", { title: current.project_id
        ? "push when you stop — one session lands on " + current.project_name
          + " with this document attached"
        : "bind this document to a project and the hours you spend in it go there",
        text: current.project_id ? "· ctrl+p to change project"
                                 : "· ctrl+p to say which project this is for" }),
      el("span", { style: "flex:1" }),
      el("span.sub", { id: "doc-path",
                       text: current.path ? "~/.mainframe/documents/" + current.path : "" }),
    ]);

    const outline = el("div.doc-outline", { id: "doc-outline" });

    paneHost.appendChild(header);
    paneHost.appendChild(actions);
    // the Project tree from this doc's side: its projects, hours, sources
    if (window.ProjectAttach) {
      paneHost.appendChild(window.ProjectAttach.strip(
        { kind: "doc", id: current.id, title: current.title || "Untitled" }, { sources: true }));
    }
    paneHost.appendChild(tools);
    paneHost.appendChild(el("div.doc-work", {}, [panes, outline]));
    paneHost.appendChild(status);
    startClockTick();
    renderPreview();
  }

  /* A two-step delete rather than window.confirm: a native modal dialog blocks
     the whole page (and wedges browser automation), and "sure?" in place reads
     better anyway. */
  function deleteControl() {
    const b = el("button.doc-act.danger", { text: "🗑 delete" });
    let armed = false, revert = null;
    b.addEventListener("click", () => {
      if (!armed) {
        armed = true;
        b.textContent = "click again to delete";
        b.classList.add("armed");
        revert = setTimeout(() => {
          armed = false; b.textContent = "🗑 delete"; b.classList.remove("armed");
        }, 4000);
        return;
      }
      clearTimeout(revert);
      guard(async () => {
        const gone = current.id;
        clearTimeout(saveTimer); dirty = false;   // don't resurrect it on the way out
        await api.docs.del(gone);
        currentId = null; current = null;
        await reloadList();
        if (!docs.length) renderEditor();
        toast("deleted");
      });
    });
    return b;
  }

  /* The push form. Takes over the preview pane rather than opening a modal —
     same move as the snapshot list, and it keeps the editor visible while you
     write the note. */
  function showPush() {
    const host = document.getElementById("doc-preview");
    if (!host) return;
    const linked = current.link_kind === "project" ? current.link_title : null;

    const dateIn = el("input.doc-mini", { type: "date", value: today() });
    const minsIn = el("input.doc-mini", { type: "number", min: "0", step: "5",
                                          placeholder: "0", style: "width:74px" });
    const noteIn = el("input.doc-mini", { placeholder: "what you did (optional)",
                                          style: "flex:1;min-width:150px" });

    clear(host);
    host.appendChild(el("h3", { text: "Push document" }));
    host.appendChild(el("p.sub", {
      text: linked
        ? "Records a timestamped work session against this document and against "
          + linked + ", so the writing counts toward the project."
        : "Records a timestamped work session against this document — a ★ on that "
          + "day's contribution square and a row in the work database.",
    }));
    // Each label stays welded to its own input — the preview pane is narrow
    // enough that a bare flex row wraps "mins" away from its box.
    host.appendChild(el("div.doc-push-row", {}, [
      el("span.doc-push-field", {}, [el("label.sub", { text: "date" }), dateIn]),
      el("span.doc-push-field", {}, [el("label.sub", { text: "mins" }), minsIn]),
    ]));
    host.appendChild(el("div.doc-push-row", {}, [noteIn]));
    host.appendChild(el("div.doc-push-row", {}, [
      el("button.doc-act", { text: "cancel", onclick: () => queuePreview() }),
      el("button.btn-primary", { text: "★ push", onclick: () => guard(async () => {
        const r = await api.docs.push(current.id, {
          date: dateIn.value || today(),
          mins: Number(minsIn.value) || 0,
          note: noteIn.value.trim(),
        });
        toast("pushed ★ " + r.date + (r.project ? " → " + r.project : ""));
        queuePreview();
      }) }),
    ]));
    noteIn.focus();
  }

  async function showHistory() {
    const snaps = await api.docs.history(current.id);
    const host = document.getElementById("doc-preview");
    if (!host) return;
    clear(host);
    host.appendChild(el("h3", { text: "Snapshots" }));
    host.appendChild(el("p.sub", {
      text: "Autosave keeps a copy before overwriting, at most one every 5 minutes. "
          + "Restoring loads the text into the editor — it isn't saved until you type or press Ctrl+S.",
    }));
    if (!snaps.length) { host.appendChild(el("p.sub", { text: "No snapshots yet." })); return; }
    snaps.forEach((s) => {
      host.appendChild(el("div.doc-snap", {}, [
        el("span", { text: new Date(s.saved_at).toLocaleString("en-GB") }),
        el("span.sub", { text: s.bytes + " bytes" }),
        el("button.doc-act", { text: "restore", onclick: () => guard(async () => {
          const snap = await api.docs.snapshot(current.id, s.name);
          const ta = document.getElementById("doc-body");
          if (!ta) return;
          ta.value = snap.content;
          queueSave(); queuePreview();
          toast("restored into the editor — Ctrl+S to keep it");
        }) }),
      ]));
    });
  }

  /* Ctrl+P — say what this document is for, from anywhere inside it, including
     mid-sentence in the body. Only while Docs is actually on screen with a
     document open: everywhere else it stays the browser's print shortcut. */
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "p") return;
    if (!current || !paneHost || !paneHost.isConnected) return;
    if (document.querySelector(".doc-pick")) return;      // already open
    e.preventDefault();
    projectSearch((proj) => bindProject(proj.id));
  });

  /* ------------------------------------------------------------------ *
   * View
   * ------------------------------------------------------------------ */
  /* Open a document from another tab. The project page's "+ new doc for this
     project" creates one and lands you in it, which is a jump to Docs — so the
     jump is part of opening, not something the caller has to arrange. */
  window.Docs = {
    open(id) {
      currentId = id;
      current = null;                    // forces a fetch on render
      if (window.PM && window.PM.go) window.PM.go("docs");
    },
  };

  window.Views = window.Views || {};
  window.Views.docs = {
    id: "docs",
    label: "Docs",
    scoped: false,
    async render(viewEl) {
      const search = el("input.doc-search", {
        type: "search", placeholder: "search titles and text…", value: query,
      });
      let searchTimer = null;
      search.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => guard(async () => {
          query = search.value.trim();
          await reloadList(true);
        }), 220);
      });

      const newBtn = el("button.btn-primary", { text: "+ New document",
        onclick: () => guard(async () => {
          await flushSave();
          const d = await api.docs.create({
            title: "Untitled", format: "markdown",
            folder: current ? (current.folder || "") : "", content: "",
          });
          await reloadList(true);
          await openDoc(d.id);
          const t = document.querySelector(".doc-title");
          if (t) { t.focus(); t.select(); }
        }) });

      const importIn = el("input", { type: "file", accept: ".md,.markdown,.tex,.txt,.text",
                                     style: "display:none" });
      importIn.addEventListener("change", () => guard(async () => {
        if (!importIn.files.length) return;
        const form = new FormData();
        form.append("file", importIn.files[0]);
        const d = await api.docs.importFile(form);
        importIn.value = "";
        await reloadList(true);
        await openDoc(d.id);
        toast("imported");
      }));
      const importBtn = el("button.doc-act", { text: "↑ import", title: ".md, .tex or .txt",
                                               onclick: () => importIn.click() });

      listHost = el("div.doc-list");
      paneHost = el("div.doc-pane");

      viewEl.appendChild(el("div.doc-wrap", {}, [
        el("div.doc-rail", {}, [
          el("div.doc-rail-top", {}, [newBtn, importBtn, importIn]),
          search,
          listHost,
        ]),
        paneHost,
      ]));

      // A missing/failing projects list must not stop Docs from opening — the
      // picker just falls back to "no project".
      try { projects = await api.projects.list(); }
      catch { projects = []; }

      await reloadList(!!currentId);
      if (currentId) {
        // Re-fetch: the file may have changed on disk since we last looked.
        try { current = await api.docs.get(currentId); }
        catch { currentId = null; current = null; }
      }
      renderEditor();
    },
  };
})();

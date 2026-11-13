/* mind.js — global mind-dump inbox: quick captures, optionally linked to a
   paper, checkable and filterable. Cards expand into a full editor and can be
   moved up/down into a manual order. Mainframe-level (/api/mind).

   Below the inbox sits a second list: the write-ups you fill in at the bottom
   of a reading pass or a project pass. Those are notes you made while on an
   item, and they used to be visible only inside that item's Master Instance —
   so this is the other half of "notes live in one place". They are SHOWN here,
   not copied here: a copy would go stale the moment you edited the pass, so
   they stay read-only and say which pass to go and edit.

   TALK IT THROUGH sits at the top: hold the mic, say what's on your mind, and
   the transcript comes back from this machine's own whisper. "find the points"
   proposes the handful worth keeping — you tick, edit and correct them, and
   nothing is written until you save. The transcript is always saved whole, so
   the long version of what you said is one hop from every point that came out
   of it. Same proposal-then-commit shape as the diary split, for the same
   reason: an extraction you can see and fix is one you keep using. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const KINDS = ["idea", "look-at", "note"];
  const KIND_LABELS = { idea: "idea", "look-at": "look at", note: "note" };
  const KIND_STYLE = {
    idea: "background:var(--amber-d);color:var(--amber)",
    "look-at": "background:var(--blue-d);color:var(--blue)",
    note: "background:var(--purple-d);color:var(--purple)",
  };

  let fStatus = "open"; // open | done | ""(all)
  let fKind = "";
  const open = new Set();  // expanded card ids, kept across reloads
  let items = [], papersRef = [], listHost = null;
  // Pass write-ups are kept out of `items` on purpose: that array is the manual
  // order, and move()/orderCol() index straight into it. A read-only row mixed
  // in would silently shift every reorder by one.
  let passNotes = [], passHost = null, passOpen = true;

  function dateFmt(iso) {
    if (!iso) return "";
    try { return new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }
    catch { return String(iso).slice(0, 10); }
  }

  /* Patch one field and keep the local copy in sync — no full reload, so the
     card keeps focus and stays expanded while you edit. */
  function fieldSaver(m, key) {
    return (input) => guard(async () => {
      const nv = input.value;
      if (String(m[key] == null ? "" : m[key]) === nv) return;
      const saved = await api.patch("/api/mind/" + m.id, { [key]: nv });
      Object.assign(m, saved);
      toast("saved");
    });
  }

  function labelled(text, node) {
    return el("label.md-field", {}, [el("span.sub", { text }), node]);
  }

  // screenshot / photo attached to a capture — shown inside the expanded card
  function imagesHost(m) {
    const host = el("div");
    window.Images.mount(host, { module: "mind", contextId: m.id, surface: "mind", title: "Images" });
    return host;
  }

  /* Swap a card with its neighbour. Only the two ids are sent, so the swap is
     correct even when the list is filtered (see ReorderRequest server-side). */
  function move(idx, dir) {
    const j = idx + dir;
    if (j < 0 || j >= items.length) return;
    const tmp = items[idx]; items[idx] = items[j]; items[j] = tmp;
    const lo = Math.min(idx, j), hi = Math.max(idx, j);
    const ids = [items[lo].id, items[hi].id];
    renderList();
    guard(() => api.post("/api/mind/reorder", { ids }));
  }

  function orderCol(idx) {
    const up = el("button.ord-btn", { title: "move up", text: "▲",
      onclick: (e) => { e.stopPropagation(); move(idx, -1); } });
    const down = el("button.ord-btn", { title: "move down", text: "▼",
      onclick: (e) => { e.stopPropagation(); move(idx, 1); } });
    if (idx === 0) up.disabled = true;
    if (idx === items.length - 1) down.disabled = true;
    return el("div.ord-col", {}, [up, down]);
  }

  function expandedBody(m) {
    const textIn = el("input", { style: "width:100%", value: m.text || "" });
    textIn.addEventListener("blur", () => fieldSaver(m, "text")(textIn));

    /* Expanding on it is + rows on the card, one thought per row. `detail`
       stays as what the system wrote there — a talked-through journal's
       transcript, a point's quote — shown read-only, because splitting a
       transcript into rows would break the sentence it was spoken in. */
    const detailBox = window.RowBox({ label: "detail", kind: "note", noun: "note", parentId: m.id,
      placeholder: "expand on it — a thought, a link, a next step…" });
    const said = (m.detail || "").trim()
      ? el("div.sub", { style: "white-space:pre-wrap;margin-top:6px", text: m.detail }) : null;

    const kindSel = el("select", {}, KINDS.map((k) => el("option", { value: k, text: KIND_LABELS[k] })));
    kindSel.value = m.kind || "idea";
    kindSel.addEventListener("change", () => fieldSaver(m, "kind")(kindSel));

    const linkIn = el("input", { placeholder: "https://…", style: "width:100%" });
    linkIn.value = m.link || "";
    linkIn.addEventListener("blur", () => fieldSaver(m, "link")(linkIn));

    const paperSel = el("select", { style: "width:100%" }, [
      el("option", { value: "", text: "— no paper —" }),
      ...papersRef.map((p) => el("option", { value: p.id, text: p.title.slice(0, 44) })),
    ]);
    paperSel.value = m.paper_id || "";
    paperSel.addEventListener("change", () => fieldSaver(m, "paper_id")(paperSel));

    return el("div.md-body", {}, [
      labelled("capture", textIn),
      said ? labelled("said", said) : null,
      detailBox.node,
      el("div.md-grid", {}, [
        labelled("kind", kindSel),
        labelled("link", linkIn),
        labelled("paper", paperSel),
      ]),
      imagesHost(m),
      el("div.task-meta", { style: "margin-top:10px" }, [
        el("span.sub", { text: "captured " + dateFmt(m.created_at) }),
        el("span.sub", { text: m.status === "done" ? "done" : "open" }),
      ]),
    ]);
  }

  function itemCard(m, idx) {
    const done = m.status === "done";
    const isOpen = open.has(m.id);

    const cb = el("input", { type: "checkbox" });
    cb.checked = done;
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", () => guard(async () => {
      const saved = await api.patch("/api/mind/" + m.id, { status: cb.checked ? "done" : "open" });
      Object.assign(m, saved);
      // A status change can drop the item out of the current filter.
      if (fStatus && saved.status !== fStatus) reload(); else renderList();
    }));

    const toggle = () => { isOpen ? open.delete(m.id) : open.add(m.id); renderList(); };
    const caret = el("button.ord-btn", { title: isOpen ? "collapse" : "expand",
      text: isOpen ? "▾" : "▸", onclick: (e) => { e.stopPropagation(); toggle(); } });

    const preview = el("div", { class: isOpen ? "" : "md-clamp",
      style: done ? "text-decoration:line-through" : "", text: m.text });
    const hasDetail = !!(m.detail && m.detail.trim());

    const head = el("div.spread", { style: "cursor:pointer", onclick: toggle }, [
      el("div.row", { style: "align-items:flex-start;gap:8px;flex:1;min-width:0" }, [
        orderCol(idx), cb,
        el("div", { style: "flex:1;min-width:0" }, [
          preview,
          el("div.task-meta", {}, [
            el("span.tk-tag", { style: KIND_STYLE[m.kind] || "", text: KIND_LABELS[m.kind] || m.kind }),
            hasDetail && !isOpen ? el("span.sub", { title: "has a detail note", text: "❐ detail" }) : null,
            // Which side of a talked-through journal this card is on.
            m.points ? el("span.sub", { title: "points taken out of this",
              text: "◆ " + m.points + " point" + (m.points === 1 ? "" : "s") }) : null,
            m.from_dump ? el("a", { href: "#", style: "color:var(--purple)",
              title: "the journal this came out of",
              onclick: (e) => { e.preventDefault(); e.stopPropagation();
                open.add(m.from_dump.id); renderList();
                const card = document.getElementById("md-" + m.from_dump.id);
                if (card) card.scrollIntoView({ block: "center", behavior: "smooth" }); },
              text: "↩ from journal" }) : null,
            m.paper_title ? el("a", { href: "#", style: "color:var(--teal)", onclick: (e) => { e.preventDefault(); e.stopPropagation(); window.PM.selectPaper(m.paper_id); }, text: "▸ " + m.paper_title.slice(0, 36) }) : null,
            m.link ? el("a", { href: m.link, target: "_blank", rel: "noopener noreferrer", style: "color:var(--blue)", onclick: (e) => e.stopPropagation(), text: "link ↗" }) : null,
            el("span.sub", { text: dateFmt(m.created_at) }),
          ]),
        ]),
      ]),
      el("div.row", { style: "gap:4px;align-items:flex-start" }, [
        caret,
        el("button.btn-sm.btn-danger", { onclick: (e) => { e.stopPropagation(); guard(async () => { await api.del("/api/mind/" + m.id); open.delete(m.id); reload(); }); }, text: "×" }),
      ]),
    ]);

    const card = el("div.card", { id: "md-" + m.id,
      style: "margin-bottom:10px;" + (done ? "opacity:.55" : "") }, [head]);
    if (isOpen) card.appendChild(expandedBody(m));
    return card;
  }

  /* ---- talk it through --------------------------------------------------- */
  /* The recorder is voicetype's, driven with an explicit field rather than
     rebuilt here: one microphone path, one whisper call, one set of permission
     problems to debug. All this adds is a button that aims it at the
     transcript box. */
  let talkText = "", talkPoints = null, talkBy = "", talkHost = null;
  // Projects, for the "and give it to" picker on a point headed for the Inbox.
  let projectsRef = [];

  function analysing(on) {
    const b = talkHost && talkHost.querySelector(".md-analyse");
    if (b) { b.disabled = on; b.textContent = on ? "reading it…" : "find the points"; }
  }

  /* Where a point goes. "journal" is a card here — something you want on
     record but aren't acting on. "inbox" makes it a real Inbox row, and the
     project picker beside it gives that row to a project in the same move,
     which is what puts it in the project tree while leaving it in the Inbox:
     one node serves both views. */
  const DESTS = [
    { v: "journal", t: "keep here" },
    { v: "inbox:idea", t: "→ inbox · idea" },
    { v: "inbox:task", t: "→ inbox · task" },
  ];

  function pointRow(pt) {
    const keep = el("input", { type: "checkbox" });
    keep.checked = true;
    const text = el("input.mform-input", { style: "flex:1;min-width:160px" });
    text.value = pt.text;

    const kind = el("select.mform-input", { style: "max-width:100px" },
      KINDS.map((k) => el("option", { value: k, text: KIND_LABELS[k] })));
    kind.value = KINDS.includes(pt.kind) ? pt.kind : "note";

    const dest = el("select.mform-input", { style: "max-width:130px" },
      DESTS.map((d) => el("option", { value: d.v, text: d.t })));
    // A point the model called "look at" or "idea" is something you meant to
    // do, so it opens pointed at the Inbox; a plain note opens staying here.
    dest.value = pt.kind === "note" ? "journal"
      : pt.kind === "idea" ? "inbox:idea" : "inbox:task";

    const proj = el("select.mform-input", { style: "max-width:190px" }, [
      el("option", { value: "", text: "— no project —" }),
      ...projectsRef.map((p) => el("option", { value: p.id, text: p.path })),
    ]);

    // The journal kind and the project picker are mutually irrelevant: one
    // applies to a card kept here, the other to a row sent onward. Showing
    // both at once would ask you to fill in a field that does nothing.
    const sync = () => {
      const toInbox = dest.value !== "journal";
      kind.style.display = toInbox ? "none" : "";
      proj.style.display = toInbox ? "" : "none";
    };
    dest.addEventListener("change", sync);
    sync();

    const row = el("div.md-point", {}, [
      el("div.row", { style: "gap:8px;align-items:center;flex-wrap:wrap" },
         [keep, text, dest, kind, proj]),
      // What you actually said, under what the model made of it. This is the
      // whole reason it is safe to let it shorten you.
      pt.quote ? el("div.md-quote", { text: "\u201C" + pt.quote + "\u201D" }) : null,
    ]);
    row._get = () => {
      const toInbox = dest.value !== "journal";
      return {
        keep: keep.checked, text: text.value.trim(), quote: pt.quote || "",
        kind: kind.value,
        dest: toInbox ? "inbox" : "journal",
        inbox_kind: toInbox ? dest.value.split(":")[1] : "idea",
        project_id: toInbox ? proj.value : "",
      };
    };
    return row;
  }

  function renderTalk() {
    if (!talkHost) return;
    clear(talkHost);

    const ta = el("textarea.md-talkbox", { rows: "4",
      placeholder: "hold the mic and talk, or type it here…" });
    ta.value = talkText;
    ta.addEventListener("input", () => { talkText = ta.value; });

    const mic = el("button.btn-sm", { text: "\u25C9 talk", title: "dictate into this box",
      onclick: () => {
        if (!window.voiceType) return toast("dictation isn't loaded", true);
        ta.focus();
        window.voiceType.recording ? window.voiceType.stop() : window.voiceType.start(ta);
      } });

    const analyse = el("button.btn-sm.btn-primary.md-analyse", { text: "find the points",
      onclick: () => guard(async () => {
        const text = ta.value.trim();
        if (!text) return toast("say something first", true);
        talkText = text;
        analysing(true);
        try {
          // Fetched here rather than on tab load: the picker only exists once
          // there are points, and this is the moment it's about to be needed.
          if (!projectsRef.length) {
            const tree = await api.get("/api/synapse/projects").catch(() => null);
            projectsRef = ((tree && tree.projects) || []).slice()
              .sort((a, b) => a.path.localeCompare(b.path));
          }
          const res = await api.post("/api/mind/analyse", { text });
          talkPoints = res.points || [];
          talkBy = res.analysed_by || "";
          if (!talkPoints.length) toast("couldn't find a point in that — save it anyway?");
        } finally { analysing(false); }
        renderTalk();
      }) });

    const clearBtn = el("button.btn-sm", { text: "clear", onclick: () => {
      talkText = ""; talkPoints = null; renderTalk();
    } });

    const kids = [
      el("div.spread", {}, [
        el("h3", { style: "margin:0", text: "Talk it through" }),
        el("span.sub", { text: "spoken here, transcribed on this machine" }),
      ]),
      ta,
      el("div.row", { style: "margin-top:8px;gap:8px;flex-wrap:wrap" },
         [mic, analyse, talkText ? clearBtn : null]),
    ];

    if (talkPoints) {
      const rows = talkPoints.map(pointRow);
      const save = el("button.btn-sm.btn-primary", { text: "save journal + points",
        onclick: () => guard(async () => {
          const points = rows.map((r) => r._get()).filter((p) => p.keep && p.text);
          const res = await api.post("/api/mind/commit", {
            transcript: talkText, points,
          });
          const bits = [];
          if (res.points_saved) bits.push(res.points_saved + " kept here");
          if (res.sent_to_inbox) bits.push(res.sent_to_inbox + " to the inbox");
          toast("journal saved" + (bits.length ? " · " + bits.join(", ") : ""));
          talkText = ""; talkPoints = null;
          renderTalk();
          reload();
        }) });
      kids.push(el("div.md-points", {}, [
        el("div.spread", { style: "margin-bottom:6px" }, [
          el("span.wl-label", { text: talkPoints.length
            ? "the points \u2014 untick what isn't one, edit the rest"
            : "no points found \u2014 the transcript still saves" }),
          talkBy ? el("span.sub", { text: "found by " + talkBy }) : null,
        ]),
        ...rows,
        el("div.row", { style: "margin-top:10px" }, [save]),
      ]));
    }

    talkHost.appendChild(el("div.card.md-talk", {}, kids.filter(Boolean)));
  }

  /* ---- notes written on an item (read-only) ------------------------------ */
  function passCard(m) {
    const label = (m.ref_kind === "project" ? "🧱 " : "📄 ") + (m.ref_title || "");
    return el("div.card.md-pass", {}, [
      m.text ? el("div", { style: "white-space:pre-wrap", text: m.text }) : null,
      m.understood ? el("div.mw-sub", { style: "white-space:pre-wrap;margin-top:6px" }, [
        el("span.wl-label", { text: "understood — " }),
        el("span", { text: m.understood }),
      ]) : null,
      el("div.task-meta", {}, [
        el("span.tk-tag", { style: KIND_STYLE.note, text: "note" }),
        el("a", { href: "#", style: "color:var(--teal)",
          title: "open " + (m.ref_title || "it"),
          onclick: (e) => {
            e.preventDefault();
            if (m.ref_kind === "paper") window.PM.selectPaper(m.ref_id);
            else window.openTab("project");
          },
          text: "▸ " + label.slice(0, 40) }),
        el("span.sub", { title: "written in the session log of pass v" + m.version
            + " — edit it there, not here",
          text: "from v" + m.version + (m.purpose ? " · " + m.purpose : "") }),
        el("span.sub", { text: dateFmt(m.created_at) }),
      ]),
    ]);
  }

  function renderPassNotes() {
    if (!passHost) return;
    clear(passHost);
    // They're all kind "note" and none of them is ever "done", so a filter that
    // excludes either would be showing them against your wishes.
    if (fKind && fKind !== "note") return;
    if (fStatus === "done") return;
    if (!passNotes.length) return;
    const head = el("div.spread", { style: "margin:22px 0 8px;cursor:pointer",
      onclick: () => { passOpen = !passOpen; renderPassNotes(); } }, [
      el("div", {}, [
        el("h3", { style: "margin:0", text: (passOpen ? "▾" : "▸") + " Written on an item · " + passNotes.length }),
        el("div.sub", { text: "Session write-ups from reading and project passes. Read-only here — edit them on the pass." }),
      ]),
    ]);
    passHost.appendChild(head);
    if (passOpen) passNotes.forEach((m) => passHost.appendChild(passCard(m)));
  }

  function renderList() {
    clear(listHost);
    if (!items.length) { listHost.appendChild(el("div.empty", { text: "Nothing here. Capture a thought above." })); return; }
    items.forEach((m, i) => listHost.appendChild(itemCard(m, i)));
  }

  async function reload() {
    const qs = [];
    if (fStatus) qs.push("status=" + fStatus);
    if (fKind) qs.push("kind=" + encodeURIComponent(fKind));
    const [dumps, passes] = await guard(() => Promise.all([
      api.get("/api/mind" + (qs.length ? "?" + qs.join("&") : "")),
      api.get("/api/mind/item-notes"),
    ])) || [[], []];
    items = dumps || [];
    passNotes = passes || [];
    renderList();
    renderPassNotes();
  }

  window.Views = window.Views || {};
  window.Views.mind = {
    id: "mind", label: "Journal", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Mind Dump" }),
        el("div.sub", { text: "Talk it through or capture a thought. Click a card to expand it; ▲▼ to reorder. "
          + "Notes you wrote on an item are collected underneath." }),
      ])]));

      // Talk first: the point of the tab is to get what's in your head out of
      // it, and speaking is the lowest-friction way in.
      talkHost = el("div");
      viewEl.appendChild(talkHost);
      renderTalk();

      // quick-add
      const textIn = el("input", { placeholder: "stick an idea / “come look at this”…", style: "width:100%" });
      const kindSel = el("select", {}, KINDS.map((k) => el("option", { value: k, text: KIND_LABELS[k] })));
      const linkIn = el("input", { placeholder: "link (optional)", style: "flex:1;min-width:120px" });
      const paperSel = el("select", { style: "flex:1;min-width:140px" });
      paperSel.appendChild(el("option", { value: "", text: "— no paper —" }));
      papersRef = await guard(() => api.papers.list());
      papersRef.forEach((p) => paperSel.appendChild(el("option", { value: p.id, text: p.title.slice(0, 44) })));
      const add = el("button.btn-sm.btn-primary", { text: "capture", onclick: () => guard(async () => {
        if (!textIn.value.trim()) return toast("write something first", true);
        await api.post("/api/mind", { text: textIn.value.trim(), kind: kindSel.value, link: linkIn.value.trim() || null, paper_id: paperSel.value || null });
        textIn.value = ""; linkIn.value = ""; toast("captured"); reload();
      }) });
      textIn.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add.click(); } });
      viewEl.appendChild(el("div.card", {}, [textIn, el("div.row", { style: "margin-top:10px" }, [kindSel, linkIn, paperSel, add])]));

      // filters
      const statusSel = el("select", {}, [{ v: "open", t: "open" }, { v: "done", t: "done" }, { v: "", t: "all" }].map((o) => el("option", { value: o.v, text: o.t })));
      statusSel.value = fStatus;
      statusSel.addEventListener("change", () => { fStatus = statusSel.value; reload(); });
      const kindFilter = el("select", {}, [{ v: "", t: "all kinds" }, ...KINDS.map((k) => ({ v: k, t: KIND_LABELS[k] }))].map((o) => el("option", { value: o.v, text: o.t })));
      kindFilter.value = fKind;
      kindFilter.addEventListener("change", () => { fKind = kindFilter.value; reload(); });
      viewEl.appendChild(el("div.row", { style: "margin:16px 0 10px" }, [statusSel, kindFilter]));

      listHost = el("div");
      viewEl.appendChild(listHost);
      passHost = el("div");
      viewEl.appendChild(passHost);
      reload();
    },
  };
})();

/* vision-youtube.js — Vision · YouTube.

   A video is a production WORKSPACE, not a tracking card (VISION_UPDATE_SPEC).
   This file is the shell: the card grid and the detail view, with Concept,
   Production Notes, Progress Journal and pipeline-driven stage advancement.
   Research / Script markers / Prompt log / Storyboard / Thumbnails register
   themselves into window.VID_SECTIONS and are rendered in order — same pattern
   as FIT_TABS/NUT_TABS, so each is its own file added in a later increment.

   Stages are NEVER hardcoded: they come from the Blueprint pipeline the video
   follows. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = () => api.vision;

  // Sections registered by later increments:
  //   {key, label, order, render(host, video, reload)}
  // `order` (not file load order) fixes their position in the detail view, so a
  // section added later can slot in between two existing ones. Spec layout:
  //   research 10 · script 20 · prompts 30 · storyboard 40 · thumbnails 50
  window.VID_SECTIONS = window.VID_SECTIONS || [];
  const sections = () => window.VID_SECTIONS.slice().sort((a, b) => (a.order || 99) - (b.order || 99));

  const TYPES = [
    { key: "educational", icon: "📚", label: "Educational", color: "var(--blue)", bg: "var(--blue-d)" },
    { key: "short", icon: "⚡", label: "Short", color: "var(--amber)", bg: "var(--amber-d)" },
    { key: "big-project", icon: "🏗️", label: "Big Project", color: "var(--purple)", bg: "var(--purple-d)" },
    { key: "tutorial", icon: "🛠️", label: "Tutorial", color: "var(--teal)", bg: "var(--teal-d)" },
    { key: "vlog", icon: "📹", label: "Vlog", color: "#DE7BA4", bg: "rgba(222,123,164,.12)" },
    { key: "series", icon: "📺", label: "Series", color: "var(--blue)", bg: "var(--blue-d)" },
  ];
  const typeOf = (k) => TYPES.find((t) => t.key === k) || TYPES[0];

  let openId = null;          // null = grid, otherwise the video detail
  // Open one video from another tab (a project's attachments).
  window.VisionVideos = { open(id) { openId = id; } };
  let filterType = "";       // "" | "type:<key>" | "stage:<name>"
  let query = "";
  let host = null, pipelines = [];

  const dateFmt = (iso) => {
    if (!iso) return "";
    try { return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
    catch { return String(iso).slice(0, 10); }
  };

  function typeBadge(k) {
    const t = typeOf(k);
    return el("span.vid-badge", { style: "background:" + t.bg + ";color:" + t.color, text: t.icon + " " + t.label });
  }

  /* --- new-video modal ---------------------------------------------------- */
  function newVideoModal(reload) {
    const title = el("input.mform-input", { placeholder: "video title" });
    const type = el("select.mform-input", {}, TYPES.map((t) => el("option", { value: t.key, text: t.icon + " " + t.label })));
    const pipe = el("select.mform-input", {}, [
      el("option", { value: "", text: "— no pipeline —" }),
      ...pipelines.map((p) => el("option", { value: p.id, text: p.name })),
    ]);
    const target = el("input.mform-input", { type: "date" });
    const framework = el("input.mform-input", { placeholder: "e.g. Hook→Story→CTA" });
    const desc = el("input.mform-input", { placeholder: "the concept — what it's about, the hook, the angle" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);

    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.appendChild(el("div.modal.vis-modal", {}, [
      el("div.modal-title", { text: "New video" }),
      field("Title", title),
      el("div.mform-row", {}, [field("Type", type), field("Pipeline", pipe)]),
      el("div.mform-row", {}, [field("Target date", target), field("Framework", framework)]),
      field("Concept", desc),
      el("div.sub", { text: "Stages come from the pipeline you pick — it starts at that pipeline's first stage." }),
      el("div.row", { style: "margin-top:16px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
          if (!title.value.trim()) return toast("the video needs a title", true);
          const v = await V().createVideo({
            title: title.value.trim(), type: type.value, pipeline_id: pipe.value || null,
            target_date: target.value || null, framework: framework.value.trim(),
            description: desc.value.trim(),
          });
          close(); toast("video created"); openId = v.id; reload();
        }), text: "Create" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    title.focus();
  }

  /* --- master view: a YouTube-homepage grid of every video ---------------- */
  // The cover is the chosen thumbnail, else the first option that has an
  // image. Hovering a video with several options cycles through them, the way
  // YouTube previews on hover — so you can compare a video's options from home.
  const coverImages = (v) => {
    const opts = (v.thumbs || []).filter((t) => t.image);
    const chosen = opts.find((t) => t.chosen);
    const list = chosen ? [chosen, ...opts.filter((t) => t !== chosen)] : opts;
    if (!list.length && v.thumbnail) return [v.thumbnail];
    return list.map((t) => t.image);
  };

  function videoCard(v, reload) {
    const t = typeOf(v.type);
    const imgs = coverImages(v);
    const card = el("div.yt-card", { onclick: () => { openId = v.id; reload(); } });
    const cover = el("div.yt-thumb");
    if (!imgs.length) cover.appendChild(el("div.vid-cover-empty", { text: t.icon }));
    if (v.stage) cover.appendChild(el("span.yt-stage", { text: v.stage }));
    // hover previews the options like YouTube; ‹ › / ←→ step through them by hand
    window.Images.cycle(cover, imgs, { hoverHost: card, autoplay: true, resetOnLeave: true });

    const nThumbs = (v.thumbs || []).length;
    const meta2 = [
      v.target_date ? "🎯 " + dateFmt(v.target_date) : "no target date",
      nThumbs ? nThumbs + " thumbnail" + (nThumbs > 1 ? "s" : "") : null,
    ].filter(Boolean).join(" · ");
    card.appendChild(cover);
    card.appendChild(el("div.yt-info", {}, [
      el("div.yt-avatar", { style: "background:" + t.bg + ";color:" + t.color, title: t.label, text: t.icon }),
      el("div", { style: "min-width:0" }, [
        el("div.yt-title", { title: v.title, text: v.title }),
        el("div.yt-meta", { text: t.label + (v.pipeline ? " · " + v.pipeline.name : "") }),
        el("div.yt-meta", { text: meta2 }),
      ]),
    ]));
    return card;
  }

  /* --- detail view -------------------------------------------------------- */
  function editableBlock(label, value, placeholder, onSave) {
    const box = el("div.vid-section");
    box.appendChild(el("div.vid-sec-head", { text: label }));
    // one statement (the concept), so one line
    const ta = el("input.mform-input", { placeholder });
    ta.value = value || "";
    ta.addEventListener("blur", () => guard(async () => {
      if ((ta.value || "") === (value || "")) return;
      await onSave(ta.value); toast("saved");
    }));
    box.appendChild(ta);
    return box;
  }

  function pipelineBar(v) {
    if (!v.pipeline_stages.length) return null;
    const bar = el("div.vid-pipebar");
    bar.appendChild(el("span.sub", { style: "flex:0 0 auto", text: "📐 " + (v.pipeline ? v.pipeline.name : "") }));
    v.pipeline_stages.forEach((s, i) => {
      if (i) bar.appendChild(el("span.vid-pipesep", { text: "›" }));
      bar.appendChild(el("span.vid-pipestage" + (s.name === v.stage ? ".on" : ""), { text: s.name }));
    });
    return bar;
  }

  function detailView(v, reload) {
    const wrap = el("div");
    wrap.appendChild(el("button.btn-sm", { style: "margin-bottom:14px",
      onclick: () => { openId = null; reload(); }, text: "← back to videos" }));

    const t = typeOf(v.type);
    const heroImgs = coverImages(v);
    const cover = el("div.vid-hero");
    if (!heroImgs.length) cover.appendChild(el("div.vid-cover-empty", { style: "font-size:40px", text: t.icon }));
    window.Images.cycle(cover, heroImgs);

    const titleIn = el("input.vis-title", { value: v.title });
    titleIn.addEventListener("blur", () => guard(async () => {
      const nv = titleIn.value.trim();
      if (!nv || nv === v.title) { titleIn.value = v.title; return; }
      await V().updateVideo(v.id, { title: nv }); v.title = nv; toast("renamed");
    }));

    const typeSel = el("select", {}, TYPES.map((x) => el("option", { value: x.key, text: x.icon + " " + x.label })));
    typeSel.value = v.type;
    typeSel.addEventListener("change", () => guard(async () => {
      await V().updateVideo(v.id, { type: typeSel.value }); reload();
    }));
    const pipeSel = el("select", {}, [
      el("option", { value: "", text: "— no pipeline —" }),
      ...pipelines.map((p) => el("option", { value: p.id, text: p.name })),
    ]);
    pipeSel.value = v.pipeline_id || "";
    pipeSel.addEventListener("change", () => guard(async () => {
      await V().updateVideo(v.id, { pipeline_id: pipeSel.value || null }); reload();
    }));
    const stageSel = el("select", {}, [
      el("option", { value: "", text: v.pipeline_stages.length ? "— pick a stage —" : "— no pipeline —" }),
      ...v.pipeline_stages.map((s) => el("option", { value: s.name, text: s.name })),
    ]);
    stageSel.value = v.stage || "";
    stageSel.addEventListener("change", () => guard(async () => {
      await V().updateVideo(v.id, { stage: stageSel.value }); reload();
    }));
    const dateIn = el("input", { type: "date", value: (v.target_date || "").slice(0, 10) });
    dateIn.addEventListener("change", () => guard(async () => {
      await V().updateVideo(v.id, { target_date: dateIn.value || null }); toast("saved");
    }));
    const fwIn = el("input", { value: v.framework || "", placeholder: "framework" });
    fwIn.addEventListener("blur", () => guard(async () => {
      if (fwIn.value === (v.framework || "")) return;
      await V().updateVideo(v.id, { framework: fwIn.value }); v.framework = fwIn.value; toast("saved");
    }));
    const llmIn = el("input", { value: v.llms_used || "", placeholder: "LLMs / AI tools used" });
    llmIn.addEventListener("blur", () => guard(async () => {
      if (llmIn.value === (v.llms_used || "")) return;
      await V().updateVideo(v.id, { llms_used: llmIn.value }); v.llms_used = llmIn.value; toast("saved");
    }));

    const atEnd = v.pipeline_stages.length &&
      v.pipeline_stages[v.pipeline_stages.length - 1].name === v.stage;
    const head = el("div.vision-card", {}, [
      el("div.vid-headgrid", {}, [
        cover,
        el("div", { style: "min-width:0" }, [
          titleIn,
          el("div.vid-fieldgrid", {}, [
            el("label.md-field", {}, [el("span.sub", { text: "type" }), typeSel]),
            el("label.md-field", {}, [el("span.sub", { text: "pipeline" }), pipeSel]),
            el("label.md-field", {}, [el("span.sub", { text: "stage" }), stageSel]),
            el("label.md-field", {}, [el("span.sub", { text: "target date" }), dateIn]),
            el("label.md-field", {}, [el("span.sub", { text: "framework" }), fwIn]),
            el("label.md-field", {}, [el("span.sub", { text: "llms / ai tools" }), llmIn]),
          ]),
          el("div.row", { style: "gap:8px;margin-top:12px" }, [
            el("button.btn-sm.btn-primary", {
              disabled: !v.pipeline_stages.length || !!atEnd,
              title: !v.pipeline_stages.length ? "link a pipeline first" : (atEnd ? "already at the final stage" : ""),
              onclick: () => guard(async () => { await V().advanceVideo(v.id); toast("stage advanced"); reload(); }),
              text: "→ move to next stage" }),
            el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + v.title + "”?", async () => {
              await V().delVideo(v.id); openId = null; reload();
            }), text: "delete" }),
          ]),
        ]),
      ]),
    ]);
    const pb = pipelineBar(v);
    if (pb) head.appendChild(pb);
    wrap.appendChild(head);
    if (window.ProjectAttach) {
      wrap.appendChild(window.ProjectAttach.strip({ kind: "video", id: v.id, title: v.title }));
    }

    wrap.appendChild(editableBlock("📋 Concept", v.description, "what the video is about — hook, angle",
      (val) => V().updateVideo(v.id, { description: val })));

    // sections contributed by later increments (research, script, prompts,
    // storyboard, thumbnails) render here in registration order
    sections().forEach((sec) => {
      const box = el("div.vid-section");
      box.appendChild(el("div.vid-sec-head", { text: sec.label }));
      sec.render(box, v, reload);
      wrap.appendChild(box);
    });

    wrap.appendChild(journalSection(v, reload));
    wrap.appendChild(notesSection(v, reload));

    const imgs = el("div.vid-section");
    imgs.appendChild(el("div.vid-sec-head", { text: "📷 Images" }));
    window.Images.mount(imgs, { module: "vision", contextId: v.id, surface: "vision-video" });
    wrap.appendChild(imgs);
    return wrap;
  }

  /* --- production notes with @-mentions ---------------------------------- */
  // Type @ to link another video, a Synapse concept, an idea or a doc. The
  // text stores `@[Label](kind:id)`; the backend mirrors those into
  // (:Video)-[:MENTIONS]->() edges, which also give us "mentioned in" backlinks.
  const MENTION_RE = /@\[([^\]\n]*)\]\((video|concept|idea|doc):([\w-]+)\)/g;
  const KIND_ICON = { video: "▶", concept: "◆", idea: "💡", doc: "📄" };

  function openMention(kind, id, reload) {
    if (kind === "video") { openId = id; return reload(); }
    if (kind === "doc" && window.Docs) return window.Docs.open(id);
    if (kind === "concept") return window.openTab && window.openTab("dictionary");
    if (kind === "idea") return window.openTab && window.openTab("inbox");
  }

  function mentionChip(kind, id, label, reload) {
    return el("span.vmn-chip.k-" + kind, {
      title: "open " + kind, text: KIND_ICON[kind] + " " + label,
      onclick: (e) => { e.stopPropagation(); openMention(kind, id, reload); },
    });
  }

  function notesSection(v, reload) {
    const box = el("div.vid-section");
    box.appendChild(el("div.vid-sec-head", { text: "📌 Production notes" }));
    const current = new Map((v.mentions || []).map((m) => [m.kind + ":" + m.id, m.label]));

    // read mode — tokens rendered as clickable chips (label kept current via the edge)
    const read = el("div.vmn-read", { title: "click to edit" });
    const paintRead = (text) => {
      clear(read);
      if (!text.trim()) { read.appendChild(el("span.sub", { style: "font-style:italic", text: "production notes, lessons learned — type @ to link a video or concept" })); return; }
      let last = 0;
      for (const m of text.matchAll(MENTION_RE)) {
        if (m.index > last) read.appendChild(document.createTextNode(text.slice(last, m.index)));
        const label = current.get(m[2] + ":" + m[3]) || m[1];
        read.appendChild(mentionChip(m[2], m[3], label, reload));
        last = m.index + m[0].length;
      }
      if (last < text.length) read.appendChild(document.createTextNode(text.slice(last)));
    };

    const ta = el("textarea.mform-input", { rows: "6", placeholder: "production notes — type @ to link a video, concept, idea or doc" });
    ta.value = v.notes || "";
    const editWrap = el("div.vmn-edit", { style: "display:none" }, [ta]);
    const pop = el("div.vmn-pop", { style: "display:none" });
    editWrap.appendChild(pop);

    const toEdit = () => { read.style.display = "none"; editWrap.style.display = ""; ta.focus(); };
    const toRead = () => { editWrap.style.display = "none"; read.style.display = ""; paintRead(ta.value); };
    read.addEventListener("click", toEdit);

    // @-autocomplete
    let items = [], sel = 0, at = -1, seq = 0;
    const hide = () => { pop.style.display = "none"; items = []; at = -1; };
    const pick = (it) => {
      const caret = ta.selectionStart;
      const token = "@[" + it.label.replace(/[\]\n]/g, " ") + "](" + it.kind + ":" + it.id + ") ";
      ta.value = ta.value.slice(0, at) + token + ta.value.slice(caret);
      const pos = at + token.length;
      ta.setSelectionRange(pos, pos);
      current.set(it.kind + ":" + it.id, it.label);
      hide(); ta.focus();
    };
    const paintPop = () => {
      clear(pop);
      if (!items.length) { pop.appendChild(el("div.sub", { style: "padding:6px 9px", text: "no matches" })); }
      items.forEach((it, k) => {
        const row = el("div.vmn-opt" + (k === sel ? ".on" : ""), {}, [
          el("span.vmn-kind.k-" + it.kind, { text: KIND_ICON[it.kind] + " " + it.kind }),
          el("span", { text: it.label }),
        ]);
        row.addEventListener("mousedown", (e) => { e.preventDefault(); pick(it); });
        pop.appendChild(row);
      });
      pop.style.display = "";
    };
    ta.addEventListener("input", async () => {
      const upto = ta.value.slice(0, ta.selectionStart);
      const m = upto.match(/(^|\s)@([^\s@\[\]()]{0,40})$/);
      if (!m) return hide();
      at = upto.length - m[2].length - 1;
      const mine = ++seq;
      const res = await V().mentionables(m[2]).catch(() => []);
      if (mine !== seq) return;               // a newer keystroke already answered
      items = res.filter((it) => !(it.kind === "video" && it.id === v.id)); sel = 0; paintPop();
    });
    ta.addEventListener("keydown", (e) => {
      if (pop.style.display === "none") { if (e.key === "Escape") ta.blur(); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (items.length) { sel = (sel + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length; paintPop(); }
      } else if ((e.key === "Enter" || e.key === "Tab") && items.length) { e.preventDefault(); pick(items[sel]); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); hide(); }
    });
    ta.addEventListener("blur", () => {
      hide();
      if ((ta.value || "") === (v.notes || "")) return toRead();
      guard(async () => {
        await V().updateVideo(v.id, { notes: ta.value }); toast("saved");
        reload();                              // refresh mentions + backlinks
      });
    });

    paintRead(ta.value);
    box.appendChild(read);
    box.appendChild(editWrap);

    if ((v.mentions || []).length) {
      box.appendChild(el("div.vmn-links", {}, [
        el("span.sub", { text: "links to" }),
        ...v.mentions.map((m) => mentionChip(m.kind, m.id, m.label, reload)),
      ]));
    }
    if ((v.mentioned_by || []).length) {
      box.appendChild(el("div.vmn-links", {}, [
        el("span.sub", { text: "mentioned in" }),
        ...v.mentioned_by.map((o) => mentionChip("video", o.id, o.title, reload)),
      ]));
    }
    return box;
  }

  function journalSection(v, reload) {
    const box = el("div.vid-section");
    box.appendChild(el("div.vid-sec-head", { text: "📖 Progress journal" }));
    const ta = el("textarea.mform-input", { rows: "2", placeholder: "what happened today?" });
    box.appendChild(ta);
    box.appendChild(el("div.row", { style: "margin-top:8px" }, [
      el("button.btn-sm", { onclick: () => guard(async () => {
        if (!ta.value.trim()) return toast("write something first", true);
        await V().addVideoEntry(v.id, { text: ta.value.trim() });
        ta.value = ""; reload();
      }), text: "+ add entry" }),
    ]));
    if (!v.entries.length) {
      box.appendChild(el("div.sub", { style: "margin-top:10px;font-style:italic", text: "No entries yet." }));
      return box;
    }
    v.entries.forEach((e) => box.appendChild(el("div.vid-entry", {}, [
      el("div.spread", {}, [
        el("span.sub", { text: dateFmt(e.date) }),
        el("button.ord-btn", { title: "delete entry", text: "×", onclick: () => guard(async () => {
          await V().delVideoEntry(v.id, e.id); reload();
        }) }),
      ]),
      el("div", { style: "margin-top:2px;white-space:pre-wrap", text: e.text }),
    ])));
    return box;
  }

  window.Views = window.Views || {};
  window.Views.youtube = {
    id: "youtube", label: "YouTube", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "YouTube" }),
        el("div.sub", { text: "Each video is a production workspace — concept, research, script, prompts, storyboard, thumbnails. Stages come from the Blueprint pipeline it follows." }),
      ])]));
      const bar = el("div"); view.appendChild(bar);
      host = el("div"); view.appendChild(host);

      let lastId = null;

      async function reload() {
        // The detail view is long and every expand/collapse re-renders it, so
        // hold the scroll position when we're staying on the same video.
        // NB the app scrolls `.view`, not the window (see .layout in main.css).
        const scroller = view.closest(".view") || view;
        const keepScroll = openId && openId === lastId;
        const y = keepScroll ? scroller.scrollTop : 0;

        pipelines = await guard(() => V().pipelines());
        clear(bar); clear(host);

        if (openId) {
          let v;
          try { v = await V().video(openId); }
          catch { openId = null; lastId = null; return reload(); }
          host.appendChild(detailView(v, reload));
          lastId = openId;
          scroller.scrollTop = keepScroll ? y : 0;
          return;
        }
        lastId = null;

        bar.appendChild(el("div.row", { style: "margin-bottom:12px;gap:10px" }, [
          el("button.btn-primary", { onclick: () => newVideoModal(reload), text: "+ video" }),
          (() => {
            const q = el("input.yt-search", { type: "search", placeholder: "search videos", value: query });
            q.addEventListener("input", () => { query = q.value; paintGrid(); });
            return q;
          })(),
        ]));
        const chips = el("div.yt-chips"); bar.appendChild(chips);

        const all = await guard(() => V().videos(""));
        if (!all.length) {
          host.appendChild(el("div.empty", { text: "No videos yet. Create one — then build it out." }));
          return;
        }
        // chips: every type and every stage actually in use
        const stages = [...new Set(all.map((v) => v.stage).filter(Boolean))];
        const usedTypes = TYPES.filter((t) => all.some((v) => v.type === t.key));
        const chip = (key, label) => el("button.yt-chip" + (filterType === key ? ".on" : ""), {
          text: label, onclick: () => { filterType = key; paintChips(); paintGrid(); },
        });
        function paintChips() {
          clear(chips);
          chips.appendChild(chip("", "All"));
          usedTypes.forEach((t) => chips.appendChild(chip("type:" + t.key, t.icon + " " + t.label)));
          if (stages.length) chips.appendChild(el("span.yt-chipsep"));
          stages.forEach((st) => chips.appendChild(chip("stage:" + st, st)));
        }
        function paintGrid() {
          clear(host);
          const needle = query.trim().toLowerCase();
          const vids = all.filter((v) => {
            if (filterType.startsWith("type:") && v.type !== filterType.slice(5)) return false;
            if (filterType.startsWith("stage:") && v.stage !== filterType.slice(6)) return false;
            return !needle || (v.title + " " + (v.description || "")).toLowerCase().includes(needle);
          });
          if (!vids.length) { host.appendChild(el("div.empty", { text: "No videos match." })); return; }
          const grid = el("div.yt-grid");
          vids.forEach((v) => grid.appendChild(videoCard(v, reload)));
          host.appendChild(grid);
        }
        paintChips(); paintGrid();
      }
      reload();
    },
  };
})();

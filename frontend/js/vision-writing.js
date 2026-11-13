/* vision-writing.js — Vision · Writing (VISION_SPEC §3).

   Blogs, articles, threads tracked through a Blueprint pipeline — the same
   stage machinery as videos, so stages are never hardcoded here either. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;

  const TYPES = ["Blog", "Article", "Thread", "Newsletter", "Essay"];
  const PLATFORMS = ["Blog", "Medium", "Substack", "LinkedIn", "Twitter", "Other"];
  const open = new Set();
  let pipelines = [];

  function card(w, reload) {
    const isOpen = open.has(w.id);
    const atEnd = w.pipeline_stages.length &&
      w.pipeline_stages[w.pipeline_stages.length - 1].name === w.stage;

    const head = el("div.spread", { style: "cursor:pointer",
      onclick: () => { isOpen ? open.delete(w.id) : open.add(w.id); reload(); } }, [
      el("div.row", { style: "gap:8px;min-width:0;flex-wrap:wrap" }, [
        el("span", { style: "font-weight:600", text: w.title }),
        el("span.vw-tag", { text: w.type }),
        el("span.vw-tag", { style: "color:var(--blue)", text: w.platform }),
        w.stage ? el("span.vw-tag", { style: "color:#FF4757;border-color:#FF4757", text: w.stage }) : null,
      ]),
      el("button.ord-btn", { text: isOpen ? "▾" : "▸" }),
    ]);
    const c = el("div.vision-card", {}, [head]);
    if (!isOpen) return c;

    const body = el("div", { style: "margin-top:12px;padding-top:11px;border-top:1px solid var(--border)" });
    const field = (label, node) => el("label.md-field", {}, [el("span.sub", { text: label }), node]);

    const typeSel = el("select", {}, TYPES.map((t) => el("option", { value: t, text: t })));
    typeSel.value = w.type;
    typeSel.addEventListener("change", () => guard(async () => {
      await V().updateWriting(w.id, { type: typeSel.value }); reload();
    }));
    const platSel = el("select", {}, PLATFORMS.map((t) => el("option", { value: t, text: t })));
    platSel.value = w.platform;
    platSel.addEventListener("change", () => guard(async () => {
      await V().updateWriting(w.id, { platform: platSel.value }); reload();
    }));
    const pipeSel = el("select", {}, [
      el("option", { value: "", text: "— no pipeline —" }),
      ...pipelines.map((p) => el("option", { value: p.id, text: p.name })),
    ]);
    pipeSel.value = w.pipeline_id || "";
    pipeSel.addEventListener("change", () => guard(async () => {
      await V().updateWriting(w.id, { pipeline_id: pipeSel.value || null }); reload();
    }));
    const stageSel = el("select", {}, [
      el("option", { value: "", text: w.pipeline_stages.length ? "— pick a stage —" : "— no pipeline —" }),
      ...w.pipeline_stages.map((s) => el("option", { value: s.name, text: s.name })),
    ]);
    stageSel.value = w.stage || "";
    stageSel.addEventListener("change", () => guard(async () => {
      await V().updateWriting(w.id, { stage: stageSel.value }); reload();
    }));
    const link = el("input", { value: w.link || "", placeholder: "published URL (optional)" });
    link.addEventListener("blur", () => guard(async () => {
      if ((link.value || "") === (w.link || "")) return;
      await V().updateWriting(w.id, { link: link.value }); w.link = link.value; toast("saved");
    }));

    body.appendChild(el("div.md-grid", {}, [
      field("type", typeSel), field("platform", platSel),
      field("pipeline", pipeSel), field("stage", stageSel), field("link", link),
    ]));

    body.appendChild(el("div", { style: "margin-top:10px" }, [
      window.RowBox({ label: "notes", placeholder: "a note, an outline point, a line to use", parentId: w.id }).node,
    ]));

    if (w.pipeline_stages.length) {
      const bar = el("div.vid-pipebar", {}, [el("span.sub", { style: "flex:0 0 auto", text: "📐 " + (w.pipeline ? w.pipeline.name : "") })]);
      w.pipeline_stages.forEach((s, i) => {
        if (i) bar.appendChild(el("span.vid-pipesep", { text: "›" }));
        bar.appendChild(el("span.vid-pipestage" + (s.name === w.stage ? ".on" : ""), { text: s.name }));
      });
      body.appendChild(bar);
    }

    window.Images.mount(body, { module: "vision", contextId: w.id, surface: "vision-writing", title: "Images" });
    body.appendChild(el("div.row", { style: "gap:8px;margin-top:10px" }, [
      el("button.btn-sm.btn-primary", {
        disabled: !w.pipeline_stages.length || !!atEnd,
        title: !w.pipeline_stages.length ? "link a pipeline first" : (atEnd ? "already at the final stage" : ""),
        onclick: () => guard(async () => { await V().advanceWriting(w.id); toast("stage advanced"); reload(); }),
        text: "→ move to next stage" }),
      w.link ? el("a.btn-sm", { href: w.link, target: "_blank", rel: "noopener noreferrer",
        style: "text-decoration:none", text: "open ↗" }) : null,
      el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + w.title + "”?", async () => {
        await V().delWriting(w.id); open.delete(w.id); reload();
      }), text: "delete" }),
    ]));
    c.appendChild(body);
    return c;
  }

  window.Views = window.Views || {};
  window.Views.writing = {
    id: "writing", label: "Writing", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Writing" }),
        el("div.sub", { text: "Blogs, articles, threads — tracked through the same Blueprint pipelines as videos." }),
      ])]));

      const titleIn = el("input", { placeholder: "title", style: "flex:1;min-width:180px" });
      const typeSel = el("select", {}, TYPES.map((t) => el("option", { value: t, text: t })));
      const platSel = el("select", {}, PLATFORMS.map((t) => el("option", { value: t, text: t })));
      const pipeSel = el("select", {});
      const add = () => guard(async () => {
        if (!titleIn.value.trim()) return toast("give it a title", true);
        await V().createWriting({ title: titleIn.value.trim(), type: typeSel.value,
          platform: platSel.value, pipeline_id: pipeSel.value || null });
        titleIn.value = ""; toast("created"); reload();
      });
      titleIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      const bar = el("div.row", { style: "margin-bottom:16px" }, [
        titleIn, typeSel, platSel, pipeSel,
        el("button.btn-primary", { onclick: add, text: "+ piece" }),
      ]);
      view.appendChild(bar);
      const host = el("div"); view.appendChild(host);

      async function reload() {
        pipelines = await guard(() => V().pipelines());
        clear(pipeSel);
        pipeSel.appendChild(el("option", { value: "", text: "— no pipeline —" }));
        pipelines.forEach((p) => pipeSel.appendChild(el("option", { value: p.id, text: p.name })));
        const items = await guard(() => V().writing());
        clear(host);
        if (!items.length) {
          host.appendChild(el("div.empty", { text: "Nothing written yet. Add a piece above." }));
          return;
        }
        items.forEach((w) => host.appendChild(card(w, reload)));
      }
      reload();
    },
  };
})();

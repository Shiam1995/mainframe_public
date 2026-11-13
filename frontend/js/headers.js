/* headers.js — user-defined custom sections. Global headers become their own
   top tabs (see app.js); this view manages them and renders each one's freeform
   markdown/text content. renderOne() is what a header-tab shows. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  async function refreshTabs() {
    // ask app.js to reload global-header tabs
    if (window.PM && window.PM.reloadHeaders) await window.PM.reloadHeaders();
  }

  window.Views = window.Views || {};
  window.Views.headers = {
    id: "headers", label: "Sections", scoped: false,

    // Rendered when a custom-header tab is opened.
    async renderOne(view, header) {
      clear(view);
      const fresh = (await guard(() => api.get("/api/synapse/headers"))).find((h) => h.id === header.id) || header;
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [ el("h1", { text: fresh.name }), fresh.description ? el("div.sub", { text: fresh.description }) : null ]),
      ]));
      const ta = el("textarea", { style: "width:100%;min-height:52vh;font-family:var(--mono);line-height:1.6", text: fresh.content || "" });
      view.appendChild(ta);
      view.appendChild(el("div.row", { style: "margin-top:10px" }, [
        el("button.btn-primary", { onclick: () => guard(async () => { await api.patch("/api/synapse/headers/" + fresh.id, { content: ta.value }); toast("saved"); }), text: "save" }),
      ]));
      window.Images.mount(view, { module: "synapse", contextId: fresh.id, surface: "synapse-section", title: "Images" });
    },

    // The management view (the "Sections" tab).
    async render(view, PM) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [ el("h1", { text: "Custom Sections" }), el("div.sub", { text: "Grow the system without code — global sections become tabs." }) ]),
      ]));
      const name = el("input", { placeholder: "section name", style: "width:180px" });
      const desc = el("input", { placeholder: "description", style: "flex:1;min-width:160px" });
      const order = el("input", { type: "number", value: "0", style: "width:70px" });
      const scope = el("select", {}, [ el("option", { value: "", text: "global (tab)" }),
        ...PM.papers.map((p) => el("option", { value: p.id, text: "scoped: " + p.title.slice(0, 26) })) ]);
      view.appendChild(el("div.row", { style: "margin-bottom:16px" }, [ name, desc, order, scope,
        el("button.btn-primary", { onclick: () => guard(async () => {
          if (!name.value.trim()) return;
          await api.post("/api/synapse/headers", { name: name.value.trim(), description: desc.value, order: +order.value, paper_id: scope.value || null, content: "" });
          name.value = desc.value = ""; await refreshTabs(); reload();
        }), text: "+ create" }) ]));
      const list = el("div.cards"); view.appendChild(list);
      async function reload() {
        const hs = await guard(() => api.get("/api/synapse/headers"));
        clear(list);
        if (!hs.length) { list.appendChild(el("div.empty", { text: "No custom sections yet." })); return; }
        hs.forEach((h) => list.appendChild(el("div.card", {}, [
          el("div.spread", {}, [ el("h3", { style: "margin:0", text: h.name }), el("span.pill", { text: h.paper_id ? "scoped" : "global" }) ]),
          h.description ? el("div.sub", { text: h.description }) : null,
          el("div.row", { style: "margin-top:10px" }, [
            el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete section “" + h.name + "”?", async () => { await api.del("/api/synapse/headers/" + h.id); await refreshTabs(); reload(); }), text: "delete" }),
          ]),
        ])));
      }
      reload();
    },
  };
})();

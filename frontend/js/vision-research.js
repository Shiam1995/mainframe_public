/* vision-research.js — Vision · YouTube § Research (VISION_UPDATE_SPEC §1).

   Where you dump links, paper references and competitor video analysis for a
   video. Registers itself into VID_SECTIONS; the shell renders it. */
(function () {
  const { el, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;

  function noteCard(v, r, reload) {
    const title = el("input.vis-title", { style: "font-size:13px", value: r.title });
    title.addEventListener("blur", () => guard(async () => {
      const nv = title.value.trim();
      if (!nv || nv === r.title) { title.value = r.title; return; }
      await V().updateResearch(v.id, r.id, { title: nv }); r.title = nv; toast("saved");
    }));
    const url = el("input", { value: r.url || "", placeholder: "https:// (optional)", style: "width:100%;font-size:11px" });
    url.addEventListener("blur", () => guard(async () => {
      if ((url.value || "") === (r.url || "")) return;
      await V().updateResearch(v.id, r.id, { url: url.value }); r.url = url.value; toast("saved");
    }));
    // findings are rows on the source node, saved as you press Enter
    const findings = window.RowBox({ label: "findings", noun: "finding", placeholder: "a finding, quote or data point", parentId: r.id });

    return el("div.vres-card", {}, [
      el("div.spread", {}, [
        title,
        el("div.row", { style: "gap:4px;flex:0 0 auto" }, [
          r.url ? el("a.btn-sm", { href: r.url, target: "_blank", rel: "noopener noreferrer",
            style: "text-decoration:none", text: "open ↗" }) : null,
          el("button.ord-btn", { title: "delete source", text: "×", onclick: () => confirmDo("Delete source “" + r.title + "”?", async () => {
            await V().delResearch(v.id, r.id); reload();
          }) }),
        ]),
      ]),
      url, findings.node,
    ]);
  }

  window.VID_SECTIONS = window.VID_SECTIONS || [];
  window.VID_SECTIONS.push({
    key: "research", label: "🔬 Research", order: 10,
    render(host, v, reload) {
      const titleIn = el("input", { placeholder: "source title", style: "flex:1;min-width:150px" });
      const urlIn = el("input", { placeholder: "url (optional)", style: "flex:1;min-width:150px" });
      const add = () => guard(async () => {
        if (!titleIn.value.trim()) return toast("the source needs a title", true);
        await V().addResearch(v.id, { title: titleIn.value.trim(), url: urlIn.value.trim() || null });
        titleIn.value = urlIn.value = ""; reload();
      });
      titleIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      host.appendChild(el("div.row", { style: "margin-bottom:10px" }, [
        titleIn, urlIn, el("button.btn-sm", { onclick: add, text: "+ add source" }),
      ]));
      if (!v.research.length) {
        host.appendChild(el("div.sub", { style: "font-style:italic", text: "No sources yet — links, papers, competitor videos go here." }));
        return;
      }
      v.research.forEach((r) => host.appendChild(noteCard(v, r, reload)));
    },
  });
})();

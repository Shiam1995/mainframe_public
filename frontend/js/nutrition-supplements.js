/* nutrition-supplements.js — supplements list (name · dose · timing · notes). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  // image widget for one list row, returned as a child node
  function imgHost(id, surface) {
    const host = window.ui.el("div");
    window.Images.mount(host, { module: "pulse", contextId: id, surface, title: "Images" });
    return host;
  }

  const P = window.PULSE;
  const N = () => api.pulse.nutrition;

  function addModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Creatine, Vitamin D" });
    const dose = el("input.mform-input", { placeholder: "e.g. 5g, 1000 IU" });
    const timing = el("input.mform-input", { placeholder: "e.g. morning, post-workout" });
    // + rows, held until the supplement exists and then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "brand, effect, when to stop…" });
    P.modal("Add supplement", [
      el("div.mform-full", {}, [el("div.mform-label", { text: "Name" }), name]),
      el("div.mform-row", {}, [el("div", {}, [el("div.mform-label", { text: "Dose" }), dose]), el("div", {}, [el("div.mform-label", { text: "Timing" }), timing])]),
      notes.node,
    ], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!name.value.trim()) return toast("name it", true); const made = await N().addSupplement({ name: name.value.trim(), dose: dose.value.trim(), timing: timing.value.trim() }); await notes.commit(made.id); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [el("button.btn-primary", { onclick: () => addModal(reload), text: "＋ add supplement" })]));
    const list = el("div"); host.appendChild(list);
    async function reload() {
      const items = await guard(() => N().supplements());
      clear(list);
      if (!items.length) { list.appendChild(el("div.empty", { text: "No supplements yet." })); return; }
      items.forEach((s) => list.appendChild(el("div.pulse-card", {}, [el("div.spread", {}, [
        el("div", {}, [
          el("span", { style: "font-weight:600", text: s.name }),
          (s.dose || s.timing) ? el("div", { style: "color:#DE7BA4;font-family:var(--mono);font-size:12px;margin-top:2px", text: [s.dose, s.timing].filter(Boolean).join(" · ") }) : null,
          window.RowBox({ label: "notes", parentId: s.id }).node,
        ]),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + s.name + "”?", async () => { await N().delSupplement(s.id); reload(); }), text: "×" }),
      ]), imgHost(s.id, "pulse-supplement")])));
    }
    reload();
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "supplements", label: "Supplements", order: 30, render });
})();

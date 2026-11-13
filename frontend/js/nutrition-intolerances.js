/* nutrition-intolerances.js — food intolerances list. */
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
  const SEV = { mild: "var(--teal)", moderate: "var(--amber)", severe: "var(--red)" };

  function addModal(reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Lactose, Gluten, Nuts" });
    const sev = el("select.mform-input", {}, ["", "mild", "moderate", "severe"].map((s) => el("option", { value: s, text: s || "— severity —" })));
    // + rows, held until the intolerance exists and then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "a reaction, an observation" });
    P.modal("Add intolerance", [
      el("div.mform-full", {}, [el("div.mform-label", { text: "Name" }), name]),
      el("div.mform-full", {}, [el("div.mform-label", { text: "Severity" }), sev]),
      notes.node,
    ], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => { if (!name.value.trim()) return toast("name it", true); const made = await N().addIntolerance({ name: name.value.trim(), severity: sev.value }); await notes.commit(made.id); close(); reload(); }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  async function render(host) {
    host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [el("button.btn-primary", { onclick: () => addModal(reload), text: "＋ add intolerance" })]));
    const list = el("div"); host.appendChild(list);
    async function reload() {
      const items = await guard(() => N().intolerances());
      clear(list);
      if (!items.length) { list.appendChild(el("div.empty", { text: "No intolerances logged." })); return; }
      items.forEach((i) => list.appendChild(el("div.pulse-card", {}, [el("div.spread", {}, [
        el("div", {}, [
          el("div.row", { style: "gap:8px" }, [el("span", { style: "font-weight:600", text: i.name }), i.severity ? el("span.pulse-tag", { style: "border:1px solid " + (SEV[i.severity] || "var(--dim)") + ";color:" + (SEV[i.severity] || "var(--dim)") + ";background:transparent", text: i.severity }) : null]),
          window.RowBox({ label: "notes", parentId: i.id }).node,
        ]),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + i.name + "”?", async () => { await N().delIntolerance(i.id); reload(); }), text: "×" }),
      ]), imgHost(i.id, "pulse-intolerance")])));
    }
    reload();
  }

  window.NUT_TABS = window.NUT_TABS || [];
  window.NUT_TABS.push({ key: "intolerances", label: "Intolerances", order: 80, undecided: true, render });
})();

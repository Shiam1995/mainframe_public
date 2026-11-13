/* medications.js — Pulse: Medications. 9 config-driven accordion sections; entries
   show name + dose·frequency (pink) + status colour tag. Separate from Medical. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const STATUSES = ["", "active", "paused", "stopped", "as-needed", "effective", "ineffective", "side-effects"];

  const open = new Set();

  function addEntryModal(sec, reload) {
    const name = el("input.mform-input", { placeholder: "e.g. Ibuprofen" });
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const dose = el("input.mform-input", { placeholder: "e.g. 200mg" });
    const freq = el("input.mform-input", { placeholder: "e.g. 2x daily / as needed" });
    const status = el("select.mform-input", {}, STATUSES.map((s) => el("option", { value: s, text: s || "— none —" })));
    // One + rows box for what used to be "details" and "notes": held until the
    // entry exists, then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "what it's for, side effects, how it's going" });
    const tags = el("input.mform-input", { placeholder: "tags, comma-separated" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Add to " + sec.label, [
      el("div.mform-row", {}, [field("Name", name), field("Date", date)]),
      el("div.mform-row-3", {}, [field("Dose", dose), field("Frequency", freq), field("Status", status)]),
      notes.node, field("Tags", tags),
    ], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("give it a name", true);
        const entry = await api.pulse.addMed(sec.key, {
          name: name.value.trim(), date: date.value, dose: dose.value.trim(), frequency: freq.value.trim(),
          status: status.value,
          tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        });
        await notes.commit(entry.id);
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function entryEl(sec, m, reload) {
    const box = el("div.med-entry");
    box.appendChild(el("div.spread", {}, [
      el("div", {}, [
        el("div.row", { style: "gap:8px" }, [
          el("span", { style: "font-weight:600", text: m.name }),
          m.status ? el("span.pulse-tag", { style: "background:transparent;border:1px solid " + (P.MED_STATUS_COLOR[m.status] || "var(--dim)") + ";color:" + (P.MED_STATUS_COLOR[m.status] || "var(--dim)"), text: m.status }) : null,
        ]),
        (m.dose || m.frequency) ? el("div", { style: "color:#DE7BA4;font-family:var(--mono);font-size:12px;margin-top:2px", text: [m.dose, m.frequency].filter(Boolean).join(" · ") }) : null,
      ]),
      el("div.row", { style: "gap:8px" }, [
        el("span.sub", { text: P.fmtDay((m.date || "").slice(0, 10)) }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + m.name + "”?", async () => { await api.pulse.delMed(sec.key, m.id); reload(); }), text: "×" }),
      ]),
    ]));
    box.appendChild(window.RowBox({ label: "notes", parentId: m.id }).node);
    if (m.tags && m.tags.length) box.appendChild(el("div.row", { style: "gap:5px;margin-top:5px" }, m.tags.map((t) => el("span.pulse-chip", { text: t }))));
    window.Images.mount(box, { module: "pulse", contextId: m.id, surface: "pulse-medication", title: "Images" });
    return box;
  }

  function accordion(sec, entries, reload) {
    const isOpen = open.has(sec.key);
    const head = el("div.acc-head", { onclick: () => { isOpen ? open.delete(sec.key) : open.add(sec.key); reload(); } }, [
      el("div.row", { style: "gap:8px" }, [el("span", { style: "font-size:16px", text: sec.icon }), el("span", { style: "font-weight:600", text: sec.label })]),
      el("div.row", { style: "gap:8px" }, [el("span.acc-count", { text: String(entries.length) }), el("span.acc-arrow", { text: isOpen ? "▾" : "›" })]),
    ]);
    const wrap = el("div.acc-section", {}, [head]);
    if (isOpen) {
      const body = el("div.acc-body");
      body.appendChild(el("div.sub", { style: "margin-bottom:10px", text: sec.desc }));
      entries.forEach((m) => body.appendChild(entryEl(sec, m, reload)));
      body.appendChild(el("button.btn-sm.btn-primary", { style: "margin-top:8px", onclick: () => addEntryModal(sec, reload), text: "＋ Add entry" }));
      wrap.appendChild(body);
    }
    return wrap;
  }

  window.Views = window.Views || {};
  window.Views.medications = {
    id: "medications", label: "Medications", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Medications" }), el("div.sub", { text: "Medication management — dose, schedule, adherence, side effects, and more." }),
      ])]));
      const host = el("div"); view.appendChild(host);
      async function reload() {
        const results = await guard(() => Promise.all(P.MED_SECTIONS.map((s) => api.pulse.meds(s.key))));
        clear(host);
        P.MED_SECTIONS.forEach((s, i) => host.appendChild(accordion(s, results[i], reload)));
      }
      reload();
    },
  };
})();

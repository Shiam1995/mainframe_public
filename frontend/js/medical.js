/* medical.js — Pulse: Medical. 11 config-driven accordion sections; entries with
   severity colours, notes/links/tags, and PDF/JPG/PNG upload (images inline). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const SEVERITIES = ["", "mild", "moderate", "severe", "active", "resolved", "chronic", "monitoring"];

  const open = new Set();

  function addEntryModal(sec, reload) {
    const title = el("input.mform-input", { placeholder: "e.g. Penicillin allergy" });
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const sev = el("select.mform-input", {}, SEVERITIES.map((s) => el("option", { value: s, text: s || "— none —" })));
    // + rows, held until the entry exists and then committed onto it.
    const details = window.RowBox({ label: "details", placeholder: "one detail per row" });
    const notes = window.RowBox({ label: "follow-ups", kind: "follow-up", noun: "follow-up", placeholder: "follow-up action, doctor's advice, observation" });
    const tags = el("input.mform-input", { placeholder: "tags, comma-separated" });
    const links = el("input.mform-input", { placeholder: "link to a scan/report (optional)" });
    const file = el("input", { type: "file", accept: ".pdf,.jpg,.jpeg,.png" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Add to " + sec.label, [
      el("div.mform-row", {}, [field("Title", title), field("Date", date)]),
      field("Severity / status", sev), details.node, notes.node,
      el("div.mform-row", {}, [field("Tags", tags), field("Link", links)]),
      field("Attach file (PDF/JPG/PNG)", file),
    ], [
      { label: "Add", primary: true, onClick: (close) => guard(async () => {
        if (!title.value.trim()) return toast("give it a title", true);
        const entry = await api.pulse.addMedical(sec.key, {
          title: title.value.trim(), date: date.value, severity: sev.value, links: links.value.trim(),
          tags: tags.value.split(",").map((t) => t.trim()).filter(Boolean),
        });
        await details.commit(entry.id); await notes.commit(entry.id);
        if (file.files.length) { const fd = new FormData(); fd.append("file", file.files[0]); await api.pulse.uploadMedical(sec.key, entry.id, fd); }
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function entryEl(sec, m, reload) {
    const box = el("div.med-entry");
    box.appendChild(el("div.spread", {}, [
      el("div.row", { style: "gap:8px" }, [
        el("span", { style: "font-weight:600", text: m.title }),
        m.severity ? el("span.pulse-tag", { style: "background:transparent;border:1px solid " + (P.SEVERITY_COLOR[m.severity] || "var(--dim)") + ";color:" + (P.SEVERITY_COLOR[m.severity] || "var(--dim)"), text: m.severity }) : null,
      ]),
      el("div.row", { style: "gap:8px" }, [
        el("span.sub", { text: P.fmtDay((m.date || "").slice(0, 10)) }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete “" + m.title + "”?", async () => { await api.pulse.delMedical(sec.key, m.id); reload(); }), text: "×" }),
      ]),
    ]));
    box.appendChild(window.RowBox({ label: "details", parentId: m.id }).node);
    box.appendChild(window.RowBox({ label: "follow-ups", kind: "follow-up", noun: "follow-up", parentId: m.id }).node);
    if (m.links) box.appendChild(el("div", { style: "margin-top:4px" }, [el("a", { href: m.links, target: "_blank", rel: "noopener noreferrer", style: "color:var(--blue);font-size:12px", text: m.links })]));
    if (m.tags && m.tags.length) box.appendChild(el("div.row", { style: "gap:5px;margin-top:5px" }, m.tags.map((t) => el("span.pulse-chip", { text: t }))));
    if (m.file_path) {
      const ext = (m.file_name || "").toLowerCase();
      const url = api.pulse.medicalFileUrl(sec.key, m.id);
      if (/\.(jpg|jpeg|png)$/.test(ext)) box.appendChild(el("img", { src: url, style: "max-width:240px;max-height:200px;border-radius:8px;margin-top:8px;display:block" }));
      else box.appendChild(el("div", { style: "margin-top:6px" }, [el("a.btn-sm", { href: url, style: "text-decoration:none", text: "⤓ " + (m.file_name || "file") })]));
    }
    // gallery alongside the section's own single-file upload (spec: extend it)
    window.Images.mount(box, { module: "pulse", contextId: m.id, surface: "pulse-medical", title: "Images" });
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
  window.Views.medical = {
    id: "medical", label: "Medical", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Medical" }), el("div.sub", { text: "Your medical record — expand a section to view or add entries." }),
      ])]));
      const host = el("div"); view.appendChild(host);
      async function reload() {
        const results = await guard(() => Promise.all(P.MEDICAL_SECTIONS.map((s) => api.pulse.medical(s.key))));
        clear(host);
        P.MEDICAL_SECTIONS.forEach((s, i) => host.appendChild(accordion(s, results[i], reload)));
      }
      reload();
    },
  };
})();

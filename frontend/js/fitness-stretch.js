/* fitness-stretch.js — Pulse Fitness Stretching: log sessions (stretches as + rows,
   kind "step"). Purple-bordered cards, expandable. Separate from workouts. */
(function () {
  const { el, clear, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  const open = new Set();

  function logModal(reload) {
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const dur = el("input.mform-input", { type: "number", min: "0", placeholder: "minutes" });
    const focus = el("input.mform-input", { placeholder: "e.g. Hips and hamstrings" });
    // + rows, held until the session exists and then committed onto it.
    const stretches = window.RowBox({ label: "stretches", kind: "step", noun: "stretch", placeholder: "e.g. Hamstring stretch 30s each side" });
    const notes = window.RowBox({ label: "notes", placeholder: "how it felt, improvements, tightness" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Log stretch session", [
      el("div.mform-row", {}, [field("Date", date), field("Duration", dur)]), field("Focus", focus),
      stretches.node, notes.node,
    ], [
      { label: "Log", primary: true, onClick: (close) => guard(async () => {
        const made = await api.pulse.fitness.logStretch({
          date: date.value, duration: parseInt(dur.value) || 0, focus: focus.value.trim(),
        });
        await stretches.commit(made.id); await notes.commit(made.id);
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function card(s, reload) {
    const isOpen = open.has(s.id);
    const c = el("div.pulse-card.stretch-card", {}, [
      el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(s.id) : open.add(s.id); reload(); } }, [
        el("div.row", { style: "gap:8px" }, [
          el("span.sub", { text: P.fmtDay((s.date || "").slice(0, 10)) }),
          el("span.sub", { text: (s.duration || 0) + "min" }),
          s.focus ? el("span.pulse-tag", { style: "background:var(--purple-d);color:var(--purple)", text: s.focus }) : null,
        ]),
      ]),
    ]);
    if (isOpen) {
      const body = el("div", { style: "margin-top:10px;border-top:1px solid var(--border);padding-top:10px" });
      body.appendChild(window.RowBox({ label: "stretches", kind: "step", noun: "stretch", parentId: s.id }).node);
      body.appendChild(window.RowBox({ label: "notes", parentId: s.id }).node);
      window.Images.mount(body, { module: "pulse", contextId: s.id, surface: "pulse-stretch", title: "Images" });
      body.appendChild(el("button.btn-sm.btn-danger", { style: "margin-top:8px", onclick: () => confirmDo("Delete this session?", async () => { await api.pulse.fitness.delStretch(s.id); reload(); }), text: "× delete" }));
      c.appendChild(body);
    }
    return c;
  }

  async function render(host) {
    async function reload() {
      const sessions = await guard(() => api.pulse.fitness.stretching());
      clear(host);
      host.appendChild(el("div.row", { style: "justify-content:flex-end;margin-bottom:12px" }, [
        el("button.btn-primary", { onclick: () => logModal(reload), text: "＋ log session" }),
      ]));
      if (!sessions.length) { host.appendChild(el("div.empty", { text: "No stretch sessions yet." })); return; }
      sessions.forEach((s) => host.appendChild(card(s, reload)));
    }
    reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "stretch", label: "Stretching", render });
})();

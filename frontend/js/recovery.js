/* recovery.js — Pulse: Recovery. Log meditation / breathing / forest bathing and
   other recovery practices. Types are a config list you can extend. Each session
   snapshots its type + a per-session note; loose cross-cutting thoughts still go
   in the shared Mainframe Mind Dump. Pink cards, single top-level Pulse tab. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const P = window.PULSE;

  const norm = (x) => String(x || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const FEELS = ["", "😌 Calm", "🙂 Refreshed", "😐 Neutral", "😴 Sleepy", "😣 Tense", "💪 Energised"];
  const open = new Set();

  function logModal(types, reload, presetName) {
    if (!types.length) return toast("add a recovery type first", true);
    const type = el("select.mform-input", {}, types.map((t) => el("option", { value: t.id, text: (t.icon || "✨") + " " + t.name })));
    const preset = presetName && types.find((t) => norm(t.name) === norm(presetName));
    if (preset) type.value = preset.id;
    const date = el("input.mform-input", { type: "date", value: P.today() });
    const dur = el("input.mform-input", { type: "number", min: "0", placeholder: "minutes" });
    const feel = el("select.mform-input", {}, FEELS.map((f) => el("option", { value: f, text: f || "— how did it feel —" })));
    // + rows, held until the session exists and then committed onto it.
    const notes = window.RowBox({ label: "notes", placeholder: "what you did, how it felt, where…" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    P.modal("Log recovery session", [
      field("Type", type),
      el("div.mform-row-3", {}, [field("Date", date), field("Minutes", dur), field("Feel", feel)]),
      notes.node,
    ], [
      { label: "Log", primary: true, onClick: (close) => guard(async () => {
        const made = await api.pulse.recovery.logSession({
          type_id: type.value, date: date.value, duration: parseInt(dur.value) || 0,
          feel: feel.value,
        });
        await notes.commit(made.id);
        close(); reload();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function typesModal(types, reload) {
    const host = el("div");
    const name = el("input.mform-input", { placeholder: "e.g. Sound bath" });
    const icon = el("input.mform-input", { placeholder: "emoji", maxLength: "3", style: "width:70px;text-align:center" });
    function paint() {
      clear(host);
      types.forEach((t) => host.appendChild(el("div.spread", { style: "padding:6px 0;border-bottom:1px solid var(--border)" }, [
        el("span", { text: (t.icon || "✨") + "  " + t.name + (t.custom ? "" : "  ·  default") }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Remove “" + t.name + "”? Past sessions are kept.", async () => { await api.pulse.recovery.delType(t.id); await refresh(); }), text: "×" }),
      ])));
    }
    async function refresh() { types = await api.pulse.recovery.types(); paint(); reload(); }
    paint();
    P.modal("Recovery types", [
      host,
      el("div.mform-label", { style: "margin-top:12px", text: "Add a type" }),
      el("div.row", { style: "gap:8px" }, [icon, name]),
    ], [
      { label: "Add", primary: true, onClick: () => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        await api.pulse.recovery.addType({ name: name.value.trim(), icon: icon.value.trim() });
        name.value = ""; icon.value = ""; await refresh();
      }) },
      { label: "Done", onClick: (close) => close() },
    ]);
  }

  function statCard(stats) {
    const cell = (label, value) => el("div", { style: "text-align:center" }, [
      el("div", { style: "font-size:24px;font-weight:700;color:var(--accent)", text: String(value) }),
      el("div.sub", { text: label }),
    ]);
    const card = el("div.pulse-card", {}, [
      el("div.row", { style: "justify-content:space-around;gap:16px" }, [
        cell("sessions this week", stats.week_sessions),
        cell("minutes this week", stats.week_minutes),
        cell("day streak", stats.streak),
        cell("sessions all-time", stats.total_sessions),
      ]),
    ]);
    if (stats.by_type && stats.by_type.length) {
      card.appendChild(el("div.row", { style: "gap:6px;flex-wrap:wrap;margin-top:12px;border-top:1px solid var(--border);padding-top:10px" },
        stats.by_type.map((b) => el("span.pulse-tag", { text: (b.icon || "✨") + " " + b.type + " · " + b.count + "×" + (b.minutes ? " · " + b.minutes + "m" : "") }))));
    }
    return card;
  }

  /* ---- protocol ---------------------------------------------------------
     A versioned bundle of recovery habits with a reason. Day states come
     from the server (derived from sessions + ticks + exceptions); clicking a
     day square cycles your manual mark: none → done → exception → none. */
  const RULE_TEXT = (h) => h.rule === "sessions"
    ? "daily · derived from sessions of type " + h.rule_types.join(", ")
    : "daily · tick";
  const uniqTypeNames = (types) => [...new Map(types.map((t) => [norm(t.name), t])).values()];

  function protocolHabitModal(types, existing, reload) {
    const R = api.pulse.recovery;
    const name = el("input.mform-input", { value: existing ? existing.name : "", placeholder: "e.g. 10 min breathing" });
    const icon = el("input.mform-input", { value: existing ? existing.icon : "", placeholder: "emoji", maxLength: "3", style: "width:70px;text-align:center" });
    const rule = el("select.mform-input", {}, [
      el("option", { value: "sessions", text: "derived from recovery sessions" }),
      el("option", { value: "tick", text: "tick by hand" }),
    ]);
    rule.value = existing ? existing.rule : "sessions";
    const chosen = new Set((existing ? existing.rule_types : []).map(norm));
    const boxes = uniqTypeNames(types).map((t) => {
      const b = el("input", { type: "checkbox" }); b.checked = chosen.has(norm(t.name)); b.dataset.name = t.name;
      return el("label.wl-check", {}, [b, el("span", { text: " " + (t.icon || "✨") + " " + t.name })]);
    });
    const typeWrap = el("div.row", { style: "gap:10px;flex-wrap:wrap" }, boxes);
    const typeField = el("div.mform-full", {}, [el("div.mform-label", { text: "Sessions that count" }), typeWrap]);
    const syncRule = () => { typeField.style.display = rule.value === "sessions" ? "" : "none"; };
    rule.addEventListener("change", syncRule); syncRule();
    const tier = el("select.mform-input", {}, ["main", "experimental"].map((t) => el("option", { value: t, text: t })));
    tier.value = existing ? existing.tier : "main";
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    const actions = [
      { label: existing ? "Save" : "Add", primary: true, onClick: (close) => guard(async () => {
        if (!name.value.trim()) return toast("name it", true);
        const rule_types = boxes.map((l) => l.querySelector("input")).filter((b) => b.checked).map((b) => b.dataset.name);
        if (rule.value === "sessions" && !rule_types.length) return toast("tick at least one session type", true);
        const body = { name: name.value.trim(), icon: icon.value.trim(), rule: rule.value, rule_types, tier: tier.value };
        if (existing) await R.updateProtocolHabit(existing.id, body); else await R.addProtocolHabit(body);
        close(); reload();
      }) },
    ];
    if (existing) actions.push({ label: "Remove from protocol", onClick: (close) => confirmDo(
      "Take “" + existing.name + "” out of the protocol? It stays in Habits.", async () => {
        await R.removeProtocolHabit(existing.id); close(); reload();
      }) });
    actions.push({ label: "Cancel", onClick: (close) => close() });
    P.modal(existing ? "Edit protocol habit" : "Add habit to protocol", [
      el("div.row", { style: "gap:8px" }, [icon, name]),
      el("div.mform-row", {}, [field("Counts when", rule), field("Tier", tier)]),
      typeField,
    ], actions);
  }

  function textModal(title, label, value, okLabel, onOk, extra) {
    const why = el("input.mform-input", { value: value || "" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);
    const ex = extra ? el("input.mform-input", { placeholder: extra.placeholder }) : null;
    P.modal(title, [ex ? field(extra.label, ex) : null, field(label, why)].filter(Boolean), [
      { label: okLabel, primary: true, onClick: (close) => guard(async () => {
        await onOk(why.value.trim(), ex ? ex.value.trim() : ""); close();
      }) },
      { label: "Cancel", onClick: (close) => close() },
    ]);
  }

  function protocolCard(data, types, reload) {
    const R = api.pulse.recovery;
    const cur = data.current;
    if (!cur) {
      return el("section.rp-proto", {}, [
        el("h2", { text: "Recovery protocol" }),
        el("div.rp-why", { text: "A small set of recovery habits you commit to, with the reason written down. Habits can count automatically from the sessions you log, or be ticked by hand." }),
        el("button.btn-primary", { style: "margin-top:10px", text: "start a protocol",
          onclick: () => textModal("Start a recovery protocol", "Why this protocol?", "", "Start",
            async (why) => { await R.startProtocol({ why }); reload(); }) }),
      ]);
    }
    const today = P.today();
    const stat = (v, l) => el("div.rp-stat", {}, [el("div.v", { text: v }), el("div.l", { text: l })]);
    const card = el("section.rp-proto", {}, [
      el("div.rp-hd", {}, [
        el("div", {}, [
          el("div.spread", {}, [
            el("h2", { text: "Recovery protocol · v" + cur.version }),
            el("span.meta", { text: "since " + P.fmtDay(cur.started) + " · " + (cur.weeks_in ? cur.weeks_in + " week" + (cur.weeks_in > 1 ? "s" : "") + " in" : "first week") }),
          ]),
          el("div.rp-why", { text: cur.why || "No reason written yet." }),
        ]),
        el("div.rp-stats", {}, [
          stat(cur.adherence == null ? "—" : cur.adherence + "%", "adherence"),
          stat(String(cur.habits.length), "habits"),
        ]),
      ]),
    ]);
    if (!cur.habits.length) card.appendChild(el("div.sub", { style: "margin:4px 0 8px", text: "No habits in this protocol yet." }));
    const NEXT = { done: "exception", exception: "clear" };
    cur.habits.forEach((h) => {
      const dots = el("div.rp-dots", {}, h.week.map((d) => {
        const sq = el("i.s-" + d.state + (d.date === today ? ".today" : ""), {
          title: P.fmtDay(d.date) + " · " + d.state + (d.state === "future" || d.state === "before" ? "" : " — click to change") });
        if (d.state !== "future" && d.state !== "before") {
          sq.addEventListener("click", () => guard(async () => {
            await R.markProtocolDay(h.id, { date: d.date, state: NEXT[d.state] || "done" }); reload();
          }));
        }
        return sq;
      }));
      const doneToday = h.week.some((d) => d.date === today && d.state === "done");
      const sessType = h.rule === "sessions" ? h.rule_types[0] : null;
      card.appendChild(el("div.rp-hab", {}, [
        el("span", { text: h.icon || "🌿" }),
        el("div.nm", {}, [el("span", { text: h.name }), el("span.meta", { text: RULE_TEXT(h) })]),
        dots,
        el("span.rp-tier." + (h.tier === "experimental" ? "exp" : "main"), { text: h.tier }),
        el("span.rp-rate", { text: h.done + " of " + h.due + (h.exceptions ? " · " + h.exceptions + " exception" + (h.exceptions > 1 ? "s" : "") : "") }),
        el("span.rp-acts", {}, [
          doneToday ? null : el("button.btn-sm", { text: "log now", onclick: () => sessType
            ? logModal(types, reload, sessType)
            : guard(async () => { await R.markProtocolDay(h.id, { date: today, state: "done" }); reload(); }) }),
          el("button.btn-sm", { text: "exception", title: "excuse today",
            onclick: () => guard(async () => { await R.markProtocolDay(h.id, { date: today, state: "exception" }); reload(); }) }),
          h.tier === "experimental" ? el("button.btn-sm", { text: "promote",
            onclick: () => guard(async () => { await R.updateProtocolHabit(h.id, { tier: "main" }); reload(); }) }) : null,
          el("button.btn-sm", { text: "✎", onclick: () => protocolHabitModal(types, h, reload) }),
        ]),
      ]));
    });
    const hist = data.history.filter((v) => v.ended);
    card.appendChild(el("div.rp-foot", {}, [
      el("div.row", {}, [
        el("button.btn-sm", { text: "+ habit to protocol", onclick: () => protocolHabitModal(types, null, reload) }),
        el("button.btn-sm", { text: "✎ why", onclick: () => textModal("Why this protocol", "Why", cur.why, "Save",
          async (why) => { await R.updateProtocol({ why }); reload(); }) }),
        el("button.btn-sm", { text: "revise protocol", title: "close this version and start the next with the same habits",
          onclick: () => textModal("Revise protocol → v" + (cur.version + 1), "Why the new version?", cur.why, "Revise",
            async (why, reason) => { await R.reviseProtocol({ why, end_reason: reason }); reload(); },
            { label: "What happened to v" + cur.version + "?", placeholder: "e.g. meditation only, dropped: never happened" }) }),
      ]),
      el("span.rp-ver", {}, hist.map((v) => el("span", {
        title: v.why || "", text: "v" + v.version + " · " + P.fmtDay(v.started) + (v.end_reason ? ", " + v.end_reason : "") + " · " })).concat(
        [el("span", { style: "color:var(--cyan,#4AC6E0)", text: "v" + cur.version + " · " + P.fmtDay(cur.started) })])),
    ]));
    return card;
  }

  // session type name → protocol habit it counts toward (for the session pill)
  function protocolIndex(data) {
    const m = new Map();
    ((data.current && data.current.habits) || []).forEach((h) => {
      if (h.rule === "sessions") h.rule_types.forEach((t) => { if (!m.has(norm(t))) m.set(norm(t), h); });
    });
    return m;
  }

  function sessionCard(s, reload, pIndex) {
    const isOpen = open.has(s.id);
    const c = el("div.pulse-card", {}, [
      el("div.spread", { style: "cursor:pointer", onclick: () => { isOpen ? open.delete(s.id) : open.add(s.id); reload(); } }, [
        el("div.row", { style: "gap:8px" }, [
          el("span", { style: "font-size:18px", text: s.type_icon || "✨" }),
          el("span", { style: "font-weight:600", text: s.type_name || "Recovery" }),
          el("span.sub", { text: P.fmtDay((s.date || "").slice(0, 10)) }),
        ]),
        el("div.row", { style: "gap:6px" }, [
          pIndex && pIndex.has(norm(s.type_name)) ? el("span.pulse-tag.rp-pill", { text: "protocol · " + pIndex.get(norm(s.type_name)).name }) : null,
          s.duration ? el("span.pulse-tag", { text: s.duration + " min" }) : null,
          s.feel ? el("span.pulse-tag", { text: s.feel }) : null,
        ]),
      ]),
    ]);
    if (isOpen) {
      const body = el("div", { style: "margin-top:10px;border-top:1px solid var(--border);padding-top:10px" });
      body.appendChild(window.RowBox({ label: "notes", parentId: s.id }).node);
      window.Images.mount(body, { module: "pulse", contextId: s.id, surface: "pulse-recovery", title: "Images" });
      body.appendChild(el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete this session?", async () => { await api.pulse.recovery.delSession(s.id); reload(); }), text: "× delete" }));
      c.appendChild(body);
    }
    return c;
  }

  window.Views = window.Views || {};
  window.Views.recovery = {
    id: "recovery", label: "Recovery", scoped: false,
    async render(view) {
      clear(view);
      let types = [];
      view.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Recovery" }),
          el("div.sub", { text: "Meditation, breathing, forest bathing and more. Loose thoughts → the shared Mind Dump." }),
        ]),
        el("div.row", { style: "gap:8px" }, [
          el("button.btn-sm", { onclick: () => typesModal(types, reload), text: "⚙ types" }),
          el("button.btn-primary", { onclick: () => logModal(types, reload), text: "＋ log session" }),
        ]),
      ]));
      const protoHost = el("div"); view.appendChild(protoHost);
      const statHost = el("div"); view.appendChild(statHost);
      const listHost = el("div"); view.appendChild(listHost);
      async function reload() {
        const [t, stats, sessions, proto] = await guard(() => Promise.all([
          api.pulse.recovery.types(), api.pulse.recovery.stats(), api.pulse.recovery.sessions(),
          api.pulse.recovery.protocol(),
        ]));
        types = t;
        const pIndex = protocolIndex(proto);
        clear(protoHost); protoHost.appendChild(protocolCard(proto, types, reload));
        clear(statHost); statHost.appendChild(statCard(stats));
        clear(listHost);
        listHost.appendChild(el("div.mform-label", { style: "margin:16px 0 8px", text: "Recent sessions" + (pIndex.size ? " · sessions that count toward a protocol habit are marked" : "") }));
        if (!sessions.length) { listHost.appendChild(el("div.empty", { text: "No recovery sessions yet. Log one above." })); return; }
        sessions.forEach((s) => listHost.appendChild(sessionCard(s, reload, pIndex)));
      }
      reload();
    },
  };
})();

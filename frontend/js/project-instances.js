/* project-instances.js — the passes you've taken at a project, and the hours
   inside them.

   This started as a flat list of :WorkSession rows: a date, a duration, what
   you did. That's the right record and the wrong shape — forty rows against
   one project tell you how long it took and nothing about what you were
   trying to do at the time.

   So the Repository's reading instances apply here unchanged. A paper gets a
   pass each time you sit down with it (v1 "first read", v2 "implement"); a
   project gets one each time you take a run at it (v1 "scaffold", v2 "vault
   module"), with the same three things written up front:

     purpose     what this run is for
     look into   what you already know you want to come back to
     the link    the referenced id — the paper, decomposition node, idea or
                 other project this run is being worked against

   Sessions are then logged INTO a pass. A session is still a :WorkSession —
   the same node the Database tab, the contribution grid and the totals read —
   it just carries a `pass_id` now. Deleting a pass never deletes its hours;
   they go back to being unfiled, because the time happened either way. */
(function () {
  const { el, clear, toast, guard, confirmDo, stampPair, todayISO, sizedArea } = window.ui;
  const api = window.api;

  const FOCUS = [
    { v: "active", t: "active", c: "var(--green)" },
    { v: "passive", t: "passive", c: "var(--blue)" },
    { v: "none", t: "—", c: "var(--dim)" },
  ];

  const P = () => window.ProjectPicker;
  const open = new Set();          // expanded session ids, kept across reloads

  /* Which pass you're looking at, per project — switching projects and coming
     back shouldn't dump you on v1. "" means the whole project: every session,
     filed or not. */
  const PASS_KEY = "project.pass";
  let passSel = (() => {
    try { return JSON.parse(localStorage.getItem(PASS_KEY) || "{}"); } catch { return {}; }
  })();
  function activePass(projectId) { return passSel[projectId] || ""; }
  function setActivePass(projectId, id) {
    passSel[projectId] = id || "";
    try { localStorage.setItem(PASS_KEY, JSON.stringify(passSel)); } catch { /* ignore */ }
  }
  // Folding the pass panel away — the boxes are for writing, and you don't
  // want them between you and the sessions while you're reading them back.
  const OPEN_KEY = "project.passOpen";
  const panelOpen = () => localStorage.getItem(OPEN_KEY) !== "0";
  const setPanelOpen = (v) => localStorage.setItem(OPEN_KEY, v ? "1" : "0");

  const hhmmToMins = (s) => {
    const m = /^(\d{1,2}):(\d{2})$/.exec((s || "").trim());
    return m ? (+m[1]) * 60 + (+m[2]) : null;
  };

  /* Minutes from a start/end pair, so you can log "14:05 → 15:20" and not do
     the arithmetic. Crossing midnight counts as the next day, not as -1385. */
  function minsFrom(start, end) {
    const a = hhmmToMins(start), b = hhmmToMins(end);
    if (a == null || b == null) return null;
    return b >= a ? b - a : (24 * 60 - a) + b;
  }

  function fmtMins(m) {
    m = Math.max(0, Math.round(m || 0));
    const h = Math.floor(m / 60);
    return h ? h + "h " + (m % 60) + "m" : m + "m";
  }

  /* ------------------------------------------------------------------ *
   * One session, expandable into a full editor
   * ------------------------------------------------------------------ */
  function sessionRow(s, ctx, reload) {
    const isOpen = open.has(s.id);
    const focus = FOCUS.find((f) => f.v === (s.focus || "none")) || FOCUS[2];
    const pass = ctx.passes.find((p) => p.id === s.pass_id);

    const head = el("div.pin-head", {
      onclick: () => { isOpen ? open.delete(s.id) : open.add(s.id); reload(); },
    }, [
      el("span.pin-caret", { text: isOpen ? "▾" : "▸" }),
      el("span.pin-date", { text: s.date || "—" }),
      el("span.pin-time", {
        text: s.start && s.end ? s.start + "–" + s.end : (s.start || ""),
      }),
      el("span.pin-mins", { text: s.mins ? fmtMins(s.mins) : "—" }),
      el("span.pin-what", { text: s.what || "(no description)" }),
      // Which pass this hour is filed under. Only worth the space when you're
      // looking at more than one pass at a time.
      ctx.showAll
        ? el("span.pin-pass", { title: pass ? "filed under v" + pass.version : "not filed under any pass",
                                text: pass ? "v" + pass.version : "unfiled" })
        : null,
      el("span.pin-focus", { style: "color:" + focus.c, text: focus.t }),
      s.completed || s.pushed ? el("span.pin-push", { text: "★ pushed" }) : null,
    ]);

    const card = el("div.pin-row", { "data-eid": s.id }, [head]);
    if (!isOpen) return card;

    /* --- the editor --- */
    const dateIn = el("input", { type: "date", value: s.date || "" });
    const startIn = el("input", { type: "time", value: s.start || "" });
    const endIn = el("input", { type: "time", value: s.end || "" });
    const minsIn = el("input", { type: "number", min: "0", step: "1",
                                 value: String(s.mins || 0), style: "width:80px" });
    // Both of these are written in, not filled in: a session's account of itself
    // runs to paragraphs as often as to a line. So they carry the S/M/L/XL bar
    // and remember the size per field, the same as the paper session log — and
    // under the same keys as the push form, so one choice covers both.
    const whatIn = el("textarea", { placeholder: "what I did", style: "width:100%" });
    whatIn.value = s.what || "";
    const notesIn = el("textarea", { placeholder: "notes", style: "width:100%" });
    notesIn.value = s.notes || "";
    const focusSel = el("select", {}, FOCUS.map((f) =>
      el("option", { value: f.v, text: f.t })));
    focusSel.value = s.focus || "none";
    const doneBox = el("input", { type: "checkbox" });
    doneBox.checked = !!(s.completed || s.pushed);
    // Re-file an hour under a different run — you often only work out which
    // pass a session belonged to after it's over.
    const passSelect = el("select", {}, [
      el("option", { value: "", text: "— unfiled —" }),
      ...ctx.passes.map((p) => el("option", { value: p.id, text: "v" + p.version + " · " + p.purpose })),
    ]);
    passSelect.value = s.pass_id || "";

    // Typing an end time fills in the duration; typing a duration by hand still
    // wins, because sometimes you know it was 40 minutes and not when.
    const syncMins = () => {
      const m = minsFrom(startIn.value, endIn.value);
      if (m != null) minsIn.value = String(m);
    };
    startIn.addEventListener("change", syncMins);
    endIn.addEventListener("change", syncMins);

    const save = el("button.btn-primary.btn-sm", { text: "save", onclick: () => guard(async () => {
      await api.work.update(s.id, {
        date: dateIn.value || null,
        start: startIn.value,
        end: endIn.value,
        mins: parseInt(minsIn.value, 10) || 0,
        what: whatIn.value,
        notes: notesIn.value,
        focus: focusSel.value,
        completed: doneBox.checked,
        pass_id: passSelect.value,
      });
      toast("session saved");
      reload();
    }) });

    const del = el("button.pi-x", { text: "delete" });
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) {
        armed = true; del.textContent = "click again"; del.classList.add("armed");
        setTimeout(() => { armed = false; del.textContent = "delete"; del.classList.remove("armed"); }, 3000);
        return;
      }
      guard(async () => {
        await api.work.del(s.id);
        open.delete(s.id);
        toast("deleted");
        reload();
      });
    });

    const field = (label, node) =>
      el("label.pin-field", {}, [el("span.sub", { text: label }), node]);

    card.appendChild(el("div.pin-body", {}, [
      el("div.row", { style: "flex-wrap:wrap;gap:10px;align-items:flex-end" }, [
        field("date", dateIn),
        field("start", startIn),
        field("end", endIn),
        // The stopwatch button the rest of the app uses: press to start, again
        // to stop. Same control, so it behaves the way you already expect.
        el("div", { style: "padding-bottom:2px" }, [stampPair(startIn, endIn, { onChange: syncMins })]),
        field("minutes", minsIn),
        field("focus", focusSel),
        ctx.passes.length ? field("instance", passSelect) : null,
        el("label.pin-field", {}, [
          el("span.sub", { text: "pushed" }),
          el("div", { style: "padding-top:6px" }, [doneBox]),
        ]),
      ]),
      sizedArea(whatIn, "proj.did", { label: "what I did" }),
      sizedArea(notesIn, "proj.notes", { label: "notes" }),
      el("div.row", { style: "margin-top:9px;justify-content:flex-end;gap:6px" }, [del, save]),
    ]));
    return card;
  }

  /* ------------------------------------------------------------------ *
   * New instance — a pass starts with intent, written before it starts
   * rather than remembered afterwards.
   * ------------------------------------------------------------------ */
  function newPassModal(projectId, nextVersion, onDone) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const purpose = el("input.mform-input", {
      value: nextVersion === 1 ? "first pass" : "",
      placeholder: "e.g. scaffold, vault module, make the voice layer work",
    });
    // No pass yet, so the rows are held and posted once create returns its id.
    const look = window.RowBox({ label: "to look into later", kind: "look into", noun: "thing to look into",
      placeholder: "a shortcut you're taking, a test you're skipping, a decision you're deferring" });
    const ref = window.RefPicker.editor(null, () => {}, { label: "worked against" });

    const fld = (label, node) => el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);

    const create = () => guard(async () => {
      const body = { purpose: purpose.value.trim() || "pass " + nextVersion };
      const r = ref.get();
      if (r.link_kind && r.link_id) { body.link_kind = r.link_kind; body.link_id = r.link_id; }
      const made = await api.projects.passes.create(projectId, body);
      await look.commit(made.id);
      setActivePass(projectId, made.id);
      setPanelOpen(true);
      toast("created v" + made.version);
      close();
      onDone();
    });

    const card = el("div.modal", {}, [
      el("div.modal-title", { text: "New instance" }),
      el("div.sub", { style: "margin:-8px 0 14px;line-height:1.45",
        text: "One run at this project. The hours you log from here go into it, "
            + "so the time groups by what you were trying to do." }),
      fld("Purpose", purpose),
      look.node,
      fld("References", ref.node),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "Create instance", onclick: create }),
        el("button.tk-btn", { text: "Cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    purpose.focus(); purpose.select();
    overlay.addEventListener("keydown", (e) => {
      // app.js sends Escape home unless a modal is on screen — it would already
      // be gone by the time the event bubbled that far, so stop it here.
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") create();
    });
  }

  /* ------------------------------------------------------------------ *
   * The chips: one per pass, plus "everything"
   * ------------------------------------------------------------------ */
  // A pass's "to look into later" rows, as the list endpoint carries them.
  const lookRows = (p) => ((p.row_text || {})["look into"]) || [];

  function passChips(projectId, passes, current, reload) {
    const chips = el("div.row", { style: "flex-wrap:wrap;gap:6px;align-items:stretch" });

    const move = (idx, dir) => guard(async () => {
      const a = passes[idx], b = passes[idx + dir];
      if (!a || !b) return;
      // reorder() gives the listed ids the slots those same nodes already hold,
      // in the order listed — so the pair must be passed in the order you want
      // them to end up. Moving `a` earlier means a first; later means b first.
      await api.projects.passes.reorder(projectId, dir < 0 ? [a.id, b.id] : [b.id, a.id]);
      reload();
    });

    chips.appendChild(el("button.btn-sm" + (current ? "" : ".btn-primary"), {
      title: "every session on this project, filed or not",
      onclick: () => { setActivePass(projectId, ""); reload(); },
      text: "everything",
    }));

    passes.forEach((p, idx) => {
      const on = p.id === current;
      chips.appendChild(el("div.row", { style: "gap:0;align-items:stretch" }, [
        el("button.btn-sm.ins-move", { title: "move earlier", disabled: idx === 0,
          onclick: (e) => { e.stopPropagation(); move(idx, -1); }, text: "◀" }),
        el("button.btn-sm" + (on ? ".btn-primary" : ""), {
          onclick: () => {
            // Clicking the pass you're already on folds its boxes away.
            if (on) setPanelOpen(!panelOpen());
            else { setActivePass(projectId, p.id); setPanelOpen(true); }
            reload();
          },
          title: on
            ? (panelOpen() ? "hide this instance's boxes" : "show this instance's boxes")
            : (lookRows(p).length ? "look into: " + lookRows(p).join(" · ") : "open this instance"),
          text: "v" + p.version + " · " + p.purpose + (lookRows(p).length ? " ⌛" : "")
              + (on ? (panelOpen() ? "  ▾" : "  ▸") : ""),
        }),
        el("button.btn-sm.ins-move", { title: "move later", disabled: idx === passes.length - 1,
          onclick: (e) => { e.stopPropagation(); move(idx, 1); }, text: "▶" }),
        el("button.btn-sm.btn-danger.ins-del", {
          title: "delete instance v" + p.version + " — its sessions are kept, unfiled",
          onclick: (e) => {
            e.stopPropagation();
            confirmDo("Delete instance v" + p.version + " (" + p.purpose + ")?\n\n"
              + "Its " + p.session_count + " session" + (p.session_count === 1 ? "" : "s")
              + " stay in the database and go back to being unfiled — "
              + "the hours happened either way.",
              async () => {
                await api.projects.passes.del(projectId, p.id);
                if (activePass(projectId) === p.id) setActivePass(projectId, "");
                toast("v" + p.version + " deleted");
                reload();
              });
          },
          text: "×",
        }),
      ]));
    });

    const next = passes.length + 1;
    chips.appendChild(el("button.btn-sm.btn-primary", {
      onclick: () => newPassModal(projectId, next, reload),
      title: "start a new run at this project",
      text: "+ new instance",
    }));
    return chips;
  }

  /* ------------------------------------------------------------------ *
   * The open pass: everything written about this run, editable
   * ------------------------------------------------------------------ */
  function passPanel(projectId, p, reload) {
    const purpose = el("input.mform-input", { value: p.purpose || "" });
    const look = window.RowBox({ label: "to look into later", kind: "look into", noun: "thing to look into",
      parentId: p.id, placeholder: "what to come back to" });
    const notes = el("textarea.mform-input", { placeholder: "how this run went — filled in as you go" });
    notes.value = p.notes || "";

    // Saves the moment it changes: a reference is one click, and asking you to
    // press save afterwards is how it ends up not set.
    const ref = window.RefPicker.editor(p, (patch) => guard(async () => {
      await api.projects.passes.update(projectId, p.id, patch);
      toast(patch.link_id ? "reference set" : "reference cleared");
      reload();
    }), { label: "worked against" });

    const save = el("button.btn-sm.btn-primary", { text: "save instance", onclick: () => guard(async () => {
      await api.projects.passes.update(projectId, p.id, {
        purpose: purpose.value.trim() || p.purpose,
        notes: notes.value,
      });
      toast("v" + p.version + " saved");
      reload();
    }) });

    /* --- links registered on this run --- */
    const linkList = el("div", { style: "margin-top:4px" });
    (p.links || []).forEach((f) => {
      const target = f.url || f.path || "";
      linkList.appendChild(el("div.proj-file", {}, [
        el("span", {}, [
          document.createTextNode("🔗 " + f.name + "  "),
          f.url
            ? el("a", { href: f.url, target: "_blank", rel: "noopener noreferrer",
                        style: "color:var(--blue)", text: target })
            : el("span.mono", { style: "font-size:11px;color:var(--dim)", text: target }),
        ]),
        f.note ? el("span.sub", { text: f.note }) : el("span"),
        el("span"),
        el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
          await api.projects.passes.delLink(projectId, p.id, f.id);
          reload();
        }), text: "×" }),
      ]));
    });
    if (!(p.links || []).length) {
      linkList.appendChild(el("div.sub", { text: "No links on this instance yet." }));
    }

    const lname = el("input", { placeholder: "name", style: "width:120px" });
    const ltarget = el("input", { placeholder: "url or /path/to/file", style: "flex:1;min-width:160px" });
    const lnote = el("input", { placeholder: "note", style: "width:120px" });
    const addLink = () => guard(async () => {
      if (!lname.value.trim() || !ltarget.value.trim()) return toast("name + url/path needed", true);
      const isUrl = /^https?:\/\//i.test(ltarget.value.trim());
      await api.projects.passes.addLink(projectId, p.id, {
        name: lname.value.trim(),
        url: isUrl ? ltarget.value.trim() : null,
        path: isUrl ? null : ltarget.value.trim(),
        note: lnote.value.trim(),
      });
      lname.value = ltarget.value = lnote.value = "";
      reload();
    });

    const fld = (label, node) => el("div.mform-full", {}, [el("div.mform-label", { text: label }), node]);

    return el("div.card.pin-pass", {}, [
      el("div.spread", {}, [
        el("h3", { style: "margin:0", text: "v" + p.version + " · " + p.purpose }),
        el("span.sub", { text: fmtMins(p.mins) + " · " + p.session_count
          + " session" + (p.session_count === 1 ? "" : "s")
          + (p.push_count ? " · ★ " + p.push_count : "")
          + (p.created_at ? " · started " + p.created_at.slice(0, 10) : "") }),
      ]),
      el("div.mform-row", {}, [fld("Purpose", purpose), fld("References", ref.node)]),
      look.node,
      fld("Notes", sizedArea(notes, "projectPassNotes")),
      el("div.mform-label", { style: "margin-top:10px", text: "Links" }),
      linkList,
      el("div.row", { style: "margin-top:6px" }, [
        lname, ltarget, lnote,
        el("button.btn-sm", { onclick: addLink, text: "+ link" }),
      ]),
      el("div.row", { style: "margin-top:12px;justify-content:flex-end" }, [save]),
    ]);
  }

  /* ------------------------------------------------------------------ *
   * The view
   * ------------------------------------------------------------------ */
  async function render(host) {
    clear(host);
    const projects = await P().load(true);   // totals change as you edit here
    const reload = () => render(host);
    P().mount(host, reload);
    if (!projects.length) return;
    const projectId = P().id;
    const project = projects.find((p) => p.id === projectId) || {};

    const passes = await guard(() => api.projects.passes.list(projectId)) || [];
    let current = activePass(projectId);
    if (current && !passes.some((p) => p.id === current)) current = "";   // deleted elsewhere
    const openPass = passes.find((p) => p.id === current) || null;

    host.appendChild(el("div.pin-passbar", {}, [
      passChips(projectId, passes, current, reload),
    ]));
    if (openPass && panelOpen()) host.appendChild(passPanel(projectId, openPass, reload));
    else if (openPass) {
      host.appendChild(el("div.sub", { style: "margin:8px 0",
        text: "v" + openPass.version + "'s boxes hidden — click it again to show them." }));
    }

    /* --- the sessions themselves --- */
    const addBtn = el("button.btn-primary", { text: "+ session", onclick: () => guard(async () => {
      const created = await api.work.create({
        date: todayISO(), module: "mainframe", ref_kind: "project",
        ref_id: projectId, ref_title: project.name || "", what: "", focus: "none",
        // A session added while a pass is open belongs to it. Added from
        // "everything", it's unfiled until you say otherwise.
        pass_id: current,
      });
      // Open the new one straight away — you added it to fill it in.
      if (created && created.id) open.add(created.id);
      reload();
    }) });

    // Time this project as you build it — stopping writes a session here, into
    // the pass that was open when you started the clock.
    const timerBtn = window.Timers
      ? window.Timers.button({ kind: "project", ref_id: projectId,
                               label: project.name || "project", module: "mainframe",
                               pass_id: current },
                             "⏱ start timer")
      : null;
    host.appendChild(el("div.row", { style: "margin:14px 0 12px;gap:6px;align-items:center" },
                        [addBtn, timerBtn,
                         el("span.sub", { text: openPass
                           ? "new sessions go into v" + openPass.version
                           : "new sessions start unfiled" })]));

    const all = (project.sessions || []).slice().sort((a, b) =>
      String(b.date || "").localeCompare(String(a.date || "")) ||
      String(b.start || "").localeCompare(String(a.start || "")));
    const sessions = current ? all.filter((s) => s.pass_id === current) : all;
    const ctx = { passes, showAll: !current };

    // The same totals the Overview header shows, repeated here because this is
    // the screen where you'd notice one of them is wrong.
    const total = sessions.reduce((n, s) => n + (s.mins || 0), 0);
    const days = new Set(sessions.map((s) => s.date).filter(Boolean)).size;
    const unfiled = all.filter((s) => !s.pass_id).length;
    host.appendChild(el("div.pin-totals", {}, [
      el("span", { text: fmtMins(total) + " total" }),
      el("span", { text: sessions.length + " session" + (sessions.length === 1 ? "" : "s") }),
      el("span", { text: days + " day" + (days === 1 ? "" : "s") }),
      el("span", { text: (sessions.filter((s) => s.completed || s.pushed).length) + " pushed" }),
      current ? null : el("span", { text: passes.length + " instance" + (passes.length === 1 ? "" : "s") }),
      // Only worth saying when there is something to file and somewhere to
      // file it — otherwise it reads as a complaint about nothing.
      (!current && unfiled && passes.length)
        ? el("span", { style: "color:var(--amber)", text: unfiled + " unfiled" })
        : null,
    ]));

    if (!sessions.length) {
      host.appendChild(el("div.empty", {
        text: openPass
          ? "Nothing logged against v" + openPass.version + " yet. Press “+ session”, "
            + "or start the timer and it lands here when you stop."
          : "No sessions logged for this project yet. Press “+ session”, then set the time you actually did it.",
      }));
      return;
    }
    sessions.forEach((s) => host.appendChild(sessionRow(s, ctx, reload)));
  }

  window.PROJ_TABS = window.PROJ_TABS || [];
  // Instances sit first — before the idea views — because a project is mostly
  // the record of the runs you took at it and the hours inside them.
  window.PROJ_TABS.unshift({ key: "instances", label: "Instances", render });
})();

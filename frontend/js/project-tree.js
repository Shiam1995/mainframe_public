/* project-tree.js — the Project tab. Two levels, hash routed.

     #project        the list: a table you edit in place, cards underneath
     #project/<id>   one project: its tree, then estimate / why / ideas /
                     sessions

   WHY TWO LEVELS RATHER THAN ONE TREE. The list answers "what am I doing and
   in what order", which is a question about all projects at once. The page
   answers "what is left in this one", which is a question about a subtree.
   Putting both on one screen made the top of it unreadable as soon as the tree
   had any depth.

   ROLL-UPS COME FROM THE SERVER. Estimate, logged hours and done-counts all
   depend on a whole subtree; see routes/inbox.py. Nothing here adds up
   numbers, it only prints them.

   The one arithmetic rule visible in the UI: a typed estimate on a project
   with children is an OVERRIDE, and overriding asks for a why, because a guess
   and a sum that happen to match are not the same claim. */
(function () {
  const { el, clear, toast, guard, todayISO } = window.ui;
  const api = window.api;
  const B = "/api/synapse";

  let host = null;
  let list = [];                 // every project, with roll-ups
  let page = null;               // the open project's tree payload
  let openId = null;
  let hideDone = false;
  // Whether the "+ instance" row is showing. Page-level rather than per render,
  // so pushing an hour and logging a second one does not mean reopening it.
  let instOpen = false;
  let dragId = null;             // row being dragged (project or task)
  // Which kind the why/note box is set to. Module scope, not per render, so
  // writing three notes in a row does not mean picking "note" three times.
  let addKind = "why";

  /* The card colours. Names rather than hex so the CSS owns the actual
     values and the two cannot drift; "" is no choice made, which falls back to
     the priority colour the card used before colours existed. */
  const COLORS = ["", "yellow", "purple", "blue", "green", "red", "pink", "teal"];
  const COLOR_LABEL = { "": "by priority", yellow: "yellow", purple: "purple",
    blue: "light blue", green: "green", red: "red", pink: "pink", teal: "teal" };

  const H = (mins) => mins ? (Math.round(mins / 6) / 10) + "h" : "";
  const N = (n) => (Math.round((n || 0) * 10) / 10).toString();
  const estText = (r) =>
    (!r.low && !r.high) ? "" : `${N(r.low)} to ${N(r.high)}h`;

  /* ---- routing ---------------------------------------------------------- */
  /* The Project tab is one of many, so the hash carries the tab as well as the
     node. Reading it back on load is what makes a project page a link you can
     paste to yourself. */
  function idFromHash() {
    const m = (location.hash || "").match(/^#project\/([^/?]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }
  /* Navigate, then fetch, then draw. Setting the hash first means the
     hashchange listener sees an id it already knows and bows out, which is
     what keeps one click from loading the page twice. */
  function go(id) {
    openId = id;
    const want = id ? "#project/" + encodeURIComponent(id) : "#project";
    if (location.hash !== want) location.hash = want;
    return guard(async () => { await load(); draw(); });
  }

  async function load() {
    if (openId) {
      const [l, p] = await Promise.all([
        api.get(B + "/projects"),
        api.get(B + "/projects/" + openId + "/tree"),
      ]);
      list = l.projects; page = p;
    } else {
      list = (await api.get(B + "/projects")).projects;
      page = null;
    }
  }
  const reload = () => guard(async () => { await load(); draw(); });

  /* ---- small shared pieces ---------------------------------------------- */
  function ask(title, fields, note, onOk) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const why = el("input.mform-input", { placeholder: "one line, optional" });
    const card = el("div.modal", {}, [
      el("div.modal-title", { text: title }),
      ...fields.map((f) => f.node),
      note ? el("div.pj-note", { text: note }) : null,
      el("div.mform-full", {}, [el("div.mform-label", { text: "why" }), why]),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "do it", onclick: () => onOk(fields.map((f) => f.get()), why.value.trim(), close) }),
        el("button.tk-btn", { text: "cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const first = card.querySelector("input,select,textarea");
    if (first) first.focus();
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); onOk(fields.map((f) => f.get()), why.value.trim(), close); }
      if (e.key === "Escape") close();
    });
  }
  function fText(label, ph, val) {
    const i = el("input.mform-input", { placeholder: ph || "", value: val || "" });
    return { node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), i]), get: () => i.value.trim() };
  }
  function fProject(label, exclude, withTop) {
    const opts = [];
    if (withTop) opts.push(el("option", { value: "", text: "(top level)" }));
    list.filter((p) => p.id !== exclude)
      .forEach((p) => opts.push(el("option", { value: p.id, text: p.path })));
    const sel = el("select.mform-input", {}, opts);
    return { node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), sel]), get: () => sel.value };
  }

  /* A cell you type into. Saves on blur or Enter, reverts on Escape. */
  function editable(value, save, opts) {
    const o = opts || {};
    const td = el("td" + (o.cls || ""), { contenteditable: "true", text: value == null ? "" : String(value) });
    let before = td.textContent;
    const commit = () => {
      const now = td.textContent.trim();
      if (now === before) return;
      before = now;
      save(now, td);
    };
    td.addEventListener("blur", commit);
    td.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); td.blur(); }
      if (e.key === "Escape") { td.textContent = before; td.blur(); }
    });
    return td;
  }

  async function patchProject(id, body) {
    await api.patch(B + "/projects/" + id, body);
  }

  /* The project's type — what working on it IS, and the default every session
     pushed onto it inherits. Saving does NOT reload: the chip has already
     repainted itself, and a full reload here would throw away the scroll
     position of a long list to change one word. */
  function typePicker(p) {
    return window.WorkLog.typeSelect(p.kind, async (kind) => {
      await patchProject(p.id, { kind });
      p.kind = kind;
      toast("type: " + kind);
    }, "pj");
  }

  /* Typing over a rolled-up estimate is an override, and an override is a
     claim that wants a reason. */
  function saveEstimate(p, field, raw, done) {
    const num = parseFloat(raw) || 0;
    const hasKids = p.rollup.child_projects > 0 || p.rollup.tasks > 0;
    if (!hasKids) {
      return guard(async () => { await patchProject(p.id, { [field]: num }); await reload(); });
    }
    ask(`override the estimate on ${p.name}`, [],
      "this project adds up to " + estText(p.rollup) + " from what is under it. "
      + "a number typed here wins until you clear it.",
      (_vals, why, close) => guard(async () => {
        // Send both ends. Switching the override on makes the stored numbers
        // the ones shown, and the end you did not type is still 0 from before
        // the project ever had an estimate — saving only the typed one would
        // blank the other half of the range.
        const body = { est_override: true, why,
                       low_h: p.rollup.low, high_h: p.rollup.high };
        body[field] = num;
        await patchProject(p.id, body);
        close(); await reload();
      }));
  }

  /* ---- LIST ------------------------------------------------------------- */
  function listView() {
    const wrap = el("div");

    wrap.appendChild(el("div.pj-vh", {}, [
      el("div", {}, [
        el("h1", { text: "Project" }),
        el("div.sub", { text: "every project, its hours, and its rank. click a card to open it." }),
      ]),
      el("button.tk-btn.teal", { text: "+ project", onclick: newTopProject }),
    ]));

    const body = el("tbody");
    // Top level only. The table is the portfolio — "what am I doing and in
    // what order" — and a rank that mixed a project with its own children
    // would be ranking a thing against part of itself.
    const tops = list.filter((p) => !p.parent_id);
    tops.forEach((p, i) => body.appendChild(listRow(p, i, tops)));
    if (!tops.length) {
      body.appendChild(el("tr", {}, [el("td.pj-empty", { colspan: "12",
        text: "no projects yet. make one here, or promote an idea from the Inbox." })]));
    }

    wrap.appendChild(el("section.card", {}, [
      el("table.pj-table", {}, [
        el("thead", {}, [el("tr", {}, [
          el("th", { style: "width:26px" }), el("th", { style: "width:22px" }),
          el("th", { text: "project" }), el("th", { text: "type" }),
          el("th.n", { text: "low" }), el("th.n", { text: "high" }),
          el("th.n", { text: "logged" }), el("th", { text: "priority" }),
          el("th", { text: "status" }), el("th", { text: "done when" }),
          el("th", { text: "progress" }), el("th", {}),
        ])]),
        body,
      ]),
      el("div.pj-note", { text: "cells edit in place. low and high on a project with children show the roll-up; typing over it is an override with a dated why. drag the rank to reorder." }),
    ]));

    const cards = el("div.pj-cards");
    tops.forEach((p) => cards.appendChild(cardEl(p)));
    wrap.appendChild(cards);
    return wrap;
  }

  function listRow(p, i, tops) {
    const r = p.rollup;
    const rank = el("td.pj-rank", { text: String(i + 1), draggable: "true",
      title: "drag to reorder" });
    rank.addEventListener("dragstart", (e) => {
      dragId = p.id; e.dataTransfer.effectAllowed = "move";
    });

    const tr = el("tr");
    tr.addEventListener("dragover", (e) => { e.preventDefault(); tr.classList.add("pj-dropping"); });
    tr.addEventListener("dragleave", () => tr.classList.remove("pj-dropping"));
    tr.addEventListener("drop", (e) => {
      e.preventDefault(); tr.classList.remove("pj-dropping");
      if (!dragId || dragId === p.id) return;
      const ids = tops.map((x) => x.id);
      const from = ids.indexOf(dragId);
      if (from < 0) return;
      ids.splice(from, 1);
      ids.splice(ids.indexOf(p.id), 0, dragId);
      dragId = null;
      guard(async () => { await api.post(B + "/projects/reorder", { ids }); await reload(); });
    });

    const prio = el("select.pj-sel", {}, [
      el("option", { value: "1", text: "1 · now" }),
      el("option", { value: "2", text: "2 · soon" }),
      el("option", { value: "3", text: "3 · later" }),
    ]);
    prio.value = String(p.priority);
    prio.addEventListener("change", () => guard(async () => {
      await patchProject(p.id, { priority: parseInt(prio.value, 10) });
      await reload();
    }));

    const status = el("select.pj-sel", {}, ["active", "paused", "not started", "holding", "done"]
      .map((s) => el("option", { value: s, text: s })));
    status.value = p.status;
    status.addEventListener("change", () => guard(async () => {
      await patchProject(p.id, { status: status.value });
      await reload();
    }));

    tr.appendChild(rank);
    tr.appendChild(el("td", {}, [swatchPicker(p)]));
    tr.appendChild(editable(p.name, (v) => guard(async () => {
      await patchProject(p.id, { name: v }); await reload();
    })));
    tr.appendChild(el("td", {}, [typePicker(p)]));
    tr.appendChild(editable(r.low || "", (v) => saveEstimate(p, "low_h", v), { cls: ".n" }));
    tr.appendChild(editable(r.high || "", (v) => saveEstimate(p, "high_h", v), { cls: ".n" }));
    tr.appendChild(el("td.n", { text: r.logged_mins ? N(r.logged_mins / 60) : "0" }));
    tr.appendChild(el("td", {}, [prio]));
    tr.appendChild(el("td", {}, [status]));
    tr.appendChild(editable(p.done_when, (v) => guard(async () => {
      await patchProject(p.id, { done_when: v }); await reload();
    })));
    tr.appendChild(el("td", {}, [progressEl(r)]));
    tr.appendChild(el("td", {}, [
      el("button.tk-btn.btn-sm", { text: "open ↗", onclick: () => go(p.id) }),
    ]));
    return tr;
  }

  /* Two readings of the same row in one bar.

     The solid fill is parts finished over parts there are, which is the
     question the row is really asking. The faint fill behind it is hours
     logged against the high end of the estimate, which is the question you
     only think to ask once something is late: half the work done and the whole
     budget spent is a row that looks fine until you see both fills at once.

     Past the estimate the faint fill turns amber rather than clipping
     silently, because "over" is the one state worth interrupting for. */
  function rowBar(r) {
    const total = r.tasks + r.child_projects;
    const done = r.tasks_done + r.child_projects_done;
    if (!total && !r.high && !r.logged_mins) return el("span.pj-rowbar-gap");
    const bar = el("span.pj-rowbar", { title: barTitle(r, done, total) });
    if (r.high) {
      const hours = r.logged_mins / 60;
      const frac = Math.min(1, hours / r.high);
      bar.appendChild(el("i.pj-rowbar-hours" + (hours > r.high ? ".over" : ""), {
        style: "width:" + (frac * 100).toFixed(1) + "%",
      }));
    }
    if (total) {
      bar.appendChild(el("i.pj-rowbar-done", {
        style: "width:" + ((done / total) * 100).toFixed(1) + "%",
      }));
    }
    return bar;
  }

  function barTitle(r, done, total) {
    const bits = [];
    if (total) bits.push(done + " of " + total + " done");
    if (r.high) {
      bits.push(N(r.logged_mins / 60) + "h logged of " + N(r.high) + "h estimated"
        + (r.logged_mins / 60 > r.high ? " (over)" : ""));
    } else if (r.logged_mins) {
      bits.push(N(r.logged_mins / 60) + "h logged, no estimate");
    }
    return bits.join(" · ");
  }

  /* A dot you click for the palette. Inline rather than a modal: choosing a
     colour is a glance-and-point decision, and a dialog for it would cost more
     attention than the choice is worth. */
  function swatchPicker(p) {
    const dot = el("button.pj-swatch", {
      "data-color": p.color || "",
      title: "border colour: " + COLOR_LABEL[p.color || ""],
    });
    dot.classList.add("p" + p.priority);
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = document.querySelector(".pj-palette");
      if (open) open.remove();
      const pal = el("div.pj-palette", {}, COLORS.map((c) => {
        const b = el("button.pj-swatch" + (c === (p.color || "") ? ".on" : ""), {
          "data-color": c, title: COLOR_LABEL[c],
        });
        if (!c) b.classList.add("p" + p.priority);
        b.addEventListener("click", (ev) => {
          ev.stopPropagation();
          pal.remove();
          guard(async () => { await patchProject(p.id, { color: c }); await reload(); });
        });
        return b;
      }));
      const r = dot.getBoundingClientRect();
      pal.style.left = (r.left + window.scrollX) + "px";
      pal.style.top = (r.bottom + window.scrollY + 4) + "px";
      document.body.appendChild(pal);
      const away = (ev) => {
        if (pal.contains(ev.target)) return;
        pal.remove(); document.removeEventListener("mousedown", away);
      };
      setTimeout(() => document.addEventListener("mousedown", away), 0);
    });
    return dot;
  }

  /* Progress is done-out-of-total across the subtree. With no estimate and no
     children there is nothing honest to draw, so it says so instead of
     drawing an empty bar that reads as zero percent. */
  function progressEl(r) {
    const total = r.tasks + r.child_projects;
    const done = r.tasks_done + r.child_projects_done;
    if (!total) return el("span.pj-note", { text: r.low || r.high ? "no parts yet" : "no estimate" });
    const pct = Math.round((done / total) * 100);
    return el("span", {}, [
      el("span.pj-bar", {}, [el("i", { style: "width:" + pct + "%" })]),
      el("span.pj-note", { text: done + " of " + total }),
    ]);
  }

  function cardEl(p) {
    const r = p.rollup;
    const kidLine = p.children.length
      ? p.children.map((k) => k.name + (k.status === "done" ? " ✓" : (k.low_h || k.high_h ? " " + N(k.low_h) + " to " + N(k.high_h) + "h" : ""))).join(" · ")
      : (p.ideas_given ? p.ideas_given + " idea" + (p.ideas_given === 1 ? "" : "s") + " given" : "nothing under it yet");
    const claim = (p.claims && p.claims[0])
      ? "claimed by " + p.claims[0].phase : "";
    return el("div.pj-card.p" + p.priority, {
      "data-color": p.color || "", "data-nav": p.id, onclick: () => go(p.id),
    }, [
      el("div.pj-cardhead", {}, [
        el("h3", { text: p.name }),
        el("span.pj-pr.p" + p.priority, { text: p.priority_word }),
      ]),
      el("div.pj-why-line", { text: p.why ? p.why.text : "no why yet" }),
      el("div.pj-kids", { text: kidLine }),
      el("div.pj-cardfoot", {}, [
        el("span.pj-note", { text: [r.logged_mins ? N(r.logged_mins / 60) + "h" : "", claim, p.status].filter(Boolean).join(" · ") }),
        el("span.pj-chip", { text: r.child_projects + " sub" }),
      ]),
    ]);
  }

  function newTopProject() {
    ask("new top-level project", [fText("project", "name")], null,
      ([name], why, close) => {
        if (!name) return;
        guard(async () => {
          const p = await api.post(B + "/projects", { name, parent_id: null, why });
          close(); toast("project created");
          await go(p.id);
        });
      });
  }

  /* ---- PAGE ------------------------------------------------------------- */

  /* ==================================================================== *
   * The instance row — log an hour on this project
   *
   * Inline, not a modal: this is the most repeated action on the page, and a
   * dialog you have to dismiss is how an hour ends up not being logged. The
   * row writes a :WorkSession ON this project, which is the same node the
   * Database tab, the contribution grid and the totals all read — there is no
   * project-local copy of the hours.
   * ==================================================================== */
  const pad2 = (n) => String(n).padStart(2, "0");
  const hm = (d) => pad2(d.getHours()) + ":" + pad2(d.getMinutes());

  function instanceRow(root, onPushed) {
    // The last hour, which is what you are almost always logging: you look up,
    // notice you have been at it a while, and write it down afterwards.
    const now = new Date();
    const started = el("input", { value: hm(new Date(now - 3600000)) });
    const finished = el("input", { value: hm(now) });
    const seg = window.WorkLog.typeSeg(root.kind);
    const what = el("input", { placeholder: "one line" });

    const push = el("button.tk-btn.teal", { text: "push" });
    push.addEventListener("click", () => guard(async () => {
      await api.post("/api/work", {
        date: todayISO(),
        start: started.value.trim(),
        end: finished.value.trim(),
        module: "mainframe",
        ref_kind: "project",
        ref_id: root.id,
        ref_title: root.name,
        kind: seg.get(),
        what: what.value.trim(),
      });
      what.value = "";
      toast("logged on " + root.name);
      onPushed();
    }));

    const field = (label, node) => el("div", {}, [el("span.pj-lbl", { text: label }), node]);
    return el("section.card", {}, [
      el("div.pj-tbl-head", {}, [
        el("h2", { style: "font-size:14px;margin:0;font-weight:600", text: "New instance" }),
        el("span.pj-note", { style: "margin:0", text: "this project · lands in Database" }),
      ]),
      el("div.pj-inst", {}, [
        field("started", started),
        field("finished", finished),
        field("type", seg.node),
        field("what, optional", what),
        push,
      ]),
      el("div.pj-instfoot", {
        text: "times default to the last hour and now. type defaults from the project.",
      }),
    ]);
  }

  /* ==================================================================== *
   * Tables — the project's own databases
   *
   * A table here is a :Sheet with (:Sheet)-[:FOR]->(:Project), which is the
   * SAME node the Sheets tab lists and opens. Not a project-local table type:
   * a copy would drift, and a formula or a link column would work in one place
   * and not the other. So this block is a second view of one thing, and
   * "open in Sheets" walks from this view to the other.
   *
   * Columns and cells are contenteditable and save on blur. No timer and no
   * push from a table — hours are logged by the instance row above, and a
   * table that could also log them would be a second way to write the same
   * node with none of the fields that make a session a session.
   * ==================================================================== */
  function tablesBlock(root) {
    const host = el("div.pj-tables");
    const wrap = el("section.card", {}, [
      el("div.pj-tbl-head", {}, [
        el("h2", { style: "font-size:14px;margin:0;font-weight:600", text: "Tables" }),
        el("div.row", { style: "gap:6px" }, [
          el("span.pj-note", { style: "margin:0", text: "columns and cells edit in place" }),
          el("button.tk-btn.btn-sm", { text: "+ table", onclick: () => guard(async () => {
            await api.post("/api/sheets", { name: "New table", project_id: root.id });
            toast("table added");
            await paint();
          }) }),
        ]),
      ]),
      host,
    ]);

    async function paint() {
      const list = await api.sheets.list(root.id);
      clear(host);
      if (!list.length) {
        host.appendChild(el("div.pj-empty", {
          text: "no tables yet. “+ table” makes one, and it shows up in Sheets too.",
        }));
        return;
      }
      // Each sheet is fetched in full — the listing carries counts, not cells.
      const full = await Promise.all(list.map((s) => api.sheets.get(s.id)));
      full.forEach((sh) => host.appendChild(sheetEl(sh, paint)));
    }

    paint();
    return wrap;
  }

  function sheetEl(sh, reloadTables) {
    const box = el("div");

    const name = el("div.pj-tbl-name", { contenteditable: "true", text: sh.name || "Untitled table" });
    let nameWas = name.textContent;
    name.addEventListener("blur", () => {
      const now = name.textContent.trim();
      if (now === nameWas) return;
      nameWas = now;
      guard(() => api.sheets.update(sh.id, { name: now }));
    });
    name.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); name.blur(); } });

    box.appendChild(el("div.pj-tbl-head", {}, [
      name,
      el("div.row", { style: "gap:6px" }, [
        el("span.pj-note", { style: "margin:0", text: sh.rows.length + " rows" }),
        el("button.tk-btn.btn-sm", { text: "+ row", onclick: () => guard(async () => {
          await api.sheets.addRow(sh.id);
          await reloadTables();
        }) }),
        el("button.tk-btn.btn-sm", { text: "↗ open in Sheets", title: "the same table, in the Sheets tab",
          onclick: () => {
            if (window.SheetsTab) window.SheetsTab.open(sh.id);
            window.openTab("sheets");
          } }),
      ]),
    ]));

    const table = el("table.pj-tbl");

    // ---- header: rename in place, and add a column at the end ----
    const head = el("tr");
    head.appendChild(el("th", { style: "width:26px;min-width:26px" }));
    sh.columns.forEach((col) => {
      const th = el("th", { contenteditable: "true", text: col.name || "" });
      let was = th.textContent;
      th.addEventListener("blur", () => {
        const now = th.textContent.trim();
        if (now === was) return;
        was = now;
        // A rename keeps the column's key, so no cell is orphaned by it.
        guard(() => api.sheets.updateColumn(sh.id, col.id, { name: now }));
      });
      th.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); th.blur(); } });
      head.appendChild(th);
    });
    head.appendChild(el("th.pj-tbl-add", { text: "+ column", title: "add a column",
      onclick: () => guard(async () => {
        await api.sheets.addColumn(sh.id, { name: "column", type: "text" });
        await reloadTables();
      }) }));
    table.appendChild(head);

    // ---- cells ----
    sh.rows.forEach((row) => {
      const tr = el("tr");
      tr.appendChild(el("td.pj-tbl-x", {}, [
        el("button", { title: "delete this row", text: "×", onclick: () => guard(async () => {
          await api.sheets.delRow(sh.id, row.id);
          await reloadTables();
        }) }),
      ]));
      sh.columns.forEach((col) => {
        const v = row.cells[col.key];
        const td = el("td", { contenteditable: "true",
          text: v == null ? "" : (Array.isArray(v) ? v.join(", ") : String(v)) });
        let was = td.textContent;
        td.addEventListener("blur", () => {
          const now = td.textContent.trim();
          if (now === was) return;
          was = now;
          guard(() => api.sheets.updateRow(sh.id, row.id, { [col.key]: now }));
        });
        // Enter commits rather than opening a second line: these are cells.
        td.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); td.blur(); } });
        tr.appendChild(td);
      });
      tr.appendChild(el("td"));
      table.appendChild(tr);
    });

    box.appendChild(el("div.pj-tbl-wrap", {}, [table]));
    return box;
  }

  /* ==================================================================== *
   * Instances — the hours already on this project
   *
   * The same :WorkSession rows the Database tab shows, filtered to this
   * project. Read-only here on purpose: the Database tab is where a row is
   * edited, and two editable copies of one row is how they disagree.
   * ==================================================================== */
  function instancesBlock(root) {
    const host = el("div");
    const wrap = el("section.card", {}, [
      el("div.pj-tbl-head", {}, [
        el("h2", { style: "font-size:14px;margin:0;font-weight:600", text: "Instances" }),
        el("span.pj-note", { style: "margin:0", id: "pj-sess-meta", text: "" }),
      ]),
      host,
    ]);

    guard(async () => {
      const rows = (await api.work.list("?ref_id=" + encodeURIComponent(root.id) + "&limit=500"))
        .sort((a, b) => (b.date + (b.start || "")).localeCompare(a.date + (a.start || "")));
      const mins = rows.reduce((n, r) => n + (r.mins || 0), 0);
      const meta = wrap.querySelector("#pj-sess-meta");
      if (meta) {
        meta.textContent = rows.length
          ? window.WorkLog.fmtMins(mins) + " · " + rows.length + " session"
            + (rows.length === 1 ? "" : "s") + " · same rows as Database, filtered to "
            + root.name
          : "same rows as Database, filtered to " + root.name;
      }
      clear(host);
      if (!rows.length) {
        host.appendChild(el("div.pj-empty", { text: "nothing logged on this project yet." }));
        return;
      }
      const table = el("table.pj-sess");
      const head = el("tr");
      [["date", ""], ["started", ""], ["finished", ""], ["mins", "n"],
       ["type", ""], ["what", ""]].forEach(([l, c]) =>
        head.appendChild(el("th" + (c ? "." + c : ""), { text: l })));
      table.appendChild(head);
      rows.forEach((r) => {
        const tr = el("tr");
        tr.appendChild(el("td.t", { text: shortDate(r.date) }));
        tr.appendChild(el("td.t", { text: r.start || "" }));
        tr.appendChild(el("td.t", { text: r.end || "" }));
        tr.appendChild(el("td.n", { text: String(r.mins || 0) }));
        tr.appendChild(el("td", {}, [window.WorkLog.typeChip(r.kind, "pj")]));
        tr.appendChild(el("td", { text: r.what || "" }));
        table.appendChild(tr);
      });
      host.appendChild(el("div.pj-tbl-wrap", {}, [table]));
    });

    return wrap;
  }

  /* "2026-09-16" → "16 sep". The table is read as a column of days, and the
     year repeated on every row is noise; it is still in the title. */
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
                  "jul", "aug", "sep", "oct", "nov", "dec"];
  function shortDate(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    if (!m) return iso || "";
    return String(+m[3]) + " " + MONTHS[+m[2] - 1];
  }

  function pageView() {
    const root = page.root, r = root.rollup;
    const wrap = el("div");

    wrap.appendChild(el("div.pj-crumb", {}, [
      el("a", { text: "Project", onclick: () => go(null) }),
      el("span", { text: " › " + page.path }),
    ]));

    const claim = (page.claims || []).map((c) =>
      c.phase + " · " + N(c.planned_h) + "h planned · " + N((c.logged_mins || 0) / 60) + "h in");

    wrap.appendChild(el("div.pj-vh", {}, [
      el("div", {}, [
        el("div.row", { style: "gap:8px;align-items:center" }, [
          el("h1", { text: root.name }), typePicker(root),
        ]),
        el("div.sub", { text: [estText(r), r.logged_mins ? N(r.logged_mins / 60) + "h logged" : "nothing logged",
          "priority " + root.priority_word, claim.length ? "claimed by " + claim.join(", ") : ""]
          .filter(Boolean).join(" · ") }),
      ]),
      el("div.row", { style: "gap:6px;flex-wrap:wrap" }, [
        // First and primary: logging an hour is what you come here to do most.
        el("button.tk-btn.teal.btn-sm", { text: "+ instance",
          title: "log an hour on this project",
          onclick: () => { instOpen = !instOpen; draw(); } }),
        el("button.tk-btn.btn-sm", { text: "+ project", onclick: () => nestUnder(root) }),
        el("button.tk-btn.btn-sm", { text: "+ task", onclick: () => addTask(root) }),
        el("button.tk-btn.btn-sm", { text: "offshoot", onclick: () => offshoot(root) }),
        el("button.tk-btn.btn-sm", { text: "+ attach", title: "attach a paper, doc, sheet or video made anywhere in Mainframe",
          onclick: () => window.ProjectAttach.open({ project: { id: root.id, name: root.name }, onDone: reload }) }),
        el("button.tk-btn.btn-sm", { text: "↗ docs (" + page.docs + ")", onclick: () => window.openTab("docs") }),
        el("button.tk-btn.btn-sm", { text: "▶ start timer", onclick: () => startTimer(root) }),
      ]),
    ]));

    const chip = el("button.pj-chip.pj-toggle" + (hideDone ? ".on" : ""), {
      text: hideDone ? "done hidden" : "hide done",
      onclick: () => { hideDone = !hideDone; draw(); },
    });
    wrap.appendChild(el("div.pj-bar", {}, [
      el("span.pj-note", { text: "tick a task: done today. tick a project: asks to mark its children. done rows stay, greyed. drag a row onto a project to move it." }),
      chip,
    ]));

    if (instOpen) wrap.appendChild(instanceRow(root, () => draw()));

    wrap.appendChild(el("section.card.pj-tree", {}, [nodeEl(root, true)]));
    wrap.appendChild(window.ProjectAttach.block({ id: root.id, name: root.name }, r, page.claims, reload));
    wrap.appendChild(tablesBlock(root));
    wrap.appendChild(instancesBlock(root));
    wrap.appendChild(panels(root));
    return wrap;
  }

  function nodeEl(p, isRoot) {
    const kids = [projRow(p)];
    (p.tasks || []).forEach((t) => {
      if (hideDone && t.status === "done") return;
      kids.push(taskRow(t, p));
    });
    kids.push(addLine(p));
    (p.children || []).forEach((k) => {
      if (hideDone && k.status === "done" && !hasOpenDescendant(k)) return;
      kids.push(nodeEl(k, false));
    });
    return el("div.pj-node" + (isRoot ? ".pj-root" : ""), {}, kids);
  }

  function hasOpenDescendant(p) {
    if ((p.tasks || []).some((t) => t.status !== "done")) return true;
    return (p.children || []).some((k) => k.status !== "done" || hasOpenDescendant(k));
  }

  function projRow(p) {
    const r = p.rollup;
    const done = p.status === "done";
    const box = el("input", { type: "checkbox" });
    box.checked = done;
    box.addEventListener("change", () => tickProject(p, box.checked));

    const name = el("span.pj-name", { text: p.name, contenteditable: "true" });
    let before = p.name;
    name.addEventListener("blur", () => {
      const v = name.textContent.trim();
      if (!v || v === before) { name.textContent = before; return; }
      before = v;
      guard(async () => { await patchProject(p.id, { name: v }); await reload(); });
    });
    name.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); name.blur(); }
      if (e.key === "Escape") { name.textContent = before; name.blur(); }
    });

    const parts = [estText(r)];
    const total = r.tasks + r.child_projects;
    if (total) parts.push((r.tasks_done + r.child_projects_done) + " of " + total + " done");
    if (r.logged_mins) parts.push(N(r.logged_mins / 60) + "h");
    if (p.done_when) parts.push("done when: " + p.done_when);
    if (done && p.done_at) parts.push("done " + p.done_at);

    const row = el("div.pj-row.pj-proj" + (done ? ".pj-rdone" : ""), { "data-nav": p.id }, [
      box, name, rowBar(r),
      el("span.pj-t", { text: parts.filter(Boolean).join(" · ") }),
      el("span.pj-acts", {}, [
        el("button.pj-act", { text: "+ task", onclick: () => addTask(p) }),
        el("button.pj-act", { text: "+ project", onclick: () => nestUnder(p) }),
        el("button.pj-act", { text: "✎ why", onclick: () => addWhy(p) }),
        el("button.pj-act", { text: "⋯", onclick: (e) => moreMenu(e, p) }),
      ]),
    ]);
    makeDraggable(row, p.id, "project");
    makeDropTarget(row, p.id);
    return row;
  }

  function taskRow(t, parent) {
    const done = t.status === "done";
    const box = el("input", { type: "checkbox" });
    box.checked = done;
    box.addEventListener("change", () => guard(async () => {
      await api.patch(B + "/tasks/" + t.id, { done: box.checked });
      await reload();
    }));

    const name = el("span.pj-name", { text: t.title, contenteditable: "true" });
    let before = t.title;
    name.addEventListener("blur", () => {
      const v = name.textContent.trim();
      if (!v || v === before) { name.textContent = before; return; }
      before = v;
      guard(async () => { await api.patch(B + "/tasks/" + t.id, { title: v }); await reload(); });
    });
    name.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); name.blur(); }
      if (e.key === "Escape") { name.textContent = before; name.blur(); }
    });

    const parts = [];
    if (t.low_h || t.high_h) parts.push(N(t.low_h) + " to " + N(t.high_h) + "h");
    if (t.logged_mins) parts.push(N(t.logged_mins / 60) + "h so far");
    if (t.due) parts.push(t.due === todayISO() ? "due today" : "due " + t.due);
    if (done && t.done_at) parts.push("done " + t.done_at);

    const row = el("div.pj-row.pj-task" + (done ? ".pj-rdone" : ""), { "data-nav": t.id }, [
      box, name,
      el("span.pj-t", { text: parts.join(" · ") }),
      el("span.pj-acts", {}, [
        el("button.pj-act", { text: "▶", title: "start the timer on this task", onclick: () => startTimer(t, true) }),
        el("button.pj-act", { text: "✎", title: "estimate and due date", onclick: () => editTask(t) }),
      ]),
    ]);
    makeDraggable(row, t.id, "task");
    return row;
  }

  /* One line under every project. Enter adds a task; a leading / makes it a
     project instead. Focus stays in the box, because adding three things in a
     row is the normal case and reaching for the mouse between them is not. */
  function addLine(p) {
    const input = el("input.pj-add", {
      placeholder: "+ task, or /name for a project, enter to add",
    });
    input.addEventListener("keydown", (e) => {
      if (e.key !== "Enter") return;
      const raw = input.value.trim();
      if (!raw) return;
      input.value = "";
      const isProject = raw.startsWith("/");
      const text = isProject ? raw.slice(1).trim() : raw;
      if (!text) return;
      guard(async () => {
        if (isProject) await api.post(B + "/projects", { name: text, parent_id: p.id, why: "" });
        else await api.post(B + "/tasks", { project_id: p.id, title: text, why: "" });
        await load();
        draw();
        // put the cursor back where it was
        const again = [...document.querySelectorAll(".pj-add")]
          .find((i) => i.dataset.pid === p.id);
        if (again) again.focus();
      });
    });
    input.dataset.pid = p.id;
    return el("div.pj-addline", {}, [input]);
  }

  function makeDraggable(row, id, kind) {
    row.setAttribute("draggable", "true");
    row.addEventListener("dragstart", (e) => {
      dragId = { id, kind }; e.dataTransfer.effectAllowed = "move";
      e.stopPropagation();
    });
  }

  function makeDropTarget(row, projectId) {
    row.addEventListener("dragover", (e) => {
      if (!dragId || dragId.id === projectId) return;
      e.preventDefault(); e.stopPropagation();
      row.classList.add("pj-dropping");
    });
    row.addEventListener("dragleave", () => row.classList.remove("pj-dropping"));
    row.addEventListener("drop", (e) => {
      e.preventDefault(); e.stopPropagation();
      row.classList.remove("pj-dropping");
      const d = dragId; dragId = null;
      if (!d || d.id === projectId) return;
      ask("move it under this project", [], "re-parenting is a decision worth a line.",
        (_v, why, close) => guard(async () => {
          if (d.kind === "task") await api.patch(B + "/tasks/" + d.id, { parent_id: projectId, why });
          else await api.post(B + "/projects/" + d.id + "/move", { parent_id: projectId, why });
          close(); toast("moved"); await reload();
        }));
    });
  }

  /* ---- page actions ----------------------------------------------------- */
  function addTask(p) {
    ask("add a task to " + p.name, [fText("task", "e.g. chapter 4")], null,
      ([title], why, close) => {
        if (!title) return;
        guard(async () => {
          await api.post(B + "/tasks", { project_id: p.id, title, why });
          close(); await reload();
        });
      });
  }
  function nestUnder(p) {
    ask("nest a project under " + p.name, [fText("project", "e.g. battle system")], null,
      ([name], why, close) => {
        if (!name) return;
        guard(async () => {
          await api.post(B + "/projects", { name, parent_id: p.id, why });
          close(); await reload();
        });
      });
  }
  function offshoot(p) {
    ask("offshoot from " + p.name, [fText("idea", "something this made you think of")],
      "it lands in the Inbox as a raw idea, not as work.",
      ([title], why, close) => {
        if (!title) return;
        guard(async () => {
          await api.post(B + "/projects/" + p.id + "/offshoot", { title, why });
          close(); toast("offshoot written to the Inbox"); await reload();
        });
      });
  }
  function addWhy(p) {
    ask("why " + p.name, [fText("why", "one line")], null, ([text], _w, close) => {
      if (!text) return;
      guard(async () => {
        await api.post(B + "/projects/" + p.id + "/why", { text });
        close(); await reload();
      });
    });
  }
  function editTask(t) {
    ask("edit " + t.title, [
      fText("low hours", "0", t.low_h || ""),
      fText("high hours", "0", t.high_h || ""),
      fText("due", "YYYY-MM-DD", t.due || ""),
    ], null, ([low, high, due], _w, close) => guard(async () => {
      await api.patch(B + "/tasks/" + t.id, {
        low_h: parseFloat(low) || 0, high_h: parseFloat(high) || 0, due,
      });
      close(); await reload();
    }));
  }
  function moreMenu(e, p) {
    e.stopPropagation();
    ask("⋯ " + p.name, [
      fText("rename to", "leave blank to keep", ""),
      fProject("move under", p.id, true),
    ], "blank fields are left alone. to drop it, set status to paused on the list.",
      ([name, parent], why, close) => guard(async () => {
        if (name) await patchProject(p.id, { name });
        if (parent !== p.parent_id) {
          await api.post(B + "/projects/" + p.id + "/move", { parent_id: parent || null, why });
        }
        close(); await reload();
      }));
  }

  function tickProject(p, checked) {
    if (!checked) {
      return guard(async () => {
        await api.post(B + "/projects/" + p.id + "/done", { done: false });
        await reload();
      });
    }
    const total = p.rollup.tasks + p.rollup.child_projects;
    if (!total) {
      return guard(async () => {
        await api.post(B + "/projects/" + p.id + "/done", { done: true, cascade: false });
        await reload();
      });
    }
    const overlay = el("div.modal-overlay");
    const close = () => { overlay.remove(); draw(); };
    overlay.addEventListener("mousedown", (ev) => { if (ev.target === overlay) close(); });
    overlay.appendChild(el("div.modal", {}, [
      el("div.modal-title", { text: "mark all children done?" }),
      el("div.pj-note", { text: p.name + " has " + total + " thing" + (total === 1 ? "" : "s") + " under it. "
        + "a project closed because it was finished has finished children; one closed because it was "
        + "abandoned does not." }),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "yes, all of them", onclick: () => guard(async () => {
          await api.post(B + "/projects/" + p.id + "/done", { done: true, cascade: true });
          overlay.remove(); await reload();
        }) }),
        el("button.tk-btn", { text: "just this one", onclick: () => guard(async () => {
          await api.post(B + "/projects/" + p.id + "/done", { done: true, cascade: false });
          overlay.remove(); await reload();
        }) }),
        el("button.tk-btn", { text: "cancel", onclick: close }),
      ]),
    ]));
    document.body.appendChild(overlay);
  }

  /* Starts the topbar timer against this node. Timers.js owns the clock and
     the logging; all this does is say what the block is for, which is what
     makes the hours land on the right task instead of in the project's
     undifferentiated pile. */
  function startTimer(node, isTask) {
    if (!window.Timers || !window.Timers.start) {
      return toast("the timer is not loaded", true);
    }
    const label = node.name || node.title;
    window.Timers.start({
      kind: isTask ? "task" : "project",
      ref_id: node.id,
      label,
      module: "synapse",
    });
    toast("timer started on " + label);
  }

  /* ---- panels ----------------------------------------------------------- */
  function panels(root) {
    const r = root.rollup;

    const low = el("input.pj-num", { value: r.low || "" });
    const high = el("input.pj-num", { value: r.high || "" });
    const dw = el("input.mform-input", { value: root.done_when || "", placeholder: "what makes this finished" });
    const due = el("input.mform-input", { type: "date", value: root.due || "" });
    const saveEst = () => guard(async () => {
      const hasKids = r.child_projects > 0 || r.tasks > 0;
      await patchProject(root.id, {
        low_h: parseFloat(low.value) || 0, high_h: parseFloat(high.value) || 0,
        done_when: dw.value, due: due.value,
        est_override: hasKids ? true : undefined,
      });
      await reload();
    });

    const est = el("section.card", {}, [
      el("h2", { text: "Estimate · " + root.name }),
      el("div.pj-est", {}, [
        el("span.pj-lbl", { text: "low" }), low,
        el("span.pj-lbl", { text: "high" }), high,
      ]),
      el("div.mform-full", { style: "margin-top:10px" }, [
        el("div.mform-label", { text: "done when" }), dw]),
      el("div.mform-full", {}, [el("div.mform-label", { text: "due" }), due]),
      el("div.row", { style: "gap:8px" }, [
        el("button.tk-btn.teal", { text: "save", onclick: saveEst }),
        r.override ? el("button.tk-btn", { text: "back to the sum", onclick: () => guard(async () => {
          await patchProject(root.id, { est_override: false }); await reload();
        }) }) : null,
      ].filter(Boolean)),
      el("div.pj-note", { text: (r.child_projects || r.tasks)
        ? ("roll-up from what is under it: " + N(r.rolled_low) + " to " + N(r.rolled_high) + "h. "
           + (r.override ? "overridden by the number above." : "no override."))
        : "a leaf shows its own numbers." }),
    ]);

    /* One dated list for both kinds. A why is marked; a note is not, because
       most entries are notes and a label on every row would be noise. */
    const whyBox = el("div");
    (page.whys || []).forEach((w) => {
      const isWhy = (w.kind || "why") === "why";
      whyBox.appendChild(el("div.pj-why" + (isWhy ? "" : ".pj-plain"), {}, [
        el("span", { text: w.text }),
        el("span.pj-why-meta", {
          text: [isWhy ? "why" : "note", w.date || "",
                 w.on && w.on !== "project" ? "on the " + w.on : ""]
            .filter(Boolean).join(" · "),
        }),
      ]));
    });
    if (!(page.whys || []).length) {
      whyBox.appendChild(el("div.pj-note", { text: "nothing written yet" }));
    }

    const kindBtns = el("div.pj-kinds", {}, ["why", "note"].map((k) =>
      el("button.pj-kind" + (k === addKind ? ".on" : ""), {
        text: k,
        onclick: (ev) => {
          addKind = k;
          [...kindBtns.children].forEach((b) => b.classList.toggle("on", b.textContent === k));
          addw.placeholder = "add a " + k + ", enter to save";
          addw.focus();
        },
      })));
    const addw = el("input.mform-input", {
      placeholder: "add a " + addKind + ", enter to save" });
    addw.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !addw.value.trim()) return;
      const text = addw.value.trim(); addw.value = "";
      const kind = addKind;
      guard(async () => {
        await api.post(B + "/projects/" + root.id + "/why", { text, kind });
        await reload();
      });
    });
    const why = el("section.card", {}, [
      el("h2", { text: "Why and notes · " + root.name }),
      whyBox,
      el("div.pj-addrow", {}, [kindBtns, addw]),
    ]);

    const ideasBody = el("tbody");
    (page.ideas_given || []).forEach((i) => ideasBody.appendChild(el("tr", {}, [
      el("td", { text: i.title }),
      el("td.pj-note", { text: [i.given_on, i.from_project ? "offshoot from " + i.from_project : ""].filter(Boolean).join(" · ") }),
      el("td", {}, [
        el("button.tk-btn.btn-sm", { text: "promote", onclick: () => guard(async () => {
          await api.post(B + "/inbox/" + i.id + "/promote", { parent_id: root.id, why: "" });
          toast("promoted"); await reload();
        }) }),
        el("button.tk-btn.btn-sm", { text: "split → task", onclick: () => guard(async () => {
          await api.patch(B + "/inbox/" + i.id, { kind: "task" });
          toast("now a task"); await reload();
        }) }),
      ]),
    ])));
    if (!(page.ideas_given || []).length) {
      ideasBody.appendChild(el("tr", {}, [el("td.pj-note", { colspan: "3",
        text: "no ideas given to this project yet. give one from the Inbox." })]));
    }
    /* Writing an idea here is the two-step Inbox route collapsed: it is created
       and handed to this project in one call, so it never sits as a raw row
       you have to come back and file. */
    const addIdea = el("input.mform-input", {
      placeholder: "add an idea for this project, enter to save" });
    addIdea.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !addIdea.value.trim()) return;
      const title = addIdea.value.trim(); addIdea.value = "";
      guard(async () => {
        await api.post(B + "/projects/" + root.id + "/ideas", { title, why: "" });
        toast("idea given to " + root.name);
        await reload();
      });
    });
    const ideas = el("section.card", {}, [
      el("h2", { text: "Ideas given" }),
      el("table.pj-table", {}, [ideasBody]),
      addIdea,
    ]);

    const chips = [
      el("span.pj-chip", { text: N(r.logged_mins / 60) + "h total" }),
      el("span.pj-chip", { text: r.sessions + " session" + (r.sessions === 1 ? "" : "s") }),
    ];
    (page.claims || []).forEach((c) => chips.push(el("span.pj-chip", {
      text: c.phase + " · " + N(c.planned_h) + "h planned · " + N((c.logged_mins || 0) / 60) + "h in" })));
    const sessBody = el("tbody");
    (page.sessions_by_task || []).forEach((t) => sessBody.appendChild(el("tr", {}, [
      el("td", { text: t.title }),
      el("td.n", { text: N(t.mins / 60) + "h" }),
      el("td.pj-note", { text: t.sessions + " session" + (t.sessions === 1 ? "" : "s") }),
    ])));
    if (!(page.sessions_by_task || []).length) {
      sessBody.appendChild(el("tr", {}, [el("td.pj-note", { colspan: "3", text: "no hours logged against this yet" })]));
    }
    const sessions = el("section.card", {}, [
      el("h2", { text: "Sessions and claims" }),
      el("div.pj-chipline", {}, chips),
      el("table.pj-table", {}, [sessBody]),
      el("button.tk-btn.btn-sm", { text: "↗ all sessions", onclick: () => window.openTab("work") }),
    ]);

    // Estimate  | Sessions and claims
    // Ideas given | Why and notes
    //
    // Sessions moves up because it is the panel you read: what this has cost
    // so far, beside what it was estimated at. Why and notes moves down
    // because it is the panel you write, and it grows without pushing the
    // numbers off the screen.
    return el("div.pj-panels", {}, [est, sessions, ideas, why]);
  }

  /* ---- draw ------------------------------------------------------------- */
  function draw() {
    clear(host);
    host.appendChild(openId && page ? pageView() : listView());
  }

  async function render(mount) {
    host = mount;
    openId = idFromHash();
    host.appendChild(el("div.pj-note", { text: "loading…" }));
    await guard(async () => { await load(); draw(); });
  }

  // Back/forward between the list and a project page.
  window.addEventListener("hashchange", () => {
    if (!host || !host.isConnected) return;
    const id = idFromHash();
    if (id === openId) return;
    openId = id;
    guard(async () => { await load(); draw(); });
  });

  /* The Inbox links straight at a node. */
  window.ProjectTree = { focusOn(id) { openId = id; } };

  window.PROJ_TABS = window.PROJ_TABS || [];
  // "Main" rather than "Tree": the tree is only half of what this shows, and
  // it is the view the Project tab opens on.
  window.PROJ_TABS.unshift({ key: "main", label: "Main", render });
})();

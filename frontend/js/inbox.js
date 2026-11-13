/* inbox.js — everything lands here first.

   One table, one node type. A row is an idea or a task and flips between them
   in place, because the thing you wrote down at 11pm does not know yet which
   one it is, and forcing that decision at the moment of writing is how notes
   stop getting written.

   The merge of the old Ideas and Tasks tabs: those were two tables over what
   turned out to be one kind of row, and moving something between them meant
   retyping it and losing its notes. See routes/inbox.py for the model.

   Nothing here deletes. Every move rewrites the row's status and draws an
   edge; a dropped idea stays in the table saying it was dropped. The "What
   changed" log under the table is the list of those moves.

   Each row opens into its editor and its numbered + notes. The JOURNAL (typed
   :TaskEntry rows — note, progress, blocker, reflection) used to be listed and
   written here too; its UI was removed 2026-11-08 at the user's request. The
   entries and /api/tasks/{id}/entries stay — Activity, Planner, Phases,
   Calendar and the voice agent still read or write them — and the row's
   "N entries" tag and the "journal entries" stat still count them. Progress
   (the old third table over these :Task nodes) is gone; its "completed"
   section is the Archive's `done` chip.

   TO DO AND ARCHIVE (mainframe_inbox_done.html). The main table is only what
   is still to do: raw ideas, open tasks and notes. Everything that has left —
   given, became, done, dropped — is the Archive card under it, dated by when
   it left. Ideas go somewhere or get closed; tasks get ticked. Closing an idea
   or dropping a row takes an optional one-line why, typed in a line that opens
   under the row.

   A ★ marks a row that matters, and starred rows lift out of the list into
   their own table above it. They are lifted rather than copied: the same row
   in two tables on one screen reads as two rows, and you would tick one and
   wonder why the other didn't change. The star is a marker, not a status —
   it says nothing about where the work is going, which is why it draws no
   line in "What changed".

   Cache2 is the shelf: rows you have not decided against and are not doing
   now. They leave the working view entirely — that is the whole point of
   putting something down — and live under their own chip until you bring one
   back. Dropped rows stay visible because they are a decision; cached rows
   hide because they are the absence of one. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const FILTERS = ["to do", "ideas", "tasks", "notes", "starred", "this phase", "questions", "cache2", "archive"];
  const ARCHIVED = new Set(["given", "became", "done", "dropped"]);
  const ARCH_FILTERS = ["all", "given", "became", "done", "dropped"];
  const ARCH_PAGE = 50;
  const isArchived = (r) => ARCHIVED.has(r.status);
  // A row moved to Questions (it carries a :Question) has left the to-do list:
  // it is worked in the Questions tab and waits here under its own chip.
  const isQuestion = (r) => !!r.question && r.status !== "cached" && !isArchived(r);
  const isLive = (r) => r.status !== "cached" && !isArchived(r) && !r.question;
  const COLS = 15;   // columns in the to-do table — journal and empty rows span them

  const PRIORITIES = ["low", "medium", "high"];

  let rows = [], log = [], projects = [];
  let filter = "to do";
  let archFilter = "all", archQuery = "", archShown = ARCH_PAGE;
  // The row whose close line is open: { id, what: "done" | "drop" }.
  let closing = null;
  let host = null;
  // Which rows are expanded into their journal. Kept across re-draws, so
  // adding a note doesn't collapse the row you were writing in.
  const open = new Set();
  // A + in the notes column opens the row with its notes box ready to type in.
  let noteFocus = null;

  const B = "/api/synapse";

  async function reload() {
    const [r, l, tree] = await Promise.all([
      api.get(B + "/inbox"),
      api.get(B + "/inbox/log"),
      api.get(B + "/projects"),
    ]);
    rows = r; log = l;
    // The list endpoint already returns each project's full path, so the
    // picker no longer rebuilds it from parent ids.
    projects = tree.projects.slice().sort((a, b) => a.path.localeCompare(b.path));
    render();
  }

  /* A cached row is out of the way everywhere except its own chip. Filtering
     it out of "ideas" and "tasks" too is deliberate: a shelf that still shows
     up in every other list is not a shelf. */
  function rowsFor(f) {
    if (f === "cache2") return rows.filter((r) => r.status === "cached");
    if (f === "questions") return rows.filter(isQuestion);
    if (f === "archive") return rows.filter(isArchived);
    return rows.filter(isLive).filter((r) =>
      f === "ideas" ? r.kind === "idea"
      : f === "tasks" ? r.kind === "task"
      : f === "notes" ? r.kind === "note"
      : f === "starred" ? r.starred
      : f === "this phase" ? !!(r.for_phase && r.for_phase.active)
      : true);
  }
  function visible() { return rowsFor(filter); }

  /* When a row left "to do", newest first; rows closed before dates were kept
     sort last. */
  function archived() {
    const q = archQuery.trim().toLowerCase();
    return rows.filter(isArchived)
      .filter((r) => archFilter === "all" || r.status === archFilter)
      .filter((r) => !q || (r.title + " " + (r.why || "")).toLowerCase().includes(q))
      .sort((a, b) => String(b.closed || "").localeCompare(String(a.closed || "")));
  }

  /* ---- moves ------------------------------------------------------------ */
  /* Every move goes through one modal shape: whatever the move needs, then a
     why. The why is optional and always last, because it is the same question
     every time and it should sit in the same place every time. */
  function moveModal(title, fields, note, onOk) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const why = el("input.mform-input", { placeholder: "one line, optional" });
    const card = el("div.modal.ib-modal", {}, [
      el("div.modal-title", { text: title }),
      ...fields.map((f) => f.node),
      note ? el("div.ib-note", { text: note }) : null,
      el("div.mform-full", {}, [
        el("div.mform-label", { text: "why" }), why,
      ]),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn.teal", { text: "do it", onclick: () => onOk(why.value.trim(), close) }),
        el("button.tk-btn", { text: "cancel", onclick: close }),
      ]),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const first = card.querySelector("input,select,textarea");
    if (first) first.focus();
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && e.target.tagName !== "TEXTAREA") {
        e.preventDefault(); onOk(why.value.trim(), close);
      }
      if (e.key === "Escape") close();
    });
  }

  /* A project picker, optionally with a "(top level)" entry. Shows full paths
     so two projects called "notes" under different parents are tellable
     apart. */
  function projectSelect(label, withTop, exclude) {
    const opts = [];
    if (withTop) opts.push(el("option", { value: "", text: "(top level)" }));
    projects.filter((p) => p.id !== exclude)
      .forEach((p) => opts.push(el("option", { value: p.id, text: p.path })));
    const sel = el("select.mform-input", {}, opts);
    return {
      node: el("div.mform-full", {}, [el("div.mform-label", { text: label }), sel]),
      get: () => sel.value,
    };
  }

  function doMove(row, what) {
    if (what === "drop") {
      closing = { id: row.id, what: "drop" };
      return render();
    }
    if (what === "question") return toggleQuestion(row);
    if (what === "cache") {
      return moveModal(`put "${row.title}" in cache2`, [],
        "out of the Inbox, not decided against \u2014 it waits under the cache2 chip",
        (why, close) => guard(async () => {
          await api.post(B + "/inbox/" + row.id + "/cache", { why });
          close(); toast("in cache2"); await reload();
        }));
    }
    if (what === "complete") {
      if (row.kind !== "idea") return markDone(row);
      closing = { id: row.id, what: "done" };
      return render();
    }
    if (what === "reopen") return guard(async () => {
      await api.post(B + "/inbox/" + row.id + "/reopen", {});
      toast("back in the Inbox");
      await reload();
    });
    if (what === "uncache") {
      return guard(async () => {
        await api.post(B + "/inbox/" + row.id + "/uncache", { why: "" });
        toast("back in the Inbox");
        await reload();
      });
    }
    if (what === "give") {
      if (!projects.length) return toast("no projects yet — make one in the Project tab", true);
      const pick = projectSelect("project", false);
      return moveModal(`give "${row.title}" to`, [pick], null, (why, close) =>
        guard(async () => {
          await api.post(B + "/inbox/" + row.id + "/give",
            { project_id: pick.get(), why });
          close(); toast("given"); await reload();
        }));
    }
    if (what === "promote") {
      const pick = projectSelect("under", true);
      return moveModal(`promote "${row.title}" to a project`, [pick],
        "the idea's text becomes the project's first why",
        (why, close) => guard(async () => {
          await api.post(B + "/inbox/" + row.id + "/promote",
            { parent_id: pick.get() || null, why });
          close(); toast("promoted"); await reload();
        }));
    }
    if (what === "grow") {
      const pick = projectSelect("under", true);
      return moveModal(`grow "${row.title}" into a project`, [pick],
        "the task becomes the new project's first child, with its sessions",
        (why, close) => guard(async () => {
          await api.post(B + "/inbox/" + row.id + "/grow",
            { parent_id: pick.get() || null, why });
          close(); toast("grown"); await reload();
        }));
    }
  }

  function flip(row, kind) {
    guard(async () => {
      await api.patch(B + "/inbox/" + row.id, { kind });
      await reload();
    });
  }

  /* Two stars, two buttons side by side: yellow ★ = priority, teal ★ =
     possible priority (stored as tone "soon"). Each toggles its own tone; a
     row carries at most one, so clicking the other one switches it over. */
  function toggleStar(r, tone) {
    const next = r.starred && (r.star_tone || "priority") === tone
      ? { starred: false } : { starred: true, tone };
    guard(async () => {
      const saved = await api.post(B + "/inbox/" + r.id + "/star", next);
      Object.assign(r, saved);
      render();
    });
  }

  /* ◆ — do this in the current phase. Draws the FOR_PHASE edge to the active
     phase; the row stays here and also shows in the Phases tab. */
  function togglePhase(r) {
    const on = !(r.for_phase && r.for_phase.active);
    guard(async () => {
      const saved = await api.post(B + "/inbox/" + r.id + "/phase", { on });
      Object.assign(r, saved);
      toast(on ? "in this phase — " + saved.for_phase.name : "out of this phase");
      render();
    });
  }

  /* ❓ — this row IS a question.

     Questions asked in a reading pass already land here as ideas (see
     routes/questions.py). This is the same fact written from the other end:
     the thing you typed at 11pm that turns out to be a question rather than a
     plan. It writes a real :Question, so the row joins the Questions tab and
     can be answered there — a chip that only coloured the row would leave the
     question in the one place that cannot answer it.

     Marking reuses this row rather than writing a second one, which is what
     `row_id` exists for. Unmarking deletes the question and leaves the row:
     the row may have been given to a project by then. The category goes back
     to blank only if marking is what filled it, so a row you filed under "rq"
     keeps its own word. */
  function toggleQuestion(r) {
    guard(async () => {
      if (r.question) {
        await api.del("/api/questions/" + r.question.id);
        if ((r.category || "") === "question")
          await api.patch(B + "/inbox/" + r.id, { category: "" });
        toast("no longer a question");
      } else {
        await api.post("/api/questions", {
          text: r.title, kind: "question", parent_id: r.id, row_id: r.id,
        });
        toast("→ Questions tab — off the to-do list");
      }
      await reload();
    });
  }

  function markDone(row, why) {
    guard(async () => {
      await api.post(B + "/inbox/" + row.id + "/done", { why: why || "" });
      closing = null;
      toast("done → archive");
      await reload();
    });
  }

  function dropRow(row, why) {
    guard(async () => {
      await api.post(B + "/inbox/" + row.id + "/drop", { why: why || "" });
      closing = null;
      toast("dropped → archive");
      await reload();
    });
  }

  /* The line that opens under a row when you close an idea or drop anything:
     one optional sentence, Enter to commit, Escape to back out. */
  function closeLine(r, cols) {
    const isDone = closing.what === "done";
    const input = el("input.ib-closein", {
      placeholder: isDone ? "answered it: it's the ratio that matters, not either alone"
                          : "not this phase",
    });
    const go = () => (isDone ? markDone(r, input.value.trim()) : dropRow(r, input.value.trim()));
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); go(); }
      if (e.key === "Escape") { closing = null; render(); }
    });
    setTimeout(() => input.focus(), 0);
    return el("tr.ib-closeline" + (isDone ? "" : ".drop"), {}, [
      el("td", { colspan: String(cols) }, [
        el("span.ib-closemeta", { text: (isDone ? "closing an idea" : "dropping a " + r.kind) + " · optional line" }),
        input,
        el("button.btn-sm.btn-primary", { text: isDone ? "close" : "drop", onclick: go }),
        el("button.btn-sm", { text: "cancel", onclick: () => { closing = null; render(); } }),
      ]),
    ]);
  }

  /* fri 9 oct, or today / tomorrow / wed when it is this week. */
  function fmtDue(iso) {
    if (!iso) return "";
    const d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return iso;
    const t = new Date(); t.setHours(0, 0, 0, 0);
    const days = Math.round((d - t) / 86400000);
    const wd = d.toLocaleDateString("en-GB", { weekday: "short" }).toLowerCase();
    if (days === 0) return "today";
    if (days === 1) return "tomorrow";
    if (days > 1 && days < 7) return wd;
    return wd + " " + d.getDate() + " " + d.toLocaleDateString("en-GB", { month: "short" }).toLowerCase();
  }

  /* "/clean laptop fri" — a leading / makes it a task, and a trailing day word
     becomes its due date. */
  const DAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
  function parseAdd(text, kind) {
    let title = text.trim(), due = "";
    if (title.startsWith("/")) { kind = "task"; title = title.slice(1).trim(); }
    if (kind !== "idea") {
      const m = /\s+(today|tomorrow|tmr|mon|tue|wed|thu|fri|sat|sun)[a-z]*$/i.exec(title);
      if (m) {
        const w = m[1].toLowerCase(), d = new Date();
        if (w === "tomorrow" || w === "tmr") d.setDate(d.getDate() + 1);
        else if (w !== "today") d.setDate(d.getDate() + ((DAYS.indexOf(w) - d.getDay() + 7) % 7));
        due = window.ui.todayISO(d);
        title = title.slice(0, m.index).trim();
      }
    }
    return { title, kind, due };
  }

  function reopen(row) {
    guard(async () => {
      await api.post(B + "/inbox/" + row.id + "/reopen", {});
      await reload();
    });
  }

  /* ---- do on / takes -----------------------------------------------------
     When you mean to do it (not the deadline, that's `due`) and how long you
     expect it to take. A row with a date and a time is a block on the Calendar,
     worked out on read; takes accepts 45, 45m, 1h30, 1.5h or 1:30. */
  function parseTakes(v) {
    const t = String(v || "").trim().toLowerCase().replace(/\s+/g, "");
    if (!t) return 0;
    let m = /^(\d+(?:\.\d+)?)$/.exec(t);
    if (m) return Math.round(+m[1]);
    m = /^(\d+):(\d{2})$/.exec(t);
    if (m) return +m[1] * 60 + +m[2];
    m = /^(?:(\d+(?:\.\d+)?)h)?(?:(\d+)m?)?$/.exec(t);
    if (m && (m[1] || m[2])) return Math.round((+m[1] || 0) * 60) + (+m[2] || 0);
    return null;
  }
  function fmtTakes(n) {
    n = +n || 0;
    if (!n) return "";
    const h = Math.floor(n / 60), m = n % 60;
    return h ? h + "h" + (m ? String(m).padStart(2, "0") : "") : m + "m";
  }
  function whenCells(r) {
    const patch = (body) => guard(async () => {
      const saved = await api.patch(B + "/inbox/" + r.id, body);
      Object.assign(r, saved);
    });
    const settled = r.status === "became";
    const day = el("input.ib-when-d", { type: "date", value: r.do_on || "", title: "the day you mean to do it" });
    const at = el("input.ib-when-t", { type: "time", value: r.do_at || "",
      title: "a time puts it on the Calendar as a block" });
    day.addEventListener("change", () => patch({ do_on: day.value || "" }));
    at.addEventListener("change", () => {
      if (at.value && !day.value) { day.value = window.ui.todayISO(); patch({ do_on: day.value, do_at: at.value }); }
      else patch({ do_at: at.value || "" });
    });
    const takes = el("input.ib-takes", { value: fmtTakes(r.takes_min), placeholder: "45m",
      title: "how long you expect it to take: 45, 45m, 1h30, 1.5h" });
    takes.addEventListener("change", () => {
      const n = parseTakes(takes.value);
      if (n === null) { toast("say it like 45m, 1h30 or 1.5h", true); takes.value = fmtTakes(r.takes_min); return; }
      takes.value = fmtTakes(n);
      patch({ takes_min: n });
    });
    [day, at, takes].forEach((i) => { i.disabled = settled; });
    return [el("td.ib-when", { "data-no-now": "" }, [day, at]), el("td.ib-takescell", {}, [takes])];
  }

  /* ---- due / started ----------------------------------------------------
     due is when you want it done by; started is the day you actually began.
     Together with do on (when you mean to) they bracket the row: planned,
     begun, wanted done. */
  function rowPatch(r, body) {
    return guard(async () => {
      const saved = await api.patch(B + "/inbox/" + r.id, body);
      Object.assign(r, saved);
      render();
    });
  }
  function dueInput(r) {
    const i = el("input.ib-due-d", { type: "date", value: r.due || "" });
    i.disabled = r.status === "became";
    i.addEventListener("change", () => rowPatch(r, { due: i.value || "" }));
    return i;
  }
  /* The start column: a date you set. Empty, it is a picker plus a one-click
     "today"; set, it stays a picker so it can be moved or cleared. */
  function startedMark(r) {
    const d = el("input.ib-started-d" + (r.started_on ? ".on" : ""), { type: "date",
      value: r.started_on || "", title: "the day you started it — clear it to un-start" });
    d.disabled = r.status === "became";
    d.addEventListener("change", () => rowPatch(r, { started_on: d.value || "" }));
    const live = r.status === "raw" || r.status === "open" || r.status === "given";
    return [d, !r.started_on && live
      ? el("button.ib-start", { text: "today", title: "started it today",
          onclick: () => rowPatch(r, { started_on: window.ui.todayISO() }) }) : null];
  }

  /* x days / x weeks until the due date, counted from today. Under two weeks
     it says days, after that weeks, so the number stays one you can feel. */
  function daysLeft(iso) {
    if (!iso) return null;
    const d = new Date(iso + "T00:00:00");
    if (isNaN(d)) return null;
    const t = new Date(); t.setHours(0, 0, 0, 0);
    return Math.round((d - t) / 86400000);
  }
  function fmtSpan(n) {
    n = Math.abs(n);
    if (n < 14) return n + (n === 1 ? " day" : " days");
    const w = Math.round(n / 7);
    return w + " weeks";
  }
  function leftCell(r) {
    const n = daysLeft(r.due);
    if (n === null || r.status === "done" || r.status === "became" || r.status === "dropped")
      return el("td.ib-left");
    const text = n === 0 ? "today" : n > 0 ? fmtSpan(n) : fmtSpan(n) + " late";
    // the planned span, start → due, rides along in the tooltip
    const s = daysLeft(r.started_on);
    const span = s !== null && n >= s ? fmtSpan(n - s) + " from start to due" : "";
    return el("td.ib-left" + (n < 0 ? ".late" : n <= 3 ? ".soon" : ""),
      { text, title: span || (n < 0 ? "past the due date" : "until the due date") });
  }

  /* ---- the journal ------------------------------------------------------ */
  /* Entries are :TaskEntry nodes owned by /api/tasks — the same ones Activity
     reads and reschedules. Writing them from here rather than inventing an
     Inbox-only note type is the whole reason a note added here shows up there. */
  function fmtMins(m) {
    m = m || 0;
    const h = Math.floor(m / 60), r = m % 60;
    return (h ? h + "h " : "") + r + "m";
  }

  /* Priority lives in the open journal rather than as an eighth column: the
     table is already as wide as it reads, and priority is something you set
     while thinking about a row, not while scanning the list. */
  function prioritySelect(r) {
    const cur = r.priority || "medium";
    const sel = el("select.prio-sel.prio-" + cur, {}, PRIORITIES.map((p) =>
      el("option", { value: p, text: p })));
    sel.value = cur;
    sel.addEventListener("change", () => guard(async () => {
      sel.className = "prio-sel prio-" + sel.value;
      await api.patch(B + "/inbox/" + r.id, { priority: sel.value });
      r.priority = sel.value;
      toast("priority → " + sel.value);
    }));
    return sel;
  }

  /* The editable fields. Every one of these already existed on the row and on
     InboxUpdate — there was simply nowhere to type them. They live in the open
     panel rather than as inline cells because the table is a list you scan,
     and editing is something you do to one row at a time.

     Saved on blur, not on a Save button: a form with a button you can walk
     away from is a form that loses what you typed. */
  function editor(r) {
    const save = (field, node, cast) => () => guard(async () => {
      const raw = cast ? cast(node.value) : node.value.trim();
      if (String(r[field] == null ? "" : r[field]) === String(raw)) return;
      const saved = await api.patch(B + "/inbox/" + r.id, { [field]: raw });
      Object.assign(r, saved);
      toast("saved");
    });

    const field = (label, node) => el("label.ib-efield", {},
      [el("span.ib-jlabel", { text: label }), node]);

    const title = el("input.mform-input", { value: r.title || "" });
    title.addEventListener("blur", save("title", title));

    const desc = el("input.mform-input", {
      placeholder: "the longer version — what it actually means, links, why it matters" });
    desc.value = r.description || "";
    desc.addEventListener("blur", save("description", desc));

    const cat = el("input.mform-input", { value: r.category || "",
      placeholder: "category" });
    cat.addEventListener("blur", save("category", cat));

    const due = el("input.mform-input", { type: "date", value: r.due || "" });
    due.addEventListener("change", save("due", due));

    // Hours are a low/high pair everywhere else in Mainframe — an estimate you
    // are honest about is a range, not a number.
    const num = (f) => {
      const n = el("input.mform-input", { type: "number", min: "0", step: "0.5",
        style: "width:84px", value: r[f] || "" });
      n.addEventListener("blur", save(f, n, (v) => Number(v) || 0));
      return n;
    };

    return el("div.ib-editor", {}, [
      field("title", title),
      field("description", desc),
      el("div.ib-erow", {}, [
        field("category", cat),
        field("due", due),
        field("hours (low)", num("low_h")),
        field("hours (high)", num("high_h")),
      ]),
    ]);
  }

  // inModal: the 👁 popup, which stays open; in the row panel, adding a note
  // closes the row (2026-11-08 — "once a note is added, close it").
  function notesBox(r, inModal) {
    // Keep the table's notes count in step as notes are added or removed,
    // without redrawing (a redraw would close the box you are typing in).
    let base = null;
    const box = window.RowBox({
      label: "notes", kind: "note", noun: "note", parentId: r.id,
      placeholder: "a note on this " + r.kind, extra: { inbox: false },
      once: true,
      onAdded: () => {
        toast("note added");
        if (!inModal) { open.delete(r.id); render(); }
      },
      onChange: (items) => {
        if (base === null) { base = items.length; return; }
        r.notes = (r.notes || 0) + items.length - base; base = items.length;
        const c = host && host.querySelector('td.ib-notes[data-id="' + r.id + '"] .ib-ncount');
        if (c) c.textContent = r.notes ? String(r.notes) : "";
      },
    });
    if (noteFocus === r.id) { noteFocus = null; setTimeout(() => box.open(), 0); }
    return box.node;
  }

  /* 👁 — read and edit a row's notes in a popup, without opening the row.
     Same RowBox as the expanded panel, so it is one store either way: click a
     note to edit it, + to add one. */
  function notesModal(r) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !e.target.closest(".lb-editor")) close();
    });
    overlay.appendChild(el("div.modal.ib-modal.ib-notesmodal", {}, [
      el("div.modal-title", { text: r.title }),
      notesBox(r, true),
      el("div.row", { style: "margin-top:16px;gap:8px" }, [
        el("button.tk-btn", { text: "close", onclick: close }),
      ]),
    ]));
    document.body.appendChild(overlay);
  }

  function journalRow(r, cols) {
    // A row that became a project is settled: its text is the record of what
    // you thought, and the server refuses edits to it anyway.
    const settled = r.status === "became";
    const body = el("td.ib-jcell", { colspan: String(cols || COLS) }, [
      el("div.row", { style: "gap:14px;align-items:center;flex-wrap:wrap" }, [
        el("span.ib-jlabel", { text: "priority" }), prioritySelect(r),
        r.total_mins ? el("span.ib-jlabel", { style: "color:var(--teal)",
          text: "⏱ " + fmtMins(r.total_mins) + " logged" }) : null,
      ]),
      settled ? el("div.ib-empty", { text: "this row became a project — its wording is part of the record now" }) : editor(r),
      // + notes on the row itself: one line each, Enter saves and opens the
      // next. inbox:false — a note on an Inbox row must not file a new row.
      el("div", { style: "margin-top:12px" }, [notesBox(r)]),
    ]);
    return el("tr.ib-journal", {}, [body]);
  }

  /* ---- render ----------------------------------------------------------- */
  function renderRow(r) {
    const kindSel = el("select.ib-kind", {
      onchange: (e) => flip(r, e.target.value),
    }, [
      el("option", { value: "idea", text: "idea" }),
      el("option", { value: "task", text: "task" }),
      el("option", { value: "note", text: "note" }),
    ]);
    kindSel.value = r.kind;
    // A row that became a project is settled: its kind is part of the record
    // of what happened, not a field any more.
    if (r.status === "became") kindSel.disabled = true;

    const isOpen = open.has(r.id);
    const caret = el("button.ib-caret", {
      text: isOpen ? "▾" : "▸",
      title: isOpen ? "close" : "open to edit it and read its journal",
      onclick: () => { if (isOpen) open.delete(r.id); else open.add(r.id); render(); },
    });

    const title = el("td", {}, [
      caret,
      el("span", { text: r.title }),
      // The entry count is the row's own history: a row with six entries has
      // been worked on, and that should be visible without opening it.
      (r.entries || []).length
        ? el("span.ib-jcount", { text: " " + r.entries.length
            + (r.entries.length === 1 ? " entry" : " entries") }) : null,
      r.total_mins ? el("span.ib-jmins", { text: " ⏱ " + fmtMins(r.total_mins) }) : null,
      r.came && r.came.label === "Project"
        ? el("span.ib-from", { text: " ← from " + r.came.name }) : null,
      r.came && r.came.label === "Paper"
        ? el("span.ib-from", { text: " ← " + r.came.name }) : null,
      // Spoken into the Journal and sent over. Worth saying on the row: a
      // point pulled out of a transcript reads differently from one you typed.
      r.came && r.came.label === "MindDump"
        ? el("span.ib-from", { title: r.came.name || "", text: " ← said in the journal" }) : null,
    ]);

    // The path is a link rather than text: "given to Games › Sample engine" is
    // only useful if it takes you there.
    const givenCell = el("td.ib-given");
    if (r.given) {
      givenCell.appendChild(el("a.ib-path", {
        text: r.given.path, title: "open this project in the Project tab",
        onclick: () => {
          if (window.Views.project && window.Views.project.focusOn)
            window.Views.project.focusOn(r.given.id);
          window.openTab("project");
        },
      }));
    } else if (r.became) {
      givenCell.appendChild(el("a.ib-path", {
        text: r.became.path, title: "open this project in the Project tab",
        onclick: () => {
          if (window.Views.project && window.Views.project.focusOn)
            window.Views.project.focusOn(r.became.id);
          window.openTab("project");
        },
      }));
    }

    // Tasks and notes are ticked; the tick sends them to the archive.
    const tickable = (r.kind === "task" || r.kind === "note") && r.status === "open";
    const chk = el("td.ib-chk", {}, [
      tickable ? el("input", { type: "checkbox", title: "tick it off — goes to the archive",
                               onchange: () => markDone(r) }) : null,
    ]);

    const status = el("td.ib-status", {}, [
      el("span.ib-st.st-" + r.status, { text: r.status === "cached" ? "cache2" : r.status }),
      // One click to take it off the shelf. Bringing something back is the
      // move you want to be easy — if it were buried in the dropdown the
      // cache would quietly become the place things go to die.
      r.status === "cached"
        ? el("button.ib-back", { text: "↩", title: "bring it back into the Inbox",
                                 onclick: () => doMove(r, "uncache") })
        : null,
    ]);

    // Every kind can carry a due — an idea you want done by a date is still
    // an idea. Set right here in the cell; the caret panel has the same field.
    const due = el("td.ib-due" + (r.due && r.due < window.ui.todayISO() ? ".late" : ""),
      { title: r.due ? fmtDue(r.due) : "when you want it done by" }, [dueInput(r)]);
    const when = whenCells(r);

    // "drop" is a button with its own line, not a dropdown entry: the select
    // fires the instant its value changes, and a stray pick dropped rows.
    const moveSel = el("select.ib-move", {
      onchange: (e) => { const v = e.target.value; e.target.value = ""; if (v) doMove(r, v); },
    }, [
      el("option", { value: "", text: "move to…" }),
      r.kind === "idea" ? el("option", { value: "promote", text: "promote → new project" }) : null,
      r.kind === "task" ? el("option", { value: "grow", text: "grow → new project" }) : null,
      el("option", { value: "give", text: "give to → project" }),
      !r.question && r.status !== "became"
        ? el("option", { value: "question", text: "question → Questions tab" }) : null,
      r.status !== "cached"
        ? el("option", { value: "cache", text: "cache2 → maybe one day" }) : null,
      r.status === "cached"
        ? el("option", { value: "uncache", text: "bring back → Inbox" }) : null,
    ].filter(Boolean));

    const acts = el("td.ib-acts", {}, [
      el("span.ib-actwrap", {}, [
        r.kind === "task" && r.given && window.Timers
          ? el("button.btn-sm", { text: "▶ start", title: "start a timer on this task",
              onclick: () => { window.Timers.start({ kind: "task", ref_id: r.id, label: r.title, module: "synapse" });
                               toast("timer started on " + r.title); } }) : null,
        moveSel,
        r.kind === "idea" && r.status === "raw"
          ? el("button.btn-sm", { text: "✓ done", title: "close this idea — with an optional line",
              onclick: () => doMove(r, "complete") }) : null,
        el("button.btn-sm", { text: "drop", title: "decided against — with an optional line",
          onclick: () => doMove(r, "drop") }),
      ]),
    ]);

    const tone = r.starred ? (r.star_tone || "priority") : "";
    const soon = tone === "soon", prio = tone === "priority", later = tone === "later";
    const star = el("button.ib-star" + (prio ? ".on" : ""), {
      text: prio ? "★" : "☆",
      title: prio ? "priority — click to unstar" : "priority (yellow star)",
      onclick: () => toggleStar(r, "priority"),
    });
    const star2 = el("button.ib-star.ib-star2" + (soon ? ".on.soon" : ""), {
      text: soon ? "★" : "☆",
      title: soon ? "possible priority — click to unstar" : "possible priority (teal star)",
      onclick: () => toggleStar(r, "soon"),
    });
    const star3 = el("button.ib-star.ib-star3" + (later ? ".on.later" : ""), {
      text: later ? "★" : "☆",
      title: later ? "could be important in a later phase — click to unstar"
                   : "could be important in a later phase (grey star)",
      onclick: () => toggleStar(r, "later"),
    });

    /* ⑤ — a five-minute job: finite, just do it. It is the row's takes,
       set to 5m, so the Calendar and Planner see the same number. */
    const isFive = r.takes_min > 0 && r.takes_min <= 5;
    const five = el("button.ib-five" + (isFive ? ".on" : ""), {
      text: "5",
      title: isFive ? "five-minute job — click to clear its takes"
                    : "mark as a five-minute job (sets takes to 5m)",
      onclick: () => rowPatch(r, { takes_min: isFive ? 0 : 5 }),
    });

    const inPhase = !!(r.for_phase && r.for_phase.active);
    const phaseBtn = el("button.ib-phase-btn" + (inPhase ? ".on" : ""), {
      text: "◆",
      title: inPhase ? "this phase (" + r.for_phase.name + ") — click to take it out"
                     : "do this in the current phase — it shows in the Phases tab too",
      onclick: () => togglePhase(r),
    });

    // Red × — deletes for real (drop is still the move for "decided against").
    const del = el("button.ib-del", {
      text: "×",
      title: "delete this row from Inbox. where it came from is kept",
      onclick: () => confirmDo(
        "Delete “" + (r.title || "this row") + "” from Inbox? The journal entry or paper "
        + "it came from stays. Use drop instead to keep a record that you decided "
        + "against it.",
        async () => {
          await api.del(B + "/inbox/" + r.id);
          toast("deleted");
          await reload();
        }),
    });

    /* Ideas only, and not once the row has become a project: a task is work
       you have decided on, and a question is what you have not. Answered
       questions keep the mark and grey it — the row still came out of one. */
    const qm = r.question;
    const qmark = (r.kind === "idea" || qm) && r.status !== "became"
      ? el("button.ib-q" + (qm ? ".on" : "") + (qm && qm.answered ? ".answered" : ""), {
          text: "?",
          title: qm
            ? (qm.answered ? "answered in the Questions tab — click to unmark"
                           : "open question in the Questions tab — click to unmark")
            : "mark as a question — it joins the Questions tab",
          onclick: () => toggleQuestion(r),
        })
      : null;

    const tr = el("tr.ib-row", { "data-nav": r.id }, [
      chk,
      el("td.ib-starcell", {}, [star, star2, star3, five, phaseBtn, del, qmark]),
      el("td", {}, [kindSel]),
      title,
      givenCell,
      el("td.ib-added", { text: fmtClosed(r.created_at), title: (r.created_at || "").slice(0, 10) }),
      el("td.ib-startcell", {}, startedMark(r)),
      due,
      leftCell(r),
      status,
      ...when,
      el("td.ib-notes", { "data-id": r.id }, [
        el("span.ib-ncount", { text: r.notes ? String(r.notes) : "" }),
        el("button.ib-nadd", { text: "+", title: "add a note to this row",
          onclick: () => { open.add(r.id); noteFocus = r.id; render(); } }),
        el("button.ib-nadd.ib-neye", { text: "👁", title: "view and edit this row's notes",
          onclick: () => notesModal(r) }),
      ]),
      el("td.ib-cat", { text: r.kind === "idea" || r.kind === "note" ? (r.category || "") : "" }),
      acts,
    ]);
    if (r.status === "cached") tr.classList.add("ib-cached");
    if (inPhase) tr.classList.add("ib-inphase");
    // Rows from a + box (note, look into, follow-up…) and questions carry the
    // box's colour, the same one the box draws (listbox.js), so where a row
    // came from reads at a glance. A category you typed yourself is not tinted.
    const toneKey = qm ? "question" : (r.category || "");
    if (window.RowTones && window.RowTones[toneKey]) {
      tr.classList.add("ib-toned");
      tr.style.setProperty("--ib-tone", window.RowTones[toneKey]);
    }
    return tr;
  }

  /* ---- the archive ------------------------------------------------------ */
  function fmtClosed(iso) {
    if (!iso) return "—";
    const d = new Date(iso.length <= 10 ? iso + "T00:00:00" : iso);
    if (isNaN(d)) return String(iso).slice(0, 10);
    const s = d.getDate() + " " + d.toLocaleDateString("en-GB", { month: "short" }).toLowerCase();
    return d.getFullYear() === new Date().getFullYear() ? s : s + " " + d.getFullYear();
  }

  function projectLink(p) {
    return el("a.ib-path", {
      text: p.path || p.name, title: "open this project in the Project tab",
      onclick: () => {
        if (window.Views.project && window.Views.project.focusOn) window.Views.project.focusOn(p.id);
        window.openTab("project");
      },
    });
  }

  function archiveRow(r) {
    const isOpen = open.has(r.id);
    const wentTo = el("td.ib-given", {}, [
      r.became ? projectLink(r.became) : r.given ? projectLink(r.given)
        : r.kind !== "idea" ? el("span.ib-none", { text: "no project" }) : null,
      r.became && r.became.name && r.became.name !== r.title
        ? el("span.ib-none", { text: ' · became "' + r.became.name + '"' }) : null,
      r.total_mins ? el("span.ib-none", { text: " · " + (r.total_mins / 60).toFixed(1).replace(/\.0$/, "") + "h" }) : null,
    ]);
    return el("tr.ib-row.ib-arch", { "data-nav": r.id }, [
      el("td.ib-closed", { text: fmtClosed(r.closed) }),
      el("td", {}, [el("span.ib-kindtag.k-" + r.kind, { text: r.kind })]),
      el("td", {}, [
        el("button.ib-caret", { text: isOpen ? "▾" : "▸", title: "open its journal",
          onclick: () => { if (isOpen) open.delete(r.id); else open.add(r.id); render(); } }),
        el("span", { text: r.title }),
        r.why ? el("span.ib-why", { text: " · " + r.why }) : null,
        r.came && r.came.name ? el("span.ib-from", { text: " ← " + (r.came.label === "Question" ? "question" : r.came.name) }) : null,
      ]),
      wentTo,
      el("td", {}, [el("span.ib-st.st-" + r.status, { text: r.status })]),
      el("td.ib-acts", {}, [
        r.status === "done" || r.status === "dropped"
          ? el("span.ib-actwrap", {}, [el("button.btn-sm", { text: "reopen", title: "back to to do",
              onclick: () => doMove(r, "reopen") })]) : null,
      ]),
    ]);
  }

  function renderArchive() {
    const all = rows.filter(isArchived);
    const list = archived();
    const chips = el("div.ib-chips", {}, ARCH_FILTERS.map((f) =>
      el("button.ib-chip" + (f === archFilter ? ".on" : ""), {
        onclick: () => { archFilter = f; archShown = ARCH_PAGE; render(); },
      }, [document.createTextNode(f),
          f === "all" ? null : el("b", { text: String(all.filter((r) => r.status === f).length) })])));
    const search = el("input.ib-archsearch", { placeholder: "search the archive", value: archQuery });
    search.addEventListener("input", () => {
      archQuery = search.value; archShown = ARCH_PAGE;
      const pos = search.selectionStart;
      render();
      const again = host.querySelector(".ib-archsearch");
      if (again) { again.focus(); again.setSelectionRange(pos, pos); }
    });
    const body = list.slice(0, archShown).flatMap((r) =>
      open.has(r.id) ? [archiveRow(r), journalRow(r, 6)] : [archiveRow(r)]);
    if (!list.length) body.push(el("tr", {}, [el("td.ib-empty", { colspan: "6",
      text: archQuery ? "nothing in the archive matches" : "nothing archived yet" })]));
    if (list.length > archShown) body.push(el("tr", {}, [el("td.ib-more", { colspan: "6" }, [
      el("button.btn-sm", { text: (list.length - archShown) + " more · show " + Math.min(ARCH_PAGE, list.length - archShown),
        onclick: () => { archShown += ARCH_PAGE; render(); } }),
    ])]));
    return el("section.card.ib-card.ib-archive", {}, [
      el("div.ib-bar", {}, [
        el("h2", { text: "Archive · " + all.length }),
        search,
        chips,
      ]),
      el("table.ib-table", {}, [
        el("thead", {}, [el("tr", {}, ["closed", "kind", "title", "went to", "status", ""]
          .map((h) => el("th", { text: h })))]),
        el("tbody", {}, body),
      ]),
    ]);
  }

  /* ---- paste a column in -------------------------------------------------
     One row per non-blank line. From a multi-column copy, the first filled
     cell of each line is the title. Repeats are folded twice over — within
     the paste ("AlexNet" three times is one row) and against what the Inbox
     already holds, which start unticked — comparing on letters and digits
     only, so "Batch Normalization" and "batch normalization" are one. */
  const normTitle = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "");

  function pasteModal(text, kindValue) {
    const have = new Map(rows.map((r) => [normTitle(r.title), r]));
    const seen = new Map();
    text.split(/\r?\n|\r/).forEach((line) => {
      const title = (line.split("\t").map((c) => c.trim()).find(Boolean) || "").trim();
      const k = normTitle(title);
      if (!k) return;
      if (seen.has(k)) { seen.get(k).times++; return; }
      const existing = have.get(k);
      seen.set(k, { title, times: 1, existing, keep: !existing });
    });
    const items = [...seen.values()];

    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const kindSel = el("select.btn-sm", {}, ["idea", "task", "note"].map((v) => el("option", { value: v, text: v })));
    kindSel.value = kindValue || "idea";
    const cat = el("input.btn-sm", { placeholder: "category (optional), e.g. paper", style: "width:220px" });
    const addBtn = el("button.btn-primary");
    const sync = () => {
      const n = items.filter((i) => i.keep).length;
      addBtn.disabled = !n;
      addBtn.textContent = n ? "add " + n + " row" + (n > 1 ? "s" : "") : "nothing ticked";
    };

    const dupesIn = items.filter((i) => i.times > 1).length;
    const already = items.filter((i) => i.existing).length;
    const list = el("div", { style: "max-height:52vh;overflow:auto;margin:10px 0;border:1px solid var(--border);border-radius:8px" },
      items.map((it) => {
        const box = el("input", { type: "checkbox" });
        box.checked = it.keep;
        box.addEventListener("change", () => { it.keep = box.checked; sync(); });
        const t = el("input.btn-sm", { value: it.title, style: "flex:1;min-width:0" });
        t.addEventListener("change", () => { it.title = t.value.trim(); });
        const tags = [
          it.times > 1 ? el("span.sub", { text: "×" + it.times + " in paste", style: "color:var(--amber);white-space:nowrap" }) : null,
          it.existing ? el("span.sub", { text: "already in Inbox (" + (it.existing.status || "") + ")", style: "color:var(--muted);white-space:nowrap" }) : null,
        ];
        return el("label.row", { style: "gap:8px;align-items:center;padding:4px 10px;border-bottom:1px solid var(--border)" },
          [box, t, ...tags]);
      }));

    addBtn.addEventListener("click", () => guard(async () => {
      const titles = items.filter((i) => i.keep && i.title).map((i) => i.title);
      addBtn.disabled = true;
      addBtn.textContent = "adding " + titles.length + "…";
      const res = await api.post(B + "/inbox/bulk", {
        titles, kind: kindSel.value, category: cat.value.trim() });
      toast(res.created + " row" + (res.created === 1 ? "" : "s") + " added");
      close();
      await reload();
    }));

    overlay.appendChild(el("div.modal", { style: "max-width:760px;width:94vw;max-height:90vh" }, [
      el("div.modal-title", { text: "Add " + items.length + " rows to the Inbox" }),
      el("div.sub", { text: [
        dupesIn ? dupesIn + " repeated in the paste, folded into one each" : "",
        already ? already + " already in the Inbox — unticked" : "",
      ].filter(Boolean).join(" · ") || "one row per line — edit a title before adding if you like" }),
      el("div.row", { style: "gap:8px;margin-top:10px;align-items:center;flex-wrap:wrap" }, [
        el("span.sub", { text: "add as" }), kindSel, cat,
        el("button.btn-sm", { text: "tick all", onclick: () => { items.forEach((i) => { i.keep = true; }); list.querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = true; }); sync(); } }),
        el("button.btn-sm", { text: "untick all", onclick: () => { items.forEach((i) => { i.keep = false; }); list.querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = false; }); sync(); } }),
      ]),
      list,
      el("div.row", { style: "gap:8px" }, [addBtn, el("button.btn-sm", { text: "cancel", onclick: close })]),
    ]));
    document.body.appendChild(overlay);
    sync();
  }

  function render() {
    clear(host);

    // filters + add box. Each chip carries its count.
    const chips = el("div.ib-chips", {}, FILTERS.map((f) =>
      el("button.ib-chip" + (f === filter ? ".on" : ""), {
        onclick: () => { filter = f; render(); },
      }, [document.createTextNode(f), el("b", { text: String(rowsFor(f).length) })])));

    const input = el("input.ib-add", { placeholder: "add an idea or a task. start with / for a task, e.g. /clean laptop fri — or paste a whole column" });
    const kind = el("select.ib-addkind", {}, [
      el("option", { value: "idea", text: "idea" }),
      el("option", { value: "task", text: "task" }),
      el("option", { value: "note", text: "note", title: "a quick to-do with a tick box" }),
    ]);
    input.addEventListener("keydown", (e) => {
      // isComposing / 229: the input method's own Enter, which is followed by
      // the real one. Acting on both saved the row twice.
      if (e.key !== "Enter" || e.isComposing || e.keyCode === 229 || e.repeat
          || !input.value.trim()) return;
      const got = parseAdd(input.value, kind.value);
      input.value = "";
      if (!got.title) return;
      guard(async () => {
        const made = await api.post(B + "/inbox", { title: got.title, kind: got.kind });
        if (got.due && made && made.id) await api.patch(B + "/inbox/" + made.id, { due: got.due });
        await reload();
      });
    });
    // A single-line <input> squashes a multi-line paste into one long row.
    // Catch it first: a column copied out of a spreadsheet becomes one row
    // per line, through a preview.
    input.addEventListener("paste", (e) => {
      const text = (e.clipboardData || window.clipboardData).getData("text");
      if (!/\r|\n/.test(text.trim())) return;          // one line: normal paste
      e.preventDefault();
      pasteModal(text, kind.value);
    });

    /* One table definition, drawn twice — starred above, the rest below. Two
       copies of this markup would drift the moment a column changed. */
    function table(list, emptyText) {
      const t = el("table.ib-table", {}, [
        el("thead", {}, [el("tr", {}, ["", "", "kind", "title", "given to", "added", "start", "due", "left",
          "status", "do on", "takes", "notes", "category", ""].map((h) => el("th", { text: h })))]),
        // An expanded row is followed by its journal as a second <tr>, so the
        // table keeps its columns and the journal gets the full width; a row
        // being closed is followed by its close line.
        el("tbody", {}, list.flatMap((r) => [
          renderRow(r),
          closing && closing.id === r.id ? closeLine(r, COLS) : null,
          open.has(r.id) ? journalRow(r) : null,
        ].filter(Boolean))),
      ]);
      if (!list.length && emptyText) {
        t.querySelector("tbody").appendChild(
          el("tr", {}, [el("td.ib-empty", { colspan: String(COLS), text: emptyText })]));
      }
      return t;
    }

    const shown = visible();
    // Under the starred chip the starred rows ARE the list; everywhere else
    // they are lifted into their own table above it.
    // Lifted in order — priority ★, soon ★, then ⑤ five-minute jobs — and
    // each row only once: a starred five-minute job sits with its star.
    const lift = filter !== "archive";
    const isFive = (r) => r.takes_min > 0 && r.takes_min <= 5;
    const toneOf = (r) => r.starred ? (r.star_tone || "priority") : "";
    const priority = lift ? shown.filter((r) => toneOf(r) === "priority") : [];
    const soonRows = lift ? shown.filter((r) => toneOf(r) === "soon") : [];
    // grey ★ — later phase. Lifted out like the others, but drawn UNDER the
    // to-do list: it is the least pressing of the three.
    const laterRows = lift ? shown.filter((r) => toneOf(r) === "later") : [];
    const fives = lift ? shown.filter((r) => !r.starred && isFive(r)) : [];
    const rest = lift ? shown.filter((r) => !r.starred && !isFive(r)) : shown;
    const starred = priority.concat(soonRows, laterRows);

    host.appendChild(stats());

    host.appendChild(el("section.card.ib-card", {}, [
      el("div.ib-addrow", {}, [input, kind]),
      el("div.ib-bar", {}, [
        chips,
        el("span.ib-hint", {
          text: filter === "cache2"
            ? "put down, not decided against — ↩ brings one back"
            : filter === "questions"
            ? "moved to the Questions tab — answer them there. click ? on a row to bring it back to to do"
            : "to do = raw ideas and open tasks. everything else is in the archive.",
        }),
      ]),
    ]));

    // The starred table only exists when something is starred — an empty
    // "important" table above everything is a permanent reproach.
    const liftedCard = (cls, heading, hint, list) => list.length
      ? host.appendChild(el("section.card.ib-card." + cls, {}, [
          el("div.ib-bar", {}, [el("h2", { text: heading + " · " + list.length }),
                                el("span.ib-hint", { text: hint })]),
          table(list),
        ])) : null;
    liftedCard("ib-starred", "★ Priority", "yellow star — click it to put one back", priority);
    liftedCard("ib-soon", "★ Possible priority", "teal star — click it to put one back", soonRows);
    liftedCard("ib-fives", "⑤ Five-minute jobs", "finite, quick — click the 5 to put one back", fives);
    // The shelf, in view under the five-minute jobs (asked for 2026-11-08) —
    // the cache2 chip still shows it on its own.
    if (filter !== "cache2" && filter !== "archive") {
      liftedCard("ib-cache2", "cache2 · shelved", "not now, not dropped — ↩ brings one back to the list",
        rows.filter((r) => r.status === "cached"));
    }

    if (filter !== "archive") {
      host.appendChild(el("section.card.ib-card", {}, [
        table(rest, filter === "cache2"
          ? "cache2 is empty — nothing shelved for later"
          : starred.length || fives.length ? "everything here is lifted, above" : "nothing to do here"),
        filter === "cache2" ? null : el("div.ib-hint.ib-foot", {
          text: "every row can carry a do-on day, a started date and a due date. a ticked task and a closed idea both go to the archive with today's date." }),
      ]));
    }

    liftedCard("ib-later", "★ Later phase", "grey star — could be important in a later phase. click it to put one back", laterRows);

    if (filter !== "cache2") host.appendChild(renderArchive());

    host.appendChild(renderLog());
  }

  /* The stats the Progress tab opened with, counted off the Inbox's own model
     rather than the done/horizon one it used to assume. "Shelved" is here
     because a growing cache2 is worth seeing without clicking into it. */
  function stats() {
    const live = rows.filter((r) => r.status !== "cached");
    const box = (val, label, color) => el("div.prog-box", {}, [
      el("div.prog-val", { style: "color:" + color, text: String(val) }),
      el("div.prog-label", { text: label }),
    ]);
    return el("div.prog-grid", {}, [
      box(live.filter((r) => r.kind === "task" && r.status === "open").length, "open tasks", "var(--amber)"),
      box(live.filter((r) => r.status === "done").length, "done", "var(--teal)"),
      box(live.filter((r) => r.kind === "idea" && r.status === "raw").length, "raw ideas", "var(--blue)"),
      box(rows.reduce((a, r) => a + (r.entries || []).length, 0), "journal entries", "var(--purple)"),
      box(fmtMins(rows.reduce((a, r) => a + (r.total_mins || 0), 0)), "time logged", "var(--teal)"),
      box(live.filter((r) => r.starred).length, "starred", "var(--amber)"),
      box(rows.filter((r) => r.status === "cached").length, "shelved", "var(--purple)"),
    ]);
  }

  function renderLog() {
    const body = log.map((m) => el("tr", {}, [
      el("td.ib-when", { text: when(m.at) }),
      el("td", { text: m.frm }),
      el("td.ib-edge", { text: m.edge }),
      el("td", { text: m.to }),
      el("td.ib-why", { text: m.why }),
    ]));
    if (!body.length) {
      body.push(el("tr", {}, [el("td.ib-empty", { colspan: "5", text: "nothing written yet" })]));
    }
    return el("section.card.ib-log", {}, [
      el("div.ib-bar", {}, [
        el("h2", { text: "What changed" }),
        el("span.ib-hint", { text: "the edges written by moves, newest first" }),
      ]),
      el("table.ib-table", {}, [
        el("thead", {}, [el("tr", {}, [
          el("th", { text: "when" }), el("th", { text: "from" }),
          el("th", { text: "edge" }), el("th", { text: "to" }),
          el("th", { text: "why" }),
        ])]),
        el("tbody", {}, body),
      ]),
    ]);
  }

  /* HH:MM for anything today, and the date as well once it is not. A log that
     says 14:32 with no day is unreadable a week later. */
  function when(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return String(iso).slice(11, 16);
    const hm = String(d.getHours()).padStart(2, "0") + ":" +
               String(d.getMinutes()).padStart(2, "0");
    const today = new Date();
    const sameDay = d.toDateString() === today.toDateString();
    return sameDay ? hm : (window.ui.todayISO(d).slice(5) + " " + hm);
  }

  window.Views = window.Views || {};
  window.Views.inbox = {
    id: "inbox", label: "Inbox", scoped: false,
    /* Open a row's journal from elsewhere — Activity uses this to land on the
       row an entry belongs to. Sets the flag before render, and clears the
       filter so a row that is shelved or done isn't filtered out from under
       the caller. */
    openJournal(taskId) {
      if (!taskId) return;
      open.add(taskId);
      const row = rows.find((r) => r.id === taskId);
      filter = !row ? "to do" : row.status === "cached" ? "cache2"
        : isArchived(row) ? "archive" : "to do";
      if (host) render();
    },
    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Inbox" }),
          el("div.sub", { text: "everything lands here first. ideas go somewhere or get closed; tasks get ticked. a task needs no project." }),
        ]),
      ]));
      host = el("div"); viewEl.appendChild(host);
      await guard(reload);
    },
  };
})();

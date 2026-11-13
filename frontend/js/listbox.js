/* listbox.js — the one list-entry box, factored out of "what the distractions
   were" so that every short-rows-you-keep-adding field in the app behaves the
   same way.

   THE PATTERN, and why each half of it is there:

     + add        one click, one empty box. A textarea you stare at asks you to
                  write a paragraph; a plus asks you for one line, which is the
                  size a question actually is.
     Enter saves  and opens the next empty box, because the moment you finish
                  writing one question is the moment the second one occurs to
                  you. Esc closes the empty box without saving.
     short rows   each saved row is a node, not a slice of a string. That is the
                  whole point: three questions in one textarea are one blob that
                  nothing can count, answer, or carry anywhere.

   EVERY ROW IS SAVED WHEN YOU PRESS ENTER, not when the surrounding form is
   saved. The rows outlive the form they were typed into, and a question you
   wrote and then navigated away from is still a question you asked.

   listBox({label, kind, parentId}) returns {node, reload, count}. `kind` is
   stored on each row so a page can filter to just its own box, and `parentId`
   is the node the rows hang off.

   `endpoint` picks which store the rows live in, and defaults to the questions
   one. Every store it talks to exposes the same four calls against the same two
   parameters — GET ?parent_id=&kind=, POST {text, kind, parent_id}, PATCH /:id,
   DELETE /:id — which is the whole reason one component can serve the main
   question on a reading pass and the suggestions on a lesson without knowing
   the difference between them.

   IN A FORM FOR SOMETHING THAT DOES NOT EXIST YET (a "new workout" modal) there
   is no parent to hang rows off. Leave `parentId` out and the box holds what you
   type; once the form has saved, `box.commit(newId)` posts them all against it.
   A box with no parent never posts on its own, so nothing is orphaned by a form
   you cancel.

   TONES. Every row kind has a colour (window.RowTone), shared with the Inbox, so
   a note, a thing to look into and a question are told apart at a glance in
   both places. RowBox(opts) is a ListBox on the /api/rows store — notes, look
   into, follow-ups, goals, steps — which is every box except questions and
   assumptions. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  /* The kinds of row and their colours. One table, read by the box and by the
     Inbox, so the colour you learned in one place means the same in the other.
     A kind not listed here falls back to the note colour. */
  const TONES = {
    "note":       "var(--blue)",
    "look into":  "var(--amber)",
    "question":   "var(--purple)",
    "follow-up":  "var(--teal)",
    "goal":       "var(--green)",
    "step":       "var(--dim)",
    "assumption": "var(--red)",
    "input":      "var(--teal)",
    "output":     "var(--green)",
    "tool":       "var(--purple)",
  };
  function rowTone(kind) { return TONES[kind] || TONES.note; }

  /* Grows with what you type, to three lines, then scrolls. A one-line box for
     a one-line question, without truncating the occasional long one. */
  function autoGrow(ta) {
    const fit = () => {
      ta.style.height = "auto";
      const line = 20, max = line * 3 + 10;
      ta.style.height = Math.min(ta.scrollHeight, max) + "px";
      ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
    };
    ta.addEventListener("input", fit);
    setTimeout(fit, 0);
    return fit;
  }

  function listBox(opts) {
    const label = opts.label || "questions";
    const kind = opts.kind || label;
    const parentId = opts.parentId || null;
    const endpoint = opts.endpoint || "/api/questions";
    const placeholder = opts.placeholder || "";
    const onChange = opts.onChange || function () {};
    // + rows (/api/rows) only: notes stay in their own area (2026-11-08).
    const isRows = endpoint === "/api/rows";
    // The module this box sits in, so the server can file the row there. A
    // shared topbar tab (Calendar, Snapshot…) has no module: area ''.
    function areaNow() {
      const PM = window.PM || {};
      if ((window.SHARED_TABS || []).includes(PM.active)) return "";
      const m = PM.activeModule || "";
      return m ? m[0].toUpperCase() + m.slice(1) : "";
    }
    // A to-do box: each row gets a tick (check reference X, reread §3).
    const todo = isRows && (opts.todo || kind === "look into");
    // The Inbox's own notes box must not offer "→ Inbox" on its own rows.
    const canSend = isRows && !(opts.extra && opts.extra.inbox === false);
    const postBody = (text) => Object.assign({ text: text, kind: kind, parent_id: pid },
      isRows ? { area: areaNow() } : {}, opts.extra || {});

    const rows = el("div.lb-rows");
    const editor = el("div.lb-editor");
    let items = [];
    // No parent yet: rows are held here until commit(id). See the header.
    let pid = parentId;
    let pending = !pid;

    const addBtn = el("button.btn-sm.lb-add", {
      text: "+ add " + (opts.noun || "question"),
      onclick: () => openEditor(),
    });
    const countTag = el("span.lb-count");

    const box = el("div.lb", { style: "--lb-tone:" + rowTone(kind) }, [
      el("div.row.lb-head", { style: "gap:8px;align-items:center" }, [
        el("span.wl-label.lb-label", { text: label }), addBtn, countTag,
        opts.note ? el("span.sub.lb-note", { style: "font-size:10px", text: opts.note }) : null,
      ]),
      rows, editor,
    ]);

    function setCount() {
      const left = todo ? items.filter((q) => !q.done).length : items.length;
      countTag.textContent = todo
        ? (items.length ? left + " to check" : "")
        : (items.length ? String(items.length) : "");
      onChange(items);
    }

    /* One empty box at a time. Enter saves and reopens, so a run of questions
       is a run of Enters; Esc closes. Blur with text in it also saves, because
       losing what you typed by clicking elsewhere is never what you meant. */
    function openEditor(seedText) {
      clear(editor);
      const ta = el("textarea.lb-input", { rows: "1", placeholder: placeholder });
      ta.value = seedText || "";
      const fit = autoGrow(ta);
      let closing = false;
      const close = () => { closing = true; clear(editor); };
      const save = async (reopen) => {
        const text = ta.value.trim();
        if (!text) { close(); return; }
        closing = true;
        // A failed save must not eat what was typed: guard has already shown
        // the error, so put the text back in a fresh box rather than closing.
        try {
          const made = pending ? { id: "pending-" + items.length + "-" + Date.now(), text: text, kind: kind }
            : await guard(async () => api.post(endpoint, postBody(text)));
          items.push(made);
          drawRows();
          setCount();
        } catch (e) { openEditor(text); return; }
        // `once`: one note per Enter, then the box closes (the Inbox wants this);
        // otherwise Enter opens the next line for a run of notes.
        if (reopen && !opts.once) openEditor(); else clear(editor);
        if (opts.onAdded) opts.onAdded(made);
      };
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); save(true); }
        // Esc closes this box only: in a create modal the modal's own Esc
        // would otherwise close it and lose the rows held so far.
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
      });
      ta.addEventListener("blur", () => { if (!closing && ta.value.trim()) save(false); });
      editor.appendChild(ta);
      ta.focus();
      fit();
    }

    function drawRows() {
      clear(rows);
      items.forEach((q, i) => rows.appendChild(rowFor(q, i)));
    }

    function rowFor(q, i) {
      const text = el("span.lb-text", { text: q.text });
      if (q.answered || (todo && q.done)) text.classList.add("lb-done");
      const tick = todo && !pending ? el("input.lb-tick", { type: "checkbox",
        title: q.done ? "not done yet" : "done" }) : null;
      if (tick) {
        tick.checked = !!q.done;
        tick.addEventListener("change", () => guard(async () => {
          Object.assign(q, await api.patch(endpoint + "/" + q.id, { done: tick.checked }));
          drawRows(); setCount();
        }));
      }
      const send = canSend && !pending ? el("button.btn-sm.lb-send" + (q.task_id ? ".on" : ""), {
        text: q.task_id ? "in Inbox" : "→ Inbox",
        title: q.task_id ? "already an Inbox task — the note stays here"
                         : "make this an Inbox task. the note stays here",
        onclick: () => q.task_id ? null : guard(async () => {
          Object.assign(q, await api.post(endpoint + "/" + q.id + "/inbox", {}));
          toast("→ Inbox task — the note stays here");
          drawRows();
        }),
      }) : null;
      const row = el("div.lb-row", { "data-nav": q.id }, [
        tick,
        // Assumptions carry a global number (A7); everything else counts the box.
        el("span.lb-n", { text: q.number ? "A" + q.number : String(i + 1) }),
        text,
        send,
        el("button.btn-sm.lb-edit", { title: "edit", text: "✎", onclick: () => startEdit(q, row) }),
        el("button.btn-sm.btn-danger.lb-del", { title: "remove", text: "×", onclick: () =>
          confirmDo("delete this " + (opts.noun || "question") + "?", async () => {
            if (!pending) await api.del(endpoint + "/" + q.id);
            items = items.filter((x) => x.id !== q.id);
            drawRows(); setCount();
          }) }),
      ]);
      return row;
    }

    /* Editing in place rather than in a modal: the row is one line, and a
       dialog to change one line is three clicks for one keystroke. */
    function startEdit(q, row) {
      const ta = el("textarea.lb-input", { rows: "1" });
      ta.value = q.text;
      const fit = autoGrow(ta);
      const done = async (commit) => {
        const text = ta.value.trim();
        if (commit && text && text !== q.text && pending) q.text = text;
        else if (commit && text && text !== q.text) {
          try {
            const up = await guard(async () => api.patch(endpoint + "/" + q.id, { text: text }));
            Object.assign(q, up);
          } catch (e) { /* guard toasted it; the row redraws unchanged */ }
        }
        drawRows();
      };
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); done(true); }
        else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); done(false); }
      });
      ta.addEventListener("blur", () => done(true));
      clear(row);
      row.appendChild(ta);
      ta.focus(); fit();
    }

    async function reload() {
      if (pending) { drawRows(); setCount(); return; }
      items = await api.get(endpoint + "?parent_id=" + encodeURIComponent(pid)
        + "&kind=" + encodeURIComponent(kind)).catch(() => []);
      drawRows(); setCount();
    }

    /* The form saved and the parent now exists: post what was typed, in the
       order it was typed, and become an ordinary box on that parent. A row
       that fails to post is toasted and dropped from the box, not retried
       silently forever. */
    async function commit(newId) {
      if (!newId) return;
      const held = pending ? items.slice() : [];
      pid = newId; pending = false; items = [];
      for (const q of held) {
        try { await api.post(endpoint, postBody(q.text)); }
        catch (e) { toast("couldn't save “" + q.text.slice(0, 40) + "”", true); }
      }
      await reload();
    }

    reload();
    return { node: box, reload: reload, commit: commit, open: () => openEditor(),
             count: () => items.length, items: () => items };
  }

  function rowBox(opts) {
    return listBox(Object.assign({ endpoint: "/api/rows", noun: "note", label: "notes", kind: "note" }, opts || {}));
  }

  window.ListBox = listBox;
  window.RowBox = rowBox;
  window.RowTone = rowTone;
  window.RowTones = TONES;
})();

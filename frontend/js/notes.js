/* notes.js — the note list, once, for every tab that has notes.

   One shape in the database (see backend/routes/notes.py) deserves one control
   in front of it, so Ideas, Project, Goals, Phases, Reasoning and Lessons all
   render notes through this file and none of them owns a note widget.

   APPEND ONLY, AND IT SHOWS. Editing a note writes a new one and keeps the old,
   so this control never has an in-place edit box. It has "revise", which opens
   a composer pre-filled with what the note currently says; saving leaves both.
   The current note is the one on top; everything it replaced folds away behind
   a line you can click. Hiding the history would make the store pointless, and
   showing all of it by default would bury today's answer under six months of
   working out.

   WHAT IT IS ATTACHED TO. Pass a `ref`, which is either a node or an edge:

       Notes.panel({ target_id: idea.id }, opts)
       Notes.panel({ from_id: idea.id, rel: "GIVEN_TO", to_id: project.id }, opts)

   The edge form needs no setup. The backend makes the (:Hop) that carries the
   notes the first time one is written against that edge.

   Nothing here fetches on construction. `panel()` returns an element and starts
   its own load, so a caller can drop it into a layout and forget about it. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  /* A ref becomes a query string one way and a POST body another; keeping both
     conversions here is what lets every caller pass the same object. */
  function refQuery(ref) {
    const q = new URLSearchParams();
    if (ref.target_id) q.set("target_id", ref.target_id);
    else { q.set("from_id", ref.from_id); q.set("rel", ref.rel); q.set("to_id", ref.to_id); }
    return q.toString();
  }
  function refBody(ref) {
    return ref.target_id
      ? { target_id: ref.target_id }
      : { from_id: ref.from_id, rel: ref.rel, to_id: ref.to_id };
  }

  const load = (ref, kind) => api.get(
    "/api/notes?" + refQuery(ref) + (kind && kind !== "all" ? "&kind=" + kind : ""));

  /* "10 sept" for this year, "10 sept 2025" for anything older: the year is
     noise until the moment it isn't. */
  function fmtDate(iso) {
    const d = new Date(String(iso).slice(0, 10) + "T12:00:00");
    if (isNaN(d)) return String(iso).slice(0, 10);
    const sameYear = d.getFullYear() === new Date().getFullYear();
    return d.toLocaleDateString("en-GB",
      { day: "numeric", month: "short", year: sameYear ? undefined : "numeric" })
      .toLowerCase();
  }

  /* ------------------------------------------------------------------ *
   * The composer
   * ------------------------------------------------------------------ */
  /* Used three ways: to add a note, to revise one (pre-filled, chained through
     `supersedes`), and standalone by `ask()` for the inline prompts other tabs
     need at the moment they write an edge. */
  function composer(ref, opts, onDone) {
    const o = opts || {};
    const box = el("textarea.nt-input", {
      placeholder: o.placeholder || (o.kind === "why" ? "why" : "note"),
      rows: 2,
    });
    if (o.value) box.value = o.value;

    const save = () => guard(async () => {
      const text = box.value.trim();
      if (!text) return toast("nothing to save", true);
      const made = await api.post("/api/notes", {
        ...refBody(ref), text, kind: o.kind === "why" ? "why" : "note",
        supersedes: o.supersedes || "",
      });
      box.value = "";
      if (onDone) onDone(made);
    });

    // Ctrl/Cmd+Enter saves. Plain Enter is a newline: these are sentences, and
    // a why worth writing is often two of them.
    box.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
      if (e.key === "Escape" && o.onCancel) o.onCancel();
    });

    return el("div.nt-composer", {}, [
      box,
      el("div.nt-composer-foot", {}, [
        el("span.nt-hint", { text: o.supersedes
          ? "saving keeps the old one and dates this one today"
          : "ctrl+enter saves" }),
        o.onCancel ? el("button.btn-sm", { text: "cancel", onclick: o.onCancel }) : null,
        el("button.btn-sm.btn-primary", { text: o.saveLabel || "save", onclick: save }),
      ]),
    ]);
  }

  /* ------------------------------------------------------------------ *
   * One note row
   * ------------------------------------------------------------------ */
  function row(n, ref, opts, reload) {
    const body = el("div.nt-row" + (n.current ? "" : ".old") + (n.kind === "why" ? ".why" : ""));
    const head = el("div.nt-rowhead", {}, [
      el("span.nt-date", { text: fmtDate(n.date) }),
      n.kind === "why" ? el("span.nt-kind", { text: "why" }) : null,
      n.current ? null : el("span.nt-replaced", { text: "replaced" }),
    ]);
    body.appendChild(head);
    body.appendChild(el("div.nt-text", { text: n.text }));

    // Only the note that currently stands can be revised. Revising a superseded
    // note would fork the chain, and a fork has no "what it says now".
    if (n.current && !opts.readonly) {
      const act = el("div.nt-acts", {}, [
        el("button.btn-sm", { text: "revise", onclick: () => {
          clear(act);
          const c = composer(ref, {
            kind: n.kind, value: n.text, supersedes: n.id, saveLabel: "save as new",
            onCancel: reload,
          }, reload);
          body.appendChild(c);
          act.remove();
          c.querySelector("textarea").focus();
        } }),
      ]);
      body.appendChild(act);
    }
    return body;
  }

  /* ------------------------------------------------------------------ *
   * The panel
   * ------------------------------------------------------------------ */
  /* opts:
       kind       "why" | "note" | "all"   which notes to show and write
       title      heading text, omitted for a bare list
       empty      what to say when there are none
       readonly   no composer, no revise (the Reasoning tab reads, it does not write)
       open       show the replaced ones from the start
       onChange   called after any write, for callers that show a count elsewhere */
  function panel(ref, opts) {
    const o = Object.assign({ kind: "all" }, opts || {});
    const host = el("div.nt-panel");
    let showOld = !!o.open;

    async function draw() {
      const notes = await guard(() => load(ref, o.kind));
      clear(host);

      if (o.title) {
        host.appendChild(el("div.spread.nt-head", {}, [
          el("span.wl-label", { text: o.title }),
          notes.length ? el("span.nt-count", {
            text: notes.length + (notes.length === 1 ? " note" : " notes") }) : null,
        ]));
      }

      const current = notes.filter((n) => n.current);
      const old = notes.filter((n) => !n.current);

      if (!current.length) {
        host.appendChild(el("div.nt-empty", { text: o.empty
          || (o.kind === "why" ? "no reason written down yet." : "no notes yet.") }));
      } else {
        current.forEach((n) => host.appendChild(row(n, ref, o, draw)));
      }

      if (old.length) {
        const older = el("div.nt-old" + (showOld ? "" : ".hidden"));
        old.forEach((n) => older.appendChild(row(n, ref, o, draw)));
        host.appendChild(el("button.nt-toggle", {
          text: (showOld ? "hide " : "show ") + old.length
              + (old.length === 1 ? " earlier version" : " earlier versions"),
          onclick: () => { showOld = !showOld; draw(); },
        }));
        host.appendChild(older);
      }

      if (!o.readonly) {
        host.appendChild(composer(ref, {
          kind: o.kind === "all" ? "note" : o.kind,
          placeholder: o.placeholder,
        }, () => { draw(); if (o.onChange) o.onChange(); }));
      }
    }

    draw();
    host.reload = draw;
    return host;
  }

  /* ------------------------------------------------------------------ *
   * ask() — the inline prompt
   * ------------------------------------------------------------------ */
  /* For the moment a tab writes an edge and wants the reason with it: giving an
     idea to a project, claiming a goal into a phase. Resolves with the note, or
     with null if it was skipped.

     Deliberately not a modal. The thing you are explaining is on screen behind
     it, and a dialog that covers it makes the answer worse. */
  function ask(hostEl, ref, opts) {
    const o = Object.assign({ kind: "why" }, opts || {});
    return new Promise((resolve) => {
      const wrap = el("div.nt-ask");
      const finish = (v) => { wrap.remove(); resolve(v); };
      wrap.appendChild(el("div.nt-asktitle", { text: o.title || "why?" }));
      wrap.appendChild(composer(ref, {
        kind: o.kind,
        placeholder: o.placeholder || "why, in your own words",
        saveLabel: o.saveLabel || "save",
        onCancel: () => finish(null),
      }, (made) => finish(made)));
      hostEl.appendChild(wrap);
      const t = wrap.querySelector("textarea");
      if (t) t.focus();
    });
  }

  /* One line for callers that want the current answer without the machinery:
     a project's why on its header, an idea's reason in a table cell. */
  async function latest(targetId, kind) {
    try {
      const r = await api.get("/api/notes/on/" + targetId + "/latest?kind=" + (kind || "why"));
      return r.note;
    } catch { return null; }
  }

  window.Notes = { panel, composer, ask, latest, load, fmtDate };
})();

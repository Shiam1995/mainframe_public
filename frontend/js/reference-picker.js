/* reference-picker.js — "what is this about?", once.

   The Repository already lets an entry point at something that exists
   elsewhere in Mainframe: a kind (paper / project / decomposition / idea) and
   the id of the actual node. That pair — the referenced id — is the same
   question a project asks, and the same question one pass of a project asks,
   so the control lives here rather than being written a third and fourth time.

   Two halves:
     editor()  the kind + "which one?" pair, saving on change
     chip()    the read-only badge, showing the CURRENT title of the target and
               jumping to it

   Nothing is cached across kinds by accident: /papers/linkable returns all four
   lists in one call, so switching the kind never costs another round trip. */
(function () {
  const { el, clear, guard } = window.ui;

  const KINDS = [
    { key: "paper",   icon: "📄", label: "Paper",         tab: null },
    { key: "project", icon: "🧱", label: "Project",       tab: "project" },
    { key: "decomp",  icon: "🌳", label: "Decomposition", tab: "decomposition" },
    { key: "idea",    icon: "💡", label: "Idea",          tab: "ideas" },
  ];
  const KIND = (k) => KINDS.find((x) => x.key === k) || null;

  // One in-flight load shared by every editor on the page — four lists that
  // change rarely, fetched once per view rather than once per control.
  let cache = null;
  function targets() {
    if (!cache) {
      cache = guard(() => window.api.papers.linkable())
        .then((d) => d || { paper: [], project: [], decomp: [], idea: [] })
        .catch(() => { cache = null; return { paper: [], project: [], decomp: [], idea: [] }; });
    }
    return cache;
  }
  // The lists go stale the moment you create a project or bring a paper in.
  function invalidate() { cache = null; }

  /* Jump to whatever is referenced. A paper opens in its own workspace; the
     rest open the tab that owns them, because those tabs have no "select one"
     entry point to aim at. */
  function open(kind, id) {
    const k = KIND(kind);
    if (!k) return;
    if (kind === "paper" && window.PM && window.PM.selectPaper) return window.PM.selectPaper(id);
    if (kind === "project" && window.ProjectArea) return window.ProjectArea.open(id);
    if (k.tab && window.openTab) window.openTab(k.tab);
  }

  /* The badge. `obj` is anything carrying link_kind / link_id / link_title —
     a project, a pass. Returns null when there's no reference, so it can be
     dropped straight into a children array. */
  function chip(obj, opts) {
    if (!obj || !obj.link_kind || !obj.link_id) return null;
    const k = KIND(obj.link_kind);
    const name = obj.link_title || "(deleted " + obj.link_kind + ")";
    return el("button.ref-chip" + (opts && opts.small ? ".small" : ""), {
      title: "open the " + (k ? k.label.toLowerCase() : obj.link_kind) + " this references",
      onclick: (e) => { e.stopPropagation(); open(obj.link_kind, obj.link_id); },
      text: (k ? k.icon : "↪") + " " + name,
    });
  }

  /* The editor. `onSave({link_kind, link_id})` fires whenever the pair settles
     — including on "— no reference —", which is how a link is cleared. */
  function editor(obj, onSave, opts) {
    opts = opts || {};
    let kindVal = (obj && obj.link_kind) || "";
    let idVal = (obj && obj.link_id) || "";

    const kindSel = el("select.ref-kind", {}, [
      el("option", { value: "", text: "— no reference —" }),
      ...KINDS.map((k) => el("option", { value: k.key, text: k.icon + " " + k.label })),
    ]);
    kindSel.value = kindVal;

    const whichSel = el("select.ref-which");
    const openBtn = el("button.btn-sm", { title: "open what this references", text: "↗" });

    function paintOpen() {
      openBtn.style.display = kindVal && idVal ? "" : "none";
      openBtn.onclick = () => open(kindVal, idVal);
    }

    async function fillWhich() {
      clear(whichSel);
      whichSel.style.display = kindVal ? "" : "none";
      if (!kindVal) { paintOpen(); return; }
      whichSel.appendChild(el("option", { value: "", text: "loading…" }));
      const all = await targets();
      const rows = all[kindVal] || [];
      clear(whichSel);
      whichSel.appendChild(el("option", { value: "", text: "— pick one —" }));
      rows.forEach((r) => whichSel.appendChild(el("option", {
        value: r.id, text: r.title + (r.note ? "  ·  " + r.note : ""),
      })));
      // A reference to something since deleted would otherwise silently reset
      // the select to "pick one" and then save that emptiness on the next edit.
      if (idVal && !rows.some((r) => r.id === idVal)) {
        whichSel.appendChild(el("option", {
          value: idVal, text: (obj && obj.link_title) || "(missing — " + idVal.slice(0, 8) + ")",
        }));
      }
      whichSel.value = idVal || "";
      paintOpen();
    }

    kindSel.addEventListener("change", async () => {
      kindVal = kindSel.value;
      idVal = "";
      await fillWhich();
      // Clearing the kind IS the save — otherwise there's no way to detach.
      if (!kindVal) onSave({ link_kind: "", link_id: "" });
    });
    whichSel.addEventListener("change", () => {
      idVal = whichSel.value;
      paintOpen();
      onSave({ link_kind: idVal ? kindVal : "", link_id: idVal });
    });

    const row = el("div.ref-editor", {}, [
      opts.label === null ? null : el("span.sub", { text: opts.label || "references" }),
      kindSel, whichSel, openBtn,
    ]);
    fillWhich();
    return {
      node: row,
      // For a form that saves once at the end (the new-pass modal) rather than
      // on every change.
      get: () => ({ link_kind: idVal ? kindVal : null, link_id: idVal || null }),
    };
  }

  window.RefPicker = { KINDS, KIND, chip, editor, open, invalidate };
})();

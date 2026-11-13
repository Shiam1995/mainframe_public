/* quickidea.js — capture an idea from anywhere.

   A floating button pinned bottom-right of every view, in every module. Ideas
   turn up while you're doing something else, so the capture has to be reachable
   without leaving what you're on: click (or press "i"), type it, pick the kind,
   save. It lands in the same :Idea table the Ideas tab reads. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  let panel = null;

  function close() {
    if (panel) { panel.remove(); panel = null; }
  }

  function open() {
    if (panel) { close(); return; }
    panel = el("div.qi-panel");

    const title = el("input", { placeholder: "the idea…", style: "width:100%" });
    const desc = el("input", { placeholder: "detail (optional)", style: "width:100%" });
    const kindHost = el("span");
    const status = el("select", {}, ["raw", "exploring", "in-progress", "parked"].map((s) =>
      el("option", { value: s, text: s })));
    const prio = el("select", {}, ["low", "medium", "high"].map((p) => {
      const o = el("option", { value: p, text: p });
      if (p === "medium") o.setAttribute("selected", "");
      return o;
    }));

    let kind = "";
    function drawKind() {
      clear(kindHost);
      kindHost.appendChild(window.IdeaKinds.select(kind, (v) => { kind = v; }, "qi-kind"));
    }

    panel.appendChild(el("div.spread", {}, [
      el("strong", { style: "font-size:13px", text: "New idea" }),
      el("button.btn-sm", { onclick: close, text: "×" }),
    ]));
    panel.appendChild(el("div", { style: "margin-top:8px" }, [title]));
    panel.appendChild(el("div", { style: "margin-top:6px" }, [desc]));
    panel.appendChild(el("div.row", { style: "gap:6px;margin-top:6px;flex-wrap:wrap" }, [
      kindHost, prio, status,
    ]));

    /* An idea had while reading belongs to what you were reading. Only offered
       when the view on screen is paper-scoped — a paper can stay "selected"
       while you're off in Vault, and silently filing a budget thought under a
       paper would be worse than not linking at all. Linking is what makes it
       show up in that paper's Master Instance. */
    const scoped = !!(window.PM && window.PM.paper && window.Views
      && window.Views[window.PM.active] && window.Views[window.PM.active].scoped);
    const linkCb = el("input", { type: "checkbox" });
    if (scoped) {
      linkCb.checked = true;
      panel.appendChild(el("label.row", { style: "gap:6px;margin-top:8px;cursor:pointer;align-items:flex-start" }, [
        linkCb,
        el("span.sub", { style: "font-size:10.5px;line-height:1.35",
          text: "link to “" + window.PM.paper.title.slice(0, 46) + (window.PM.paper.title.length > 46 ? "…" : "") + "” — it'll appear in its Master Instance" }),
      ]));
    }
    panel.appendChild(el("div.row", { style: "gap:6px;margin-top:10px" }, [
      el("span.sub", { style: "font-size:10px", text: "⌘/Ctrl+Enter to save" }),
      el("button.btn-primary", { style: "margin-left:auto", onclick: () => save(), text: "+ add idea" }),
    ]));

    document.body.appendChild(panel);
    window.IdeaKinds.load().then(drawKind);
    title.focus();

    // One save at a time: a double click or a second Ctrl+Enter before the
    // panel closed used to post the idea twice.
    let saving = false;
    async function save() {
      if (saving) return;
      const t = title.value.trim();
      if (!t) return toast("what's the idea?", true);
      saving = true;
      try { await guard(async () => {
        await api.post("/api/synapse/ideas", {
          title: t,
          description: desc.value.trim(),
          category: kind,
          priority: prio.value,
          status: status.value,
          paper_id: scoped && linkCb.checked ? window.PM.paper.id : null,
        });
        toast(scoped && linkCb.checked ? "idea captured → linked to this paper" : "idea captured");
        close();
        // if the Inbox is the tab on screen, redraw it so the row appears
        if (window.PM && window.PM.active === "inbox" && window.Views.inbox) {
          const view = document.getElementById("view");
          if (view) window.Views.inbox.render(view);
        }
      }); } catch (e) { /* guard already toasted it */ } finally { saving = false; }
    }

    panel.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.stopPropagation(); close(); }
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); save(); }
    });
  }

  function mount() {
    if (document.querySelector(".qi-fab")) return;
    document.body.appendChild(el("button.qi-fab", {
      title: "capture an idea (i)",
      onclick: open,
      text: "+ idea",
    }));
    // "i" anywhere that isn't a text field opens the capture
    document.addEventListener("keydown", (e) => {
      if (e.key !== "i" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      e.preventDefault();
      open();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();

  window.QuickIdea = { open, close };
})();

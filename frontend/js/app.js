/* app.js — the Mainframe shell: module switcher, tab bar, view routing, shared
   paper selection, health pill. Reads the module registry from modules.js.
   Loaded last, after every view has registered itself on window.Views. */
(function () {
  const { el, clear, toast, guard } = window.ui;

  // Shared state across views.
  const PM = {
    paper: null,                 // currently selected paper (object)
    papers: [],                  // cache for pickers
    active: "snapshot",
    activeModule: (() => { try { return localStorage.getItem("mainframe.module") || "synapse"; } catch { return "synapse"; } })(),
    customHeaders: [],           // global custom-header tabs (Synapse module)
    listeners: [],
    async selectPaper(id) {
      if (PM.activeModule !== "synapse") setModule("synapse");
      this.paper = await guard(() => window.api.papers.get(id));
      renderContext();
      activate("workspace");
      toast("selected: " + this.paper.title);
    },
    onPaperChange(fn) { this.listeners.push(fn); },
  };
  window.PM = PM;

  const tabsEl = document.getElementById("tabs");
  const viewEl = document.getElementById("view");
  const ctxEl = document.getElementById("context-panel");

  function currentModule() {
    return (window.MODULES || []).find((m) => m.key === PM.activeModule) || (window.MODULES || [])[0];
  }

  // Two-tier nav: shared Mainframe tabs live on the top bar; the active module's
  // own tabs (+ Synapse custom headers) live on the second bar underneath.
  function sharedViews() {
    return (window.SHARED_TABS || []).map((id) => window.Views[id]).filter(Boolean);
  }
  function moduleViews() {
    const mod = currentModule();
    const builtin = (mod ? mod.tabs : []).map((id) => window.Views[id]).filter(Boolean);
    const headers = (mod && mod.key === "synapse" ? PM.customHeaders : []).map((h) => ({
      id: "header:" + h.id, label: h.name, scoped: false, header: h,
      render: (view) => window.Views.headers.renderOne(view, h),
    }));
    return builtin.concat(headers);
  }
  function allTabs() { return sharedViews().concat(moduleViews()); }

  function renderSwitcher() {
    const host = document.getElementById("module-switch");
    if (!host) return;
    clear(host);
    (window.MODULES || []).forEach((m) => {
      host.appendChild(el("button.mod-btn" + (m.key === PM.activeModule ? ".active" : ""), {
        onclick: () => setModule(m.key),
        style: "--mod-accent:" + m.accent,
        text: m.label,
      }));
    });
  }

  function setModule(key) {
    if (!(window.MODULES || []).some((m) => m.key === key)) return;
    PM.activeModule = key;
    try { localStorage.setItem("mainframe.module", key); } catch { /* ignore */ }
    const mod = currentModule();
    document.documentElement.dataset.module = key;
    const bn = document.querySelector(".brand-name");
    if (bn && mod) bn.innerHTML = mod.topbar;
    renderSwitcher();
    // if the current tab isn't in this module, jump to its first tab
    if (!allTabs().some((t) => t.id === PM.active)) {
      const first = (mod.tabs.find((id) => window.Views[id])) || (window.SHARED_TABS || [])[0];
      activate(first);
    } else {
      renderTabs();
    }
  }
  window.setModule = setModule;

  /* Tabs under review — kept but highlighted amber until a keep/cut decision.
     Not a module thing: this used to sit inside renderTabs() where every member
     happened to be a Synapse tab, which made it look like a Synapse feature. It
     is a Mainframe-level mark, so it lives at Mainframe level and any tab on
     either bar can carry it. Snapshot is the first shared tab to. */
  const REVIEW_TABS = new Set([
    "snapshot",                                   // shared
    "scanner", "headers",                          // synapse
    "blueprint",                                   // vision
  ]);

  function renderTabs() {
    const moduleTabsEl = document.getElementById("module-tabs");
    const paint = (host, views) => {
      if (!host) return;
      clear(host);
      views.forEach((v) => {
        const btn = el("button.tab" + (v.id === PM.active ? ".active" : "") + (REVIEW_TABS.has(v.id) ? ".review" : ""), {
          onclick: () => activate(v.id), text: v.label,
        });
        btn.dataset.tab = v.id;
        host.appendChild(btn);
        // A view can put a live count on its own tab (Assumptions does).
        if (v.badge) v.badge(btn);
      });
    };
    // FAQ is the last tab in the strip (after Settings), not a pinned button.
    paint(tabsEl, sharedViews());           // top bar
    paint(moduleTabsEl, moduleViews());     // second (module) bar
  }

  function activate(id) {
    const v = allTabs().find((t) => t.id === id);
    if (!v) return;
    PM.active = id;
    renderTabs();
    // Context panel only for paper-scoped views.
    ctxEl.classList.toggle("hidden", !v.scoped);
    if (v.scoped) renderContext();
    clear(viewEl);
    guard(async () => {
      await v.render(viewEl, PM);
      // a slow render can finish after the user has moved on — don't graft this
      // view's control onto whatever is on screen now
      if (PM.active === v.id) {
        mountWorkLog(v);
        mountPulseScores(v);
      }
    });
  }

  /* Re-render whatever is on screen. The voice assistant calls this after a
     confirmed action: it may have just changed the very data the open view is
     displaying, and a stale screen after "done ✓" reads as a bug. */
  window.refreshActive = () => { if (PM.active) activate(PM.active); };

  /* Jump to another tab from inside a view. The project page uses it to hand
     you a new document in the Docs editor — the thing you asked for is on a
     different tab, so taking you there is the whole action, not a side effect. */
  PM.go = activate;

  /* Every view outside Vault can push time to the work database.
     Views that own a specific entity (project / idea / task) carry their own
     per-row button as well — this is the catch-all for the view itself. */
  const WORK_REF_KIND = {
    tasks: "task", progress: "task", activity: "task",
    ideas: "idea", mind: "idea",
    project: "project",
    repo: "paper", workspace: "paper", dictionary: "paper", scanner: "paper",
    refgraph: "paper", timeline: "paper", kg: "paper", deepdive: "paper", headers: "paper",
    benchmark: "habit", habits: "habit", tracking: "habit", experiments: "habit",
    routines: "habit", fitness: "habit", nutrition: "habit", recovery: "habit",
    medical: "habit", medications: "habit",
  };
  // the Database is the table itself (it has its own "+ new row"), and Vault is
  // excluded wholesale per the user's call
  // ...and the FAQ is a guide, not something you log time against
  const WORK_SKIP = new Set(["work", "log", "help"]);

  function mountWorkLog(v) {
    if (!window.WorkLog || PM.activeModule === "vault") return;
    if (WORK_SKIP.has(v.id) || String(v.id).startsWith("header:")) return;
    const kind = WORK_REF_KIND[v.id] || "other";
    // a paper-scoped view logs against the active paper; otherwise the view itself
    const scoped = v.scoped && PM.paper;
    window.WorkLog.mountHeader(viewEl, {
      module: PM.activeModule,
      ref_kind: kind,
      ref_id: scoped ? PM.paper.id : null,
      ref_title: scoped ? PM.paper.title : v.label,
    });
  }

  /* Pulse's ten tabs are a filing cabinet; the score strip is the dashboard
     over them. Mounted by the shell so none of the ten has to know about it.
     Skipped on Benchmark, which is itself the deep version of the same idea. */
  const SCORE_SKIP = new Set(["benchmark"]);
  function mountPulseScores(v) {
    if (!window.PulseScores || PM.activeModule !== "pulse") return;
    if (SCORE_SKIP.has(v.id) || String(v.id).startsWith("header:")) return;
    // Pulse's OWN tabs only. Tasks and Calendar are Mainframe-level and happen
    // to be on screen while Pulse is selected — putting health scores above
    // your task list would be a category error.
    const mod = currentModule();
    if (!mod || !mod.tabs.includes(v.id)) return;
    window.PulseScores.mount(viewEl);
  }

  /* A view that redraws itself (the workspace does, after every save) rebuilds
     its own header and loses the log-time button, which is mounted by the shell
     rather than by the view. Let a view ask for it back. */
  window.remountWorkLog = () => {
    const v = allTabs().find((t) => t.id === PM.active);
    if (v) mountWorkLog(v);
  };

  function renderContext() {
    const v = allTabs().find((t) => t.id === PM.active);
    if (!v || !v.scoped) return;
    clear(ctxEl);
    ctxEl.appendChild(el("label", { text: "ACTIVE SUBJECT" }));
    const picker = el("select", { style: "width:100%;margin-bottom:12px" });
    picker.appendChild(el("option", { value: "", text: "— none —" }));
    // Icon says what each entry is, so a project and a paper are tellable
    // apart in a list that now holds both.
    const ICON = {
      topic: "🌀", paper: "📄", book: "📕", video: "🎬", course: "🎓",
      article: "📰", note: "🗒️", event: "🎟️", project: "🧱", decomp: "🌳", idea: "💡",
    };
    PM.papers.forEach((p) => {
      const o = el("option", { value: p.id, text: (ICON[p.kind] || ICON.paper) + " " + p.title.slice(0, 42) });
      if (PM.paper && p.id === PM.paper.id) o.setAttribute("selected", "");
      picker.appendChild(o);
    });
    picker.addEventListener("change", async () => {
      if (!picker.value) { PM.paper = null; renderContext(); activate(PM.active); return; }
      PM.paper = await guard(() => window.api.papers.get(picker.value));
      renderContext(); activate(PM.active);
    });
    ctxEl.appendChild(picker);
    if (PM.paper) {
      const p = PM.paper;
      ctxEl.appendChild(el("h3", { style: "margin:6px 0", text: p.title }));
      ctxEl.appendChild(el("div.sub", { text: (p.authors || []).join(", ") }));
      ctxEl.appendChild(el("div.sub", { style: "margin-top:4px", text: [p.year, p.venue].filter(Boolean).join(" · ") }));
      ctxEl.appendChild(el("div", { style: "margin-top:8px" }, [ el("span.pill." + (p.status||"unread"), { text: p.status || "unread" }) ]));
      if (p.abstract) ctxEl.appendChild(el("p.sub", { style: "margin-top:12px;line-height:1.5", text: p.abstract }));
    } else {
      ctxEl.appendChild(el("div.empty", { style: "padding:20px 0", text: "Pick something to work on — or start one from the Workspace tab." }));
    }
  }

  async function refreshPapers() {
    PM.papers = await guard(() => window.api.papers.list());
    PM.listeners.forEach((fn) => fn());
  }
  PM.refreshPapers = refreshPapers;
  // Renaming the open subject changes what the left panel says about it, and
  // the panel is drawn here rather than by the view that did the renaming.
  PM.renderContext = renderContext;

  async function pollHealth() {
    try {
      const h = await window.api.health();
      const dn = document.getElementById("dot-neo4j");
      const dl = document.getElementById("dot-llm");
      dn.className = "dot " + (h.neo4j ? "ok" : "");
      const eff = h.llm && h.llm.effective;
      dl.className = "dot " + (eff === "ollama" ? "ok" : "warn");
      document.getElementById("llm-label").textContent = eff || "llm";
    } catch { /* backend down; dots stay red */ }
  }

  async function loadCustomHeaders() {
    try {
      const hs = await window.api.get("/api/synapse/headers");
      PM.customHeaders = hs.filter((h) => !h.paper_id); // global ones become tabs
    } catch { PM.customHeaders = []; }
  }
  PM.reloadHeaders = async () => { await loadCustomHeaders(); renderTabs(); };

  /* ---- home screen ↔ module shell ------------------------------------- */
  // The home screen is an overlay above the shell. Opening a module hides it
  // and switches the shell underneath; "← mainframe" brings it back.
  function showChrome(on) {
    document.querySelectorAll(".topbar, .module-bar, .layout").forEach((n) => {
      n.style.display = on ? "" : "none";
    });
    const back = document.getElementById("back-home");
    if (back) back.classList.toggle("visible", on);
  }
  window.openModule = function (key, tab) {
    if (window.Home) window.Home.hide();
    showChrome(true);
    setModule(key);
    if (tab && window.Views[tab]) activate(tab);
  };
  /* Jump to a tab in the module that owns it. Shared tabs (Ideas, Project…)
     are reachable from wherever you are; a module tab switches module first. */
  window.openTab = function (id) {
    if (!window.Views[id]) return;
    if ((window.SHARED_TABS || []).includes(id)) { activate(id); return; }
    const owner = (window.MODULES || []).find((m) => (m.tabs || []).includes(id));
    if (owner) window.openModule(owner.key, id); else activate(id);
  };
  window.goHome = function () {
    showChrome(false);
    if (window.Home) window.Home.show();
  };

  async function boot() {
    // initialise module chrome (theme, brand, switcher) before first paint of tabs
    const mod = currentModule();
    document.documentElement.dataset.module = PM.activeModule;
    const bn = document.querySelector(".brand-name");
    if (bn && mod) bn.innerHTML = mod.topbar;
    renderSwitcher();

    await Promise.all([refreshPapers(), loadCustomHeaders(), pollHealth()]);
    renderTabs();
    activate("snapshot");
    setInterval(pollHealth, 8000);

    // Land on the home screen; the shell sits behind it until a module is opened.
    if (window.Home) {
      await window.Home.mount();
      showChrome(false);
      window.Home.show();
    }
    const back = document.getElementById("back-home");
    if (back) back.addEventListener("click", window.goHome);
    document.addEventListener("keydown", (e) => {
      const onHome = document.getElementById("home").classList.contains("open");
      if (e.key === "Escape" && !onHome && !document.querySelector(".modal-overlay")) window.goHome();
    });
  }
  boot();
})();

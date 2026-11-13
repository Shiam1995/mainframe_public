/* unlogged.js — the ⏱ chip beside the bell: work you did that never got time
   logged against it, for everything at once.

   This used to be a banner at the top of the Workspace, per paper: it told you
   about the one subject you happened to have open, and it told you every single
   time you opened it. Two problems with that. You can't review what you haven't
   looked at, and a warning you can't dismiss stops being read.

   So it moved into the chrome, next to the reminders bell, and it answers the
   whole question instead of one paper's worth of it. Silent when there's
   nothing outstanding; a number when there is; the list only when you ask.

   Everything here is derived (/api/work/gaps) — nothing is written until you
   push a session, and pushing one is what clears the item. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const REFRESH_MS = 120000;          // slow: the answer changes as you work, not by the second
  let feed = { items: [], total: 0, item_count: 0 };
  let panel = null;
  const open = new Set();             // which items have their events unfolded

  // Same vocabulary the subject picker uses, so a row reads as the thing it is.
  const ICON = {
    paper: "📄", project: "🧱", task: "✓", idea: "💡",
    document: "🗒️", habit: "↻", other: "•",
  };
  // Where "open it" should take you, per kind. Papers select the subject and
  // land on the Workspace; the rest are a tab away.
  const TAB = { project: "project", task: "tasks", idea: "ideas", document: "docs", habit: "habits" };

  const when = (ts) => (ts || "").slice(0, 16).replace("T", " ");

  /* ------------------------------------------------------------------ *
   * The panel
   * ------------------------------------------------------------------ */
  function close() { if (panel) { panel.remove(); panel = null; } }

  function itemRow(it) {
    const isOpen = open.has(it.ref_id);
    const logged = window.WorkLog.fmtMins(it.total_mins || 0);
    const formHost = el("div.ul-form");

    const toggle = el("button.ul-count", {
      title: isOpen ? "hide what" : "show what",
      text: it.unlogged_count + " ⏱ " + (isOpen ? "▾" : "▸"),
      onclick: (e) => {
        e.stopPropagation();
        isOpen ? open.delete(it.ref_id) : open.add(it.ref_id);
        draw();
      },
    });

    const title = el("button.ul-title", {
      title: "open " + it.ref_title,
      text: (ICON[it.ref_kind] || ICON.other) + " " + it.ref_title,
      onclick: () => {
        close();
        if (it.ref_kind === "paper" && window.PM) window.PM.selectPaper(it.ref_id);
        else if (TAB[it.ref_kind]) window.openTab(TAB[it.ref_kind]);
      },
    });

    const row = el("div.ul-item", {}, [
      el("div.ul-head", {}, [title, toggle]),
      el("div.ul-meta", {}, [
        el("span", { text: it.last_logged_at
          ? "last logged " + it.last_logged_at.slice(0, 10) + " · " + logged + " so far"
          : "nothing logged here yet" }),
        el("span", { style: "flex:1" }),
        window.WorkLog.button({
          mountInto: formHost, module: it.module || "mainframe",
          ref_kind: it.ref_kind, ref_id: it.ref_id, ref_title: it.ref_title, lockRef: true,
        }, () => refresh().then(draw), "+ log it"),
      ]),
    ]);

    if (isOpen) {
      const list = el("div.ul-events");
      (it.unlogged || []).forEach((e) => list.appendChild(el("div.ul-ev", {}, [
        el("span.mono.ul-when", { text: when(e.timestamp) }),
        el("span.tk-tag.ul-cat", { text: e.category || "—" }),
        el("span", { text: e.action || "" }),
        e.detail ? el("span.sub", { style: "opacity:.7", text: "· " + String(e.detail).slice(0, 44) }) : null,
      ])));
      // The count is exact; the sample the server sends back is capped.
      if (it.unlogged_count > (it.unlogged || []).length) {
        list.appendChild(el("div.sub", { style: "font-size:10.5px;margin-top:4px",
          text: "…and " + (it.unlogged_count - it.unlogged.length) + " more" }));
      }
      row.appendChild(list);
    }
    row.appendChild(formHost);
    return row;
  }

  function draw() {
    if (!panel) return;
    clear(panel);
    panel.appendChild(el("div.rm-head", {}, [
      el("span.rm-title", { text: feed.total
        ? feed.total + " thing" + (feed.total === 1 ? "" : "s") + " done since you last logged time"
        : "Everything is logged" }),
      el("button.rm-x", { text: "×", onclick: close }),
    ]));
    const body = el("div.rm-body");
    if (!feed.total) {
      body.appendChild(el("div.rm-empty", {
        text: "Nothing outstanding — every item you've touched has time against it. "
            + "This fills up on its own as you work; logging a session clears the item.",
      }));
    } else {
      body.appendChild(el("div.rm-group", {
        text: feed.item_count + " item" + (feed.item_count === 1 ? "" : "s") + " · most recent first" }));
      feed.items.forEach((it) => body.appendChild(itemRow(it)));
    }
    panel.appendChild(body);
  }

  function show() {
    close();
    panel = el("div.rm-panel.ul-panel");
    document.body.appendChild(panel);
    draw();
    // Opening is the moment you care — make sure the list is current.
    guard(async () => { await refresh(); draw(); });
  }

  /* ------------------------------------------------------------------ *
   * The chip
   * ------------------------------------------------------------------ */
  function paint() {
    const b = document.getElementById("ul-chip");
    if (!b) return;
    b.className = "rm-bell ul-chip" + (feed.total ? " on" : "");
    b.textContent = feed.total ? "⏱ " + feed.total : "⏱";
    b.title = feed.total
      ? feed.total + " thing(s) across " + feed.item_count
        + " item(s) done since you last logged time — click to review"
      : "nothing done that isn't logged";
  }

  async function refresh() {
    try { feed = await api.work.gaps(); } catch { /* backend down; leave the last count */ }
    paint();
  }

  function mount() {
    const host = document.getElementById("status-pill");
    if (!host) return;
    const chip = el("button.rm-bell.ul-chip", { id: "ul-chip", text: "⏱",
      onclick: (e) => { e.stopPropagation(); panel ? close() : show(); } });
    // Sit beside the bell rather than at the front of the strip: both are
    // "things waiting for you", and they read as a pair.
    const bell = document.getElementById("rm-bell");
    if (bell) bell.insertAdjacentElement("afterend", chip);
    else host.insertBefore(chip, host.firstChild);

    document.addEventListener("click", (e) => {
      if (panel && !panel.contains(e.target) && e.target.id !== "ul-chip") close();
    });

    refresh();
    setInterval(refresh, REFRESH_MS);
  }

  // Anything that pushes a session can clear an item — let the rest of the app
  // say so instead of waiting out the interval.
  window.Unlogged = { open: show, refresh, count: () => feed.total };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

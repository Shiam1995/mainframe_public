/* project-overview.js — the master header: everything about one project, read
   at a glance.

   `/api/projects/{id}/master` already gathered the totals and every piece of
   prose written anywhere about a project — the note, each file's note, and the
   text of every work session. It was buried behind a collapsed "▸ master" link
   inside a card. Here it is the first thing you see when you open a project,
   which is what a master header is for. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const P = () => window.ProjectPicker;

  function fmtHours(mins) {
    const h = (mins || 0) / 60;
    return h >= 10 ? h.toFixed(0) : h.toFixed(1);
  }

  function stat(value, label, colour) {
    return el("div.pov-stat", {}, [
      el("div.pov-stat-v", { style: colour ? "color:" + colour : "", text: value }),
      el("div.pov-stat-l", { text: label }),
    ]);
  }

  async function render(host) {
    clear(host);
    const projects = await P().load();
    P().mount(host, () => render(host));
    if (!projects.length) return;
    const projectId = P().id;

    const m = await api.projects.master(projectId);
    const ideas = await api.projects.ideas(projectId);

    /* --- the header itself --- */
    const span = (m.first_worked && m.last_worked)
      ? m.first_worked + " → " + m.last_worked
      : "not started";
    host.appendChild(el("div.pov-head", {}, [
      el("div.pov-name", { text: m.name }),
      el("div.sub", { text: span + " · " + (m.distinct_days || 0) + " distinct days" }),
      el("div.pov-stats", {}, [
        stat(fmtHours(m.total_mins), "hours", "var(--accent)"),
        stat(String(m.session_count || 0), "instances", "#7FA8C8"),
        stat(String(m.push_count || 0), "pushed", "#DE7BA4"),
        stat(String(m.file_count || 0), "files", "var(--amber)"),
        stat(String(ideas.length), "ideas", "var(--purple)"),
        stat(String(ideas.filter((i) => i.look_status === "to-look-at").length),
             "to look at", "var(--amber)"),
      ]),
    ]));

    /* --- a book's master record ---------------------------------------
       When this project IS a book, its record is the point of the page, so it
       sits directly under the header rather than below the file notes. Same
       component the Workspace mounts: the project and the book are two views
       of one pair, and the record must not read differently depending on which
       one you opened. */
    const project = projects.find((x) => x.id === projectId) || {};
    if (project.link_kind === "paper" && project.link_id && window.BookMaster) {
      const bookHost = el("div.pov-book", {});
      host.appendChild(bookHost);
      // Fire and forget: a book with no sessions yet renders its own empty
      // state, and the rest of the page must not wait on it.
      window.BookMaster.render(bookHost, project.link_id, {});
    }

    /* --- where the time went --- */
    const focus = m.focus_mins || {};
    const focusTotal = (focus.active || 0) + (focus.passive || 0) + (focus.none || 0);
    if (focusTotal > 0) {
      const seg = (mins, colour, label) => {
        const pct = Math.round((mins / focusTotal) * 100);
        if (!pct) return null;
        return el("div.pov-seg", {
          style: "width:" + pct + "%;background:" + colour,
          title: label + " · " + fmtHours(mins) + "h · " + pct + "%",
        });
      };
      host.appendChild(el("div.pov-focus", {}, [
        el("div.sub", { text: "focus" }),
        el("div.pov-bar", {}, [
          seg(focus.active || 0, "var(--green)", "active"),
          seg(focus.passive || 0, "var(--blue)", "passive"),
          seg(focus.none || 0, "var(--border)", "unclassified"),
        ]),
        el("div.pov-legend", {}, [
          el("span", { style: "color:var(--green)", text: "■ active " + fmtHours(focus.active || 0) + "h" }),
          el("span", { style: "color:var(--blue)", text: "■ passive " + fmtHours(focus.passive || 0) + "h" }),
          el("span", { style: "color:var(--dim)", text: "■ unclassified " + fmtHours(focus.none || 0) + "h" }),
        ]),
      ]));
    }

    /* --- everything written about it, in one read --- */
    host.appendChild(el("div.pov-section", { text: "Everything written about this project" }));
    if (!m.blocks || !m.blocks.length) {
      host.appendChild(el("div.empty", {
        text: "Nothing written yet — the project note, file notes and instance text all collect here.",
      }));
    } else {
      m.blocks.forEach((b) => {
        host.appendChild(el("div.pov-block", {}, [
          el("div.pov-block-src", {
            text: b.source + (b.mins ? " · " + Math.round(b.mins) + "m" : ""),
          }),
          el("div.pov-block-text", { text: b.text }),
        ]));
      });
    }
  }

  window.PROJ_TABS = window.PROJ_TABS || [];
  // Overview is the master header, so it goes first of all.
  window.PROJ_TABS.unshift({ key: "overview", label: "Overview", render });
})();

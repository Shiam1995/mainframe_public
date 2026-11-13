/* project-workspace.js — one project, opened.

   The Repo → Workspace pattern, for projects: the Projects sub-tab is the
   library where you browse every card, and "⤢ open" (or the picker chip here)
   drops you into a single project to work on it — rename, note, log sessions,
   push, upload and link files, images, the master document. The editable card
   itself is window.ProjectCard, shared with the list so the two can't drift. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const P = () => window.ProjectPicker;

  async function render(host) {
    clear(host);
    const projects = await P().load();
    P().mount(host, () => render(host));
    if (!projects.length) return;

    const p = projects.find((x) => x.id === P().id);
    if (!p) return;

    const reload = () => guard(async () => {
      await P().load(true);
      render(host);
    });

    const body = el("div", { style: "margin-top:12px" });
    body.appendChild(window.ProjectCard(p, reload, { workspace: true }));
    host.appendChild(body);
  }

  window.PROJ_TABS = window.PROJ_TABS || [];
  window.PROJ_TABS.push({ key: "workspace", label: "Workspace", render });
})();

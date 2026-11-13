/* habits.js — the Habits sub-shell inside Pulse. Renders a secondary sub-tab bar
   from window.HABIT_TABS (My Habits · Trends) and swaps the active sub-view.
   Loaded AFTER the habits-*.js sub-views. */
(function () {
  const { el, clear, guard } = window.ui;
  let sub = (() => { try { return localStorage.getItem("habits.sub2") || "areas"; } catch { return "list"; } })();

  window.Views = window.Views || {};
  window.Views.habits = {
    id: "habits", label: "Habits", scoped: false,
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Habits" }), el("div.sub", { text: "Repeating behaviours — nest sub-habits, journal, and trend your consistency." }),
      ])]));
      const tabs = window.HABIT_TABS || [];
      if (!tabs.some((t) => t.key === sub)) sub = tabs[0] && tabs[0].key;
      const bar = el("div.fit-subtabs");
      const host = el("div.fit-sub");
      function draw() {
        clear(bar);
        tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
          onclick: () => { sub = t.key; try { localStorage.setItem("habits.sub2", sub); } catch { /* */ } draw(); },
          text: t.label,
        })));
        clear(host);
        const t = tabs.find((x) => x.key === sub);
        if (t) guard(() => t.render(host));
      }
      view.appendChild(bar);
      view.appendChild(host);
      draw();
    },
  };
})();

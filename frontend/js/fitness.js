/* fitness.js — the Fitness sub-module shell inside Pulse. Renders a secondary
   sub-tab bar from window.FIT_TABS (each fitness-*.js registers into it) and
   swaps the active sub-view. Loaded AFTER the fitness-*.js sub-views. */
(function () {
  const { el, clear, guard } = window.ui;
  let sub = (() => { try { return localStorage.getItem("fitness.sub") || "dashboard"; } catch { return "dashboard"; } })();

  window.Views = window.Views || {};
  window.Views.fitness = {
    id: "fitness", label: "Fitness", scoped: false,
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Fitness" }), el("div.sub", { text: "Training, workouts, body, activity and stretching." }),
      ])]));
      const tabs = window.FIT_TABS || [];
      if (!tabs.some((t) => t.key === sub)) sub = tabs[0] && tabs[0].key;
      const bar = el("div.fit-subtabs");
      const host = el("div.fit-sub");
      function draw() {
        clear(bar);
        tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
          onclick: () => { sub = t.key; try { localStorage.setItem("fitness.sub", sub); } catch { /* */ } draw(); },
          text: t.label,
        })));
        clear(host);
        const t = tabs.find((x) => x.key === sub);
        if (t) guard(() => t.render(host));
      }
      // Jump to a sub-tab from elsewhere (the Log form's "create one" link).
      window.FIT = window.FIT || {};
      window.FIT.go = (key) => {
        if (!tabs.some((t) => t.key === key)) return;
        sub = key; try { localStorage.setItem("fitness.sub", sub); } catch { /* */ }
        draw();
      };
      view.appendChild(bar);
      view.appendChild(host);
      draw();
    },
  };
})();

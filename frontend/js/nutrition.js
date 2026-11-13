/* nutrition.js — the Nutrition sub-shell inside Pulse. Renders a sub-tab bar from
   window.NUT_TABS (each nutrition-*.js registers into it). Loaded AFTER the sub-views. */
(function () {
  const { el, clear, guard } = window.ui;
  let sub = (() => { try { return localStorage.getItem("nutrition.sub") || "log"; } catch { return "log"; } })();

  window.Views = window.Views || {};
  window.Views.nutrition = {
    id: "nutrition", label: "Nutrition", scoped: false,
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Nutrition" }),
        el("div.sub", { text: "Food log, drinks, supplements — your own food library, built from what you actually eat." }),
      ])]));
      // Sub-views register themselves; `order` decides the bar, not load order,
      // so a new tab slots in without touching index.html's script order.
      const tabs = (window.NUT_TABS || []).slice()
        .sort((a, b) => (a.order || 999) - (b.order || 999));
      if (!tabs.some((t) => t.key === sub)) sub = tabs[0] && tabs[0].key;
      const bar = el("div.fit-subtabs");
      const host = el("div.fit-sub");
      function draw() {
        clear(bar);
        tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.undecided ? ".undecided" : "") + (t.key === sub ? ".active" : ""), {
          title: t.undecided ? "Undecided — kept for now, may be removed" : "",
          onclick: () => { sub = t.key; try { localStorage.setItem("nutrition.sub", sub); } catch { /* */ } draw(); },
          text: t.label,
        })));
        clear(host);
        const t = tabs.find((x) => x.key === sub);
        if (t) guard(() => t.render(host));
      }
      view.appendChild(bar); view.appendChild(host);
      draw();
    },
  };
})();

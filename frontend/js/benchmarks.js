/* benchmarks.js — the Benchmark sub-shell inside Pulse. Renders a secondary
   sub-tab bar from window.BENCH_TABS (each benchmark-*.js registers into it):
   Baseline · Snapshots · Trends. Loaded AFTER the benchmark-*.js sub-views. */
(function () {
  const { el, clear, guard } = window.ui;
  let sub = (() => { try { return localStorage.getItem("benchmark.sub") || "baseline"; } catch { return "baseline"; } })();

  window.Views = window.Views || {};
  window.Views.benchmark = {
    id: "benchmark", label: "Benchmark", scoped: false,
    render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Benchmark" }),
        el("div.sub", { text: "Your baseline now, point-in-time snapshots, and trends over time." }),
      ])]));
      const tabs = window.BENCH_TABS || [];
      if (!tabs.some((t) => t.key === sub)) sub = tabs[0] && tabs[0].key;
      const bar = el("div.fit-subtabs");
      const host = el("div.fit-sub");
      function draw() {
        clear(bar);
        tabs.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
          onclick: () => { sub = t.key; try { localStorage.setItem("benchmark.sub", sub); } catch { /* */ } draw(); },
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

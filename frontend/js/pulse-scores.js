/* pulse-scores.js — a few named scores above Pulse's ten tabs.

   The idea is lifted from how consumer health apps frame things: don't show
   every metric you hold, roll them into a handful of named domains, each with
   one number, a colour band and a sentence saying what it means. You read the
   strip in two seconds and only go deeper when a band is off.

   Pulse has ten tabs. That's a filing cabinet, not a dashboard — this sits on
   top of it.

   Three things carried over deliberately:
     · a NUMBER is paired with a SENTENCE. A metric with no interpretation
       moves the thinking onto you every single time you look at it.
     · NO DATA is grey and says "not tracked" — never a red zero. Scoring
       silence as failure teaches you to ignore the dashboard.
     · the calculation is on the card (hover), because a number you can't
       interrogate is a number you stop trusting. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const BAND = {
    good: { c: "var(--green)", t: "good" },
    ok: { c: "var(--amber)", t: "fair" },
    attention: { c: "var(--red)", t: "needs attention" },
    none: { c: "var(--dim)", t: "not tracked" },
  };

  /* A 14-point sparkline. Inline SVG, no library — same approach as the
     Benchmark trends. Flat-zero series draw nothing rather than a misleading
     line along the floor. */
  function spark(series, colour) {
    const n = series.length;
    const max = Math.max(...series, 0);
    if (!n || max <= 0) return el("div.ps-spark-empty");
    const w = 100, h = 22;
    const pts = series.map((v, i) => {
      const x = (i / (n - 1)) * w;
      const y = h - (v / max) * (h - 3) - 1.5;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "ps-spark");
    const area = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
    area.setAttribute("points", `0,${h} ${pts} ${w},${h}`);
    area.setAttribute("fill", colour);
    area.setAttribute("opacity", "0.14");
    svg.appendChild(area);
    const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    line.setAttribute("points", pts);
    line.setAttribute("fill", "none");
    line.setAttribute("stroke", colour);
    line.setAttribute("stroke-width", "1.5");
    line.setAttribute("vector-effect", "non-scaling-stroke");
    svg.appendChild(line);
    return svg;
  }

  function card(s) {
    const band = BAND[s.band] || BAND.none;
    const hasValue = s.value !== null && s.value !== undefined;
    return el("div.ps-card", { "data-band": s.band, title: s.basis }, [
      el("div.ps-top", {}, [
        el("span.ps-dot", { style: "background:" + band.c }),
        el("span.ps-name", { text: s.label }),
        el("span.ps-val", { style: "color:" + band.c,
                            text: hasValue ? s.value + "%" : "—" }),
      ]),
      spark(s.series || [], band.c),
      el("div.ps-says", { text: s.says }),
    ]);
  }

  async function render(host) {
    const data = await api.get("/api/pulse/scores");
    clear(host);

    const head = el("div.ps-head", {}, [
      el("span.ps-title", { text: "Last " + data.window_days + " days" }),
      data.overall !== null
        ? el("span.ps-overall", { text: data.overall + "%" }) : null,
      el("span.ps-sub", {
        text: data.tracked
          ? data.tracked + " of " + data.scores.length + " tracked"
          : "nothing tracked yet — log a habit, a workout or a rest session",
      }),
    ]);

    const grid = el("div.ps-grid", {}, data.scores.map(card));
    host.appendChild(el("div.ps-strip", {}, [head, grid]));
  }

  /* Mounted by app.js at the top of every Pulse view. Kept out of the ten tab
     files so none of them has to know it exists. */
  window.PulseScores = {
    mount(viewEl) {
      const host = el("div.ps-host");
      viewEl.insertBefore(host, viewEl.firstChild);
      guard(() => render(host)).catch(() => host.remove());
    },
  };
})();

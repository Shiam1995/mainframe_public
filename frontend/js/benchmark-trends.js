/* benchmark-trends.js — Benchmark ▸ Trends. A sparkline per baseline numeric and
   per tracked metric, drawn from the values captured across snapshots. Vanilla
   inline SVG, no libraries. Shows latest value + change since the first snapshot,
   coloured by whether that change is an improvement for that metric. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;
  const BM = () => api.pulse.benchmarks;
  const NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k]));
    return n;
  }

  function sparkline(points, improved) {
    const W = 200, H = 44, pad = 4;
    const vals = points.map((p) => p.value);
    const min = Math.min(...vals), max = Math.max(...vals);
    const span = max - min || 1;
    const n = points.length;
    const x = (i) => n === 1 ? W / 2 : pad + (i * (W - 2 * pad)) / (n - 1);
    const y = (v) => H - pad - ((v - min) / span) * (H - 2 * pad);
    const stroke = improved == null ? "var(--dim)" : improved ? "var(--green)" : "var(--red)";
    const svg = svgEl("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H, style: "overflow:visible" });
    if (n >= 2) {
      svg.appendChild(svgEl("polyline", {
        points: points.map((p, i) => x(i) + "," + y(p.value)).join(" "),
        fill: "none", stroke, "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round",
      }));
    }
    points.forEach((p, i) => svg.appendChild(svgEl("circle", { cx: x(i), cy: y(p.value), r: i === n - 1 ? 3.5 : 2, fill: stroke })));
    return svg;
  }

  function card(series) {
    const pts = series.points;
    const first = pts[0].value, last = pts[pts.length - 1].value;
    const diff = Math.round((last - first) * 100) / 100;
    const improved = pts.length < 2 || diff === 0 ? null : (series.higher_is_better ? diff > 0 : diff < 0);
    const changeText = pts.length < 2 ? "1 snapshot" : (diff === 0 ? "no change" : (diff > 0 ? "+" : "") + diff + " since first");
    const changeColor = improved == null ? "var(--dim)" : improved ? "var(--green)" : "var(--red)";
    return el("div.pulse-card", { style: "min-width:230px;flex:1" }, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:6px" }, [el("span", { text: series.icon || "📊" }), el("span", { style: "font-weight:600", text: series.name })]),
        el("div", { style: "text-align:right" }, [
          el("div", { style: "font-size:18px;font-weight:700", text: last + (series.unit && !series.unit.startsWith("/") ? " " + series.unit : "") }),
          el("div.sub", { style: "color:" + changeColor, text: changeText }),
        ]),
      ]),
      el("div", { style: "margin-top:8px" }, [sparkline(pts, improved)]),
      el("div.sub", { style: "margin-top:2px", text: pts.length + " snapshot" + (pts.length === 1 ? "" : "s") + " · " + pts[0].date.slice(0, 10) + " → " + pts[pts.length - 1].date.slice(0, 10) }),
    ]);
  }

  function section(title, seriesList) {
    if (!seriesList.length) return null;
    return el("div", { style: "margin-bottom:18px" }, [
      el("div.mform-label", { style: "margin:6px 0 8px", text: title }),
      el("div", { style: "display:flex;flex-wrap:wrap;gap:12px" }, seriesList.map(card)),
    ]);
  }

  async function render(host) {
    const data = await guard(() => BM().trends());
    clear(host);
    if (!data.count) {
      host.appendChild(el("div.empty", { text: "No snapshots yet. Save a snapshot in the Baseline or Snapshots tab, then trends appear here." }));
      return;
    }
    if (!data.baseline.length && !data.metrics.length) {
      host.appendChild(el("div.empty", { text: "Snapshots exist but have no numeric data yet." }));
      return;
    }
    const b = section("Baseline", data.baseline);
    const m = section("Metrics", data.metrics);
    if (b) host.appendChild(b);
    if (m) host.appendChild(m);
    host.appendChild(el("div.sub", { text: "Green = moving in the better direction for that metric (e.g. resting HR down, VO₂max up)." }));
  }

  window.BENCH_TABS = window.BENCH_TABS || [];
  window.BENCH_TABS.push({ key: "trends", label: "Trends", render });
})();

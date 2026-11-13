/* habits-trends.js — Habits ▸ Trends. Analytics across ALL habits: per-habit
   weekly done-count bars (last 12 weeks), current + longest streak, and 30/90-day
   completion rates. Vanilla inline-SVG bars, no libraries. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;
  const P = window.PULSE;
  const NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs) {
    const n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach((k) => n.setAttribute(k, attrs[k]));
    return n;
  }

  function weeklyBars(weekly) {
    const W = 260, H = 54, pad = 4, n = weekly.length;
    const bw = (W - 2 * pad) / n;
    const max = 7;
    const svg = svgEl("svg", { width: W, height: H, viewBox: "0 0 " + W + " " + H });
    weekly.forEach((wk, i) => {
      const h = Math.max(1, (wk.count / max) * (H - 2 * pad));
      const x = pad + i * bw;
      const y = H - pad - h;
      const bar = svgEl("rect", { x: x + 1, y, width: Math.max(1, bw - 2), height: h, rx: 1.5, fill: wk.count ? "var(--accent)" : "var(--border)" });
      const t = svgEl("title", {}); t.textContent = wk.week + ": " + wk.count + "/7 days";
      bar.appendChild(t);
      svg.appendChild(bar);
    });
    return svg;
  }

  function stat(label, value, color) {
    return el("div", { style: "text-align:center" }, [
      el("div", { style: "font-size:17px;font-weight:700" + (color ? ";color:" + color : ""), text: String(value) }),
      el("div.sub", { text: label }),
    ]);
  }

  function habitCard(h) {
    const rateColor = (r) => r >= 70 ? "var(--green)" : r >= 40 ? "var(--amber)" : "var(--red)";
    return el("div.pulse-card", {}, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:8px" }, [
          el("span", { style: "font-size:18px", text: P.catIcon(P.HABIT_CATS, h.category) }),
          el("span", { style: "font-weight:600", text: h.name }),
          h.active === false ? el("span.pulse-tag", { text: "inactive" }) : null,
        ]),
        el("div.row", { style: "gap:16px" }, [
          stat("🔥 streak", h.streak),
          stat("longest", h.longest),
          stat("30d", h.rate30 + "%", rateColor(h.rate30)),
          stat("90d", h.rate90 + "%", rateColor(h.rate90)),
        ]),
      ]),
      el("div", { style: "margin-top:10px" }, [weeklyBars(h.weekly)]),
      el("div.sub", { style: "margin-top:2px", text: "done-days per week · last " + h.weekly.length + " weeks · " + h.total + " total logged" }),
    ]);
  }

  async function render(host) {
    const data = await guard(() => api.pulse.habitTrends());
    clear(host);
    const habits = data.habits || [];
    if (!habits.length) {
      host.appendChild(el("div.empty", { text: "No habits yet. Add habits in My Habits, then log days in Active Tracking — trends build from there." }));
      return;
    }
    // overall summary
    const totalDays = habits.reduce((a, h) => a + h.total, 0);
    const bestStreak = habits.reduce((a, h) => Math.max(a, h.streak), 0);
    const bestLongest = habits.reduce((a, h) => Math.max(a, h.longest), 0);
    host.appendChild(el("div.pulse-card", {}, [
      el("div.row", { style: "justify-content:space-around;gap:16px" }, [
        stat("habits", habits.length),
        stat("done-days logged", totalDays),
        stat("🔥 best current streak", bestStreak),
        stat("longest ever", bestLongest),
      ]),
    ]));
    if (data.habits.every((h) => h.total === 0)) {
      host.appendChild(el("div.sub", { style: "margin:10px 0", text: "No day-logs yet — log completions in Active Tracking and the weekly bars fill in." }));
    }
    host.appendChild(el("div.mform-label", { style: "margin:16px 0 8px", text: "Per-habit trends" }));
    habits.forEach((h) => host.appendChild(habitCard(h)));
  }

  window.HABIT_TABS = window.HABIT_TABS || [];
  window.HABIT_TABS.push({ key: "trends", label: "Trends", render });
})();

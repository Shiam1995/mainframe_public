/* nutrition-dashboard.js — today at a glance (NUTRITION_SPEC §1).

   The calorie ring is the hero visual and the spec forbids skipping it. Every
   number here is computed server-side from the same log the other tabs write,
   so the dashboard can't disagree with the food log. */
(function () {
  const { el, clear, guard } = window.ui;

  function render(host) {
    clear(host);
    const body = el("div");
    host.appendChild(body);

    guard(async () => {
      const d = await window.NUT.N().dashboard();
      const { MACRO, calorieRing, macroBar, SLOT, n0, n1 } = window.NUT;
      clear(body);

      const cal = d.totals.calories || 0;
      const target = d.goals.daily_calories || 0;

      // --- hero: ring + macro bars ---
      const bars = el("div", { style: "flex:1;min-width:240px;display:flex;flex-direction:column;gap:12px" },
        MACRO.map((m) => macroBar(m, d.totals[m.key] || 0, d.goals[m.goal] || 0)));
      body.appendChild(el("div.card", {}, [
        el("div.row", { style: "gap:24px;flex-wrap:wrap;align-items:center" }, [
          el("div", { style: "display:flex;flex-direction:column;align-items:center;gap:6px" }, [
            calorieRing(cal, target),
            el("div.sub", { style: "font-size:11px", text: d.date }),
          ]),
          bars,
        ]),
      ]));

      // --- water + weight + streak ---
      const stat = (v, l, c) => el("div.prog-box", {}, [
        el("div.prog-val", { style: "color:" + c, text: String(v) }),
        el("div.prog-label", { text: l }),
      ]);
      const w = d.water || {};
      const trend = d.weight && d.weight.trend;
      const arrow = !trend ? "" : trend.direction === "up" ? "▲" : trend.direction === "down" ? "▼" : "▬";
      // Down is only "good" when the goal is to lose — the arrow states the
      // direction, the colour states whether it's the way you wanted.
      const goalDir = d.goals.weight_goal;
      const good = trend && ((goalDir === "lose" && trend.direction === "down")
        || (goalDir === "gain" && trend.direction === "up")
        || (goalDir === "maintain" && trend.direction === "stable"));
      body.appendChild(el("div.prog-grid", { style: "margin-top:14px" }, [
        stat(n0(w.total_ml) + " / " + n0(w.target_ml) + "ml", "water", "#5DA9FF"),
        stat(d.weight && d.weight.current != null ? n1(d.weight.current) + "kg" : "—", "weight", window.NUT.GREEN),
        stat(trend ? arrow + " " + Math.abs(trend.delta) + "kg" : "—", "vs last week",
          !trend ? "var(--dim)" : good ? window.NUT.GREEN : "var(--amber)"),
        stat(d.streak_days, d.streak_days === 1 ? "day streak" : "day streak", "var(--amber)"),
        stat(n0(d.weekly_avg_calories), "weekly avg cal", "var(--dim)"),
        stat(d.entry_count, "entries today", "var(--dim)"),
      ]));

      // --- meal summary ---
      const logged = {};
      (d.slots || []).forEach((s) => { logged[s.meal_slot] = s; });
      const cards = window.NUT.SLOTS.map((s) => {
        const hit = logged[s.key];
        return el("div.nt-meal" + (hit ? "" : ".empty"), {}, [
          el("span", { text: s.icon }),
          el("span", { style: "flex:1", text: s.label }),
          el("span.mono", { style: "font-size:11px;color:" + (hit ? window.NUT.GREEN : "var(--muted)"),
            text: hit ? n0(hit.calories) + " cal" : "not logged" }),
        ]);
      });
      // any custom slot the user invented, after the six fixed ones
      Object.keys(logged).filter((k) => !window.NUT.SLOTS.some((s) => s.key === k)).forEach((k) => {
        cards.push(el("div.nt-meal", {}, [
          el("span", { text: SLOT(k).icon }), el("span", { style: "flex:1", text: k }),
          el("span.mono", { style: "font-size:11px;color:" + window.NUT.GREEN, text: n0(logged[k].calories) + " cal" }),
        ]));
      });
      body.appendChild(el("div.card", { style: "margin-top:14px" }, [
        el("h3", { style: "margin:0 0 8px", text: "Today's meals" }),
        el("div.nt-meals", {}, cards),
      ]));

      if (d.fasting_active) {
        body.appendChild(el("div.card", { style: "margin-top:14px" }, [
          el("div.row", { style: "gap:8px;align-items:center" }, [
            el("span", { text: "⏳" }),
            el("span", { text: "Fasting since " + (d.fasting_active.start_time || "").slice(0, 16).replace("T", " ") }),
            el("span.sub", { style: "margin-left:auto;font-size:11px",
              text: "target " + d.fasting_active.target_hours + "h" }),
          ]),
        ]));
      }

      if (!d.entry_count) {
        body.appendChild(el("div.empty", { style: "margin-top:14px",
          text: "Nothing logged today — the Food Log tab is where the day gets filled in." }));
      }
    });
  }

  window.NUT_TABS = window.NUT_TABS || [];
  // Dropped from the Nutrition tab bar 2026-08-18 (user: "the rest i dont think need to stay").
  // The view still works — uncomment to bring it back. Data is untouched either way.
  // window.NUT_TABS.push({ key: "dashboard", label: "Dashboard", order: 10, render });
})();

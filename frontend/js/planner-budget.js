/* planner-budget.js — PLANNER_SPEC v2 §3, the Budget surface.

   Answers "what fits before the horizon, and in what order?". Capacity × weeks
   gives a supply; items are funded top-down in priority order until it runs
   out. Everything below the cutline is deferred — that visible cost is the
   whole point of the view.

   Every edit here also moves the Calendar: a change to priority, hours/week or
   total hours re-runs auto-placement, so the week strip under the supply bar
   repaints and any mounted Calendar view is told to refetch (spec §3, §11.2). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const BASE = "/api/planner";

  const fmtH = (h) => (h == null ? "—" : (Math.round(h * 10) / 10) + "h");
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  const iso = (d) => {
    const x = new Date(d);
    return new Date(x.getTime() - x.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
  };

  /* --------------------------------------------------------------- render */
  async function render(host, ctx) {
    const P = window.PLANNER;

    async function reload() {
      const [budget, settings, week] = await guard(() => Promise.all([
        api.get(BASE + "/budget"),
        api.get(BASE + "/settings"),
        api.get(BASE + "/calendar?view=week&date=" + iso(new Date())),
      ]));
      draw(budget, settings, week);
    }

    /* A budget edit changes what auto-placement produces, so the calendar has
       to be recomputed too — not just the funding numbers. */
    async function commit(fn) {
      await guard(fn);
      P.notify();
      await reload();
    }

    function draw(budget, settings, week) {
      clear(host);

      /* ------------------------------------------------------ supply head */
      const capVal = el("span.plb-num", { text: fmtH(settings.capacity_per_week) + "/wk" });
      const cap = el("input", {
        type: "range", min: "1", max: "60", step: "1",
        value: String(Math.round(settings.capacity_per_week)),
        style: "flex:1",
      });
      cap.addEventListener("input", () => { capVal.textContent = cap.value + "h/wk"; });
      cap.addEventListener("change", () => commit(() =>
        api.patch(BASE + "/settings", { capacity_per_week: parseFloat(cap.value) })));

      const weeksNow = Math.max(1, Math.round(budget.weeks_to_horizon));
      const horVal = el("span.plb-num", {
        text: budget.horizon_date + " · " + weeksNow + "w",
      });
      const hor = el("input", {
        type: "range", min: "1", max: "104", step: "1",
        value: String(Math.min(104, weeksNow)), style: "flex:1",
      });
      hor.addEventListener("input", () => {
        const d = new Date();
        d.setDate(d.getDate() + parseInt(hor.value, 10) * 7);
        horVal.textContent = iso(d) + " · " + hor.value + "w";
      });
      hor.addEventListener("change", () => {
        const d = new Date();
        d.setDate(d.getDate() + parseInt(hor.value, 10) * 7);
        commit(() => api.patch(BASE + "/settings", { horizon_date: iso(d) }));
      });

      host.appendChild(el("div.plb-controls", {}, [
        el("label.plb-ctl", {}, [el("span.plb-ctl-l", { text: "capacity" }), cap, capVal]),
        el("label.plb-ctl", {}, [el("span.plb-ctl-l", { text: "horizon" }), hor, horVal]),
      ]));

      /* ------------------------------------------------- used / supply bar */
      const pct = budget.supply_hours > 0
        ? Math.min(100, (budget.used_hours / budget.supply_hours) * 100) : 0;
      const over = budget.summary.deferred > 0 || budget.summary.partial > 0;
      host.appendChild(el("div.plb-supply", {}, [
        el("div.spread", {}, [
          el("span.plb-supply-l", {
            text: fmtH(budget.used_hours) + " committed of " + fmtH(budget.supply_hours) + " supply",
          }),
          el("span.sub", { text: fmtH(budget.remaining_hours) + " unspent" }),
        ]),
        el("div.pl-prog", {}, [
          el("div.pl-prog-fill" + (over ? ".tight" : ""), { style: "width:" + pct + "%" }),
        ]),
        el("div.plb-summary", {}, [
          el("span.pl-chip.ontrack", { text: budget.summary.funded + " fully funded" }),
          el("span.pl-chip.drift", { text: budget.summary.partial + " partial" }),
          el("span.pl-chip.dropped", { text: budget.summary.deferred + " deferred" }),
        ]),
      ]));

      host.appendChild(weekStrip(week));

      /* ----------------------------------------------------------- adder */
      const nName = el("input.mform-input", { placeholder: "new item, e.g. Finish the C textbook" });
      const nTotal = el("input.mform-input", {
        type: "number", min: "0", step: "0.5", placeholder: "total h", style: "width:90px",
      });
      const nCat = el("select.mform-input", { style: "width:110px" },
        Object.keys(P.CATS).map((c) => el("option", { value: c, text: c })));
      const add = () => {
        const total = parseFloat(nTotal.value);
        if (!nName.value.trim()) return toast("name is required", true);
        if (!(total > 0)) return toast("total hours must be greater than 0", true);
        return commit(async () => {
          await api.post(BASE + "/items", {
            name: nName.value.trim(), category: nCat.value,
            total_hours: total, hours_per_week: 0,
          });
          nName.value = ""; nTotal.value = "";
        });
      };
      nName.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      host.appendChild(el("div.plb-add", {}, [
        nName, nTotal, nCat,
        el("button.btn-primary", { onclick: add, text: "＋ add" }),
      ]));

      /* ------------------------------------------------------- item rows */
      if (!budget.rows.length) {
        host.appendChild(el("div.empty", {
          text: "No plan items yet. Add the things you are working through above — "
              + "books, lecture series, builds, problem sets.",
        }));
        return;
      }

      const list = el("div.plb-list");
      budget.rows.forEach((r, idx) => list.appendChild(row(r, idx, budget)));
      host.appendChild(list);
    }

    /* -------------------------------------------------------------- a row */
    function row(r, idx, budget) {
      const P = window.PLANNER;
      const move = (dir) => commit(() => {
        const ids = budget.rows.map((x) => x.id);
        const j = idx + dir;
        if (j < 0 || j >= ids.length) return Promise.resolve();
        [ids[idx], ids[j]] = [ids[j], ids[idx]];
        return api.post(BASE + "/items/reorder", { ids });
      });

      const hpwVal = el("span.plb-hpw-v", { text: fmtH(r.hours_per_week) + "/wk" });
      const hpw = el("input", {
        type: "range", min: "0", max: "40", step: "0.5",
        value: String(r.hours_per_week || 0), style: "width:110px",
        title: r.placement === "auto"
          ? "weekly budget — drives how much calendar time this claims"
          : "weekly budget (this item is hand-placed, so it claims no auto slots)",
      });
      hpw.addEventListener("input", () => { hpwVal.textContent = hpw.value + "h/wk"; });
      hpw.addEventListener("change", () => commit(() =>
        api.patch(BASE + "/items/" + r.id, { hours_per_week: parseFloat(hpw.value) })));

      const total = el("input.plb-total", {
        type: "number", min: "0", step: "0.5", value: String(r.total_hours),
        title: "total hours estimate",
      });
      total.addEventListener("change", () => {
        const v = parseFloat(total.value);
        if (!(v > 0)) { toast("total hours must be greater than 0", true); return; }
        commit(() => api.patch(BASE + "/items/" + r.id, { total_hours: v }));
      });

      const chipCls = { funded: ".ontrack", partial: ".drift", deferred: ".dropped" }[r.funding_state];
      return el("div.plb-row" + (r.funding_state === "deferred" ? ".is-deferred" : ""), {}, [
        el("div.plb-ord", {}, [
          el("button.ord-btn", { onclick: () => move(-1), title: "move up", text: "▲" }),
          el("button.ord-btn", { onclick: () => move(1), title: "move down", text: "▼" }),
        ]),
        el("span.plb-swatch", {
          style: "background:" + P.CATS[r.category], title: r.category,
        }),
        el("div.plb-name", {}, [
          el("span.plb-title", {
            title: "open the item card",
            onclick: () => ctx.openItem(r.id),
            text: r.name,
          }),
          P.markerGlyph(r.marker),
          r.placement === "manual"
            ? el("span.plb-hand", { title: "hand-placed on the calendar", text: "hand" })
            : null,
        ].filter(Boolean)),
        el("span.pl-chip" + chipCls, { text: r.funding_chip }),
        el("div.plb-hpw", {}, [hpw, hpwVal]),
        el("div.plb-hours", {}, [
          el("span", { text: fmtH(r.funded_hours) }),
          el("span.sub", { text: " / " }), total, el("span.sub", { text: "h" }),
        ]),
        el("button.plb-x", {
          title: "remove this item",
          onclick: () => confirmDo("Remove “" + r.name + "” from the plan?",
            () => commit(() => api.del(BASE + "/items/" + r.id))),
          text: "✕",
        }),
      ]);
    }

    /* ---------------------------------------------- live auto-placed week */
    /* Proof that Budget and Calendar are one list: this repaints on every
       edit above, without touching the Calendar tab (spec §11.2). */
    function weekStrip(week) {
      const mins = {};
      (week.events || []).forEach((e) => {
        if (e.source !== "auto") return;
        const d = e.start.slice(0, 10);
        mins[d] = (mins[d] || 0) + e.minutes;
      });
      const days = [];
      const mon = new Date(week.range_start + "T00:00:00");
      for (let i = 0; i < 7; i++) {
        const d = new Date(mon); d.setDate(d.getDate() + i);
        days.push(iso(d));
      }
      const max = Math.max(60, ...days.map((d) => mins[d] || 0));
      const total = days.reduce((s, d) => s + (mins[d] || 0), 0) / 60;

      return el("div.plb-week", {}, [
        el("div.spread", {}, [
          el("span.plb-week-l", { text: "auto-placed this week" }),
          el("span.sub", { text: fmtH(total) + " scheduled" }),
        ]),
        el("div.plb-week-grid", {}, days.map((d, i) => {
          const m = mins[d] || 0;
          const blocked = Object.prototype.hasOwnProperty.call(week.blocked || {}, d);
          const col = el("div.plb-week-col" + (blocked ? ".blocked" : ""), {
            title: blocked ? d + " — blocked off"
                           : d + " · " + fmtH(m / 60) + " auto-placed",
          }, [
            el("div.plb-week-bar-wrap", {}, [
              el("div.plb-week-bar", { style: "height:" + (m ? Math.max(4, (m / max) * 100) : 0) + "%" }),
            ]),
            el("span.plb-week-d", { text: blocked ? "off" : DOW[i] }),
          ]);
          return col;
        })),
      ]);
    }

    await reload();
    return reload;
  }

  window.PLANNER_TABS = window.PLANNER_TABS || [];
  window.PLANNER_TABS.push({ key: "budget", label: "Budget", order: 10, render });
})();

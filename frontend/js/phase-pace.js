/* phase-pace.js — Pace: the plan against the hours, day by day.

   The Phase view answers "what did I set out to do". This one answers the
   question you can only ask once a phase is running: was the plan any good?

   IT IS AN INSTRUMENT, NOT A SCOREBOARD. A phase is seeded with fourteen weeks
   of guessed hours. Two or three real weeks are enough to tell you which of
   those guesses were fantasy, and the point of showing it every day is that
   there is still phase left to spend when you find out. So the verdicts are
   about the PLAN, not about you: "plan too heavy" means the plan asked for more
   than a real week of yours holds.

   THREE NUMBERS ON THE DAY, because a day has no plan of its own — the plan is
   written in weeks, and collapsing it to a single daily target would hide the
   one number that actually moves:
     share    what an even week would ask of today
     logged   what you put in
     catch-up this week's plan still outstanding ÷ the days left in it. Skip a
              day and it climbs. That climb is the earliest honest warning.

   IT REFUSES TO GUESS. Under two complete weeks with work in them, every
   verdict reads "not enough weeks yet" in as many words, and the view says how
   many weeks are still needed. A confident bar over four days of data would be
   the one way this screen could actually mislead.

   Everything here is read from /api/phases/active/pace in one request against
   one `today`. The only thing it writes is a work session, because a view that
   asks you to log hours and then makes you go elsewhere to do it will not be
   used on a Tuesday. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const DOW = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const h1 = (n) => (n == null ? "—" : (Math.round(n * 10) / 10).toFixed(1) + "h");

  /* Verdict → colour. The band in the middle is deliberately wide; a plan that
     has to be met to the hour is not a plan. */
  const VERDICT = {
    "plan too heavy": { c: "var(--amber)", why: "the plan asked for more than the week held" },
    "plan too light": { c: "var(--teal)",  why: "you did more than the plan asked for" },
    "about right":    { c: "var(--green)", why: "the plan and the week agree" },
    "unknown":        { c: "var(--dim)",   why: "nothing planned and nothing logged" },
  };
  const verdictColor = (v) => (VERDICT[v] || { c: "var(--dim)" }).c;

  function stat(label, value, sub, colour) {
    return el("div.pace-stat", {}, [
      el("div.wl-label", { text: label }),
      el("div.pace-statv", { style: colour ? "color:" + colour : "", text: value }),
      sub ? el("div.pace-statsub", { text: sub }) : null,
    ]);
  }

  /* A bar that can go past its own end, because the whole point is to show when
     it does. `over` paints the excess in a second colour rather than clipping
     it, which is what a capacity you have blown through looks like. */
  function bar(value, ref, colour) {
    const pct = ref > 0 ? Math.min(100, (value / ref) * 100) : 0;
    const over = ref > 0 && value > ref;
    return el("div.pace-bar", { title: h1(value) + " of " + h1(ref) }, [
      el("div.pace-barfill", {
        style: "width:" + (over ? 100 : pct) + "%;background:" +
               (over ? "var(--amber)" : (colour || "var(--accent)")),
      }),
    ]);
  }

  window.PhasePace = {
    /* `reload` lets the host tab re-read after something is logged. */
    async render(host, reload) {
      const d = await guard(() => api.get("/api/phases/active/pace"));
      clear(host);
      if (!d || !d.phase) {
        host.appendChild(el("div.card", {}, [
          el("div.sub", { text: "no phase running — nothing to pace against." }),
        ]));
        return;
      }

      const cal = d.calibration;
      const grid = el("div.ph-grid");
      host.appendChild(grid);

      /* ---------------- 1. the day ---------------- */
      const day = el("div.card.ph-span7");
      grid.appendChild(day);
      if (!d.started) {
        day.appendChild(el("div.wl-label", { text: "today" }));
        day.appendChild(el("div.pace-lede", {
          text: "the phase starts in " + d.days_until_start +
                (d.days_until_start === 1 ? " day" : " days") + ".",
        }));
        day.appendChild(el("div.sub", {
          text: "nothing to measure yet. from day one this page fills in on its own — " +
                "log the hours as you go and it will tell you which weeks were honest.",
        }));
      } else {
        const t = d.today_row || {};
        day.appendChild(el("div.pace-head", {}, [
          el("div.wl-label", { text: "today · week " + (t.week || d.phase.week_index) + " of " + d.phase.weeks }),
          el("div.pace-meta", { text: (t.days_left_in_week || 0) + " days left in the week" }),
        ]));
        day.appendChild(el("div.pace-stats", {}, [
          stat("logged", h1(t.logged_h),
               t.logged_h >= (t.share_h || 0) ? "at or past the even share" : "under the even share",
               t.logged_h >= (t.share_h || 0) ? "var(--green)" : null),
          stat("even share", h1(t.share_h), "the week's plan ÷ 7"),
          stat("catch-up", h1(t.catchup_h),
               "per remaining day to still hit " + h1(t.week_planned_h),
               (t.catchup_h || 0) > 10 ? "var(--red)" : "var(--muted)"),
        ]));
        day.appendChild(el("div.pace-wk", {}, [
          el("div.pace-wklabel", {
            text: "week " + t.week + ": " + h1(t.week_logged_h) + " of " + h1(t.week_planned_h) +
                  " planned · capacity " + h1(d.phase.capacity_h_per_week),
          }),
          bar(t.week_logged_h, t.week_planned_h),
        ]));
      }

      /* ---------------- 2. the calibration verdict ---------------- */
      const verdict = el("div.card.ph-span5");
      grid.appendChild(verdict);
      verdict.appendChild(el("div.pace-head", {}, [
        el("div.wl-label", { text: "is the plan any good?" }),
        el("div.pace-chip", {
          style: "border-color:" + (cal.weeks_complete >= cal.weeks_needed ? "var(--accent)" : "var(--border)"),
          text: cal.confidence,
        }),
      ]));
      if (cal.weeks_complete < cal.weeks_needed) {
        const need = cal.weeks_needed - cal.weeks_complete;
        verdict.appendChild(el("div.pace-lede", {
          text: need + " more complete " + (need === 1 ? "week" : "weeks") + " before this can say.",
        }));
        verdict.appendChild(el("div.sub", {
          text: cal.weeks_complete === 0
            ? "a verdict off zero weeks would be a guess with a number on it."
            : cal.weeks_complete + " week in so far. one more and the per-project read below turns on.",
        }));
      } else {
        verdict.appendChild(el("div.pace-lede", {
          style: "color:" + verdictColor(cal.verdict), text: cal.verdict,
        }));
        verdict.appendChild(el("div.sub", {
          text: "over " + cal.weeks_complete + " complete weeks, a real week of yours holds " +
                h1(cal.real_week_h) + ". the plan asks " + h1(cal.plan_week_h) + ".",
        }));
      }
      /* True on day one, and the reason this box is never empty: the plan's own
         arithmetic against the capacity the phase claims to have. */
      verdict.appendChild(el("div.pace-rule"));
      verdict.appendChild(el("div.wl-label", { text: "before any hours are logged" }));
      const planned = cal.plan_total_h, capacity = cal.capacity_total_h || 0;
      const ratio = capacity > 0 ? planned / capacity : null;
      verdict.appendChild(el("div.pace-lines", {}, [
        el("div", { text: "the plan asks " + h1(planned) + " across " + d.phase.weeks + " weeks" }),
        el("div", {
          text: "capacity is " + h1(capacity) + " (" + h1(cal.capacity_h) + "/week" +
                (cal.capacity_ceiling_h ? ", ceiling " + h1(cal.capacity_ceiling_h) : "") + ")",
        }),
        ratio ? el("div", {
          style: "color:" + (ratio > 1.05 ? "var(--red)" : "var(--muted)"),
          text: "that is " + (Math.round(ratio * 100) / 100) + "× capacity",
        }) : null,
        cal.unplanned_claim_h ? el("div", {
          style: "color:var(--amber)",
          text: "+ " + h1(cal.unplanned_claim_h) + " claimed with no weekly plan (the cadences), " +
                "which the week totals cannot see",
        }) : null,
        cal.off_plan_h ? el("div", {
          text: h1(cal.off_plan_h) + " logged in the window on nothing the phase claimed",
        }) : null,
      ]));

      /* ---------------- 3. the day strip ---------------- */
      if (d.days.length) {
        const strip = el("div.card.ph-span12");
        grid.appendChild(strip);
        strip.appendChild(el("div.pace-head", {}, [
          el("div.wl-label", { text: "the last " + d.days.length + " days" }),
          el("div.pace-meta", { text: "bar height is hours logged · the line is the even share for that week" }),
        ]));
        const peak = Math.max(1, ...d.days.map((x) => Math.max(x.logged_h, x.share_h)));
        const row = el("div.pace-strip");
        d.days.forEach((x) => {
          const hpx = Math.round((x.logged_h / peak) * 56);
          const spx = Math.round((x.share_h / peak) * 56);
          row.appendChild(el("div.pace-daycol" + (x.is_today ? ".now" : ""), {
            title: x.date + " · " + h1(x.logged_h) + " logged · " + h1(x.share_h) + " even share" +
                   (x.sessions ? " · " + x.sessions + " sessions" : ""),
          }, [
            el("div.pace-daybars", {}, [
              el("div.pace-dayshare", { style: "bottom:" + spx + "px" }),
              el("div.pace-daybar", {
                style: "height:" + hpx + "px;background:" +
                       (x.logged_h === 0 ? "rgba(255,255,255,.07)"
                        : x.logged_h >= x.share_h ? "var(--green)" : "var(--accent)"),
              }),
            ]),
            el("div.pace-daydow", { text: DOW[x.dow] }),
          ]));
        });
        strip.appendChild(row);
      }

      /* ---------------- 4. the weeks ---------------- */
      const wk = el("div.card.ph-span6");
      grid.appendChild(wk);
      wk.appendChild(el("div.wl-label", { text: "weeks" }));
      const wt = el("table.pace-table");
      wt.appendChild(el("thead", {}, [el("tr", {}, [
        el("th", { text: "wk" }), el("th", { text: "from" }),
        el("th.num", { text: "planned" }), el("th.num", { text: "logged" }),
        el("th.num", { text: "vs cap" }), el("th", { text: "" }),
      ])]));
      const wb = el("tbody");
      d.weeks.forEach((w) => {
        const over = w.over_capacity_h;
        wb.appendChild(el("tr" + (w.current ? ".now" : "") + (w.complete ? "" : ".ahead"), {}, [
          el("td", { text: String(w.week) }),
          el("td.mono", { text: w.start.slice(5) }),
          el("td.num", { text: h1(w.planned_h) }),
          el("td.num", { text: w.complete || w.current ? h1(w.logged_h) : "" }),
          el("td.num", {
            style: over > 0 ? "color:var(--red)" : "",
            text: over == null ? "" : (over > 0 ? "+" : "") + h1(over),
          }),
          el("td", {}, [w.complete || w.current ? bar(w.logged_h, w.planned_h) : null]),
        ]));
      });
      wt.appendChild(wb);
      wk.appendChild(wt);

      /* ---------------- 5. the projects ---------------- */
      const pj = el("div.card.ph-span6");
      grid.appendChild(pj);
      pj.appendChild(el("div.pace-head", {}, [
        el("div.wl-label", { text: "per project" }),
        el("div.pace-meta", {
          text: cal.weeks_complete >= cal.weeks_needed
            ? "measured over the " + cal.weeks_complete + " complete weeks only"
            : "verdicts turn on after " + cal.weeks_needed + " complete weeks",
        }),
      ]));
      const pt = el("table.pace-table");
      pt.appendChild(el("thead", {}, [el("tr", {}, [
        el("th", { text: "project" }), el("th.num", { text: "plan/wk" }),
        el("th.num", { text: "real/wk" }), el("th", { text: "" }),
      ])]));
      const pb = el("tbody");
      const order = { "plan too heavy": 0, "plan too light": 1, "about right": 2 };
      d.projects.slice().sort((a, b) =>
        (order[a.verdict] ?? 9) - (order[b.verdict] ?? 9) ||
        b.planned_total_h - a.planned_total_h
      ).forEach((p) => {
        const known = p.ratio != null;
        pb.appendChild(el("tr", {}, [
          el("td", {}, [
            el("div.pace-pname", { text: p.name }),
            el("div.pace-meta", { text: p.tier + (p.ref ? " · " + p.ref : "") +
              " · " + h1(p.planned_total_h) + " planned in all" }),
          ]),
          el("td.num", { text: p.planned_per_week_h == null ? "—" : h1(p.planned_per_week_h) }),
          el("td.num", { text: p.logged_per_week_h == null ? "—" : h1(p.logged_per_week_h) }),
          el("td", {}, [
            el("div.pace-vd", {
              style: "color:" + verdictColor(p.verdict),
              title: (VERDICT[p.verdict] || {}).why || "",
              text: known ? p.verdict : "—",
            }),
            known ? el("div.pace-ratio", { text: "×" + p.ratio }) : null,
          ]),
        ]));
      });
      pt.appendChild(pb);
      pj.appendChild(pt);

      /* ---------------- 6. log an hour ---------------- */
      const logc = el("div.card.ph-span12");
      grid.appendChild(logc);
      logc.appendChild(el("div.pace-head", {}, [
        el("div.wl-label", { text: "log hours" }),
        el("div.pace-meta", {
          text: "writes one work session — the same rows every number above is summed from",
        }),
      ]));
      const pick = el("select.pace-pick");
      d.projects.forEach((p) => pick.appendChild(el("option", { value: p.id, text: p.name })));
      const when = el("input.pace-when", { type: "date", value: d.today });
      const hrs = el("input.pace-hrs", { type: "number", step: "0.25", min: "0", placeholder: "h" });
      const what = el("input.pace-what", { type: "text", placeholder: "what you did (optional)" });
      const go = el("button.btn-primary", { text: "log" });
      go.addEventListener("click", async () => {
        const hours = parseFloat(hrs.value);
        if (!(hours > 0)) { toast("how many hours?", true); return; }
        const opt = pick.options[pick.selectedIndex];
        await guard(() => api.post("/api/work", {
          date: when.value || d.today,
          mins: Math.round(hours * 60),
          module: "synapse",
          ref_kind: "project",
          ref_id: pick.value,
          ref_title: opt ? opt.text : "",
          what: what.value || "",
        }));
        toast(hours + "h logged");
        hrs.value = ""; what.value = "";
        if (reload) reload(); else this.render(host, reload);
      });
      logc.appendChild(el("div.pace-logrow", {}, [pick, when, hrs, what, go]));
    },
  };
})();

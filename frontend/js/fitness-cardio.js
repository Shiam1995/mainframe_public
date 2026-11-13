/* fitness-cardio.js — Cardio, kept separate from strength.

   Sets and reps say nothing useful about a run. This section tracks distance,
   pace, heart rate and time-in-zone instead. Pace is never entered — it's
   derived server-side from distance and duration, so it can't drift out of
   step with them. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const TYPES = ["run", "walk", "cycle", "swim", "row", "hike", "other"];
  // Z1 easy → Z5 max
  const ZONE_COLOR = ["#7FA8C8", "#00D4AA", "#00F5D4", "#F0A030", "#FF4757"];
  const ZONE_NAME = ["Z1 easy", "Z2 aerobic", "Z3 tempo", "Z4 threshold", "Z5 max"];

  const fmtPace = (p) => (p == null ? "—" : Math.floor(p) + ":" + String(Math.round((p % 1) * 60)).padStart(2, "0") + " /km");

  function zoneBar(zones) {
    const total = zones.reduce((a, b) => a + (b || 0), 0);
    const bar = el("div.cardio-zones", { title: zones.map((z, i) => ZONE_NAME[i] + " " + z + "m").join(" · ") });
    if (!total) return el("span.sub", { style: "font-size:11px", text: "no zone data" });
    zones.forEach((z, i) => {
      if (!z) return;
      bar.appendChild(el("div", { style: "width:" + (100 * z / total) + "%;background:" + ZONE_COLOR[i],
        title: ZONE_NAME[i] + " · " + z + " min" }));
    });
    return bar;
  }

  function form(reload, host) {
    const date = el("input", { type: "date", value: new Date().toISOString().slice(0, 10) });
    const type = el("select", {}, TYPES.map((t) => el("option", { value: t, text: t })));
    // LISS = one steady block; HIIT = intervals, counted in sets.
    const style = el("select", {}, [["", "—"], ["liss", "LISS"], ["hiit", "HIIT"]].map(([v, t]) => el("option", { value: v, text: t })));
    const sets = el("input", { type: "number", min: "1", placeholder: "sets", style: "width:64px" });
    const paintSets = () => { sets.disabled = style.value !== "hiit"; if (sets.disabled) sets.value = ""; };
    style.addEventListener("change", paintSets);
    paintSets();
    const dist = el("input", { type: "number", step: "0.01", min: "0", placeholder: "km", style: "width:86px" });
    const mins = el("input", { type: "number", min: "0", placeholder: "mins", style: "width:80px" });
    const avg = el("input", { type: "number", min: "0", placeholder: "avg HR", style: "width:82px" });
    const max = el("input", { type: "number", min: "0", placeholder: "max HR", style: "width:82px" });
    const rpe = el("input", { type: "number", min: "1", max: "10", placeholder: "RPE", style: "width:64px" });
    const route = el("input", { placeholder: "route (optional)", style: "flex:1;min-width:140px" });
    const zs = ZONE_NAME.map(() => el("input", { type: "number", min: "0", value: "0", style: "width:56px" }));
    const notes = el("input", { placeholder: "notes", style: "flex:1;min-width:160px" });
    const field = (l, n) => el("label.wl-field", {}, [el("span.wl-label", { text: l }), n]);

    // live pace preview, so you see it before saving
    const preview = el("span.sub", { style: "font-size:11px" });
    const calc = () => {
      const d = Number(dist.value) || 0, m = Number(mins.value) || 0;
      preview.textContent = d && m ? fmtPace(m / d) + " · " + (d / (m / 60)).toFixed(2) + " km/h" : "";
    };
    [dist, mins].forEach((n) => n.addEventListener("input", calc));

    return el("div.card", {}, [
      el("div.sub", { style: "text-transform:uppercase;letter-spacing:1px;font-size:10px", text: "Log a session" }),
      el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap;align-items:flex-end" }, [
        field("date", date), field("type", type), field("style", style), field("HIIT sets", sets), field("distance", dist), field("duration", mins),
        field("avg HR", avg), field("max HR", max), field("RPE", rpe), preview,
      ]),
      el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap;align-items:flex-end" }, [
        ...zs.map((z, i) => field(ZONE_NAME[i], z)),
      ]),
      el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap" }, [
        route, notes,
        el("button.btn-primary", {
          onclick: () => guard(async () => {
            if (!Number(dist.value) && !Number(mins.value) && !Number(sets.value)) return toast("distance, duration or HIIT sets, at least", true);
            await api.post("/api/pulse/fitness/cardio", {
              date: date.value, type: type.value, style: style.value || null,
              sets: style.value === "hiit" && Number(sets.value) > 0 ? Math.round(Number(sets.value)) : null,
              distance_km: Number(dist.value) || 0, duration_mins: Number(mins.value) || 0,
              avg_hr: avg.value === "" ? null : Number(avg.value),
              max_hr: max.value === "" ? null : Number(max.value),
              zones: zs.map((z) => Number(z.value) || 0),
              perceived_effort: rpe.value === "" ? null : Number(rpe.value),
              route: route.value.trim(), notes: notes.value.trim(),
            });
            dist.value = mins.value = avg.value = max.value = rpe.value = route.value = notes.value = sets.value = "";
            zs.forEach((z) => { z.value = "0"; }); calc();
            toast("logged"); reload();
          }),
          text: "+ log cardio",
        }),
      ]),
    ]);
  }

  async function render(view) {
    clear(view);
    const host = el("div");
    view.appendChild(host);

    async function reload() {
      const [rows, sum] = await guard(() => Promise.all([
        api.get("/api/pulse/fitness/cardio"), api.get("/api/pulse/fitness/cardio/summary"),
      ]));
      clear(host);

      const stat = (v, l, c) => el("div.prog-box", {}, [
        el("div.prog-val", { style: "color:" + c + ";font-size:20px", text: String(v) }),
        el("div.prog-label", { text: l }),
      ]);
      host.appendChild(el("div.prog-grid", {}, [
        stat(sum.total_km.toFixed(1) + "km", "distance", "#00F5D4"),
        stat(sum.sessions, "sessions", "#7FA8C8"),
        stat(Math.round(sum.total_mins / 6) / 10 + "h", "time", "#2DE2FF"),
        stat(fmtPace(sum.avg_pace), "avg pace", "#F0A030"),
      ]));
      if (sum.zones.some((z) => z)) {
        host.appendChild(el("div.card", { style: "margin-top:10px" }, [
          el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px", text: "Time in zone — all sessions" }),
          el("div", { style: "margin-top:8px" }, [zoneBar(sum.zones)]),
          el("div.row", { style: "gap:10px;margin-top:6px;flex-wrap:wrap" },
            sum.zones.map((z, i) => el("span.sub", { style: "font-size:11px;color:" + ZONE_COLOR[i], text: ZONE_NAME[i] + " " + z + "m" }))),
        ]));
      }
      host.appendChild(el("div", { style: "margin-top:10px" }, [form(reload, host)]));

      if (!rows.length) {
        host.appendChild(el("div.empty", { style: "margin-top:12px", text: "No cardio logged yet." }));
        return;
      }
      const list = el("div", { style: "margin-top:12px" });
      rows.forEach((c) => {
        list.appendChild(el("div.card", { style: "margin-bottom:8px" }, [
          el("div.spread", {}, [
            el("div.row", { style: "gap:8px;flex-wrap:wrap;align-items:baseline" }, [
              el("span.pill", { text: c.type }),
              c.style ? el("span.pill", { style: "color:" + (c.style === "hiit" ? "#FF4757" : "#00D4AA"),
                text: c.style.toUpperCase() + (c.style === "hiit" && c.sets ? " × " + c.sets + " sets" : "") }) : null,
              c.workout_id ? el("span.sub", { style: "font-size:11px", title: "logged as part of a workout", text: "in a workout" + (c.from ? " · " + c.from : "") }) : null,
              el("strong", { style: "font-size:14px", text: (c.distance_km || 0) + " km" }),
              el("span.sub", { text: (c.duration_mins || 0) + " min" }),
              el("span.pill", { style: "color:#F0A030", text: fmtPace(c.pace_min_per_km) }),
              c.avg_hr ? el("span.sub", { style: "font-size:11px", text: "♥ " + c.avg_hr + (c.max_hr ? " / " + c.max_hr : "") }) : null,
              c.perceived_effort ? el("span.sub", { style: "font-size:11px", text: "RPE " + c.perceived_effort }) : null,
            ]),
            el("div.row", { style: "gap:8px" }, [
              el("span.sub", { style: "font-size:11px", text: c.date }),
              el("button.btn-sm.btn-danger", {
                onclick: () => confirmDo("Delete this session?", async () => {
                  await api.del("/api/pulse/fitness/cardio/" + c.id); reload();
                }), text: "×" }),
            ]),
          ]),
          el("div", { style: "margin-top:6px" }, [zoneBar(c.zones || [])]),
          (c.route || c.notes) ? el("div.sub", { style: "margin-top:6px;font-size:11px",
            text: [c.route, c.notes].filter(Boolean).join(" · ") }) : null,
        ]));
      });
      host.appendChild(list);
    }
    await reload();
  }

  window.FIT_TABS = window.FIT_TABS || [];
  window.FIT_TABS.push({ key: "cardio", label: "Cardio", render });
})();

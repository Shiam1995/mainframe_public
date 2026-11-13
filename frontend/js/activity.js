/* activity.js — Activity timeline: task completions + journal entries + other
   logged events, chronological & grouped by day. Task completions and entries
   are editable (fix the date → it moves on the timeline). Read /api/tasks + /api/log. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const ENTRY_LABELS = { initial_idea: "Initial idea", progress: "Progress", note: "Note", blocker: "Blocker", reflection: "Reflection", completed: "Completed" };
  const CAT_COLOR = {
    paper: "#5A9DE0", highlight: "#00D4AA", term: "#F0A030", ref: "#E05A5A",
    kg: "#8B7EC8", status: "#5A9DE0", deepdive: "#00D4AA", idea: "#F0A030",
    header: "#5A9DE0", instance: "#00D4AA", dictionary: "#F0A030", mind: "#2DE2FF",
  };

  function dayLabel(iso) {
    try { return new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" }); }
    catch { return iso; }
  }
  function timeLabel(iso) { return (iso || "").slice(11, 16); }
  // date input value → ISO at noon (keeps it stable across timezones)
  function toISO(dateVal) { return dateVal ? dateVal + "T12:00:00" : null; }

  function dateEditor(iso, onSave) {
    const inp = el("input", { type: "date", value: (iso || "").slice(0, 10), style: "width:140px" });
    inp.addEventListener("change", () => { if (inp.value) guard(() => onSave(toISO(inp.value))); });
    return inp;
  }

  window.Views = window.Views || {};
  window.Views.activity = {
    id: "activity", label: "Activity", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Activity" }),
        el("div.sub", { text: "When you completed tasks and logged work — chronological, editable." }),
      ])]));
      const host = el("div"); viewEl.appendChild(host);

      async function reload() {
        const [tasks, log] = await guard(() => Promise.all([api.get("/api/tasks"), api.get("/api/log?limit=800")]));
        const items = [];
        tasks.forEach((t) => {
          if (t.done && t.done_at) items.push({ ts: t.done_at, kind: "completed", task: t });
          (t.entries || []).forEach((e) => { if (e.date) items.push({ ts: e.date, kind: "entry", task: t, entry: e }); });
        });
        // other logged activity (task events already covered above)
        log.forEach((l) => { if (l.category !== "task" && l.ts) items.push({ ts: l.ts, kind: "log", log: l }); });

        items.sort((a, b) => (a.ts < b.ts ? 1 : -1));
        const byDay = {};
        items.forEach((it) => { const d = it.ts.slice(0, 10); (byDay[d] = byDay[d] || []).push(it); });
        const days = Object.keys(byDay).sort().reverse();

        clear(host);
        if (!days.length) { host.appendChild(el("div.empty", { text: "No activity yet. Complete a task or log some work." })); return; }
        days.forEach((d) => {
          host.appendChild(el("h3", { style: "font-family:var(--mono);color:var(--teal);font-size:13px;margin:20px 0 8px", text: dayLabel(d + "T00:00:00") }));
          byDay[d].forEach((it) => host.appendChild(row(it, reload)));
        });
      }

      function row(it, reload) {
        if (it.kind === "completed") {
          const t = it.task;
          return el("div.act-row.act-done", {}, [
            el("span.act-time", { text: timeLabel(it.ts) }),
            el("span.act-badge", { style: "background:var(--green-d);color:var(--green)", text: "✓ completed" }),
            el("div.act-body", {}, [
              el("span", { style: "cursor:pointer", onclick: () => activate(t), text: t.title }),
              el("div.act-meta", {}, [
                el("span.pill", { text: t.horizon }), el("span.pill", { text: t.module }),
                t.total_mins ? el("span.sub", { text: "⏱ " + t.total_mins + "m logged" }) : null,
              ]),
            ]),
            el("div.row", { style: "gap:6px" }, [
              dateEditor(it.ts, async (iso) => { await api.patch("/api/tasks/" + t.id, { done_at: iso }); toast("rescheduled"); reload(); }),
              el("button.btn-sm", { onclick: () => guard(async () => { await api.patch("/api/tasks/" + t.id, { done: false }); toast("reopened"); reload(); }), text: "reopen" }),
            ]),
          ]);
        }
        if (it.kind === "entry") {
          const t = it.task, e = it.entry;
          return el("div.act-row", {}, [
            el("span.act-time", { text: timeLabel(it.ts) }),
            el("span.act-badge", { style: "background:var(--raised);color:var(--dim)", text: ENTRY_LABELS[e.type] || e.type }),
            el("div.act-body", {}, [
              el("span", { text: e.notes || "(no note)" }),
              el("div.act-meta", {}, [
                el("span", { style: "cursor:pointer;color:var(--dim)", onclick: () => activate(t), text: "▸ " + t.title }),
                e.time_spent_mins ? el("span.sub", { text: "⏱ " + e.time_spent_mins + "m" }) : null,
              ]),
            ]),
            el("div", {}, [dateEditor(it.ts, async (iso) => { await api.patch("/api/tasks/" + t.id + "/entries/" + e.id, { date: iso }); toast("entry rescheduled"); reload(); })]),
          ]);
        }
        // read-only log event
        const l = it.log;
        return el("div.act-row.act-log", {}, [
          el("span.act-time", { text: timeLabel(it.ts) }),
          el("span.act-badge", { style: "background:var(--surface);color:" + (CAT_COLOR[l.category] || "#8194a8"), text: l.category }),
          el("div.act-body", {}, [el("span.sub", { text: l.action + (l.detail ? " — " + l.detail : "") + (l.paper_title ? " · " + l.paper_title.slice(0, 34) : "") })]),
        ]);
      }

      function activate(t) {
        // Jump to the Inbox and open that row's journal. Used to point at the
        // Progress tab; the journal moved into the Inbox when Progress went.
        if (t && t.id && window.Views.inbox && window.Views.inbox.openJournal)
          window.Views.inbox.openJournal(t.id);
        window.openTab("inbox");
      }

      reload();
    },
  };
})();

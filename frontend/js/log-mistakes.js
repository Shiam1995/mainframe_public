/* log-mistakes.js — the mistake tracker and viewer, mounted inside the Log.

   The Log's other half is the activity stream: everything the app did. This
   half is everything *you* got wrong — the Learning entries, read as a record
   rather than a worklist.

   Two halves, because they answer different questions:

     the tracker — is this getting better or worse? Counts alone can't say, so
       it shows per-kind rhythm: how often, how recently, and whether the gaps
       between occurrences are widening (fading) or narrowing (getting worse).
       It also shows how many mistakes have options written but nothing picked,
       which is the difference between having thought about something and
       having decided about it.

     the viewer — what actually happened, in order, expandable down to the
       options you wrote and the one you went with.

   Nothing here edits: this is where you look. Editing is in Learning, one
   button away, with the entry already open. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const STATUS_COLOR = { open: "var(--amber)", working: "var(--blue)", resolved: "var(--teal)" };
  const STATUS_LABEL = { open: "open", working: "working on it", resolved: "resolved" };
  const MOD_COLOR = {
    synapse: "#00F5D4", pulse: "#DE7BA4", vision: "#FF4757",
    vault: "#D4A017", mainframe: "#7FA8C8",
  };
  const OPT_COLOR = {
    option: "var(--muted)", chosen: "var(--teal)", done: "var(--blue)", dropped: "var(--dim)",
  };
  const OPT_LABEL = {
    option: "considering", chosen: "plan to do", done: "done", dropped: "dropped",
  };
  const TREND = {
    improving: { text: "gaps widening — fading", color: "var(--teal)" },
    worsening: { text: "gaps narrowing — worse", color: "var(--red)" },
    flat: { text: "steady", color: "var(--muted)" },
  };
  const WEEKS = 12;                       // how far the rhythm strips look back

  const filters = { kind: "", status: "", module: "", q: "" };
  const opened = new Set();               // expanded entries in the viewer

  const day = 86400000;
  function weekStarts(n) {
    // Monday-anchored, oldest first, so the strip reads left-to-right as time.
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
    return Array.from({ length: n }, (_, i) => new Date(d.getTime() - (n - 1 - i) * 7 * day));
  }
  const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
                     + "-" + String(d.getDate()).padStart(2, "0");
  function daysAgo(dstr) {
    if (!dstr) return null;
    const t = Date.parse(dstr.slice(0, 10) + "T12:00:00");
    if (isNaN(t)) return null;
    return Math.round((Date.now() - t) / day);
  }
  const ago = (n) => n == null ? "—" : n === 0 ? "today" : n === 1 ? "yesterday" : n + "d ago";

  /* A week-by-week strip. Deliberately not a line chart: the question is "how
     many, how recently", and twelve squares answer it in less space and with
     no axis to read. */
  function strip(dates, title) {
    const buckets = weekStarts(WEEKS).map((w) => {
      const from = iso(w), to = iso(new Date(w.getTime() + 7 * day));
      return { from, n: dates.filter((d) => d >= from && d < to).length };
    });
    const peak = Math.max(1, ...buckets.map((b) => b.n));
    return el("div.mt-strip", { title: title || (WEEKS + " weeks, one square per week") },
      buckets.map((b) => el("span.mt-week", {
        style: b.n ? "background:rgba(224,90,90," + (0.22 + 0.78 * (b.n / peak)).toFixed(2) + ")" : "",
        title: "week of " + b.from + " — " + (b.n || "none"),
      })));
  }

  function pill(text, color, title) {
    return el("span.pill", { style: "color:" + color + ";border-color:" + color, text, title: title || "" });
  }

  window.LogMistakes = {
    /* `host` is an element the Log hands over; this owns everything inside it. */
    async render(host) {
      clear(host);
      const [items, sum, kindRows] = await guard(() => Promise.all([
        api.get("/api/learning"), api.get("/api/learning/summary"), api.get("/api/learning/kinds"),
      ]));
      const groupOf = {};
      kindRows.forEach((k) => { groupOf[k.name] = k.group; });

      if (!items.length) {
        host.appendChild(el("div.empty", { text: "No mistakes logged yet. They're written in Learning; this is where you read them back." }));
        return;
      }

      /* ------------------------------------------------------------ tracker */
      const t = sum.tally;
      const tracker = el("div.card", { style: "margin-bottom:14px" });
      tracker.appendChild(el("div.spread", {}, [
        el("h3", { style: "margin:0", text: "Mistake tracker" }),
        el("span.sub", { style: "font-size:11px", text: "last " + WEEKS + " weeks · one square per week" }),
      ]));
      tracker.appendChild(el("div.row", { style: "gap:6px;margin-top:10px;flex-wrap:wrap" }, [
        pill(t.total + " logged", "var(--muted)"),
        pill(t.active + " still open", t.active ? "var(--amber)" : "var(--muted)"),
        pill(t.resolved + " resolved", "var(--teal)"),
        pill(t.repeating_kinds + " repeating", t.repeating_kinds ? "var(--red)" : "var(--muted)"),
        // The two that say whether writing options turned into deciding.
        pill((t.options_chosen + t.options_done) + " of " + t.options + " options picked",
             t.options ? "var(--teal)" : "var(--dim)", "across every entry"),
        t.undecided ? pill(t.undecided + " undecided", "var(--amber)",
          "entries with options written but none picked") : null,
        t.no_options ? pill(t.no_options + " with no options", "var(--red)",
          "open entries where nothing has been written down to do about it") : null,
      ].filter(Boolean)));

      tracker.appendChild(el("div", { style: "margin-top:12px" }, [
        el("div.sub", { style: "font-size:11px;margin-bottom:4px", text: "everything, by week" }),
        strip(items.map((i) => (i.occurred_at || "").slice(0, 10)).filter(Boolean)),
      ]));

      // Per-kind rhythm. Kinds logged once are included — a mistake that has
      // only happened once is exactly the one you want to keep at once.
      const byKind = new Map();
      items.forEach((i) => {
        const k = (i.kind || "").trim() || "(no kind)";
        if (!byKind.has(k)) byKind.set(k, []);
        byKind.get(k).push(i);
      });
      const repeatOf = {};
      (sum.repeats || []).forEach((r) => { repeatOf[(r.kind || "").trim()] = r; });

      const rows = [...byKind.entries()].map(([kind, list]) => {
        const dates = list.map((i) => (i.occurred_at || "").slice(0, 10)).filter(Boolean).sort();
        return { kind, list, dates, rep: repeatOf[kind] || null,
                 last: dates[dates.length - 1] || "", active: list.filter((i) => i.status !== "resolved").length };
      });
      rows.sort((a, b) => (b.list.length - a.list.length) || (b.last > a.last ? 1 : -1));

      const table = el("table.wk-table");
      table.appendChild(el("tr", {}, [
        el("th", { style: "min-width:150px", text: "Kind" }),
        el("th", { style: "min-width:96px", text: "Habit" }),
        el("th", { style: "min-width:60px", text: "Times" }),
        el("th", { style: "min-width:96px", text: "Last" }),
        el("th", { style: "min-width:110px", text: "Every" }),
        el("th", { style: "min-width:150px", text: "Trend" }),
        el("th", { style: "min-width:150px", text: "Rhythm" }),
      ]));
      rows.forEach((r) => {
        const trend = r.rep ? (TREND[r.rep.trend] || TREND.flat) : null;
        const tr = el("tr.wk-row", { style: "cursor:pointer", title: "filter the list below to this kind",
          onclick: () => { filters.kind = filters.kind === r.kind ? "" : r.kind; this.render(host); } });
        tr.appendChild(el("td", {}, [
          el("span.pill", { style: "color:var(--red)", text: r.kind }),
          r.active ? el("span.sub", { style: "font-size:10px", text: " " + r.active + " open" }) : null,
        ].filter(Boolean)));
        tr.appendChild(el("td", { style: "color:var(--dim)", text: groupOf[r.kind.toLowerCase()] || "—" }));
        tr.appendChild(el("td", { style: "font-family:var(--mono)", text: String(r.list.length) }));
        tr.appendChild(el("td", { style: "font-family:var(--mono);font-size:11px", text: ago(daysAgo(r.last)) }));
        tr.appendChild(el("td", { style: "font-family:var(--mono);font-size:11px;color:var(--dim)",
          text: r.rep && r.rep.avg_gap_days != null ? "~" + r.rep.avg_gap_days + "d apart" : "—" }));
        tr.appendChild(el("td", { style: "font-size:11px;color:" + (trend ? trend.color : "var(--dim)"),
          text: trend ? trend.text : "only once" }));
        tr.appendChild(el("td", {}, [strip(r.dates, r.kind)]));
        table.appendChild(tr);
      });
      tracker.appendChild(el("div.wk-scroll", { style: "margin-top:12px" }, [table]));
      host.appendChild(tracker);

      /* ------------------------------------------------------------- viewer */
      const viewer = el("div.card");
      const kinds = [...byKind.keys()].sort();
      const sel = (label, key, values) => {
        const s = el("select", {}, [el("option", { value: "", text: "all " + label }),
          ...values.map((v) => el("option", { value: v, text: v }))]);
        s.value = filters[key];
        s.addEventListener("change", () => { filters[key] = s.value; this.render(host); });
        return s;
      };
      const q = el("input", { placeholder: "search what happened…", value: filters.q, style: "flex:1;min-width:180px" });
      // Redraw on every keystroke would re-create the box and lose the caret;
      // this list is small enough that searching on change is no wait at all.
      q.addEventListener("change", () => { filters.q = q.value.trim(); this.render(host); });

      viewer.appendChild(el("div.spread", {}, [
        el("h3", { style: "margin:0", text: "Mistake viewer" }),
        el("span.sub", { style: "font-size:11px", text: "click an entry to read it in full" }),
      ]));
      viewer.appendChild(el("div.row", { style: "gap:8px;margin-top:10px;flex-wrap:wrap" }, [
        sel("kinds", "kind", kinds),
        sel("statuses", "status", ["open", "working", "resolved"]),
        sel("modules", "module", [...new Set(items.map((i) => i.module).filter(Boolean))].sort()),
        q,
        (filters.kind || filters.status || filters.module || filters.q)
          ? el("button.btn-sm", { text: "clear filters", onclick: () => {
              filters.kind = filters.status = filters.module = filters.q = "";
              this.render(host);
            } })
          : null,
      ].filter(Boolean)));

      const shown = items.filter((i) =>
        (!filters.kind || ((i.kind || "").trim() || "(no kind)") === filters.kind)
        && (!filters.status || i.status === filters.status)
        && (!filters.module || i.module === filters.module)
        && (!filters.q || ((i.what_happened || "") + " " + (i.detail || ""))
              .toLowerCase().includes(filters.q.toLowerCase())));

      const list = el("div", { style: "margin-top:10px" });
      if (!shown.length) list.appendChild(el("div.empty", { text: "Nothing matches those filters." }));

      shown.forEach((i) => {
        const isOpen = opened.has(i.id);
        const head = el("div.mt-head", {
          onclick: () => { isOpen ? opened.delete(i.id) : opened.add(i.id); this.render(host); },
        }, [
          el("span.dd-caret", { text: isOpen ? "▾" : "▸" }),
          el("span.mono", { style: "font-size:11px;color:var(--muted);min-width:88px", text: i.occurred_at || "" }),
          i.kind ? el("span.pill", { style: "color:var(--red)", text: i.kind }) : null,
          el("span", { style: "flex:1;min-width:160px", text: i.what_happened }),
          el("span.pill", { style: "color:" + (MOD_COLOR[i.module] || "var(--dim)"), text: i.module }),
          el("span.pill", { style: "color:" + STATUS_COLOR[i.status], text: STATUS_LABEL[i.status] }),
          i.option_count ? el("span.pill", {
            style: "color:" + (i.planned_count ? "var(--teal)" : "var(--amber)"),
            title: i.planned_count ? "picked, out of the options written" : "nothing picked yet",
            text: i.planned_count + "/" + i.option_count + " picked",
          }) : null,
        ].filter(Boolean));

        const entry = el("div.mt-entry", {}, [head]);

        if (isOpen) {
          const body = el("div.mt-body");
          if (i.detail) {
            body.appendChild(el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px", text: "what led to it" }));
            body.appendChild(el("div.mt-text", { text: i.detail }));
          }
          if (i.action) {
            body.appendChild(el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-top:10px", text: "what I said I'd do" }));
            body.appendChild(el("div.mt-text", { text: i.action }));
          }
          if ((i.options || []).length) {
            body.appendChild(el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-top:10px",
              text: "options — " + i.planned_count + " of " + i.option_count + " picked" }));
            (i.options || []).forEach((o) => body.appendChild(el("div.mt-opt", {}, [
              el("span.pill", { style: "color:" + OPT_COLOR[o.status], text: OPT_LABEL[o.status] || o.status }),
              el("span", { style: o.status === "dropped" ? "color:var(--dim);text-decoration:line-through" : "", text: o.text }),
            ])));
          }
          (i.consulted || []).forEach((c, n) => {
            if (!n) body.appendChild(el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-top:10px", text: "who / what I asked" }));
            body.appendChild(el("div.mt-text", { text: c }));
          });
          (i.notes || []).forEach((n, k) => {
            if (!k) body.appendChild(el("div.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-top:10px", text: "notes over time" }));
            body.appendChild(el("div.mt-text", {}, [
              el("span.mono", { style: "font-size:10px;color:var(--muted)", text: (n.created_at || "").slice(0, 10) + "  " }),
              el("span", { text: n.text }),
            ]));
          });
          body.appendChild(el("div.row", { style: "margin-top:12px;gap:8px" }, [
            el("button.btn-sm", {
              text: "edit in Learning →",
              onclick: () => {
                if (window.Views.learning && window.Views.learning.reveal) window.Views.learning.reveal(i.id);
                window.openModule(window.PM.activeModule, "learning");
              },
            }),
          ]));
          entry.appendChild(body);
        }
        list.appendChild(entry);
      });

      viewer.appendChild(list);
      host.appendChild(viewer);
    },
  };
})();

/* planner-calendar.js — PLANNER_SPEC v2 §5, the Calendar surface.

   Answers "when does it happen?". Three views over one merged feed:
     · Day   — a timed grid across the day bounds, blocks drawn to scale
     · Week  — seven columns of compact chips in time order
     · Month — a Monday-first grid of category dots and marker glyphs

   The feed merges two kinds of block. Manual and external events are stored
   rows and can be edited or deleted here. Auto blocks are computed by the
   backend from the funded budget on every read — they are read-only, and
   clicking one takes you to Budget, which is the only place they can change
   (spec §5, §11.8). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const BASE = "/api/planner";

  const PX_PER_HOUR = 44;
  const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];

  const iso = (d) => {
    const x = new Date(d);
    return new Date(x.getTime() - x.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
  };
  const parse = (s) => new Date(s + "T00:00:00");
  const addDays = (s, n) => { const d = parse(s); d.setDate(d.getDate() + n); return iso(d); };
  const addMonths = (s, n) => {
    const d = parse(s); const day = d.getDate();
    d.setDate(1); d.setMonth(d.getMonth() + n);
    d.setDate(Math.min(day, new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()));
    return iso(d);
  };
  const mins = (hhmm) => {
    const [h, m] = String(hhmm).split(":").map(Number);
    return (h || 0) * 60 + (m || 0);
  };
  const atMin = (s) => mins(String(s).slice(11, 16));
  const hhmm = (m) => String(Math.floor(m / 60)).padStart(2, "0") + ":" + String(m % 60).padStart(2, "0");
  const fmtH = (h) => (Math.round(h * 10) / 10) + "h";

  /* module-level so the view survives a tab switch on the same anchor */
  let view = "week";
  let anchor = iso(new Date());

  async function render(host, ctx) {
    const P = window.PLANNER;
    let feed = null;

    async function reload() {
      feed = await guard(() => api.get(
        BASE + "/calendar?view=" + view + "&date=" + anchor));
      draw();
    }
    /* Budget edits change what auto-placement produces; the shell calls this
       so the week in view updates with no manual refresh (spec §11.2). */
    ctx.onExternalChange(reload);

    async function commit(fn) {
      await guard(fn);
      P.notify();
      await reload();
    }

    const isBlocked = (d) => Object.prototype.hasOwnProperty.call(feed.blocked || {}, d);

    function toggleBlock(d) {
      return isBlocked(d)
        ? commit(() => api.del(BASE + "/dayblocks/" + d))
        : commit(() => api.post(BASE + "/dayblocks/" + d, { reason: "" }));
    }

    function byDay() {
      const map = {};
      (feed.events || []).forEach((e) => {
        const d = e.start.slice(0, 10);
        (map[d] = map[d] || []).push(e);
      });
      Object.values(map).forEach((l) => l.sort((a, b) => a.start.localeCompare(b.start)));
      return map;
    }

    /* ------------------------------------------------------------- chrome */
    function draw() {
      clear(host);
      const step = view === "month" ? addMonths : (s, n) => addDays(s, n * (view === "week" ? 7 : 1));

      host.appendChild(el("div.plc-bar", {}, [
        el("div.row", { style: "gap:4px" }, [
          el("button.btn-sm", { onclick: () => { anchor = step(anchor, -1); reload(); }, text: "‹" }),
          el("button.btn-sm", { onclick: () => { anchor = iso(new Date()); reload(); }, text: "today" }),
          el("button.btn-sm", { onclick: () => { anchor = step(anchor, 1); reload(); }, text: "›" }),
        ]),
        el("span.plc-label", { text: label() }),
        el("div.row", { style: "gap:4px" }, ["day", "week", "month"].map((v) =>
          el("button.btn-sm" + (view === v ? ".btn-primary" : ""), {
            onclick: () => { view = v; reload(); }, text: v,
          }))),
      ]));

      host.appendChild(snapshot());

      if (view === "day") host.appendChild(dayGrid(anchor));
      else if (view === "week") host.appendChild(weekCols());
      else host.appendChild(monthGrid());

      host.appendChild(composer());
    }

    function label() {
      const d = parse(anchor);
      if (view === "month") return MONTHS[d.getMonth()] + " " + d.getFullYear();
      if (view === "day") {
        return DOW[(d.getDay() + 6) % 7] + " " + d.getDate() + " "
             + MONTHS[d.getMonth()].slice(0, 3) + " " + d.getFullYear();
      }
      return feed.range_start + " → " + feed.range_end;
    }

    /* ----------------------------------------------------- snapshot panel */
    function snapshot() {
      const s = feed.snapshot;
      const box = (v, l, cls) => el("div.prog-box" + (cls || ""), {}, [
        el("div.prog-val", { text: v }), el("div.prog-label", { text: l }),
      ]);
      return el("div.plc-snap", {}, [
        box(fmtH(s.hours_placed) + " / " + fmtH(s.capacity_target), "study placed vs capacity"),
        box(String(s.days_blocked), "days blocked"),
        box(String(s.priority_count), "priority", s.priority_count ? ".is-priority" : ""),
        box(String(s.important_count), "important", s.important_count ? ".is-important" : ""),
      ]);
    }

    /* ------------------------------------------------------------ shared */
    function openEvent(e) {
      if (e.source === "auto") {
        // auto blocks are budget output, not calendar input
        toast("auto-placed from the budget — adjust it in Budget");
        ctx.goto("budget");
        return;
      }
      eventModal(e);
    }

    function blockChip(e, withTime) {
      const P2 = window.PLANNER;
      return el("div.plc-chip" + (e.source === "auto" ? ".is-auto" : ""), {
        style: "--c:" + P2.CATS[e.category],
        title: e.title + " · " + e.start.slice(11, 16) + "–" + e.end.slice(11, 16)
             + (e.source === "auto" ? " (auto-placed)" : ""),
        onclick: () => openEvent(e),
      }, [
        P2.markerGlyph(e.marker),
        withTime ? el("span.plc-chip-t", { text: e.start.slice(11, 16) }) : null,
        el("span.plc-chip-n", { text: e.title }),
      ].filter(Boolean));
    }

    /* --------------------------------------------------------- day view */
    function dayGrid(day) {
      const lo = mins(feed.day_bounds.start), hi = mins(feed.day_bounds.end);
      const hours = [];
      for (let m = lo; m <= hi; m += 60) hours.push(m);
      const list = (byDay()[day] || []);
      const blocked = isBlocked(day);

      const axis = el("div.plc-axis", {}, hours.map((m) =>
        el("div.plc-hour", { text: hhmm(m) })));

      const body = el("div.plc-daybody", {
        style: "height:" + ((hi - lo) / 60 * PX_PER_HOUR) + "px",
      });
      hours.forEach((m) => body.appendChild(el("div.plc-rule", {
        style: "top:" + ((m - lo) / 60 * PX_PER_HOUR) + "px",
      })));

      if (blocked) {
        body.appendChild(el("div.plc-blocked-wash", {
          text: "blocked off" + (feed.blocked[day] ? " — " + feed.blocked[day] : ""),
        }));
      }

      list.forEach((e) => {
        const s = Math.max(lo, atMin(e.start)), en = Math.min(hi, atMin(e.end));
        if (en <= s) return;
        body.appendChild(el("div.plc-block" + (e.source === "auto" ? ".is-auto" : ""), {
          style: "top:" + ((s - lo) / 60 * PX_PER_HOUR) + "px;"
               + "height:" + Math.max(14, (en - s) / 60 * PX_PER_HOUR - 2) + "px;"
               + "--c:" + P.CATS[e.category],
          onclick: () => openEvent(e),
          title: e.source === "auto" ? "auto-placed — click to open Budget" : "click to edit",
        }, [
          el("div.plc-block-t", {}, [
            P.markerGlyph(e.marker),
            el("span", { text: e.title }),
          ]),
          el("div.plc-block-n", {
            text: e.start.slice(11, 16) + "–" + e.end.slice(11, 16)
                + (e.source === "auto" ? " · auto" : ""),
          }),
        ]));
      });

      return el("div", {}, [
        el("div.spread", { style: "margin-bottom:8px" }, [
          el("span.sub", {
            text: list.length + (list.length === 1 ? " block" : " blocks")
                + " · " + feed.day_bounds.start + "–" + feed.day_bounds.end,
          }),
          el("button.btn-sm" + (blocked ? ".btn-primary" : ""), {
            onclick: () => toggleBlock(day),
            text: blocked ? "un-block this day" : "block this day off",
          }),
        ]),
        el("div.plc-day", {}, [axis, body]),
      ]);
    }

    /* -------------------------------------------------------- week view */
    function weekCols() {
      const map = byDay();
      const cols = [];
      for (let i = 0; i < 7; i++) {
        const d = addDays(feed.range_start, i);
        const blocked = isBlocked(d);
        const list = map[d] || [];
        cols.push(el("div.plc-wcol" + (blocked ? ".blocked" : "")
                   + (d === iso(new Date()) ? ".today" : ""), {}, [
          el("div.plc-whead", {}, [
            el("span.plc-wdow", {
              onclick: () => { anchor = d; view = "day"; reload(); },
              title: "open " + d,
              text: DOW[i],
            }),
            el("span.plc-wnum", {
              onclick: () => toggleBlock(d),
              title: blocked ? "un-block " + d : "block " + d + " off",
              text: blocked ? "off" : String(parse(d).getDate()),
            }),
          ]),
          el("div.plc-wbody", {}, list.length
            ? list.map((e) => blockChip(e, true))
            : [el("div.plc-wempty", { text: blocked ? "" : "—" })]),
        ]));
      }
      return el("div.plc-week", {}, cols);
    }

    /* ------------------------------------------------------- month view */
    function monthGrid() {
      const map = byDay();
      const cells = [DOW.map((d) => el("div.plc-mdow", { text: d }))].flat();
      const grid = el("div.plc-month", {}, cells);
      const mLo = feed.month_start, mHi = feed.month_end;
      let d = feed.range_start;
      while (d <= feed.range_end) {
        const list = map[d] || [];
        const out = d < mLo || d > mHi;
        const blocked = isBlocked(d);
        const cats = [...new Set(list.map((e) => e.category))];
        // priority beats important when a day carries both (spec §6)
        const marker = list.some((e) => e.marker === "priority") ? "priority"
          : list.some((e) => e.marker === "important") ? "important" : "none";
        const day = d;
        grid.appendChild(el("div.plc-mcell" + (out ? ".dim" : "")
                          + (blocked ? ".blocked" : "")
                          + (d === iso(new Date()) ? ".today" : ""), {
          onclick: () => { anchor = day; view = "day"; reload(); },
          title: day + (blocked ? " — blocked off" : "")
               + (list.length ? " · " + list.length + " blocks" : ""),
        }, [
          el("div.plc-mnum", {}, [
            P.markerGlyph(marker),
            el("span", { text: String(parse(d).getDate()) }),
            blocked ? el("span.plc-moff", { text: "off" }) : null,
          ].filter(Boolean)),
          el("div.plc-mdots", {}, cats.map((c) =>
            el("span.plc-mdot", { style: "background:" + P.CATS[c], title: c }))),
        ]));
        d = addDays(d, 1);
      }
      return grid;
    }

    /* --------------------------------------------------------- composer */
    function snap(v) {                       // 15-minute steps, inside bounds
      const lo = mins(feed.day_bounds.start), hi = mins(feed.day_bounds.end);
      return hhmm(Math.min(hi, Math.max(lo, Math.round(mins(v) / 15) * 15)));
    }

    function composer() {
      const day = el("input.mform-input", {
        type: "date", value: view === "day" ? anchor : feed.range_start,
      });
      const from = el("input.mform-input", { type: "time", step: "900", value: "09:00" });
      const to = el("input.mform-input", { type: "time", step: "900", value: "10:00" });
      const title = el("input.mform-input", { placeholder: "e.g. study block, gym, dentist" });
      const cat = el("select.mform-input", {},
        ["fixed", "fitness", "event"].map((c) => el("option", { value: c, text: c })));
      const marker = el("select.mform-input", {},
        ["none", "priority", "important"].map((m) => el("option", { value: m, text: m })));

      const place = () => {
        if (!title.value.trim()) return toast("title is required", true);
        const s = snap(from.value), e = snap(to.value);
        if (e <= s) return toast("the event must end after it starts", true);
        return commit(async () => {
          await api.post(BASE + "/events", {
            title: title.value.trim(),
            start: day.value + "T" + s + ":00",
            end: day.value + "T" + e + ":00",
            category: cat.value, marker: marker.value,
          });
          title.value = "";
        });
      };
      title.addEventListener("keydown", (ev) => { if (ev.key === "Enter") place(); });

      return el("div.plc-composer", {}, [
        el("div.plc-composer-h", { text: "hand-place a commitment or event" }),
        el("div.plc-composer-r", {}, [
          title, day, from, to, cat, marker,
          el("button.btn-primary", { onclick: place, text: "place" }),
        ]),
      ]);
    }

    function eventModal(e) {
      const title = el("input.mform-input", { value: e.title });
      const day = el("input.mform-input", { type: "date", value: e.start.slice(0, 10) });
      const from = el("input.mform-input", { type: "time", step: "900", value: e.start.slice(11, 16) });
      const to = el("input.mform-input", { type: "time", step: "900", value: e.end.slice(11, 16) });
      const cat = el("select.mform-input", {},
        Object.keys(P.CATS).map((c) => el("option", { value: c, text: c })));
      cat.value = e.category;
      const marker = el("select.mform-input", {},
        ["none", "priority", "important"].map((m) => el("option", { value: m, text: m })));
      marker.value = e.marker;
      const f = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);

      window.PULSE.modal("Edit event", [
        f("Title", title),
        el("div.mform-row-3", {}, [f("Day", day), f("From", from), f("To", to)]),
        el("div.mform-row", {}, [f("Category", cat), f("Marker", marker)]),
        e.source === "external"
          ? el("div.sub", { text: "Synced from an external calendar — deleting hides it locally." })
          : null,
      ].filter(Boolean), [
        {
          label: "Save", primary: true, onClick: (close) => {
            const s = snap(from.value), en = snap(to.value);
            if (en <= s) return toast("the event must end after it starts", true);
            return commit(async () => {
              await api.patch(BASE + "/events/" + e.id, {
                title: title.value.trim(), category: cat.value, marker: marker.value,
                start: day.value + "T" + s + ":00",
                end: day.value + "T" + en + ":00",
              });
              close();
            });
          },
        },
        {
          label: e.source === "external" ? "Hide" : "Delete", danger: true,
          onClick: (close) => confirmDo(
            (e.source === "external" ? "Hide " : "Delete ") + "“" + e.title + "”?",
            () => commit(async () => { await api.del(BASE + "/events/" + e.id); close(); })),
        },
        { label: "Cancel", onClick: (close) => close() },
      ]);
    }

    await reload();
    return reload;
  }

  window.PLANNER_TABS = window.PLANNER_TABS || [];
  window.PLANNER_TABS.push({ key: "calendar", label: "Calendar", order: 20, render });
})();

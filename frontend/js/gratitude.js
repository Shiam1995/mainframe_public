/* gratitude.js — the Gratitude tab (design: the gratitude mockup).

   BANNER       a random crop of one of your wallpapers (the same pool as the
                home screen), "Gratitude" in script over it, and one random
                gratitude row from any period underneath. ↻ re-rolls either.
   EXCITED FOR  things coming up. Ticking one moves it to ENJOYED and stamps
                the day it happened (server-side; you never type that date).
   PERIOD BOXES year / month / week / day. ‹ › walk to the previous or next
                period and reload its rows. + add writes a row dated today
                when you are looking at the current period, or the first day
                of the period you are looking at otherwise. Cells save on blur;
                emptying a cell and leaving it deletes the row. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const CSS = `
@font-face{font-family:'Great Vibes';src:url(/vendor/fonts/GreatVibes-Regular.woff2) format('woff2');font-display:swap}
.gr-wrap{max-width:1100px}
.gr-banner{position:relative;height:220px;border-radius:12px;overflow:hidden;margin-bottom:14px;background:#000 center/cover no-repeat;box-shadow:0 8px 28px rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.25)}
.gr-banner:after{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.15),rgba(0,0,0,.55))}
.gr-banner .gr-title{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;z-index:1;font-family:'Great Vibes',cursive;font-size:88px;color:#fff;text-shadow:0 2px 18px rgba(0,0,0,.6);letter-spacing:1px;pointer-events:none}
.gr-banner .gr-q{position:absolute;left:22px;right:22px;bottom:14px;z-index:1;color:#fff;font-size:14px;text-shadow:0 1px 8px rgba(0,0,0,.8)}
.gr-banner .gr-from{font-family:var(--mono,monospace);font-size:10.5px;opacity:.75;margin-top:2px}
.gr-banner .gr-tools{position:absolute;top:10px;right:10px;z-index:1;display:flex;gap:6px}
.gr-banner .gr-tools button{background:rgba(0,0,0,.45);border-color:rgba(255,255,255,.3);color:#fff}
.gr-two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:800px){.gr-two{grid-template-columns:1fr}}
.gr-card{background:var(--surface);border:1px solid var(--border);border-top-width:4px;border-radius:10px;padding:16px 18px;margin-bottom:14px}
.gr-card h2{font-size:14px;margin:0;font-weight:600}
.gr-spread{display:flex;justify-content:space-between;align-items:center;gap:10px}
.gr-meta{font-family:var(--mono,monospace);font-size:10.5px;color:var(--dim)}
.gr-list{list-style:none;margin:0;padding:0}
.gr-list li{display:flex;gap:10px;align-items:flex-start;padding:7px 0;border-bottom:1px solid var(--border)}
.gr-list li:last-child{border:0}
.gr-list input[type=checkbox]{width:16px;height:16px;margin-top:1px;accent-color:var(--teal);cursor:pointer;flex:none}
.gr-list .t{flex:1}.gr-list .when{font-family:var(--mono,monospace);font-size:10.5px;color:var(--dim);white-space:nowrap}
.gr-list .x{opacity:0;padding:0 6px}.gr-list li:hover .x,.gr-table tr:hover .x{opacity:1}
.gr-enjoyed li{color:var(--muted)}.gr-enjoyed .t{text-decoration:line-through;text-decoration-color:var(--border)}
.gr-add{display:flex;gap:8px;margin-top:10px}.gr-add input{flex:1}
.gr-nav{display:flex;align-items:center;gap:8px}
.gr-nav .cur{font-family:var(--mono,monospace);font-size:12px;min-width:120px;text-align:center}
.gr-nav button{padding:3px 9px}
.gr-cal{position:fixed;z-index:1000;background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--green);border-radius:10px;padding:12px;box-shadow:0 12px 36px rgba(0,0,0,.5);width:262px;user-select:none}
.gr-cal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px}
.gr-cal-head .m{font-family:var(--mono,monospace);font-size:12.5px;color:var(--green);font-weight:600}
.gr-cal-head button{padding:2px 9px}
.gr-cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:3px}
.gr-cal-grid .dow{font-family:var(--mono,monospace);font-size:9.5px;color:var(--dim);text-align:center;padding:2px 0;text-transform:uppercase}
.gr-cal-grid button{padding:0;height:32px;font-size:12px;border-radius:6px;background:var(--bg);border:1px solid transparent}
.gr-cal-grid button.out{opacity:.35}
.gr-cal-grid button.past{color:var(--dim)}
.gr-cal-grid button.today{border-color:var(--green);color:var(--green)}
.gr-cal-grid button.sel{background:var(--green);color:var(--bg);font-weight:700;border-color:var(--green)}
.gr-cal-grid button:hover{border-color:var(--teal);color:var(--teal)}
.gr-cal-grid button.sel:hover{color:var(--bg)}
.gr-cal-foot{display:flex;gap:6px;justify-content:space-between;margin-top:10px}
.gr-datebtn{flex:none;white-space:nowrap}
.gr-datebtn.set{border-color:var(--green);color:var(--green)}
.gr-table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:6px}
.gr-table th,.gr-table td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--border);vertical-align:top}
.gr-table th{color:var(--muted);font-family:var(--mono,monospace);font-size:10px;text-transform:uppercase;letter-spacing:.05em;font-weight:500}
.gr-table td.d{font-family:var(--mono,monospace);font-size:11px;color:var(--dim);white-space:nowrap;width:90px}
.gr-table td.x-cell{width:30px;text-align:right}
.gr-table td[contenteditable]:focus{outline:1px solid var(--teal);background:var(--bg);border-radius:4px}
.gr-table td[contenteditable]:empty:before{content:'grateful for…';color:var(--dim)}
.gr-excited{border-top-color:var(--green)}.gr-excited h2{color:var(--green)}
.gr-enjoyedbox{border-top-color:var(--teal)}.gr-enjoyedbox h2{color:var(--teal)}
.gr-year{border-top-color:var(--amber)}.gr-year h2,.gr-year .cur{color:var(--amber)}
.gr-month{border-top-color:var(--purple)}.gr-month h2,.gr-month .cur{color:var(--purple)}
.gr-week{border-top-color:var(--blue)}.gr-week h2,.gr-week .cur{color:var(--blue)}
.gr-day{border-top-color:#DE7BA4;background:rgba(44,24,34,.92)}.gr-day h2,.gr-day .cur,.gr-day th{color:#DE7BA4}
`;

  const MON = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const short = (iso) => { const [, m, d] = String(iso).slice(0, 10).split("-"); return +d + " " + MON[+m - 1]; };
  const localISO = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0")
    + "-" + String(d.getDate()).padStart(2, "0");
  const nowHM = () => new Date().toTimeString().slice(0, 5);

  let wallpapers = null;    // cached across visits; the listing call also syncs the cache

  window.Views = window.Views || {};
  window.Views.gratitude = {
    id: "gratitude", label: "Gratitude", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      if (!document.getElementById("gr-style")) {
        document.head.appendChild(el("style", { id: "gr-style", text: CSS }));
      }
      const wrap = el("div.gr-wrap");
      viewEl.appendChild(wrap);

      /* ── banner ─────────────────────────────────────────── */
      const rq = el("div"), rf = el("div.gr-from");
      const banner = el("div.gr-banner", {}, [
        el("div.gr-tools", {}, [
          el("button.btn-sm", { text: "↻ image", title: "another wallpaper crop", onclick: () => pickWallpaper() }),
          el("button.btn-sm", { text: "↻ entry", title: "another entry", onclick: () => guard(pickRandom) }),
        ]),
        el("div.gr-title", { text: "Gratitude" }),
        el("div.gr-q", {}, [rq, rf]),
      ]);
      wrap.appendChild(banner);

      async function pickWallpaper() {
        if (!wallpapers) {
          const r = await api.wallpapers.list().catch(() => ({ images: [] }));
          wallpapers = (r.images || []).map((i) => i.url);
        }
        if (!wallpapers.length) return;   // stays plain black, like the design's fallback
        const url = wallpapers[Math.floor(Math.random() * wallpapers.length)];
        banner.style.backgroundImage = `url("${url}")`;
        banner.style.backgroundSize = `${140 + Math.floor(Math.random() * 120)}%`;   // zoomed in, so it's a crop
        banner.style.backgroundPosition = `${Math.floor(Math.random() * 100)}% ${Math.floor(Math.random() * 100)}%`;
      }

      async function pickRandom() {
        const g = await api.get("/api/gratitude/random");
        if (!g || !g.id) {
          rq.textContent = "Nothing written yet — add something you're grateful for below.";
          rf.textContent = "";
          return;
        }
        rq.textContent = g.text;
        rf.textContent = [g.period, g.period === "day" && g.time ? g.time : null, short(g.date)]
          .filter(Boolean).join(" · ");
      }

      /* ── excited for → enjoyed ──────────────────────────── */
      const excitedUl = el("ul.gr-list");
      const enjoyedUl = el("ul.gr-list.gr-enjoyed");
      const excIn = el("input", { placeholder: "something coming up" });
      // "when" is picked on a clickable month calendar, so it is a real date
      // that can be sorted and counted down to.
      let newWhen = "";
      const whenBtn = el("button.gr-datebtn", { title: "pick the date on a calendar" });
      const showNewWhen = () => {
        whenBtn.textContent = newWhen ? "📅 " + short(newWhen) : "📅 pick date";
        whenBtn.classList.toggle("set", !!newWhen);
      };
      showNewWhen();
      whenBtn.addEventListener("click", () => openCalendar(whenBtn, newWhen, (iso) => { newWhen = iso; showNewWhen(); }));
      const addExcited = () => guard(async () => {
        const text = excIn.value.trim();
        if (!text) return;
        await api.post("/api/gratitude/excited", { text, when: newWhen });
        excIn.value = ""; newWhen = ""; showNewWhen();
        await loadExcited();
        excIn.focus();
      });
      excIn.addEventListener("keydown", (e) => { if (e.key === "Enter") addExcited(); });

      wrap.appendChild(el("div.gr-two", {}, [
        el("section.gr-card.gr-excited", {}, [
          el("div.gr-spread", {}, [el("h2", { text: "What am I excited for" }), el("span.gr-meta", { text: "tick when it has happened" })]),
          excitedUl,
          el("div.gr-add", {}, [excIn, whenBtn, el("button", { text: "+ add", onclick: addExcited })]),
        ]),
        el("section.gr-card.gr-enjoyedbox", {}, [
          el("div.gr-spread", {}, [el("h2", { text: "Enjoyed" }), el("span.gr-meta", { text: "moved here when ticked, date kept" })]),
          enjoyedUl,
        ]),
      ]));

      function excitedRow(x, enjoyed) {
        const cb = el("input", { type: "checkbox" });
        cb.checked = !!enjoyed;
        cb.addEventListener("change", () => guard(async () => {
          await api.patch("/api/gratitude/excited/" + x.id, { enjoyed: cb.checked });
          if (cb.checked) toast("enjoyed ✓");
          await loadExcited();
        }));
        const del = el("button.btn-sm.x", { text: "×", title: "remove", onclick: () => guard(async () => {
          await api.del("/api/gratitude/excited/" + x.id);
          await loadExcited();
        }) });
        return el("li", {}, [
          cb,
          el("span.t", { text: x.text }),
          enjoyed ? el("span.when", { text: x.enjoyed_at ? short(x.enjoyed_at) : "" }) : whenCell(x),
          del,
        ]);
      }

      const ISO = /^\d{4}-\d{2}-\d{2}$/;
      function countdown(iso) {
        const days = Math.round((new Date(iso + "T00:00") - new Date(localISO(new Date()) + "T00:00")) / 864e5);
        return days === 0 ? "today" : days === 1 ? "tomorrow" : days > 0 ? "in " + days + "d" : -days + "d ago";
      }
      // The date on an upcoming item: click it to open the calendar and move it.
      function whenCell(x) {
        const has = ISO.test(x.when || "");
        const label = el("span.when", {
          style: "cursor:pointer", title: "click to pick a date",
          text: has ? "📅 " + short(x.when) + " · " + countdown(x.when) : (x.when || "📅 ＋ date"),
        });
        label.addEventListener("click", () => openCalendar(label, has ? x.when : "", (iso) => guard(async () => {
          await api.patch("/api/gratitude/excited/" + x.id, { when: iso });
          await loadExcited();
        })));
        return label;
      }

      /* A month calendar you click a day on. Opens under `anchor`; ‹ › change
         month; Escape or a click outside closes it without changing anything. */
      let calEl = null;
      function closeCalendar() {
        if (!calEl) return;
        calEl.remove(); calEl = null;
        document.removeEventListener("mousedown", onOutside, true);
        document.removeEventListener("keydown", onEsc, true);
      }
      function onOutside(e) { if (calEl && !calEl.contains(e.target)) closeCalendar(); }
      function onEsc(e) { if (e.key === "Escape") closeCalendar(); }
      function openCalendar(anchor, selected, onPick) {
        closeCalendar();
        const todayISO = localISO(new Date());
        const base = new Date((selected || todayISO) + "T00:00");
        let y = base.getFullYear(), m = base.getMonth();
        calEl = el("div.gr-cal");
        const pick = (iso) => { closeCalendar(); onPick(iso); };

        function draw() {
          clear(calEl);
          const title = new Date(y, m, 1).toLocaleDateString("en-GB", { month: "long", year: "numeric" });
          calEl.appendChild(el("div.gr-cal-head", {}, [
            el("button.btn-sm", { text: "‹", title: "previous month", onclick: () => { m--; if (m < 0) { m = 11; y--; } draw(); } }),
            el("span.m", { text: title }),
            el("button.btn-sm", { text: "›", title: "next month", onclick: () => { m++; if (m > 11) { m = 0; y++; } draw(); } }),
          ]));
          const grid = el("div.gr-cal-grid");
          ["mo", "tu", "we", "th", "fr", "sa", "su"].forEach((d) => grid.appendChild(el("div.dow", { text: d })));
          const first = new Date(y, m, 1);
          const start = new Date(y, m, 1 - ((first.getDay() + 6) % 7));     // back to Monday
          for (let i = 0; i < 42; i++) {
            const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i);
            if (i === 35 && d.getMonth() !== m) break;                          // 6th row only when the month reaches it
            const iso = localISO(d);
            const cls = ["button"];
            if (d.getMonth() !== m) cls.push("out");
            if (iso < todayISO) cls.push("past");
            if (iso === todayISO) cls.push("today");
            if (iso === selected) cls.push("sel");
            grid.appendChild(el(cls.join("."), { text: String(d.getDate()), title: short(iso), onclick: () => pick(iso) }));
          }
          calEl.appendChild(grid);
          calEl.appendChild(el("div.gr-cal-foot", {}, [
            el("button.btn-sm", { text: "today", onclick: () => pick(todayISO) }),
            selected ? el("button.btn-sm", { text: "clear date", onclick: () => pick("") }) : null,
            el("button.btn-sm", { text: "close", onclick: closeCalendar }),
          ]));
        }
        draw();
        document.body.appendChild(calEl);
        // Under the anchor, kept on screen.
        const r = anchor.getBoundingClientRect();
        const w = calEl.offsetWidth, h = calEl.offsetHeight;
        let left = Math.min(r.left, window.innerWidth - w - 8);
        let top = r.bottom + 6;
        if (top + h > window.innerHeight - 8) top = Math.max(8, r.top - h - 6);
        calEl.style.left = Math.max(8, left) + "px";
        calEl.style.top = top + "px";
        setTimeout(() => {
          document.addEventListener("mousedown", onOutside, true);
          document.addEventListener("keydown", onEsc, true);
        }, 0);
      }

      async function loadExcited() {
        const r = await api.get("/api/gratitude/excited");
        clear(excitedUl); clear(enjoyedUl);
        r.excited.forEach((x) => excitedUl.appendChild(excitedRow(x, false)));
        r.enjoyed.forEach((x) => enjoyedUl.appendChild(excitedRow(x, true)));
        if (!r.excited.length) excitedUl.appendChild(el("li.gr-meta", { text: "nothing lined up yet" }));
        if (!r.enjoyed.length) enjoyedUl.appendChild(el("li.gr-meta", { text: "tick something on the left once it's happened" }));
      }

      /* ── period tables ──────────────────────────────────── */
      const PERIODS = [
        { key: "year", title: "Gratitude year" },
        { key: "month", title: "Gratitude month" },
        { key: "week", title: "Gratitude week" },
        { key: "day", title: "Gratitude day" },
      ];

      function periodBox(p) {
        let state = null;              // last response: label, start, prev, next, is_current, rows
        const cur = el("span.cur");
        const table = el("table.gr-table");
        const load = (at) => guard(async () => {
          state = await api.get(`/api/gratitude/period/${p.key}` + (at ? "?at=" + at : ""));
          draw();
        });
        const box = el(`section.gr-card.gr-${p.key}`, {}, [
          el("div.gr-spread", { style: "margin-bottom:6px" }, [
            el("h2", { text: p.title }),
            el("div.gr-nav", {}, [
              el("button", { text: "‹", title: "previous " + p.key, onclick: () => load(state.prev) }),
              cur,
              el("button", { text: "›", title: "next " + p.key, onclick: () => load(state.next) }),
              el("button.btn-sm", { text: "today", title: "back to this " + p.key, onclick: () => load() }),
              el("button.btn-sm", { text: "+ add", onclick: () => addRow() }),
            ]),
          ]),
          table,
        ]);

        async function addRow() {
          const date = state.is_current ? localISO(new Date()) : state.start;
          const g = await api.post("/api/gratitude", {
            period: p.key, text: "", date, time: p.key === "day" ? nowHM() : null,
          });
          state.rows.push(g);
          draw(g.id);
        }

        function draw(focusId) {
          cur.textContent = state.label;
          clear(table);
          table.appendChild(el("tr", {}, [
            el("th", { text: p.key === "day" ? "time" : "date" }), el("th", { text: "grateful for" }), el("th"),
          ]));
          if (!state.rows.length) {
            table.appendChild(el("tr", {}, [el("td.d", { text: "" }),
              el("td", { style: "color:var(--dim)", text: "nothing yet — + add" }), el("td")]));
          }
          state.rows.forEach((g) => {
            const cell = el("td", { contenteditable: "true", text: g.text || "" });
            cell.addEventListener("keydown", (e) => {
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); cell.blur(); }
            });
            cell.addEventListener("blur", () => guard(async () => {
              const text = cell.textContent.trim();
              if (!text) {                     // emptied → gone
                await api.del("/api/gratitude/" + g.id);
                state.rows = state.rows.filter((r) => r.id !== g.id);
                draw();
                return;
              }
              if (text === g.text) return;
              const up = await api.patch("/api/gratitude/" + g.id, { text });
              Object.assign(g, up);
              toast("saved");
            }));
            const del = el("button.btn-sm.x", { text: "×", title: "delete row", onclick: () => guard(async () => {
              await api.del("/api/gratitude/" + g.id);
              state.rows = state.rows.filter((r) => r.id !== g.id);
              draw();
            }) });
            table.appendChild(el("tr", {}, [
              el("td.d", { text: p.key === "day" ? (g.time || "") : short(g.date) }),
              cell,
              el("td.x-cell", {}, [del]),
            ]));
            if (focusId === g.id) setTimeout(() => cell.focus(), 0);
          });
        }

        load();
        return box;
      }

      PERIODS.forEach((p) => wrap.appendChild(periodBox(p)));

      pickWallpaper();
      await Promise.all([loadExcited(), pickRandom()]).catch((e) => toast(String(e.message || e), true));
    },
  };
})();

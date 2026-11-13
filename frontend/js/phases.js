/* phases.js — Phases (topbar): fourteen-week sprints.

   A phase is what you set out to do; the hours under it are what you actually
   put in. One phase runs at a time — while it does, the only thing on offer is
   ending it, and the numbers across the top are summed from the work log, never
   typed. Ending it walks every project in the phase and asks for one word:
   done, carried or dropped. It will not close until all of them have an answer,
   because the tally underneath is the record you keep, and a tally with a hole
   in it is worse than none.

   Nothing is created for you when a phase ends. The break is the point.

   A phase also collects: everything you make while one is running is filed
   under it by the server (see backend/phasehook.py), which is what the
   dashboard in this tab reads back. The tab therefore asks for
   /api/phases/active/dashboard — the whole screen against one `today` — and
   only falls back to the plain list for the closed phases underneath.

   Built from notes/ui/mainframe_phases_modals.html. */
(function () {
  const { el, clear, toast, guard, sizedArea, todayISO } = window.ui;
  const api = window.api;

  const OUTCOMES = [
    { key: "done",    label: "done",    c: "var(--green)" },
    { key: "carried", label: "carried", c: "var(--amber)" },
    { key: "dropped", label: "dropped", c: "var(--dim)" },
  ];

  const h = (mins) => (mins / 60).toFixed(1) + "h";

  /* "07 sep to 13 dec 2026" — the year only once, on the end. */
  function span(a, b) {
    const f = (iso, withYear) => {
      const d = new Date(iso + "T12:00:00");
      return d.toLocaleDateString("en-GB",
        { day: "2-digit", month: "short", year: withYear ? "numeric" : undefined })
        .toLowerCase();
    };
    return f(a, false) + " to " + f(b, true);
  }
  function plusWeeks(iso, weeks) {
    const d = new Date(iso + "T12:00:00");
    d.setDate(d.getDate() + weeks * 7 - 1);   // inclusive last day
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") +
      "-" + String(d.getDate()).padStart(2, "0");
  }
  const seqLabel = (n) => String(n || 1).padStart(2, "0");

  /* "thu 10 sep" — the day, the way the dates line and the day header say it. */
  function fmtDay(iso) {
    return new Date(iso + "T12:00:00")
      .toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
      .toLowerCase();
  }
  /* "6 days" until a phase that has not started. Said in days rather than as a
     date because the date is already on the line next to it. */
  function daysUntil(iso) {
    const d = Math.round((new Date(iso + "T12:00:00") - new Date()) / 86400000);
    return d <= 0 ? "starting" : d === 1 ? "1 day" : d + " days";
  }

  /* one project's line under a phase: hours, sessions, and whatever the
     project's own note says it got to. */
  function projStat(p) {
    const bits = [h(p.mins || 0), (p.sessions || 0) + " sessions"];
    const note = (p.note || "").trim().split("\n")[0];
    if (note) bits.push(note.length > 46 ? note.slice(0, 46) + "…" : note);
    return bits.join(" · ");
  }

  /* The banner picker, shared by the new-phase and edit-phase modals.

     Both modals need the same three states — nothing chosen, a file waiting to
     upload, an image already on the phase — but they resolve differently: an
     existing phase can be patched straight away, while a new one has no id to
     hang an image off until it has been created. So this only *collects* the
     choice; `commit(phaseId)` is what actually uploads and patches, and the
     caller decides when that is safe to run. */
  function bannerPicker(current) {
    let picked = null;                    // a File waiting to go up
    let url = current || "";              // what the phase has now
    let cleared = false;                  // "remove" pressed on an existing one

    const file = el("input", { type: "file", accept: "image/*", style: "display:none" });
    const preview = el("div.ph-bannerprev");
    const name = el("span.ph-oc-stat");
    const removeBtn = el("button.btn-sm", { type: "button", text: "remove" });

    function paint() {
      preview.style.backgroundImage = picked
        ? "url(" + URL.createObjectURL(picked) + ")"
        : (url && !cleared ? "url(" + url + ")" : "");
      preview.classList.toggle("empty", !picked && (!url || cleared));
      name.textContent = picked ? picked.name
        : (url && !cleared ? "current banner" : "no banner yet");
      removeBtn.style.display = (picked || (url && !cleared)) ? "" : "none";
    }
    file.addEventListener("change", () => {
      picked = file.files[0] || null;
      if (picked) cleared = false;
      paint();
    });
    removeBtn.addEventListener("click", () => {
      picked = null; file.value = ""; cleared = !!url; paint();
    });
    paint();

    return {
      el: el("div.ph-bannerpick", {}, [
        preview,
        el("div", {}, [
          el("div.mform-label", { text: "banner" }),
          name,
          el("div.row", { style: "gap:6px;margin-top:6px" }, [
            el("button.btn-sm", { type: "button", text: "🖼 choose image",
              onclick: () => file.click() }),
            removeBtn,
          ]),
        ]),
        file,
      ]),
      /* Upload, then point the phase at the file. Two calls rather than one
         because the image service is Mainframe-level and knows nothing about
         phases — it just needs a context id to hang the image off. */
      async commit(phaseId) {
        if (picked) {
          const img = await api.images.upload(picked, "phase banner", "phases", phaseId);
          await api.patch("/api/phases/" + phaseId, { banner_url: api.images.fileUrl(img.id) });
        } else if (cleared) {
          await api.patch("/api/phases/" + phaseId, { banner_url: "" });
        }
      },
      get touched() { return !!picked || cleared; },
    };
  }

  window.Views = window.Views || {};
  window.Views.phases = {
    id: "phases", label: "Phases", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      let active = null;
      let past = [];
      let dash = {};
      // Which of the two reads of a phase is on screen. "phase" is what you set
      // out to do; "pace" is the plan against the hours (see phase-pace.js).
      // Remembered, because whichever one you check daily is the one you want
      // when you open the tab.
      let mode = localStorage.getItem("mainframe.phases.mode") || "phase";

      const head = el("div.view-head");
      const body = el("div");
      viewEl.appendChild(head);
      viewEl.appendChild(body);

      /* ================= end phase modal ================= */
      function openEnd(phase) {
        const overlay = el("div.modal-overlay");
        const close = () => overlay.remove();
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

        // outcome + note per project, held here until the phase closes as one
        const state = {};
        phase.projects.forEach((p) => {
          state[p.project_id] = { outcome: p.outcome || "", note: p.outcome_note || "" };
        });

        const tally = el("div.ph-tally");
        const blocker = el("span.ph-blocker");
        const closeBtn = el("button.btn-primary", { text: "◼ close phase" });

        function paintTally() {
          clear(tally);
          const answered = Object.values(state).filter((s) => s.outcome);
          OUTCOMES.forEach((o) => {
            const n = answered.filter((s) => s.outcome === o.key).length;
            tally.appendChild(el("b", { text: String(n) }));
            tally.appendChild(document.createTextNode(" " + o.label + " · "));
          });
          const left = phase.projects.length - answered.length;
          tally.appendChild(el("b", {
            text: String(left), style: left ? "color:var(--amber)" : "",
          }));
          tally.appendChild(document.createTextNode(" not answered"));
          blocker.textContent = left === 0 ? ""
            : left === 1 ? "1 project still needs an outcome"
            : left + " projects still need an outcome";
          closeBtn.disabled = left > 0;
        }

        const rows = phase.projects.map((p) => {
          const seg = el("div.ph-seg");
          const btns = OUTCOMES.map((o) => {
            const b = el("button." + o.key, { type: "button", text: o.label });
            b.addEventListener("click", () => {
              state[p.project_id].outcome = o.key;
              btns.forEach((x) => x.classList.remove("on"));
              b.classList.add("on");
              paintTally();
            });
            if (state[p.project_id].outcome === o.key) b.classList.add("on");
            return b;
          });
          btns.forEach((b) => seg.appendChild(b));

          const note = el("input", {
            placeholder: "what happened here, one or two lines…", style: "width:100%",
          });
          note.value = state[p.project_id].note;
          note.addEventListener("input", () => { state[p.project_id].note = note.value; });

          return el("div.ph-oc", {}, [
            el("div.ph-oc-top", {}, [
              el("div", {}, [
                el("strong", { text: p.name }),
                el("div.ph-oc-stat", { text: projStat(p) }),
              ]),
              seg,
            ]),
            note,
          ]);
        });

        const reflection = el("textarea", {
          placeholder: "what would you tell yourself at the start of it…",
        });
        reflection.style.minHeight = "90px";

        closeBtn.addEventListener("click", () => guard(async () => {
          await api.post("/api/phases/" + phase.id + "/close", {
            outcomes: Object.entries(state).map(([project_id, s]) => ({
              project_id, outcome: s.outcome, note: s.note.trim(),
            })),
            reflection: reflection.value.trim(),
          });
          close();
          toast("phase closed");
          load();
        }));

        overlay.appendChild(el("div.modal", {}, [
          el("div.ph-mhead", {}, [
            el("h2", { text: "End " + phase.name }),
            el("div.sub", { text: "say how each project went. the phase won't close until every one has an answer." }),
          ]),
          el("div.row", { style: "gap:16px;margin-bottom:14px" }, [
            el("span.ph-oc-stat", {}, [
              document.createTextNode(span(phase.start, phase.end) + " · " +
                phase.weeks + " weeks · "),
              el("b", { text: phase.hours + "h", style: "color:var(--teal)" }),
              document.createTextNode(" · " + phase.sessions + " sessions"),
            ]),
          ]),
          ...rows,
          tally,
          el("div", { style: "margin-top:8px" }, [
            sizedArea(reflection, "phase-reflection",
              { label: "looking back at the whole phase", dflt: "s" }),
          ]),
          el("div.ph-mfoot", {}, [
            blocker,
            el("button", { text: "cancel", onclick: close }),
            closeBtn,
          ]),
        ]));
        document.body.appendChild(overlay);
        paintTally();
      }

      /* ================= new phase modal ================= */
      async function openNew() {
        const cands = await guard(() => api.get("/api/phases/candidates"));
        const seq = past.length + 1;
        const overlay = el("div.modal-overlay");
        const close = () => overlay.remove();
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

        const name = el("input", { placeholder: "what this stretch is for" });
        const start = el("input", { type: "date", value: todayISO() });
        const weeks = el("input", { type: "number", value: 14, min: 1, max: 26 });
        const ends = el("div.ph-derived");
        const paintEnd = () => {
          const w = parseInt(weeks.value, 10);
          ends.textContent = (start.value && w > 0)
            ? new Date(plusWeeks(start.value, w) + "T12:00:00")
                .toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
                .toLowerCase() + " · from start + weeks"
            : "—";
        };
        start.addEventListener("change", paintEnd);
        weeks.addEventListener("input", paintEnd);
        paintEnd();

        const goal = el("input", { placeholder: "what does the end of this phase look like…" });
        const banner = bannerPicker("");

        const pick = el("div.ph-pick");
        const boxes = cands.map((c) => {
          const cb = el("input", { type: "checkbox" });
          cb.checked = !!c.carried;
          cb.dataset.id = c.id;
          pick.appendChild(el("label", {}, [
            cb,
            document.createTextNode(c.name),
            el("span.pill", {
              text: c.carried ? "carried" : c.status,
              style: c.carried ? "border-color:var(--amber);color:var(--amber)" : "",
            }),
          ]));
          return cb;
        });
        if (!cands.length) pick.appendChild(el("div.ph-oc-stat", { text: "no open projects yet — start one in the Project tab" }));

        const startBtn = el("button.btn-primary", { text: "▶ start phase " + seqLabel(seq) });
        startBtn.addEventListener("click", () => guard(async () => {
          if (!name.value.trim()) return toast("give the phase a name", true);
          // The phase has to exist before an image can hang off it, so the
          // banner goes up second, against the id we just got back.
          const made = await api.post("/api/phases", {
            name: name.value.trim(),
            start: start.value,
            weeks: parseInt(weeks.value, 10) || 14,
            goal: goal.value.trim(),
            project_ids: boxes.filter((b) => b.checked).map((b) => b.dataset.id),
          });
          await banner.commit(made.id);
          close();
          toast("phase " + seqLabel(seq) + " started");
          load();
        }));

        overlay.appendChild(el("div.modal", {}, [
          el("div.ph-mhead", {}, [
            el("h2", { text: "New Phase" }),
            el("div.sub", { text: "phase " + seqLabel(seq) + ". fourteen weeks unless you say otherwise." }),
          ]),
          el("div.mform-row", {}, [
            el("div", {}, [el("div.mform-label", { text: "name" }), name]),
            el("div", {}, [el("div.mform-label", { text: "starts" }), start]),
          ]),
          el("div.mform-row", {}, [
            el("div", {}, [el("div.mform-label", { text: "weeks" }), weeks]),
            el("div", {}, [el("div.mform-label", { text: "ends" }), ends]),
          ]),
          el("div", { style: "margin-bottom:12px" }, [
            sizedArea(goal, "phase-goal", { label: "goal", dflt: "s" }),
          ]),
          banner.el,
          el("div", { style: "margin-bottom:4px" }, [
            el("div.spread", { style: "margin-bottom:4px" }, [
              el("span.mform-label", { text: "projects coming in", style: "margin:0" }),
              el("span.ph-oc-stat", { text: "carried projects are already ticked" }),
            ]),
            pick,
            el("div.ph-oc-stat", { style: "margin-top:6px", text: "anything you work on after the start date joins on its own; this list is just the opening lineup." }),
          ]),
          el("div.ph-mfoot", {}, [
            el("button", { text: "cancel", onclick: close }),
            startBtn,
          ]),
        ]));
        document.body.appendChild(overlay);
        name.focus();
      }

      /* ================= edit phase modal ================= */
      /* The pencil on a running phase. Same fields as the new-phase modal minus
         the project lineup — projects join and leave through their own outcome,
         not by being un-ticked here. `end` stays derived; you change the length,
         not the last day. */
      function openEdit(phase) {
        const overlay = el("div.modal-overlay");
        const close = () => overlay.remove();
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

        const name = el("input", { value: phase.name || "" });
        const start = el("input", { type: "date", value: phase.start });
        const weeks = el("input", { type: "number", value: phase.weeks, min: 1, max: 26 });
        const ends = el("div.ph-derived");
        const paintEnd = () => {
          const w = parseInt(weeks.value, 10);
          ends.textContent = (start.value && w > 0)
            ? new Date(plusWeeks(start.value, w) + "T12:00:00")
                .toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
                .toLowerCase() + " · from start + weeks"
            : "—";
        };
        start.addEventListener("change", paintEnd);
        weeks.addEventListener("input", paintEnd);
        paintEnd();

        const goal = el("input", { placeholder: "what does the end of this phase look like…" });
        goal.value = phase.goal || "";
        const banner = bannerPicker(phase.banner_url || "");

        const saveBtn = el("button.btn-primary", { text: "save" });
        saveBtn.addEventListener("click", () => guard(async () => {
          if (!name.value.trim()) return toast("give the phase a name", true);
          await api.patch("/api/phases/" + phase.id, {
            name: name.value.trim(),
            start: start.value,
            weeks: parseInt(weeks.value, 10) || phase.weeks,
            goal: goal.value.trim(),
          });
          await banner.commit(phase.id);
          close();
          toast("phase updated");
          load();
        }));

        overlay.appendChild(el("div.modal", {}, [
          el("div.ph-mhead", {}, [
            el("h2", { text: "Edit " + phase.name }),
            el("div.sub", { text: "the phase you are in. moving the dates moves what counts as inside it." }),
          ]),
          el("div.mform-row", {}, [
            el("div", {}, [el("div.mform-label", { text: "name" }), name]),
            el("div", {}, [el("div.mform-label", { text: "starts" }), start]),
          ]),
          el("div.mform-row", {}, [
            el("div", {}, [el("div.mform-label", { text: "weeks" }), weeks]),
            el("div", {}, [el("div.mform-label", { text: "ends" }), ends]),
          ]),
          el("div", { style: "margin-bottom:12px" }, [
            sizedArea(goal, "phase-goal", { label: "goal", dflt: "s" }),
          ]),
          banner.el,
          el("div.ph-mfoot", {}, [
            el("button", { text: "cancel", onclick: close }),
            saveBtn,
          ]),
        ]));
        document.body.appendChild(overlay);
        // "🖼 banner" and "✎ phase" open the same modal — a banner is a field of
        // the phase, not a separate thing — so the banner button just puts you
        // in front of the right field rather than opening a second dialog.
        if (bannerFirst) {
          banner.el.scrollIntoView({ block: "center" });
          banner.el.style.outline = "1px solid var(--teal)";
          banner.el.style.outlineOffset = "6px";
        } else {
          name.focus();
        }
      }

      /* ================= the tab ================= */
      function paintHead() {
        clear(head);
        head.appendChild(el("div", {}, [
          el("h1", { text: "Phases" }),
          el("div.sub", { text: "fourteen-week sprints. what you set out to do, and what you actually put in." }),
        ]));
        // While a phase runs, its own controls live on the banner, where the
        // thing they act on is. The head only ever offers the one thing you
        // cannot do from there: start the next one.
        const right = el("div.row");
        if (active) {
          const seg = el("div.ph-hz");
          [["phase", "phase"], ["pace", "pace"]].forEach(([key, label]) => {
            seg.appendChild(el("button" + (mode === key ? ".on" : ""), {
              text: label,
              onclick: () => {
                if (mode === key) return;
                mode = key;
                localStorage.setItem("mainframe.phases.mode", key);
                paintHead();
                paintBody();
              },
            }));
          });
          right.appendChild(seg);
        } else {
          right.appendChild(el("button.btn-primary", { text: "+ new phase", onclick: () => openNew() }));
        }
        head.appendChild(right);
      }

      function statGrid(p) {
        const wrap = el("div", { style: "margin-bottom:12px" });
        const grid = el("div.prog-grid");
        [
          [p.hours + "h", "hours in phase", "var(--teal)"],
          [p.hours_per_week + "h", "hours / week", "var(--blue)"],
          [String(p.sessions), "sessions", ""],
          [String(p.project_count), "projects", ""],
        ].forEach(([v, l, c]) => grid.appendChild(el("div.prog-box", {}, [
          el("div.prog-val", { text: v, style: c ? "color:" + c : "" }),
          el("div.prog-label", { text: l }),
        ])));
        wrap.appendChild(grid);
        const filed = filedLine(dash.filed);
        if (filed) wrap.appendChild(filed);
        return wrap;
      }

      /* What the IN_PHASE hook has filed. Reads as a sentence rather than a
         table because it is context, not a figure you act on — but it is also
         the only place the hook is visible, so it says nothing at all rather
         than "0" when a phase is genuinely still empty. */
      const FILED_WORDS = {
        Task: ["task", "tasks"], WorkSession: ["session", "sessions"],
        Session: ["planned session", "planned sessions"],
        CalEvent: ["event", "events"], Goal: ["goal", "goals"],
        Document: ["doc", "docs"], Change: ["change", "changes"],
        Mistake: ["mistake", "mistakes"], Lesson: ["lesson", "lessons"],
        Project: ["project", "projects"],
      };
      function filedLine(filed) {
        const bits = Object.entries(filed || {})
          .filter(([k, n]) => n > 0 && FILED_WORDS[k] && k !== "Project")
          .map(([k, n]) => n + " " + FILED_WORDS[k][n === 1 ? 0 : 1]);
        if (!bits.length) return null;
        return el("div.ph-oc-stat", { style: "margin-top:10px",
          text: "filed under this phase: " + bits.join(" · ") });
      }

      /* ================= banner ================= */
      /* Phase number, name, dates, and one pip per week. The three buttons sit
         on the banner rather than in the page head because they act on this
         phase, not on the tab. */
      function banner(p) {
        const weeks = el("div.ph-weeks");
        for (let i = 1; i <= p.weeks; i++) {
          const cls = i < p.weeks_in ? ".done" : i === p.weeks_in ? ".now" : "";
          weeks.appendChild(el("i.ph-wk" + cls));
        }
        const line = [span(p.start, p.end)];
        line.push(p.weeks_in ? "week " + p.weeks_in + " of " + p.weeks
                             : "starts in " + daysUntil(p.start));
        line.push(fmtDay(dash.today));
        if (p.hours) line.push(p.hours + "h in");

        const sec = el("section.ph-banner" + (p.banner_url ? "" : ".ph-nobanner"));
        if (p.banner_url) sec.style.backgroundImage = "url(" + p.banner_url + ")";
        sec.appendChild(el("div.ph-over", {}, [
          el("div", {}, [
            el("div.ph-num", { text: "PHASE " + seqLabel(p.seq) }),
            el("h1.ph-name", { text: p.name }),
          ]),
          el("div", {}, [weeks, el("div.ph-dates", { text: line.join(" · ") })]),
        ]));
        sec.appendChild(el("div.ph-bannerbtns", {}, [
          el("button.btn-sm", { text: "🖼 banner", onclick: () => openEdit(p, true) }),
          el("button.btn-sm", { text: "✎ phase", onclick: () => openEdit(p) }),
          el("button.btn-sm", {
            text: p.weeks_in >= p.weeks ? "◼ end" : "◼ end early",
            onclick: () => openEnd(p),
          }),
        ]));
        return sec;
      }

      /* ================= time viewer ================= */
      /* One horizon at a time. The day is a list of tasks, the week and the
         month are the goals those days are supposed to add up to — which is
         why the toggle is not three views of one thing but three different
         questions about the same phase. */
      let horizon = sessionStorage.getItem("ph-horizon") || "day";
      let openTalk = null;              // id of the goal being talked through

      function timeViewer() {
        const box = el("section.card.ph-span7");
        const panel = el("div");

        const seg = el("div.ph-hz");
        ["day", "week", "month"].forEach((hz) => {
          seg.appendChild(el("button" + (hz === horizon ? ".on" : ""), {
            text: hz,
            onclick: () => {
              horizon = hz;
              sessionStorage.setItem("ph-horizon", hz);
              openTalk = null;
              paintSeg();
              paintPanel();
            },
          }));
        });
        function paintSeg() {
          [...seg.children].forEach((b, i) =>
            b.classList.toggle("on", ["day", "week", "month"][i] === horizon));
        }

        const flag = el("span.ph-meta", {
          text: dash.flagged ? dash.flagged + (dash.flagged === 1 ? " goal flagged" : " goals flagged") : "",
        });

        box.appendChild(el("div.ph-tv-head", {}, [
          el("div", {}, [
            el("h2", { text: "Time viewer", style: "margin:0" }),
            el("div.sub", { text: "today, then the projects it belongs to" }),
          ]),
          el("div.row", { style: "gap:8px" }, [flag, seg]),
        ]));
        box.appendChild(panel);

        function paintPanel() {
          clear(panel);
          (horizon === "day" ? dayPanel : goalPanel)(panel);
        }
        paintPanel();
        return box;
      }

      /* --- the day: today's tasks --- */
      function dayPanel(into) {
        const tasks = dash.tasks || [];
        const planned = tasks.reduce((n, t) => n + (t.planned_mins || 0), 0);
        const logged = tasks.reduce((n, t) => n + (t.logged_mins || 0), 0);

        const bits = [fmtDay(dash.today), tasks.length + (tasks.length === 1 ? " task" : " tasks")];
        if (planned) bits.push(h(planned) + " planned");
        if (logged) bits.push(h(logged) + " logged");
        into.appendChild(el("div.spread", { style: "margin-bottom:6px" }, [
          el("span.wl-label", { text: bits.join(" · ") }),
        ]));

        if (!tasks.length) {
          into.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
            text: "nothing due today and nothing in the calendar for it. a task joins this list "
                + "by being due today or by having a block that plans it." }));
          return;
        }

        tasks.forEach((t) => {
          const cb = el("input", { type: "checkbox" });
          cb.checked = !!t.done;
          cb.addEventListener("change", () => guard(async () => {
            await api.patch("/api/tasks/" + t.id, { done: cb.checked });
            load();
          }));
          // "2h · 12:00" before it happens, "1.5h · logged" once it has.
          const right = [];
          if (t.logged_mins) right.push(h(t.logged_mins) + " · logged");
          else if (t.planned_mins) right.push(h(t.planned_mins));
          if (t.at && !t.logged_mins) right.push(t.at);

          into.appendChild(el("div.ph-task" + (t.done ? ".done" : ""), {}, [
            cb,
            el("span.ph-title", { text: t.title }),
            t.serves ? el("span.ph-serves", { text: t.serves.text, title: t.serves.text }) : null,
            el("span.ph-meta", { text: right.join(" · ") }),
          ]));
        });
        into.appendChild(el("div.ph-meta", { style: "display:block;margin-top:10px;line-height:1.5",
          text: "the chip on each task is the project it sits under. tasks with no chip count toward "
              + "hours but not toward whether the week landed." }));
      }

      /* --- goal progress ---
         Three ways a bar can fill, picked per goal (poolgoals.progress):
         count, bumped here by hand; hours, the sessions logged on its project
         this week or this month, never typed; tasks, the tasks serving it. */
      function progressBar(g) {
        const p = g.progress || { pct: 0, label: "", measure: "count", auto: false };
        const bar = el("div.ph-prog", {}, [el("div.ph-prog-fill", { style: "width:" + p.pct + "%" })]);
        const bits = [bar, el("span.ph-prog-label", { text: p.label + (p.total ? " · " + p.pct + "%" : "") })];
        if (p.measure === "count" && g.status !== "done") {
          const bump = (d) => guard(async () => {
            await api.patch("/api/phases/goals/" + g.id, { scope_done: Math.max(0, (g.scope_done || 0) + d) });
            load();
          });
          bits.push(el("button.btn-sm", { text: "−1", title: "one fewer", onclick: () => bump(-1) }));
          bits.push(el("button.btn-sm", { text: "+1", title: "one more done", onclick: () => bump(1) }));
        }
        return el("div.ph-progrow", {}, bits);
      }

      function goalForm(done) {
        const projects = ((active && active.projects) || []).slice()
          .sort((a, b) => (b.mins || 0) - (a.mins || 0));
        const text = el("input", { placeholder: horizon === "week"
          ? "e.g. finish chapter 2 of the textbook" : "e.g. 20 hours on the side project" });
        const measure = el("select", {}, [
          el("option", { value: "count", text: "count (x of n, you tick it up)" }),
          el("option", { value: "hours", text: "hours logged on a project" }),
          el("option", { value: "tasks", text: "tasks done (tasks you point at it)" }),
        ]);
        const target = el("input", { type: "number", min: "0", step: "0.5", placeholder: "n", style: "width:90px" });
        const project = el("select", {}, [el("option", { value: "", text: "no project" }),
          ...projects.map((p) => el("option", { value: p.project_id, text: p.name }))]);
        const due = el("input", { type: "date", title: "defaults to the end of the " + horizon });
        const paint = () => {
          target.placeholder = measure.value === "hours" ? "hours" : measure.value === "count" ? "n" : "";
          target.style.display = measure.value === "tasks" ? "none" : "";
        };
        measure.addEventListener("change", paint);
        paint();
        const save = () => guard(async () => {
          if (!text.value.trim()) return toast("say what the goal is", true);
          const m = measure.value, n = Number(target.value) || 0;
          if (m !== "tasks" && !n) return toast("give it a target", true);
          if (m === "hours" && !project.value) return toast("an hours goal needs a project", true);
          await api.post("/api/phases/goals", {
            text: text.value.trim(), horizon, measure: m, project_id: project.value,
            due: due.value || "",
            scope_total: m === "count" ? n : 0,
            target_h: m === "hours" ? n : 0,
          });
          toast(horizon + " goal set");
          done();
          load();
        });
        text.addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
        setTimeout(() => text.focus(), 0);
        return el("div.ph-goalform", {}, [
          text,
          el("div.row", { style: "gap:6px;flex-wrap:wrap" }, [measure, target, project, due,
            el("button.btn-sm.btn-primary", { text: "add", onclick: save }),
            el("button.btn-sm", { text: "cancel", onclick: done })]),
        ]);
      }

      /* --- the week and the month: goals --- */
      function goalPanel(into) {
        const goals = (dash.goals && dash.goals[horizon]) || [];
        const label = horizon === "week"
          ? span(dash.week.start, dash.week.end) + " · " + dash.week.hours + "h logged"
          : "week " + dash.week.index + " of " + active.weeks;

        const formHost = el("div");
        into.appendChild(el("div.spread", { style: "margin-bottom:6px" }, [
          el("span.wl-label", { text: label }),
          el("div.row", { style: "gap:6px" }, [
            el("button.btn-sm", { text: "+ " + horizon + " goal", onclick: () => {
              if (formHost.firstChild) { clear(formHost); return; }
              formHost.appendChild(goalForm(() => clear(formHost)));
            } }),
            el("button.btn-sm", { text: "pull in", onclick: () => openPull() }),
          ]),
        ]));
        into.appendChild(formHost);

        if (!goals.length) {
          into.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
            text: "no " + horizon + " goals yet. a goal with a due date, a project and planned "
                + "hours is one the drift rules can actually check; one without is just a note." }));
          return;
        }

        goals.forEach((g) => {
          if (openTalk === g.id) { into.appendChild(talkPanel(g)); return; }
          const cls = g.status === "flagged" ? ".flag"
            : g.status === "done" ? ".done"
            : g.status === "renegotiated" ? ".renegotiated" : "";
          into.appendChild(el("div.ph-goal" + cls, {}, [
            el("div", {}, [
              el("span.ph-goaltext", { text: g.text }),
              progressBar(g),
              el("span.ph-meta", { text: g.status === "flagged" ? g.flag_reason : g.meta }),
            ]),
            g.status === "done" ? null : el("button.btn-sm", { title: "mark this goal done",
              text: "done", onclick: () => guard(async () => {
                await api.patch("/api/phases/goals/" + g.id, { status: "done" });
                toast("goal done");
                load();
              }) }),
            g.status === "flagged"
              ? el("button.btn-sm.ph-talk", {
                  text: "talk this through",
                  onclick: () => { openTalk = g.id; refreshViewer(); },
                })
              : el("button.btn-sm", { title: "let this go for now — it stays in the pool",
                  text: "drop", onclick: () => guard(async () => {
                    await api.del("/api/phases/" + active.id + "/pull/" + g.id);
                    toast("dropped back to the pool");
                    load();
                  }) }),
          ]));
        });
      }

      /* --- talk this through --- */
      /* The reason stays on screen while you decide, because the decision is a
         reply to it. Whichever lever you pull writes a :Change with your reason
         on it; that log is the whole point, so the reason is not optional. */
      const LEVERS = [
        { key: "move_due", label: "move the due date",
          hint: "the work is right, the date was wrong", ph: "new due date" },
        { key: "cut_scope", label: "cut the scope",
          hint: "less of it, by the same date", ph: "new total" },
        { key: "add_hours", label: "add hours",
          hint: "same scope, more of the week goes to it", ph: "new hours a day" },
      ];

      function talkPanel(g) {
        let lever = "cut_scope";
        const value = el("input");
        const reason = el("input", { placeholder: "why — this is what the log will say in a month" });
        const row = el("div.ph-levers");

        function paintLevers() {
          clear(row);
          LEVERS.forEach((l) => {
            row.appendChild(el("button.ph-lever" + (l.key === lever ? ".on" : ""), {
              type: "button",
              onclick: () => { lever = l.key; paintLevers(); prime(); },
            }, [el("b", { text: l.label }), el("span", { text: l.hint })]));
          });
        }
        function prime() {
          const l = LEVERS.find((x) => x.key === lever);
          value.placeholder = l.ph;
          value.type = lever === "move_due" ? "date" : "number";
          value.value = lever === "move_due" ? (g.due || "")
            : lever === "cut_scope" ? (g.scope_total || "")
            : (g.plan_h_day || "");
        }
        paintLevers();
        prime();

        return el("div.ph-talkpanel", {}, [
          el("h4", { text: g.text }),
          el("span.ph-talkwhy", { text: g.flag_reason }),
          row,
          el("div.row", { style: "gap:8px;align-items:stretch" }, [
            el("div", { style: "flex:0 0 160px" }, [value]),
            el("div", { style: "flex:1" }, [reason]),
          ]),
          el("div.ph-talkfoot", {}, [
            el("button", { text: "leave it flagged", onclick: () => { openTalk = null; refreshViewer(); } }),
            el("button.btn-primary", {
              text: "agree it",
              onclick: () => guard(async () => {
                if (!value.value) return toast("say what it changes to", true);
                if (!reason.value.trim()) return toast("say why — the reason is the point", true);
                await api.post("/api/phases/goals/" + g.id + "/renegotiate", {
                  lever, value: String(value.value), reason: reason.value.trim(),
                });
                openTalk = null;
                toast("renegotiated");
                load();
              }),
            }),
          ]),
        ]);
      }

      /* --- pull in --- */
      /* A phase does not make projects, tasks or habits. It claims them from
         the pools they already live in, for a number of hours, with an optional
         reason attached to the claim rather than to the thing: a project
         claimed by two phases was claimed for two different reasons.

         Claiming a parent project claims everything under it — the server
         cascades down CHILD_OF — because a phase that has taken on a parent
         project has taken on the work inside it.

         Sessions are not in here. They arrive on their own through the
         IN_PHASE hook, because work you did during a phase is in it whether or
         not you remembered to say so. */
      function openPull() {
        const overlay = el("div.modal-overlay");
        const close = () => overlay.remove();
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });

        let kind = "project";
        const list = el("div.ph-pull");
        const seg = el("div.ph-hz");
        const search = el("input", { placeholder: "search the pool" });

        let items = [];
        function paintList() {
          clear(list);
          const q = search.value.trim().toLowerCase();
          const hits = items.filter((i) => !q || (i.text || "").toLowerCase().includes(q));
          if (!items.length) {
            list.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
              text: "every project is already in this phase. new ones come from the "
                  + "Project tab, or from promoting an idea in the Inbox." }));
            return;
          }
          if (!hits.length) {
            list.appendChild(el("div.ph-meta", { style: "display:block", text: "nothing matches." }));
            return;
          }
          hits.forEach((it) => {
            const hours = el("input.ph-pullh", { type: "number", step: "0.5", min: "0",
              placeholder: "h", value: it.estimate_h || "" });
            const why = el("input.ph-pullwhy", { placeholder: "why this phase (optional)" });
            const take = el("button.btn-sm.btn-primary", { text: "take it" });
            take.addEventListener("click", () => guard(async () => {
              await api.post("/api/phases/" + active.id + "/pull", {
                kind, id: it.id,
                hours: parseFloat(hours.value) || 0,
                why: why.value.trim(),
              });
              toast("pulled in");
              items = items.filter((x) => x.id !== it.id);
              paintList();
              load();
            }));
            list.appendChild(el("div.ph-pullrow", {}, [
              el("div", {}, [
                el("div", { text: it.text }),
                el("div.ph-meta", { text: [it.sub, it.meta].filter(Boolean).join(" · ") }),
              ]),
              hours, why, take,
            ]));
          });
        }

        function loadKind(k) {
          kind = k;
          clear(list);
          list.appendChild(el("div.ph-meta", { text: "…" }));
          guard(async () => {
            items = await api.get("/api/phases/pullable?kind=" + k);
            paintList();
          });
        }
        // A phase pulls whole projects; attachments and tasks come with them.
        seg.appendChild(el("span.ph-meta", { text: "projects, with everything attached to them" }));
        search.addEventListener("input", paintList);

        overlay.appendChild(el("div.modal.ph-pullmodal", {}, [
          el("div.ph-mhead", {}, [
            el("h2", { text: "Pull into " + active.name }),
            el("div.sub", { text: "claiming is not creating. these projects already exist and outlive "
              + "the phase; this says it is taking them on, attachments and all, and for how many hours." }),
          ]),
          el("div.spread", { style: "margin-bottom:10px" }, [seg, search]),
          list,
          el("div.ph-mfoot", {}, [el("button", { text: "done", onclick: close })]),
        ]));
        document.body.appendChild(overlay);
        loadKind("project");
      }

      /* Repaint just the viewer — used by the talk panel, which must not lose
         the rest of the page's scroll position to open one flag. */
      let viewerSlot = null;
      function refreshViewer() {
        if (!viewerSlot) return;
        const fresh = timeViewer();
        viewerSlot.replaceWith(fresh);
        viewerSlot = fresh;
      }

      /* ================= in this phase =================
         The projects the phase pulled in (CLAIMED_BY), each opening onto what
         is attached to it, then whatever joined on its own. A phase pulls whole
         projects; attachments come with them. Every number is the shared
         roll-up (backend hours.py) over the phase's own weeks, the same figure
         the project page gives as "counted there". */
      const openRows = new Set();
      let showZero = false;
      function lineRow(x, depth) {
        const icon = { project: "◆", paper: "📑", book: "📕", article: "📰", video: "🎬", doc: "📄", sheet: "▦", writing: "✍" }[x.chip || x.kind] || "•";
        return el("div.pj-ph-item", { style: "padding-left:" + (depth * 16) + "px" }, [
          el("span", { text: icon }),
          el("span.pj-ph-nm", {}, [el("span", { text: x.title }), el("span.pj-kind.k-" + x.chip, { text: x.chip })]),
          el("span.ph-meta", { text: h(x.mins || 0) + " · " + (x.sessions || 0) }),
          el("button.btn-sm", { text: "↗", title: "open where it lives", onclick: () => window.ProjectAttach.openNode(x) }),
        ]);
      }
      function projectsBox(p) {
        const lu = dash.lineup || { pulled: [], auto: [], auto_zero: [] };
        const box = el("section.card.ph-span5", {}, [
          el("div.spread", { style: "margin-bottom:6px" }, [
            el("h2", { text: "In this phase", style: "margin:0" }),
            el("span.ph-meta", { text: lu.pulled.length + " pulled in" }),
          ]),
        ]);
        if (!lu.pulled.length && !lu.auto.length && !lu.auto_zero.length) {
          box.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6",
            text: "nothing in it yet. pull a project in, or just log work against one and it joins on the next read." }));
          return box;
        }
        if (!lu.pulled.length) {
          box.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.6;margin-bottom:6px",
            text: "no project pulled in yet. pulling one says this phase is taking it on, attachments and all." }));
        }
        lu.pulled.forEach((pr, i) => {
          const isOpen = openRows.has(pr.id);
          const frac = pr.planned_h ? Math.min(1, pr.mins / 60 / pr.planned_h) : 0;
          box.appendChild(el("div.ph-proj.pj-ph-pull", { onclick: () => {
            isOpen ? openRows.delete(pr.id) : openRows.add(pr.id); paintBody(); } }, [
            el("span.ph-rank", { text: String(i + 1) }),
            el("div", {}, [
              el("div.spread", {}, [
                el("span", { title: pr.name, text: (pr.items.length ? (isOpen ? "▾ " : "▸ ") : "") + pr.name }),
                el("span.ph-meta", { text: h(pr.mins || 0) + (pr.planned_h ? " of " + pr.planned_h + "h" : "")
                  + " · " + (pr.sessions || 0) + " sessions" }),
              ]),
              pr.planned_h ? el("div.ph-bar", {}, [el("i", { style: "width:" + Math.round(frac * 100) + "%" })]) : null,
            ]),
          ]));
          if (isOpen) {
            const kids = el("div.pj-ph-kids");
            if (!pr.items.length) kids.appendChild(el("div.ph-meta", { text: "nothing attached. attach from the project page." }));
            pr.items.forEach((x) => {
              kids.appendChild(lineRow(x, 0));
              (x.sources || []).forEach((src) => kids.appendChild(lineRow(src, 1)));
            });
            kids.appendChild(el("a.pj-ph-open", { text: "↗ " + pr.name,
              onclick: () => window.ProjectAttach.openNode({ kind: "project", id: pr.id }) }));
            box.appendChild(kids);
          }
        });
        if (lu.auto.length) {
          box.appendChild(el("div.ph-meta", { style: "display:block;margin:10px 0 2px", text: "joined automatically" }));
          lu.auto.forEach((pr) => box.appendChild(el("div.pj-ph-auto", {}, [
            el("a", { text: pr.name, onclick: () => window.ProjectAttach.openNode({ kind: "project", id: pr.id }) }),
            el("span.ph-meta", { text: h(pr.mins || 0) + " · " + (pr.sessions || 0) + " sessions" }),
          ])));
        }
        if (lu.auto_zero.length) {
          box.appendChild(el("div.pj-ph-zero", {
            title: "joined because something was filed in the window, with no hours here yet",
            onclick: () => { showZero = !showZero; paintBody(); },
            text: (showZero ? "▾ " : "▸ ") + lu.auto_zero.length + " more joined automatically" }));
          if (showZero) box.appendChild(el("div.ph-meta", { style: "display:block;line-height:1.7;padding-left:14px",
            text: lu.auto_zero.map((x) => x.name).join(" · ") }));
        }
        return box;
      }

      /* The phase's own goal, beside the score it is the yardstick for. */
      function phaseGoalBox(p) {
        return el("section.card", {}, [
          el("div.spread", {}, [
            el("h2", { text: "Phase goal", style: "margin:0" }),
            el("button.btn-sm", { text: "✎", onclick: () => openEdit(p) }),
          ]),
          p.goal
            ? el("div.sub", { style: "margin-top:8px;line-height:1.55", text: p.goal })
            : el("div.ph-meta", { style: "display:block;margin-top:8px;line-height:1.55",
                text: "not written yet. this is what the weekly score is measured against, "
                    + "so it is worth a sentence." }),
        ]);
      }

      /* A box a later step fills. Named and sized now so the grid is the real
         one from the start, rather than reflowing under you next week. */
      /* Inbox rows marked ◆ "do this phase". The edge is set in the Inbox and
         read back here — one fact, two views. Done ones stay, struck through,
         so the box shows how much of what you committed to has landed. */
      function inboxBox() {
        const list = dash.inbox || [];
        const done = list.filter((t) => t.status === "done" || t.status === "became").length;
        const box = el("section.card.ph-span12", {}, [
          el("div.spread", { style: "margin-bottom:8px" }, [
            el("h2", { text: "◆ To do this phase", style: "margin:0" }),
            el("span.ph-meta", { text: list.length ? done + " of " + list.length + " done" : "" }),
          ]),
        ]);
        if (!list.length) {
          box.appendChild(el("span.ph-meta", { text: "nothing marked yet — click ◆ on a row in the Inbox" }));
          return box;
        }
        list.forEach((t) => {
          const fin = t.status === "done" || t.status === "became";
          const star = t.starred ? el("span", { text: "★",
            style: "color:" + (t.star_tone === "soon" ? "#5FE0D0" : t.star_tone === "later" ? "#9AA3AD" : "var(--amber)") }) : null;
          box.appendChild(el("div.ph-inbox-row" + (fin ? ".done" : ""), { "data-nav": t.id }, [
            star,
            el("span.ph-inbox-t", { text: t.title }),
            t.takes_min > 0 && t.takes_min <= 5 ? el("span.ph-meta", { text: "⑤" }) : null,
            el("span.ph-meta", { text: t.kind + " · " + t.status + (t.due ? " · due " + t.due : "") }),
          ]));
        });
        return box;
      }

      function soonBox(span, title, what) {
        return el("section.card.ph-soon" + (span ? ".ph-span" + span : ""), {}, [
          el("h2", { text: title, style: "margin:0" }),
          el("span.ph-meta", { text: what }),
        ]);
      }

      /* Two boxes sharing one column. The score and the phase goal stack because
         they are a pair: the number and the thing the number is measured
         against. Splitting them across rows would leave the score arguing with
         nothing. */
      function stack(children) {
        return el("div.ph-stack.ph-span4", {}, children);
      }

      function dashboard(p) {
        const grid = el("div.ph-grid");
        viewerSlot = timeViewer();
        grid.appendChild(viewerSlot);
        grid.appendChild(projectsBox(p));
        grid.appendChild(inboxBox());
        grid.appendChild(soonBox(12, "Body and habits",
          "the strip, the exceptions drawer and the habit week strips — step 4."));
        grid.appendChild(soonBox(8, "Targets",
          "count, hours and timeline targets, down to the instance behind each milestone — step 3."));
        grid.appendChild(stack([
          soonBox(0, "Score, this week",
            "habits, hours, content and mistakes, 25 each — step 5."),
          phaseGoalBox(p),
        ]));
        grid.appendChild(soonBox(12, "This week",
          "the phase's calendar, with the blocks an event displaced in amber — step 5."));
        grid.appendChild(soonBox(12, "What changed",
          "schedule health, then every change, mistake, lesson and event tagged to the phase — step 5."));
        return grid;
      }

      function pastCard(p) {
        const rows = p.projects.map((pr) => {
          const o = OUTCOMES.find((x) => x.key === pr.outcome);
          return el("div.ph-oc", {}, [
            el("div.ph-oc-top", {}, [
              el("div", {}, [
                el("strong", { text: pr.name }),
                el("div.ph-oc-stat", { text: projStat(pr) }),
              ]),
              el("span.pill", {
                text: pr.outcome || "unanswered",
                style: o ? "border-color:" + o.c + ";color:" + o.c : "",
              }),
            ]),
            pr.outcome_note ? el("div.ph-oc-stat", { style: "color:var(--muted);line-height:1.5", text: pr.outcome_note }) : null,
          ]);
        });
        return el("div.card", { style: "margin-bottom:12px" }, [
          el("div.spread", {}, [
            el("h2", { text: p.name }),
            el("span.pill", { text: "phase " + seqLabel(p.seq) }),
          ]),
          el("div.ph-oc-stat", { style: "margin:4px 0 10px",
            text: span(p.start, p.end) + " · " + p.weeks + " weeks · " + p.hours + "h · " +
                  p.sessions + " sessions · " + p.tally.done + " done, " +
                  p.tally.carried + " carried, " + p.tally.dropped + " dropped" }),
          ...rows,
          p.reflection ? el("div", { style: "margin-top:12px;line-height:1.55", text: p.reflection }) : null,
        ]);
      }

      async function load() {
        // Two reads, and they do different jobs: the dashboard is the active
        // phase as one coherent snapshot (steps 2 to 5 fill the rest of it in),
        // the list is only the closed phases stacked underneath.
        const [payload, all] = await guard(() => Promise.all([
          api.get("/api/phases/active/dashboard"),
          api.get("/api/phases"),
        ]));
        dash = payload;
        active = dash.phase;
        past = all;
        paintHead();
        paintBody();
      }

      function paintBody() {
        clear(body);
        if (active && mode === "pace") {
          // Pace reads its own endpoint: it needs the plan off the claims and
          // the hours per day, neither of which the dashboard payload carries.
          body.appendChild(banner(active));
          const host = el("div");
          body.appendChild(host);
          window.PhasePace.render(host, () => window.PhasePace.render(host));
          return;
        }
        if (active) {
          body.appendChild(banner(active));
          body.appendChild(statGrid(active));
          body.appendChild(dashboard(active));
        } else {
          body.appendChild(el("div.card", {}, [
            el("div.sub", { text: past.length
              ? "no phase running. the break is the point — start the next one when you have decided what it is for."
              : "no phases yet. a phase is fourteen weeks at a handful of projects." }),
          ]));
        }
        const closed = past.filter((p) => p.status === "closed");
        if (closed.length) {
          body.appendChild(el("div.wl-label", { style: "display:block;margin:26px 0 10px", text: "closed phases" }));
          closed.forEach((p) => body.appendChild(pastCard(p)));
        }
      }

      load();
    },
  };
})();

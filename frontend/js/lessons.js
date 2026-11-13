/* lessons.js — what went wrong, what you do instead, and whether it happened
   again. Built 2026-10-04 from the lessons mockup.

   ONE ROW PER MISTAKE. Every time it happens is an instance under it, rather
   than a fresh row that has to be hand-linked to the first. Underneath this is
   still the SAME_AS model (see routes/lessons.py): the first time is the row,
   each instance is a later lesson pointing at it, and `repeated` lands on those
   later ones, so the phase score's mistakes part reads what it always read.

   "Instead" sits in the row, not behind the expander, because it is the half
   that makes it a lesson rather than a complaint, and a row without one says
   so in amber.

   SOLUTIONS are the working list you got to "instead" with. Each one carries
   how trying it went (worked / mixed / failed), because "I tried headphones
   and they still come up" is worth as much as the fix that held.

   DISTRACTIONS logged from reading sessions are not lessons until you make one.
   They sit in a collapsed tally by pattern; "make lesson" turns a pattern into
   a lesson whose instances are those sessions, and later distractions with the
   same pattern join it on their own.

   CATEGORIES are yours (the strip seeds eight from the mockup). Click one to
   filter; "categories" edits names, colours and what belongs in each. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const NEUTRAL = "#7FA8C8";
  const SOL_LABEL = { "": "not tried", worked: "worked", mixed: "mixed", failed: "didn't work" };
  const fmt = (d) => (d ? window.Notes.fmtDate(d) : "");
  // "Sample Book: A Long Subtitle… v16" → "Sample Book v16"
  const short = (t) => String(t || "").replace(/:.*?( v\d+)?$/, "$1");

  window.Views = window.Views || {};
  window.Views.learning = {
    id: "learning", label: "Lessons", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      let data = { lessons: [], categories: [], tally: [], since: "" };
      let cat = null;                    // category name filter, null = all
      let chip = "all";                  // all | repeated | noinstead | phase
      const open = new Set();            // expanded lesson ids, kept across reloads

      const colorOf = (name) =>
        (data.categories.find((g) => g.name === name) || {}).color || NEUTRAL;
      const known = () => new Set(data.categories.filter((c) => c.name).map((c) => c.name));
      const catOf = (l) => (known().has(l.group) ? l.group : "");

      const tag = (name) => {
        const c = colorOf(name);
        return el("span.lx-tag", { style: "--c:" + c, text: name || "no category" });
      };
      const instead = (l) => l.instead
        ? el("span.lx-instead", { text: l.instead })
        : el("span.lx-instead.none", { text: "no instead yet" });

      viewEl.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Lessons" }),
          el("div.sub", { text: "what went wrong, what you do instead, and whether it happened "
            + "again. one row per mistake, every time it happens is an instance under it." }),
        ]),
        el("div.row", { style: "gap:6px" }, [
          el("button.btn-sm", { text: "categories", onclick: () => openCategories() }),
          el("button.btn-primary", { text: "+ lesson", onclick: () => openEditor(null) }),
        ]),
      ]));

      const catsEl = el("div.lx-cats");
      const repEl = el("div");
      const tallyEl = el("div");
      const listEl = el("div.card");
      [catsEl, repEl, tallyEl, listEl].forEach((n) => viewEl.appendChild(n));

      /* ------------------------------------------------------ categories */
      function paintCats() {
        clear(catsEl);
        data.categories.forEach((c) => {
          const key = c.name;
          catsEl.appendChild(el("div.lx-cat" + (cat === key ? ".on" : ""), {
            style: "--c:" + (c.color || NEUTRAL),
            title: cat === key ? "show every category" : "show only " + (key || "uncategorised"),
            onclick: () => { cat = cat === key ? null : key; paintCats(); paintList(); },
          }, [
            el("div.n", { text: String(c.count) }),
            el("div.l", { text: c.name || "Uncategorised" }),
            el("div.m", { text: c.note || "" }),
            c.repeated ? el("div.rep", { text: c.repeated + " repeated" }) : null,
          ]));
        });
      }

      /* ------------------------------------------- repeated this phase */
      function paintRepeated() {
        clear(repEl);
        const reps = data.lessons.filter((l) => l.repeats_this_phase > 0)
          .sort((a, b) => b.times - a.times);
        if (!reps.length) return;
        repEl.appendChild(el("div.lx-repbox", {}, [
          el("div.spread", {}, [
            el("h2", { text: "Repeated this phase" }),
            el("span.ph-meta", { text: "since " + fmt(data.since) + " · counts against the score's "
              + "mistakes part · a lesson is repeated when a new instance is marked as the same" }),
          ]),
          el("table.lx-table", {}, [
            el("tr", {}, ["lesson", "category", "times", "last", "instead, as it stands", ""]
              .map((h) => el("th", { text: h }))),
            ...reps.map((l) => el("tr", {}, [
              el("td", { text: l.wrong }),
              el("td", {}, [tag(catOf(l))]),
              el("td.lx-n", {}, [el("b", { text: String(l.times) })]),
              el("td.lx-d", { text: fmt(l.last) }),
              el("td", {}, [instead(l)]),
              el("td", {}, [el("button.btn-sm", { text: "open", onclick: () => reveal(l.id) })]),
            ])),
          ]),
        ]));
      }

      /* -------------------------------------------------- distractions */
      let tallyOpen = false;
      function paintTally() {
        clear(tallyEl);
        if (!data.tally.length) return;
        const times = data.tally.reduce((s, t) => s + t.times, 0);
        const det = el("details", tallyOpen ? { open: true } : {});
        det.addEventListener("toggle", () => { tallyOpen = det.open; });
        det.appendChild(el("summary", { text: "distractions logged from sessions, not lessons until "
          + "you make one · " + data.tally.length + " patterns · " + times + " times" }));
        det.appendChild(el("table.lx-table", { style: "margin-top:8px" }, [
          el("tr", {}, ["pattern", "times", "last", "while", "", ""].map((h) => el("th", { text: h }))),
          ...data.tally.map((t) => el("tr", {}, [
            el("td", { text: t.pattern }),
            el("td.lx-n", { text: String(t.times) }),
            el("td.lx-d", { text: fmt(t.last) }),
            el("td.ph-meta", { text: t.while.slice(0, 3).map(short).join(", ") }),
            el("td", {}, [t.lesson_id
              ? el("button.btn-sm.lx-link", { text: "→ lesson", title: "open the lesson it became",
                  onclick: () => reveal(t.lesson_id) })
              : el("button.btn-sm", { text: "make lesson", onclick: () => openPromote(t) })]),
            el("td", {}, [t.loose.length ? el("button.btn-sm.btn-danger", { text: "delete",
              title: "delete these logged distractions",
              onclick: () => confirmDo("Delete the " + t.loose.length + " logged distraction"
                + (t.loose.length > 1 ? "s" : "") + " “" + t.pattern + "”? This can't be undone.",
                async () => {
                  for (const x of t.loose) await api.del("/api/lessons/" + x.id);
                  toast("deleted");
                  load();
                }) }) : null]),
          ])),
        ]));
        tallyEl.appendChild(el("div.card", {}, [det]));
      }

      /* ------------------------------------------------------ the list */
      function shown() {
        return data.lessons.filter((l) => {
          if (cat !== null && catOf(l) !== cat) return false;
          if (chip === "repeated") return l.times > 1;
          if (chip === "noinstead") return !l.instead;
          if (chip === "phase") return l.last >= data.since;
          return true;
        });
      }

      function paintList() {
        clear(listEl);
        const chips = [["all", "all"], ["repeated", "repeated"], ["noinstead", "no instead yet"],
                       ["phase", "this phase"]];
        listEl.appendChild(el("div.lx-filters", {}, [
          ...chips.map(([k, label]) => el("span.lx-chip" + (chip === k ? ".on" : ""),
            { text: label, onclick: () => { chip = k; paintList(); } })),
          cat !== null ? el("span.lx-chip.on", { text: (cat || "uncategorised") + " ×",
            title: "clear the category filter",
            onclick: () => { cat = null; paintCats(); paintList(); } }) : null,
          el("span.ph-meta", { style: "margin-left:auto",
            text: "click a row for instances, solutions, notes" }),
        ]));

        if (!data.lessons.length) {
          listEl.appendChild(el("div.sub", { style: "line-height:1.6", text: "nothing written down "
            + "yet. a lesson is two sentences: what went wrong, and what you would do instead." }));
          return;
        }
        const rows = shown();
        if (!rows.length) {
          listEl.appendChild(el("div.ph-meta", { style: "display:block", text: "nothing matches that filter." }));
          return;
        }
        const table = el("table.lx-table", {}, [
          el("tr", {}, [["date"], ["category"], ["what went wrong"], ["instead"],
            ["times", "width:60px"], ["solved", "width:60px"], ["", "width:70px"]]
            .map(([h, st]) => el("th", { text: h, style: st || "" }))),
        ]);
        rows.forEach((l) => {
          const isOpen = open.has(l.id);
          table.appendChild(el("tr.lx-l" + (isOpen ? ".open" : ""), {
            id: "lx-" + l.id, "data-eid": l.id,
            onclick: () => { isOpen ? open.delete(l.id) : open.add(l.id); paintList(); },
          }, [
            el("td.lx-d", { text: fmt(l.date) }),
            el("td", {}, [tag(catOf(l))]),
            el("td", { text: l.wrong }),
            el("td", {}, [instead(l)]),
            el("td.lx-n", {}, [l.times > 1 ? el("b", { text: String(l.times) }) : String(l.times)]),
            el("td.lx-n", { text: l.state === "solved" ? "✓" : l.state }),
            el("td", {}, [el("button.btn-sm.btn-danger", { text: "delete", title: "delete lesson",
              onclick: (e) => { e.stopPropagation(); removeLesson(l); } })]),
          ]));
          if (isOpen) table.appendChild(el("tr.lx-x", {}, [el("td", { colspan: "7" }, [detail(l)])]));
        });
        listEl.appendChild(table);
      }

      function reveal(id) {
        chip = "all"; cat = null; open.add(id);
        paintCats(); paintList();
        const row = document.getElementById("lx-" + id);
        if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
      }

      function removeLesson(l) {
        confirmDo("Delete “" + l.wrong + "”? Instances you typed go with it; ones logged from "
          + "sessions go back to the distractions tally.", async () => {
          await api.del("/api/lessons/" + l.id);
          open.delete(l.id);
          toast("lesson deleted");
          load();
        });
      }

      /* ------------------------------------------------- expanded row */
      function addLine(placeholder, onAdd, extra) {
        const input = el("input", { placeholder });
        const go = () => guard(async () => {
          const v = input.value.trim();
          if (!v) return;
          await onAdd(v);
          input.value = "";
        });
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
        return el("div.lx-addline", {}, [input, ...(extra || []),
          el("button.btn-sm", { text: "add", onclick: go })]);
      }

      function detail(l) {
        const left = el("div"), right = el("div");

        /* instances */
        left.appendChild(el("h3", { text: "instances · " + l.times }));
        l.instances.forEach((i) => {
          const what = [i.text, i.about ? short(i.about.title) : ""].filter(Boolean).join(" · ");
          left.appendChild(el("div.lx-occ", {}, [
            el("span.d", { text: fmt(i.date) }),
            el("span", { style: "flex:1", text: what || (i.first ? l.wrong : "") }),
            el("span.w", { text: i.first ? "first"
              : i.source === "distraction" ? "from a session" : "marked same" }),
            i.first ? null : el("button.btn-sm.lx-x-btn", {
              title: i.source === "distraction" ? "not the same: send it back to the distractions tally"
                : "remove this instance",
              text: "×", onclick: () => guard(async () => {
                if (i.source === "distraction") await api.patch("/api/lessons/" + i.id, { same_as: "" });
                else await api.del("/api/lessons/" + i.id);
                load();
              }) }),
          ]));
        });
        const when = el("input", { type: "date", value: new Date().toLocaleDateString("en-CA"),
          style: "width:auto" });
        left.appendChild(addLine("+ instance: what happened this time", async (v) => {
          await api.post("/api/lessons/" + l.id + "/instances", { detail: v, date: when.value });
          toast("logged again");
          load();
        }, [when]));
        const loose = data.tally.flatMap((t) => t.loose.map((x) => ({ ...x, pattern: t.pattern })));
        if (loose.length) {
          const sel = el("select", {}, [el("option", { value: "", text: "…or mark a logged distraction as this one" }),
            ...loose.map((x) => el("option", { value: x.id, text: fmt(x.date) + " · " + x.pattern }))]);
          sel.addEventListener("change", () => guard(async () => {
            if (!sel.value) return;
            await api.post("/api/lessons/" + l.id + "/instances", { from_id: sel.value });
            toast("marked as the same");
            load();
          }));
          left.appendChild(el("div.lx-addline", {}, [sel]));
        }

        /* notes */
        left.appendChild(el("h3", { style: "margin-top:14px", text: "notes" }));
        l.notes.forEach((n) => left.appendChild(el("div.lx-note", {}, [
          el("span", { text: n.text }),
          el("span.ph-meta", { style: "display:block;margin-top:2px",
            text: fmt((n.created_at || "").slice(0, 10)) }),
          el("button.btn-sm.lx-x-btn", { text: "×", title: "delete note", onclick: () =>
            guard(async () => { await api.del("/api/lessons/entries/" + n.id); load(); }) }),
        ])));
        left.appendChild(addLine("+ note", async (v) => {
          await api.post("/api/lessons/entries", { parent_id: l.id, kind: "note", text: v });
          load();
        }));

        /* solutions */
        right.appendChild(el("h3", { text: "solutions · try one, mark how it went" }));
        l.solutions.forEach((s) => {
          const status = el("select.lx-solstat", {}, Object.entries(SOL_LABEL)
            .map(([k, t]) => el("option", { value: k, text: t })));
          status.value = s.status;
          status.addEventListener("change", () => guard(async () => {
            await api.patch("/api/lessons/entries/" + s.id, { status: status.value });
            load();
          }));
          const outcome = el("input.lx-outcome", { value: s.outcome,
            placeholder: s.status ? "how it went" : "e.g. sign ordered" });
          outcome.addEventListener("change", () => guard(async () => {
            await api.patch("/api/lessons/entries/" + s.id, { outcome: outcome.value });
            load();
          }));
          right.appendChild(el("div.lx-sol" + (s.status ? "." + s.status : ""), {}, [
            el("div.spread", {}, [
              el("span", { text: s.text }),
              el("button.btn-sm.lx-x-btn", { text: "×", title: "delete solution", onclick: () =>
                guard(async () => { await api.del("/api/lessons/entries/" + s.id); load(); }) }),
            ]),
            el("div.row", { style: "gap:6px;margin-top:4px;flex-wrap:nowrap" }, [
              status,
              s.tried_at ? el("span.ph-meta", { style: "white-space:nowrap", text: "tried " + fmt(s.tried_at) }) : null,
              outcome,
            ]),
          ]));
        });
        right.appendChild(addLine("+ solution", async (v) => {
          await api.post("/api/lessons/entries", { parent_id: l.id, kind: "suggestion", text: v });
          load();
        }));

        right.appendChild(el("div.row", { style: "margin-top:12px;gap:6px" }, [
          el("button.btn-sm", { text: l.status === "solved" ? "↺ reopen" : "✓ mark solved",
            onclick: () => guard(async () => {
              await api.patch("/api/lessons/" + l.id, { status: l.status === "solved" ? "" : "solved" });
              toast(l.status === "solved" ? "reopened" : "marked solved");
              load();
            }) }),
          el("button.btn-sm", { text: "✎ edit / category", onclick: () => openEditor(l) }),
          el("button.btn-sm", { text: "merge into another", onclick: () => openMerge(l) }),
          el("button.btn-sm.btn-danger", { text: "delete lesson", onclick: () => removeLesson(l) }),
        ]));

        const wrap = el("div.lx-inst", { onclick: (e) => e.stopPropagation() }, [left, right]);
        return wrap;
      }

      /* -------------------------------------------------------- modals */
      function modal(title, sub, body, onSave, saveText) {
        const overlay = el("div.modal-overlay");
        const close = () => overlay.remove();
        overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
        overlay.appendChild(el("div.modal", {}, [
          el("div.ph-mhead", {}, [el("h2", { text: title }), sub ? el("div.sub", { text: sub }) : null]),
          ...body,
          el("div.ph-mfoot", {}, [
            el("button", { text: onSave ? "cancel" : "done", onclick: close }),
            onSave ? el("button.btn-primary", { text: saveText || "save",
              onclick: () => guard(async () => { if ((await onSave()) !== false) { close(); load(); } }) }) : null,
          ]),
        ]));
        document.body.appendChild(overlay);
        return close;
      }
      const field = (label, input) => el("div", { style: "margin-bottom:10px" },
        [el("div.mform-label", { text: label }), input]);
      const catSelect = (value) => {
        const s = el("select", {}, [el("option", { value: "", text: "— no category —" }),
          ...data.categories.filter((c) => c.name).map((c) => el("option", { value: c.name, text: c.name }))]);
        s.value = value || "";
        return s;
      };

      function openEditor(l) {
        const wrong = el("input", { style: "width:100%", placeholder: "what went wrong" });
        const inst = el("input", { style: "width:100%", placeholder: "what you would do instead" });
        const when = el("input", { type: "date", value: l ? l.date : new Date().toLocaleDateString("en-CA") });
        const grp = catSelect(l ? catOf(l) : cat || "");
        if (l) { wrong.value = l.wrong; inst.value = l.instead; }
        modal(l ? "Edit lesson" : "New lesson",
          "the second box is the one that matters: what you would do instead is what makes this usable.",
          [field("what went wrong", wrong), field("what I would do instead", inst),
           el("div.mform-row", {}, [field("first time", when), field("category", grp)])],
          async () => {
            if (!wrong.value.trim()) { toast("say what went wrong", true); return false; }
            const payload = { wrong: wrong.value.trim(), instead: inst.value.trim(),
              date: when.value, group: grp.value };
            if (l) await api.patch("/api/lessons/" + l.id, payload);
            else await api.post("/api/lessons", payload);
            toast(l ? "lesson updated" : "written down");
          }, l ? "save" : "write it down");
        wrong.focus();
      }

      function openPromote(t) {
        const wrong = el("input", { value: t.pattern });
        const grp = catSelect(cat || "Environment");
        modal("Make a lesson from “" + t.pattern + "”",
          "the first time becomes the lesson and the other " + (t.times - 1)
          + " become its instances. later distractions with this pattern join it on their own, "
          + "and each one after the first counts as a repeat.",
          [field("what went wrong", wrong), field("category", grp)],
          async () => {
            const r = await api.post("/api/lessons/promote",
              { pattern: t.pattern, wrong: wrong.value.trim(), group: grp.value });
            open.add(r.id);
            toast("lesson made, " + r.instances + " instance" + (r.instances === 1 ? "" : "s"));
          }, "make lesson");
      }

      function openMerge(l) {
        const others = data.lessons.filter((x) => x.id !== l.id);
        const sel = el("select", {}, others.map((x) =>
          el("option", { value: x.id, text: fmt(x.date) + " · " + String(x.wrong).slice(0, 60) })));
        modal("Merge into another lesson",
          "this lesson, its instances, solutions and notes move under the one you pick. "
          + "every moved occurrence then counts as a repeat of it.",
          others.length ? [field("merge into", sel)] : [el("div.sub", { text: "no other lesson to merge into." })],
          others.length ? async () => {
            await api.post("/api/lessons/" + l.id + "/merge", { into: sel.value });
            open.delete(l.id); open.add(sel.value);
            toast("merged");
          } : null, "merge");
      }

      function openCategories() {
        const list = el("div");
        const draw = () => {
          clear(list);
          data.categories.filter((c) => c.name).forEach((g) => {
            const col = el("input", { type: "color", value: g.color, style: "width:40px;padding:2px" });
            const note = el("input", { value: g.note, placeholder: "what belongs here" });
            const save = () => guard(async () => {
              await api.put("/api/lessons/groups", { name: g.name, color: col.value, note: note.value.trim() });
              await load(); draw();
            });
            col.addEventListener("change", save);
            note.addEventListener("change", save);
            list.appendChild(el("div.row", { style: "padding:4px 0;gap:6px;flex-wrap:nowrap" }, [
              col, el("span", { style: "width:110px;flex:none", text: g.name }), note,
              el("button.btn-sm.btn-danger", { text: "×", onclick: () =>
                confirmDo("Delete the category “" + g.name + "”? Lessons in it keep their text.",
                  async () => { await api.del("/api/lessons/groups/" + encodeURIComponent(g.name));
                    await load(); draw(); }) }),
            ]));
          });
        };
        draw();
        const name = el("input", { placeholder: "new category" });
        modal("Categories", "yours to define. the useful groupings are the ones you notice yourself making.",
          [list, el("div.row", { style: "margin-top:10px;gap:6px;flex-wrap:nowrap" }, [
            name,
            el("button.btn-sm.btn-primary", { text: "add", onclick: () => guard(async () => {
              if (!name.value.trim()) return;
              await api.put("/api/lessons/groups", { name: name.value.trim(), color: NEUTRAL });
              name.value = "";
              await load(); draw();
            }) }),
          ])], null);
      }

      async function load() {
        data = await guard(() => api.get("/api/lessons/board"));
        if (!data) return;
        paintCats(); paintRepeated(); paintTally(); paintList();
      }
      load();
    },
  };
})();

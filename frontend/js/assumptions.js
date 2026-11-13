/* assumptions.js — every assumption, wherever it was made.

   The sibling of questions.js. A question is what a pass left you asking; an
   assumption is what you went ahead on without asking. Each one is a row typed
   into an assumptions list box (reading pass, project, workout) and numbered
   A1, A2… once, globally, so the number you jot elsewhere keeps meaning the
   same assumption.

   OPEN FIRST, AND OPEN IS THE DEFAULT VIEW. An unchecked assumption is work;
   one that held or broke is a record. Checking is inline: held / broke, and a
   note on what showed you which.

   WRITABLE HERE TOO (2026-10-28). The box at the top adds one straight from
   the tab — on its own, or pinned to a project — through the same POST the
   list boxes use, so it is numbered like any other.

   THE TOP-BAR TAB CARRIES THE OPEN COUNT (see `badge`, read by app.js), so
   unchecked assumptions are visible from anywhere without opening the tab. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const COLOR = { open: "var(--amber)", held: "var(--teal)", broke: "var(--red)" };

  /* Where the row came from, in words. Shared with the source grouping so the
     dropdown and the row caption can't disagree. */
  function sourceOf(a) {
    if (a.paper) return { id: a.paper.id, title: a.paper.title };
    if (a.on) {
      const t = a.on.title || (a.on.label === "Workout" ? "workout " + (a.on.date || "").slice(0, 10) : a.on.label);
      return { id: a.on.id, title: (a.on.label ? a.on.label.toLowerCase() + ": " : "") + t };
    }
    return { id: "", title: "no source" };
  }

  async function paintBadge(btn) {
    const c = await api.get("/api/assumptions/count").catch(() => null);
    if (!c || !btn.isConnected) return;
    let b = btn.querySelector(".tab-badge");
    if (!b) { b = el("span.tab-badge"); btn.appendChild(b); }
    b.textContent = c.open ? String(c.open) : "";
    b.title = c.open + " open of " + c.total;
    b.style.display = c.open ? "" : "none";
  }
  // Anything that changes a count calls this, so the badge stays true without
  // waiting for the next tab repaint.
  window.refreshAssumptionBadge = () => {
    document.querySelectorAll(".tab[data-tab='assumptions']").forEach((b) => paintBadge(b));
  };

  window.Views = window.Views || {};
  window.Views.assumptions = {
    id: "assumptions", label: "Assumptions", scoped: false,
    badge: paintBadge,
    async render(viewEl) {
      clear(viewEl);
      let all = [];
      let show = "open";                 // open | held | broke | all
      let source = "";
      const open = new Set();            // rows with the note box out

      const head = el("div.row", { style: "gap:10px;align-items:center;flex-wrap:wrap" });
      const list = el("div", { style: "margin-top:12px" });
      viewEl.appendChild(el("h2", { text: "Assumptions" }));
      viewEl.appendChild(el("div.sub", {
        text: "What you went ahead on without checking — from reading passes, projects and workouts. "
            + "Numbered once; mark each one held or broke when you find out.",
      }));
      viewEl.appendChild(composer());
      viewEl.appendChild(head);
      viewEl.appendChild(list);

      function composer() {
        const input = el("input", { style: "flex:1;min-width:220px",
          placeholder: "something you're taking for granted — Enter to add" });
        const about = el("select", { title: "what it's assumed about (optional)" },
          [el("option", { value: "", text: "no project" })]);
        api.get("/api/projects").then((ps) => {
          ps.filter((p) => !/^(dropped|archived|done)$/.test(p.status || ""))
            .sort((a, b) => (a.name || "").localeCompare(b.name || ""))
            .forEach((p) => about.appendChild(el("option", { value: p.id, text: p.name })));
        }).catch(() => {});
        const add = () => guard(async () => {
          const text = input.value.trim();
          if (!text) { input.focus(); return; }
          const body = { text, kind: about.value ? "project assumption" : "assumption" };
          if (about.value) body.parent_id = about.value;
          const a = await api.post("/api/assumptions", body);
          all.unshift(a);
          input.value = "";
          if (show !== "open" && show !== "all") show = "open";
          toast("A" + a.number + " added");
          window.refreshAssumptionBadge();
          draw();
          input.focus();
        });
        input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); add(); } });
        return el("div.row", { style: "gap:8px;margin:12px 0 4px;flex-wrap:wrap" }, [
          input, about, el("button.btn-sm.btn-primary", { text: "+ add", onclick: add }),
        ]);
      }

      function draw() {
        clear(head); clear(list);
        const counts = { all: all.length };
        ["open", "held", "broke"].forEach((k) => { counts[k] = all.filter((a) => a.status === k).length; });
        ["open", "held", "broke", "all"].forEach((k) => {
          const on = show === k;
          head.appendChild(el("button.btn-sm", {
            style: on ? "border-color:var(--teal);color:var(--teal)" : "",
            text: k + " " + counts[k],
            onclick: () => { show = k; draw(); },
          }));
        });

        const sources = [];
        const seen = new Set();
        all.forEach((a) => {
          const s = sourceOf(a);
          if (seen.has(s.id)) return;
          seen.add(s.id); sources.push(s);
        });
        if (sources.length > 1) {
          const sel = el("select", { onchange: () => { source = sel.value; draw(); } });
          sel.appendChild(el("option", { value: "", text: "every source" }));
          sources.forEach((s) => {
            const o = el("option", { value: s.id, text: s.title });
            if (s.id === source) o.setAttribute("selected", "");
            sel.appendChild(o);
          });
          head.appendChild(sel);
        }

        let rows = all.filter((a) => show === "all" || a.status === show);
        if (source) rows = rows.filter((a) => sourceOf(a).id === source);
        if (!rows.length) {
          list.appendChild(el("div.sub", { style: "margin-top:16px",
            text: show === "open" ? "No open assumptions. Write one in the box above, or under a reading pass, a project or a workout."
              : "Nothing here yet." }));
          return;
        }
        rows.forEach((a) => list.appendChild(rowFor(a)));
      }

      async function patch(a, body, msg) {
        const up = await api.patch("/api/assumptions/" + a.id, body);
        Object.assign(a, up);
        if (msg) toast(msg);
        window.refreshAssumptionBadge();
        draw();
      }

      function rowFor(a) {
        const text = el("div", { text: a.text, style: "font-size:13px;line-height:1.5" });
        if (a.status !== "open") text.style.color = "var(--dim)";
        const where = [sourceOf(a).title];
        if (a.on && a.on.label === "Instance" && a.on.version) where.push("v" + a.on.version);
        if (a.created_at) where.push(String(a.created_at).slice(0, 10));

        const body = el("div", { style: "flex:1" }, [
          text,
          el("div.sub", { style: "font-size:10px;margin-top:2px", text: where.join(" · ") }),
          a.note ? el("div", { style: "font-size:12px;margin-top:6px;padding-left:8px;border-left:2px solid "
            + COLOR[a.status], text: a.note }) : null,
        ]);

        const num = el("span.mono", { style: "min-width:38px;font-size:12px;color:" + COLOR[a.status],
          title: a.status, text: "A" + a.number });
        const stateBtn = (k, label) => el("button.btn-sm", {
          title: a.status === k ? "back to open" : "mark " + k,
          style: a.status === k ? "border-color:" + COLOR[k] + ";color:" + COLOR[k] : "",
          text: label,
          onclick: () => guard(() => patch(a, { status: a.status === k ? "open" : k },
            a.status === k ? "reopened" : k)),
        });
        const write = el("button.btn-sm", {
          text: a.note ? "edit note" : "note",
          onclick: () => { open.has(a.id) ? open.delete(a.id) : open.add(a.id); draw(); },
        });
        const del = el("button.btn-sm.btn-danger", {
          title: "delete. Its number is not reused.", text: "×",
          onclick: () => confirmDo("delete A" + a.number + "? Its number is not reused.", async () => {
            await api.del("/api/assumptions/" + a.id);
            all = all.filter((x) => x.id !== a.id);
            window.refreshAssumptionBadge();
            draw();
          }),
        });

        const row = el("div", { style: "padding:8px 0;border-bottom:1px solid var(--border)" }, [
          el("div.row", { style: "gap:8px;align-items:flex-start" },
            [num, body, stateBtn("held", "✓ held"), stateBtn("broke", "✗ broke"), write, del]),
        ]);
        if (open.has(a.id)) {
          const ta = el("input", { style: "width:100%;margin-top:6px",
            placeholder: "what showed you whether it held", value: a.note || "" });
          row.appendChild(ta);
          row.appendChild(el("div.row", { style: "gap:6px;margin-top:6px" }, [
            el("button.btn-sm.btn-primary", { text: "save note", onclick: () => guard(async () => {
              open.delete(a.id);
              await patch(a, { note: ta.value.trim() }, "note saved");
            }) }),
            el("button.btn-sm", { text: "cancel", onclick: () => { open.delete(a.id); draw(); } }),
          ]));
        }
        return row;
      }

      all = await api.get("/api/assumptions").catch(() => []);
      draw();
    },
  };

  /* The pair of list boxes every surface gets: questions, then assumptions.
     One call so a reading pass, a project and a workout can't drift apart.
     Returns a node; `kindPrefix` names the box ("project", "workout") so each
     surface's rows stay filterable by kind. */
  window.QABoxes = function (parentId, kindPrefix, opts) {
    opts = opts || {};
    const pre = kindPrefix ? kindPrefix + " " : "";
    const q = window.ListBox({
      label: opts.qLabel || "questions", kind: pre + "question", parentId: parentId,
      noun: "question", placeholder: "a question this leaves you with, one per row",
      note: "each one goes to the Questions tab and the Inbox",
    });
    const a = window.ListBox({
      label: "assumptions", kind: pre + "assumption", parentId: parentId,
      endpoint: "/api/assumptions", noun: "assumption",
      placeholder: "something you're taking for granted, one per row",
      note: "numbered in the Assumptions tab",
      onChange: () => window.refreshAssumptionBadge && window.refreshAssumptionBadge(),
    });
    return el("div.qa-boxes", { style: "margin-top:10px" }, [q.node, a.node]);
  };
})();

/* questions.js — every question, wherever it was asked, laid out like the Inbox.

   The questions tab exists because the main question stopped being a textarea.
   One question per node means they can be counted, answered and gathered.

   SAME SHAPE AS THE INBOX (2026-11-08). Stats on top, an add box and chips,
   then the same two stars lifting rows into their own tables: yellow ★ =
   priority, teal ★ = possible priority. The star markup and CSS are the
   Inbox's own (.ib-star / .ib-star2 / .ib-starred / .ib-soon), so a star means
   the same thing in both tabs.

   OPEN IS THE DEFAULT VIEW. A question you have answered is a note; a question
   you have not is work. Answered ones live under their own chip.

   ANSWERING IS INLINE. The answer opens as a line under the row. Marking
   answered without writing anything is allowed: sometimes the answer is that
   the question dissolved.

   Every question is also a row in the Inbox — a row moved here with
   "question → Questions tab" keeps that row (see routes/questions.py). */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const Q = "/api/questions";
  const COLS = 7;

  window.Views = window.Views || {};
  window.Views.questions = {
    id: "questions", label: "Questions", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      let all = [];
      let show = "open";                 // open | starred | answered | all
      let source = "";                   // paper id, or '' for every source
      const open = new Set();            // which rows have the answer line out
      const host = el("div");
      viewEl.appendChild(host);

      const toneOf = (q) => q.starred ? (q.star_tone || "priority") : "";
      const isSoon = (q) => toneOf(q) === "soon";
      const isPrio = (q) => toneOf(q) === "priority";
      const isLater = (q) => toneOf(q) === "later";

      function rowsFor(k) {
        let r = all.filter((q) =>
          k === "all" ? true
          : k === "answered" ? q.answered
          : k === "starred" ? q.starred && !q.answered
          : !q.answered);
        if (source) r = r.filter((q) => (q.paper ? q.paper.id : "") === source);
        return r;
      }

      async function save(q, body, msg) {
        await guard(async () => {
          const up = await api.patch(Q + "/" + q.id, body);
          Object.assign(q, up);
          if (msg) toast(msg);
          draw();
        });
      }
      function toggleStar(q, tone) {
        const off = q.starred && (q.star_tone || "priority") === tone;
        save(q, off ? { starred: false } : { starred: true, star_tone: tone });
      }

      function whereOf(q) {
        if (q.paper) return q.paper.title + (q.on && q.on.version ? " · v" + q.on.version : "");
        if (q.on && q.on.label === "Task") return "Inbox";
        if (q.on && q.on.title) return (q.on.label === "Project" ? "project: " : "") + q.on.title;
        if (q.on && q.on.label) return q.on.label.toLowerCase();
        return "asked here";
      }
      function fmtDate(iso) {
        if (!iso) return "—";
        const d = new Date(iso);
        if (isNaN(d)) return String(iso).slice(0, 10);
        return d.getDate() + " " + d.toLocaleDateString("en-GB", { month: "short" }).toLowerCase();
      }

      function rowFor(q) {
        const soon = isSoon(q), prio = isPrio(q);
        const star = el("button.ib-star" + (prio ? ".on" : ""), {
          text: prio ? "★" : "☆",
          title: prio ? "priority — click to unstar" : "priority (yellow star)",
          onclick: () => toggleStar(q, "priority"),
        });
        const star2 = el("button.ib-star.ib-star2" + (soon ? ".on.soon" : ""), {
          text: soon ? "★" : "☆",
          title: soon ? "possible priority — click to unstar" : "possible priority (teal star)",
          onclick: () => toggleStar(q, "soon"),
        });
        const later = isLater(q);
        const star3 = el("button.ib-star.ib-star3" + (later ? ".on.later" : ""), {
          text: later ? "★" : "☆",
          title: later ? "could be important in a later phase — click to unstar"
                       : "could be important in a later phase (grey star)",
          onclick: () => toggleStar(q, "later"),
        });
        const tick = el("input", { type: "checkbox", title: q.answered ? "reopen" : "mark answered" });
        tick.checked = !!q.answered;
        tick.addEventListener("change", () =>
          save(q, { answered: tick.checked }, tick.checked ? "answered" : "reopened"));

        const tr = el("tr.ib-row" + (q.answered ? ".ib-settled" : ""), { "data-nav": q.id }, [
          el("td", {}, [tick]),
          el("td.ib-starcell", {}, [star, star2, star3]),
          el("td", {}, [el("span", { text: q.text })]),
          el("td.ib-added", { text: whereOf(q) }),
          el("td.ib-added", { text: fmtDate(q.created_at) }),
          el("td.ib-notes", { style: "white-space:normal;color:var(--muted)",
            text: q.answer || (q.answered ? "(dissolved)" : "") }),
          el("td", { style: "white-space:nowrap" }, [
            el("button.btn-sm", { text: q.answer ? "edit answer" : "answer",
              onclick: () => { open.has(q.id) ? open.delete(q.id) : open.add(q.id); draw(); } }),
            " ",
            el("button.ib-del", { text: "×", title: "delete the question. Its Inbox row stays.",
              onclick: () => confirmDo("delete this question? Its Inbox row stays.", async () => {
                await api.del(Q + "/" + q.id);
                all = all.filter((x) => x.id !== q.id);
                draw();
              }) }),
          ]),
        ]);
        const out = [tr];
        if (open.has(q.id)) {
          const inp = el("input.ib-add", { style: "width:100%",
            placeholder: "what the answer turned out to be", value: q.answer || "" });
          const commit = () => { open.delete(q.id);
            save(q, { answer: inp.value.trim(), answered: true }, "answer saved"); };
          inp.addEventListener("keydown", (e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { open.delete(q.id); draw(); }
          });
          out.push(el("tr.ib-journal", {}, [el("td.ib-jcell", { colspan: String(COLS) }, [
            el("div.row", { style: "gap:6px;align-items:center" }, [
              inp,
              el("button.btn-sm.btn-primary", { text: "save answer", onclick: commit }),
              el("button.btn-sm", { text: "cancel", onclick: () => { open.delete(q.id); draw(); } }),
            ]),
          ])]));
          setTimeout(() => inp.focus(), 0);
        }
        return out;
      }

      function table(list, emptyText) {
        const t = el("table.ib-table", {}, [
          el("thead", {}, [el("tr", {}, ["", "", "question", "from", "asked", "answer", ""]
            .map((h) => el("th", { text: h })))]),
          el("tbody", {}, list.flatMap(rowFor)),
        ]);
        if (!list.length && emptyText)
          t.querySelector("tbody").appendChild(el("tr", {}, [
            el("td.ib-empty", { colspan: String(COLS), text: emptyText })]));
        return t;
      }

      function stats() {
        const live = all.filter((q) => !q.answered);
        const box = (v, l, c) => el("div.prog-box", {}, [
          el("div.prog-val", { style: "color:" + c, text: String(v) }),
          el("div.prog-label", { text: l }),
        ]);
        return el("div.prog-grid", {}, [
          box(live.length, "open", "var(--purple)"),
          box(all.length - live.length, "answered", "var(--teal)"),
          box(live.filter(isPrio).length, "priority", "var(--amber)"),
          box(live.filter(isSoon).length, "possible priority", "#5FE0D0"),
        ]);
      }

      function draw() {
        clear(host);
        host.appendChild(stats());

        // add box + chips, as in the Inbox
        const input = el("input.ib-add", { placeholder: "ask a question — it also lands in the Inbox" });
        input.addEventListener("keydown", (e) => {
          if (e.key !== "Enter" || !input.value.trim()) return;
          const text = input.value.trim();
          guard(async () => {
            const q = await api.post(Q, { text });
            all.unshift(q);
            toast("asked");
            draw();
          });
        });
        const chips = el("div.ib-chips", {}, ["open", "starred", "answered", "all"].map((k) =>
          el("button.ib-chip" + (k === show ? ".on" : ""), {
            onclick: () => { show = k; draw(); },
          }, [document.createTextNode(k), el("b", { text: String(rowsFor(k).length) })])));

        // Group by where the question came from.
        const sources = [], seen = new Set();
        all.forEach((q) => {
          const id = q.paper ? q.paper.id : "";
          if (seen.has(id)) return;
          seen.add(id);
          sources.push({ id, title: q.paper ? q.paper.title : "no source" });
        });
        const sel = sources.length > 1 ? el("select.ib-move", {
          onchange: (e) => { source = e.target.value; draw(); } }, [
          el("option", { value: "", text: "every source" }),
          ...sources.map((s) => el("option", { value: s.id, text: s.title })),
        ]) : null;
        if (sel) sel.value = source;

        host.appendChild(el("section.card.ib-card", {}, [
          el("div.ib-addrow", {}, [input]),
          el("div.ib-bar", {}, [chips, sel,
            el("span.ib-hint", { text: "every question is also a row in the Inbox. move one here with “question → Questions tab”." })]),
        ]));

        const shown = rowsFor(show);
        // Stars lift rows into their own tables, as in the Inbox — except
        // under answered, where the list is the record, not the work.
        const lift = show !== "answered";
        const prio = lift ? shown.filter(isPrio) : [];
        const soon = lift ? shown.filter(isSoon) : [];
        const laterQs = lift ? shown.filter(isLater) : [];
        const rest = lift ? shown.filter((q) => !q.starred) : shown;

        const card = (cls, heading, hint, list) => list.length
          ? host.appendChild(el("section.card.ib-card." + cls, {}, [
              el("div.ib-bar", {}, [el("h2", { text: heading + " · " + list.length }),
                                    el("span.ib-hint", { text: hint })]),
              table(list),
            ])) : null;
        card("ib-starred", "★ Priority", "yellow star — click it to put one back", prio);
        card("ib-soon", "★ Possible priority", "teal star — click it to put one back", soon);

        if (show !== "starred" || !shown.length) {
          host.appendChild(el("section.card.ib-card", {}, [
            table(rest, show === "open" ? (prio.length || soon.length
                ? "everything open is starred, above"
                : "no open questions — ask one above, or move an Inbox row here")
              : show === "starred" ? "nothing starred" : "nothing here yet"),
          ]));
        }
        card("ib-later", "★ Later phase", "grey star — could be important in a later phase", laterQs);
      }

      all = await api.get(Q).catch(() => []);
      draw();
    },
  };
})();

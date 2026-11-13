/* book-master.js — the book's master record.

   Generated and read-only, like the Master Instance it grew out of. Nothing
   here is authored: it assembles from the sessions, so a session deleted in the
   Workspace takes its part of the record with it.

   ONE COMPONENT, TWO MOUNTS. It renders the same on the book's Project page and
   under "open" in the Workspace, because it is the same record — the project
   and the book are two views of one pair, and a record that read differently
   depending on which door you came through would be two records.

   The only writable things on it are a chapter's done-tick and its estimate,
   which sessions cannot tell you: whether a chapter with no exercises counts as
   finished is a judgement, and what a chapter will take is a forecast. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const fmtH = (h) => (h >= 10 ? h.toFixed(0) : h.toFixed(1)) + "h";

  /* "pp.22 →" is not a typo. The end page was never written down, and the
     record says so rather than borrowing the next session's start page — a
     number nobody recorded has no business in a document meant to be shown. */
  function pagesText(s) {
    const lo = s.pages_from, hi = s.pages_to;
    if (lo == null && hi == null) return "";
    if (lo != null && hi == null) return "pp. " + lo + " →";
    if (lo == null) return "to p. " + hi;
    return "pp. " + lo + "–" + hi;
  }

  function chapterName(ch) {
    if (!ch) return "Chapter not recorded";
    return /^\d/.test(ch) ? "Chapter " + ch : ch.charAt(0).toUpperCase() + ch.slice(1);
  }

  function stat(v, label) {
    return el("div.bkm-stat", {}, [
      el("div.bkm-stat-v", { text: String(v) }),
      el("div.bkm-stat-l", { text: label }),
    ]);
  }

  function sessionBlock(s) {
    const head = [s.date, pagesText(s), s.mins ? window.WorkLog.fmtMins(s.mins) : ""]
      .filter(Boolean).join("  ·  ");
    const rows = [el("div.bkm-shead", {}, [
      s.mode ? el("span.bkm-mode", { "data-mode": s.mode, text: s.mode }) : null,
      el("span", { text: head }),
    ])];
    // The write-up arrives as + rows (one thought each), so it reads as a list
    // like the questions beside it rather than as a paragraph.
    const list = (label, items) => {
      if (!(items || []).length) return;
      rows.push(el("div.bkm-lbl", { text: label }));
      rows.push(el("ul.bkm-list", {}, items.map((q) => el("li", { text: q }))));
    };
    list("what I understood", s.understood);
    list("questions", s.questions);
    list("to look into later", s.look_into);
    list("notes", s.notes);
    // Inline, not a gallery: a screenshot of the thing you were stuck on reads
    // with the sentence about being stuck on it, not in a strip at the bottom.
    if ((s.images || []).length) {
      rows.push(el("div.bkm-imgs", {}, s.images.map((im) => el("figure.bkm-fig", {}, [
        el("img", { src: im.url, alt: im.name, loading: "lazy" }),
        el("figcaption", { text: im.name }),
      ]))));
    }
    if ((s.distractions || []).length) {
      rows.push(el("div.bkm-lbl", { text: "distractions" }));
      rows.push(el("ul.bkm-list", {}, s.distractions.map((d) => el("li", { text: d }))));
    }
    return el("div.bkm-sess", {}, rows);
  }

  function chapterBlock(m, ch, reload) {
    const head = el("div.bkm-chead", {}, [
      el("h3", { text: chapterName(ch.chapter) }),
      ch.done
        ? el("span.bkm-pill.done", {
            title: ch.done_by === "rule"
              ? "read and exercises both logged"
              : "ticked by hand" + (ch.done_at ? " on " + ch.done_at : ""),
            text: "done" + (ch.done_by === "hand" ? " · by hand" : "") })
        : el("span.bkm-pill.open", {
            title: [ch.has_read ? null : "no read session yet",
                    ch.has_exercises ? null : "no exercises session yet"]
              .filter(Boolean).join(" · ") || "open",
            text: "open" }),
    ]);

    const n = ch.sessions.length;
    const meta = el("div.bkm-cmeta", { text:
      fmtH(ch.hours) + " · " + n + " session" + (n === 1 ? "" : "s")
      + (ch.estimate_h ? " · estimate " + fmtH(ch.estimate_h) : "") });

    /* The two hand-set values. The tick only ever turns a chapter ON: one that
       already satisfies the rule cannot be un-ticked, because the sessions
       saying you did the work are still there and the record would be lying. */
    const controls = el("div.bkm-cctl", {});
    if (ch.chapter) {
      const tick = el("label.bkm-tick", {}, [
        el("input", {
          type: "checkbox", checked: ch.done_by === "hand" || undefined,
          disabled: ch.done_by === "rule" || undefined,
          onchange: (e) => guard(async () => {
            await api.patch("/api/books/" + m.book.id + "/chapters/"
                            + encodeURIComponent(ch.chapter), { done: e.target.checked });
            toast(e.target.checked ? "ticked done" : "untinked");
            reload();
          }),
        }),
        el("span", { title: ch.done_by === "rule"
          ? "already done by the rule — read and exercises are both logged"
          : "mark this chapter done without an exercises session",
          text: "done by hand" }),
      ]);
      const est = el("input.bkm-est", {
        type: "number", min: "0", step: "0.5", value: ch.estimate_h || "",
        placeholder: "h", title: "hours this chapter is expected to take — what the phase forecast reads",
        onchange: () => guard(async () => {
          await api.patch("/api/books/" + m.book.id + "/chapters/"
                          + encodeURIComponent(ch.chapter),
                          { estimate_h: Number(est.value) || 0 });
          toast("estimate saved");
          reload();
        }),
      });
      controls.appendChild(tick);
      controls.appendChild(el("label.bkm-estwrap", {}, [
        el("span", { text: "estimate" }), est, el("span", { text: "h" })]));
    }

    return el("div.bkm-ch", {}, [
      head, meta, controls,
      n ? el("div", {}, ch.sessions.map(sessionBlock))
        : el("div.sub", { style: "margin-top:6px", text: "No sessions logged in this chapter yet." }),
    ]);
  }

  /* `bookId` is the :Paper. Both mounts pass it — the Project page resolves it
     from the project's link first, because the project is the view, not the
     thing being recorded. */
  async function render(host, bookId, opts) {
    opts = opts || {};
    clear(host);
    host.appendChild(el("div.sub", { text: "building…" }));
    const m = await guard(() => api.get("/api/books/" + bookId + "/master"));
    if (!m) return;
    clear(host);
    const reload = () => render(host, bookId, opts);
    const t = m.totals;

    const share = el("button.btn-sm", {
      title: "one self-contained HTML file, dated — open it anywhere, or Ctrl+P it to PDF",
      onclick: () => { window.open("/api/books/" + bookId + "/share", "_blank", "noopener"); },
      text: "⤴ share",
    });
    const download = el("button.btn-sm", {
      title: "download the same file",
      onclick: () => { window.location.href = "/api/books/" + bookId + "/share.html"; },
      text: "↓ file",
    });

    /* `compact` is for a mount that already has a card header of its own — the
       Workspace one. Repeating the title inside it would print "Master record"
       twice, so only the buttons come through. */
    host.appendChild(opts.compact
      ? el("div.row", { style: "gap:6px;justify-content:flex-end" }, [share, download])
      : el("div.spread", {}, [
          el("div", {}, [
            el("h3", { style: "margin:0", text: opts.title || "Master record" }),
            el("div.sub", { text: "Auto-generated · read-only · every session, by chapter" }),
          ]),
          el("div.row", { style: "gap:6px" }, [share, download]),
        ]));

    const span = t.first_session
      ? t.first_session + " → " + t.last_session : "not started";
    host.appendChild(el("div.bkm-stats", {}, [
      stat(fmtH(t.hours), "total hours"),
      stat(t.sessions, "sessions"),
      stat(t.chapters_done + "/" + t.chapters_total, "chapters done"),
      stat(span, "first → last"),
    ]));

    if (!m.chapters.length) {
      host.appendChild(el("div.empty", {
        text: "Nothing logged yet. Sessions on this book build the record." }));
      return;
    }
    m.chapters.forEach((ch) => host.appendChild(chapterBlock(m, ch, reload)));
  }

  window.BookMaster = { render, mount: render };
})();

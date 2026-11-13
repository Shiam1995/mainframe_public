/* deepdive.js — topic-first deep dives: pick a topic, write info, list sources
   (a title+link table AND a free-text box). Reads /api/synapse/deepdive.
   Dives are module-scoped: the same card UI is registered once per module that
   carries a Deep Dive tab (Synapse "deepdive", Pulse "pulsedive"), each seeing
   only its own topics. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const BASE = "/api/synapse/deepdive"; // historical prefix; serves all modules

  function sourceRow(d, s, reload) {
    return el("tr", {}, [
      el("td", {}, [s.link ? el("a", { href: s.link, target: "_blank", rel: "noopener noreferrer", style: "color:var(--blue)", text: s.title }) : el("span", { text: s.title })]),
      el("td", { class: "mono", style: "font-size:11px;color:var(--dim)", text: s.link || "" }),
      el("td", {}, [el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.del(BASE + "/" + d.id + "/sources/" + s.id); reload(); }), text: "×" })]),
    ]);
  }

  function stop(e) { e.stopPropagation(); }

  // A dive's notes, as + rows joined for the collapsed preview.
  const infoText = (d) => (d.info_rows || []).join(" · ");

  function preview(text, n) {
    const t = (text || "").replace(/\s+/g, " ").trim();
    return t.length > n ? t.slice(0, n - 1) + "…" : t;
  }

  function makeDeepDive(viewId, module, subtitle, title) {
    // Which cards are expanded — kept across reloads so saving a field doesn't
    // collapse the card you're working in.
    const open = new Set();

    function diveCard(d, reload) {
      const isOpen = open.has(d.id);
      const card = el("div.dd-card" + (isOpen ? ".dd-open" : ""));
      const sources = d.sources || [];
      const extra = (d.sources_text || "").trim() ? 1 : 0;

      // --- collapsed face: press anywhere on it to expand ---
      const head = el("div.dd-head", {
        title: isOpen ? "collapse" : "expand",
        onclick: () => { isOpen ? open.delete(d.id) : open.add(d.id); reload(); },
      }, [
        el("div.dd-head-top", {}, [
          el("span.dd-caret", { text: isOpen ? "▾" : "▸" }),
          // when open the body carries the editable title, so don't repeat it here
          isOpen ? el("span.sub", { style: "font-size:11px", text: "press to collapse" })
            : el("span.dd-topic", { text: d.topic || "(untitled)" }),
        ]),
        el("div.dd-meta", {}, [
          el("span.pill", { text: sources.length + " source" + (sources.length === 1 ? "" : "s") }),
          extra ? el("span.pill", { text: "+ notes" }) : null,
          infoText(d) ? null : el("span.sub", { style: "font-size:10px", text: "empty" }),
          el("span.sub", { style: "font-size:10px;margin-left:auto", text: (d.updated_at || d.created_at || "").slice(0, 10) }),
        ]),
        !isOpen && infoText(d)
          ? el("div.dd-preview", { text: preview(infoText(d), 150) })
          : null,
      ]);
      card.appendChild(head);
      if (!isOpen) return card;

      // --- expanded body ---
      const body = el("div.dd-body", { onclick: stop });
      card.appendChild(body);

      // topic (editable) + delete
      const topic = el("input", { value: d.topic || "", style: "font-size:16px;font-weight:600;flex:1;min-width:180px;background:transparent;border:none;color:var(--text)" });
      topic.addEventListener("change", () => guard(async () => { await api.patch(BASE + "/" + d.id, { topic: topic.value }); toast("topic saved"); }));
      body.appendChild(el("div.spread", {}, [topic,
        // Log a learning entry straight off a dive — pre-filled with the topic,
        // so what you got wrong while studying something lands in the same
        // repeat-detection as everywhere else instead of being retyped.
        el("button.btn-sm", { title: "log a learning opportunity from this deep dive",
          onclick: () => window.LearningPush && window.LearningPush({
            kind: "", module: module,
            what: "while deep-diving “" + (d.topic || "untitled") + "”: ",
            detail: infoText(d).slice(0, 400),
          }), text: "↗ learning" }),
        el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete deep dive “" + d.topic + "”?", async () => { await api.del(BASE + "/" + d.id); open.delete(d.id); reload(); }), text: "delete" }),
      ]));
      // info
      // info: one note / finding per row, each saved on Enter.
      body.appendChild(window.RowBox({ label: "notes", kind: "note", noun: "note", parentId: d.id,
        placeholder: "what you're digging into — a note, a finding…" }).node);

      window.Images.mount(body, { module: module, contextId: d.id, surface: module + "-deepdive", title: "Images" });

      // sources table
      body.appendChild(el("div.sub", { style: "margin:14px 0 6px;text-transform:uppercase;letter-spacing:1px;font-size:10px", text: "Sources" }));
      const tbody = el("tbody");
      (d.sources || []).forEach((s) => tbody.appendChild(sourceRow(d, s, reload)));
      body.appendChild(el("table.dd-sources", {}, [
        el("thead", {}, [el("tr", {}, [el("th", { text: "title" }), el("th", { text: "link" }), el("th", { text: "" })])]),
        tbody,
      ]));
      const stitle = el("input", { placeholder: "source title", style: "flex:1;min-width:140px" });
      const slink = el("input", { placeholder: "link (optional)", style: "flex:1;min-width:120px" });
      body.appendChild(el("div.row", { style: "margin-top:8px" }, [stitle, slink,
        el("button.btn-sm", { onclick: () => guard(async () => {
          if (!stitle.value.trim()) return toast("source needs a title", true);
          await api.post(BASE + "/" + d.id + "/sources", { title: stitle.value.trim(), link: slink.value.trim() || null });
          stitle.value = slink.value = ""; reload();
        }), text: "+ row" }),
      ]));

      // free-text sources
      const stext = el("textarea.mform-input", { rows: "2", placeholder: "…or paste sources as free text", style: "width:100%;margin-top:10px" });
      stext.value = d.sources_text || "";
      stext.addEventListener("change", () => guard(async () => { await api.patch(BASE + "/" + d.id, { sources_text: stext.value }); toast("sources saved"); }));
      body.appendChild(stext);
      return card;
    }

    return {
      id: viewId, label: title, scoped: false,
      async render(view) {
        clear(view);
        view.appendChild(el("div.view-head", {}, [el("div", {}, [
          el("h1", { text: title }),
          el("div.sub", { text: subtitle }),
        ])]));

        const topicIn = el("input", { placeholder: "new deep-dive topic", style: "flex:1;min-width:200px" });
        view.appendChild(el("div.row", { style: "margin-bottom:16px" }, [topicIn,
          el("button.btn-primary", { onclick: () => guard(async () => {
            if (!topicIn.value.trim()) return toast("enter a topic", true);
            await api.post(BASE, { topic: topicIn.value.trim(), module: module });
            topicIn.value = ""; reload();
          }), text: "+ topic" }),
        ]));
        const bar = el("div.row", { style: "gap:6px;margin-bottom:10px" });
        view.appendChild(bar);
        const grid = el("div.dd-grid"); view.appendChild(grid);

        async function reload() {
          const dives = await guard(() => api.get(BASE + "?module=" + module));
          clear(grid); clear(bar);
          if (!dives.length) { grid.appendChild(el("div.empty", { text: "No deep dives yet. Add a topic above." })); return; }
          const allOpen = dives.every((d) => open.has(d.id));
          bar.appendChild(el("span.sub", { text: dives.length + " topic" + (dives.length === 1 ? "" : "s") + " · press a card to open it" }));
          bar.appendChild(el("button.btn-sm", {
            style: "margin-left:auto",
            onclick: () => {
              if (allOpen) open.clear();
              else dives.forEach((d) => open.add(d.id));
              reload();
            },
            text: allOpen ? "collapse all" : "expand all",
          }));
          dives.forEach((d) => grid.appendChild(diveCard(d, reload)));
        }
        reload();
      },
    };
  }

  window.Views = window.Views || {};
  // Synapse calls this a Project (user request, 2026-08-20); Pulse keeps the
  // original Deep Dive wording. Same card UI, same API, separate topics.
  window.Views.deepdive = makeDeepDive("deepdive", "synapse",
    "Pick a topic, write what you learn, and list your sources.", "Project");
  window.Views.pulsedive = makeDeepDive("pulsedive", "pulse",
    "Dig into a health, training or nutrition topic — notes and sources in one card.", "Deep Dive");
})();

/* diary.js — Mainframe · Diary. The day in your own words.

   Two ways to write, because some days work one way and some the other:

     MIND DUMP    — type the whole day into one box. "Sort it out" asks the
                    local model (or keyword rules, if it's offline) to cut the
                    text into segments and say which module each belongs to.
                    That comes back as a PROPOSAL: every segment shows an
                    editable module, and nothing is saved until you file it.
                    The split only ever cuts your words — it never rewrites
                    them — so filing can't replace what you wrote.

     BY SECTION   — you already know where it goes. Pick the module, write,
                    save. Same thing a module's own diary tab does.

   Either way the entry lands in one store with a `module` property, so the
   day view below and the module's own diary tab are two windows onto it. */
(function () {
  const { el, clear, toast, guard, todayISO } = window.ui;
  const api = window.api;

  const MODULE_META = {
    mainframe: { label: "Mainframe", accent: "#8892a6", hint: "the day itself, admin, mood" },
    synapse:   { label: "Synapse",   accent: "#00D4AA", hint: "research, reading, thesis" },
    pulse:     { label: "Pulse",     accent: "#DE7BA4", hint: "body, food, training, sleep" },
    vision:    { label: "Vision",    accent: "#FF4757", hint: "content, video, writing" },
    vault:     { label: "Vault",     accent: "#D4A017", hint: "money, spending, budget" },
  };
  const ORDER = ["mainframe", "synapse", "pulse", "vision", "vault"];
  const meta = (m) => MODULE_META[m] || MODULE_META.mainframe;

  const fmtDay = (d) => {
    const t = new Date(d + "T00:00:00");
    return isNaN(t) ? d : t.toLocaleDateString(undefined,
      { weekday: "long", day: "numeric", month: "long" });
  };

  function moduleSelect(value, onChange) {
    const sel = el("select.cellinput", { style: "font-size:11px" },
      ORDER.map((m) => el("option", { value: m, text: meta(m).label })));
    sel.value = value;
    const paint = () => { sel.style.color = meta(sel.value).accent; };
    paint();
    sel.addEventListener("change", () => { paint(); onChange(sel.value); });
    return sel;
  }

  /* ----------------------------------------------------------------- */
  /* Mind dump: write → propose → correct → file                        */
  /* ----------------------------------------------------------------- */
  function dumpMode(dateOf, afterFile) {
    const box = el("div.vault-card");
    const dump = el("textarea", { rows: "8",
      placeholder: "Dump the whole day. Don't worry about where any of it goes — "
                 + "write it how you'd say it, then press “sort it out”.",
      style: "width:100%" });
    const proposal = el("div", { style: "margin-top:12px" });

    /* The proposal is held here, not read back off the DOM, so a correction
       survives a re-render and "file" writes exactly what's on screen. */
    let segments = [];

    function renderProposal(routedBy) {
      clear(proposal);
      if (!segments.length) return;

      proposal.appendChild(el("div.spread", { style: "margin-bottom:8px" }, [
        el("span.sub", { text: segments.length + " piece" + (segments.length === 1 ? "" : "s")
                             + " · sorted by " + routedBy }),
        el("span.sub", { style: "font-size:11px;opacity:.7", text: "nothing saved yet — check the modules" }),
      ]));

      segments.forEach((seg, i) => {
        const ta = el("textarea.mform-input", { rows: "3", style: "width:100%" });
        ta.value = seg.text;
        ta.addEventListener("input", () => { seg.text = ta.value; });

        const sel = moduleSelect(seg.module, (m) => {
          seg.module = m;
          rowBox.style.borderLeft = "3px solid " + meta(m).accent;
        });

        /* A low-confidence guess is worth flagging rather than hiding: it's
           exactly the row you want to look at before filing. */
        const unsure = seg.confidence < 0.5
          ? el("span.pulse-chip", { style: "font-size:9px;opacity:.8", title: "low confidence — worth a look", text: "unsure" })
          : null;

        const rowBox = el("div.vault-card", { style: "border-left:3px solid " + meta(seg.module).accent + ";margin-bottom:8px" }, [
          el("div.spread", { style: "margin-bottom:6px;align-items:center" }, [
            el("div.row", { style: "gap:6px;align-items:center" }, [sel, unsure]),
            el("button.ord-btn", { title: "drop this piece", text: "×",
              onclick: () => { segments.splice(i, 1); renderProposal(routedBy); } }),
          ]),
          ta,
        ]);
        proposal.appendChild(rowBox);
      });

      proposal.appendChild(el("div.row", { style: "margin-top:6px" }, [
        el("button.btn-primary", {
          text: "file " + segments.length + " into the day",
          onclick: () => guard(async () => {
            const payload = segments
              .filter((s) => s.text.trim())
              .map((s) => ({ date: dateOf(), text: s.text.trim(), module: s.module,
                             section: s.section || "", source: "dump" }));
            if (!payload.length) return toast("nothing left to file", true);
            const res = await api.diary.commit(dateOf(), payload);
            toast("filed " + res.saved + " — each is now in its module's diary too");
            dump.value = ""; segments = []; clear(proposal);
            afterFile();
          }),
        }),
        el("button.btn-sm", { text: "start over", onclick: () => { segments = []; clear(proposal); } }),
      ]));
    }

    const sortBtn = el("button.btn-primary", { text: "sort it out →" });
    sortBtn.addEventListener("click", () => guard(async () => {
      if (!dump.value.trim()) return toast("write the day first", true);
      sortBtn.disabled = true; sortBtn.textContent = "sorting…";
      try {
        const res = await api.diary.split(dump.value);
        segments = res.segments || [];
        if (!segments.length) return toast("couldn't find anything to sort", true);
        renderProposal(res.routed_by || "rules");
      } finally {
        sortBtn.disabled = false; sortBtn.textContent = "sort it out →";
      }
    }));

    box.appendChild(dump);
    box.appendChild(el("div.spread", { style: "margin-top:8px;align-items:center" }, [
      el("span.sub", { style: "font-size:11px;opacity:.7",
        text: "your words are only ever cut, never rewritten" }),
      sortBtn,
    ]));
    box.appendChild(proposal);
    return box;
  }

  /* ----------------------------------------------------------------- */
  /* Section by section: you already know where it goes                 */
  /* ----------------------------------------------------------------- */
  function sectionMode(dateOf, afterSave) {
    let module = "mainframe";
    const hint = el("span.sub", { style: "font-size:11px;opacity:.7", text: meta(module).hint });
    const sel = moduleSelect(module, (m) => { module = m; hint.textContent = meta(m).hint; });
    const titleIn = el("input", { placeholder: "title (optional)", style: "flex:1;min-width:160px" });
    const textIn = el("textarea", { rows: "5", placeholder: "what happened…", style: "width:100%;margin-top:8px" });

    const save = () => guard(async () => {
      if (!textIn.value.trim()) return toast("write something first", true);
      await api.diary.create({ date: dateOf(), title: titleIn.value.trim(),
                               text: textIn.value.trim(), module, source: "section" });
      titleIn.value = ""; textIn.value = "";
      toast("saved to " + meta(module).label); afterSave();
    });

    return el("div.vault-card", {}, [
      el("div.row", { style: "gap:8px;align-items:center" }, [sel, hint]),
      el("div.row", { style: "margin-top:8px" }, [titleIn]),
      textIn,
      el("div.row", { style: "margin-top:8px;justify-content:flex-end" }, [
        el("button.btn-primary", { onclick: save, text: "+ entry" }),
      ]),
    ]);
  }

  /* ----------------------------------------------------------------- */
  window.Views = window.Views || {};
  window.Views.diary = {
    id: "diary", label: "Diary", scoped: false,
    async render(view) {
      clear(view);

      let day = todayISO();
      let mode = (() => {
        try { return localStorage.getItem("diary.mode") || "dump"; } catch { return "dump"; }
      })();

      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Diary" }),
        el("div.sub", { text: "The day in your own words — dumped in one go and sorted, "
                            + "or written section by section. Either way it lands in the module it belongs to." }),
      ])]));

      const dateIn = el("input", { type: "date", value: day });
      dateIn.addEventListener("change", () => { day = dateIn.value || todayISO(); redrawAll(); });
      view.appendChild(el("div.row", { style: "margin-bottom:12px;align-items:center;gap:8px" }, [
        dateIn, el("span.sub", { id: "diary-daylabel", text: fmtDay(day) }),
      ]));

      const bar = el("div.fit-subtabs");
      const writer = el("div", { style: "margin-bottom:18px" });
      const dayHost = el("div");

      function drawWriter() {
        clear(bar);
        [{ k: "dump", l: "Mind dump" }, { k: "section", l: "By section" }].forEach((t) => {
          bar.appendChild(el("button.fit-subtab" + (t.k === mode ? ".active" : ""), {
            text: t.l,
            onclick: () => {
              mode = t.k;
              try { localStorage.setItem("diary.mode", mode); } catch { /* private mode */ }
              drawWriter();
            },
          }));
        });
        clear(writer);
        const dateOf = () => day;
        writer.appendChild(mode === "dump" ? dumpMode(dateOf, drawDay) : sectionMode(dateOf, drawDay));
      }

      async function drawDay() {
        const data = await guard(() => api.diary.day(day));
        clear(dayHost);
        const label = document.getElementById("diary-daylabel");
        if (label) label.textContent = fmtDay(day);

        if (!data || !data.count) {
          dayHost.appendChild(el("div.empty", { text: "Nothing written for this day yet." }));
          return;
        }
        dayHost.appendChild(el("div.spread", { style: "margin-bottom:10px" }, [
          el("span.sub", { text: data.count + " entr" + (data.count === 1 ? "y" : "ies") }),
          el("span.sub", { text: data.words + " words" }),
        ]));

        ORDER.filter((m) => data.modules[m]).forEach((m) => {
          const es = data.modules[m];
          const box = el("div.vault-card", { style: "border-left:3px solid " + meta(m).accent + ";margin-bottom:10px" });
          box.appendChild(el("div.spread", { style: "margin-bottom:6px" }, [
            el("span.sub", { style: "color:" + meta(m).accent, text: meta(m).label.toUpperCase() + " · " + es.length }),
          ]));
          es.forEach((e) => {
            const ta = el("textarea.mform-input", { rows: String(Math.min(6, Math.max(2, Math.ceil((e.text || "").length / 70)))), style: "width:100%" });
            ta.value = e.text || "";
            ta.addEventListener("blur", () => guard(async () => {
              if ((ta.value || "") === (e.text || "")) return;
              await api.diary.update(e.id, { text: ta.value }); e.text = ta.value; toast("saved");
            }));
            box.appendChild(el("div", { style: "margin-bottom:8px" }, [
              el("div.spread", { style: "align-items:center;margin-bottom:3px" }, [
                el("div.row", { style: "gap:6px;align-items:center" }, [
                  e.title ? el("span.sub", { style: "font-weight:600", text: e.title }) : null,
                  /* Re-file from here: the module is a live control, not a
                     label. Sorting a dump wrong shouldn't cost you a retype. */
                  moduleSelect(e.module, (m) => guard(async () => {
                    await api.diary.update(e.id, { module: m });
                    toast("moved to " + meta(m).label); drawDay();
                  })),
                  e.source === "dump" ? el("span.pulse-chip", { style: "font-size:9px;opacity:.7", text: "from dump" }) : null,
                ]),
                el("button.ord-btn", { title: "delete", text: "×",
                  onclick: () => guard(async () => { await api.diary.del(e.id); drawDay(); }) }),
              ]),
              ta,
            ]));
          });
          dayHost.appendChild(box);
        });
      }

      /* The strip of days you've actually written on — a diary you can't
         navigate is a diary you only ever write into. */
      const strip = el("div.row", { style: "gap:5px;flex-wrap:wrap;margin:4px 0 16px" });
      async function drawStrip() {
        const days = await guard(() => api.diary.days(21));
        clear(strip);
        (days || []).forEach((d) => {
          const chip = el("button.btn-sm", {
            title: d.count + " entries · " + d.modules.map((m) => meta(m).label).join(", "),
            text: d.date.slice(5) + " · " + d.count,
            onclick: () => { day = d.date; dateIn.value = d.date; redrawAll(); },
          });
          chip.style.borderLeft = "3px solid " + meta(d.modules[0] || "mainframe").accent;
          if (d.date === day) chip.style.fontWeight = "700";
          strip.appendChild(chip);
        });
      }

      function redrawAll() { drawWriter(); drawDay(); drawStrip(); }

      view.appendChild(bar);
      view.appendChild(writer);
      view.appendChild(strip);
      view.appendChild(dayHost);
      redrawAll();
    },
  };
})();

/* section-diary.js — a module's own diary tab, built once and reused.

   There is no such thing as a "section diary" separate from the Mainframe one.
   A module's tab is the SAME :DiaryEntry store filtered to `module`, which is
   what makes "send it up to the top bar" free: an entry written here is already
   in the day view the moment it saves, because there is nothing to send.

   Use it from a module's view file:
       window.Views.findiary = window.makeSectionDiary({
         id: "findiary", label: "Diary", module: "vault",
         blurb: "Financial reflections, reviews and decisions.",
         tagHint: "monthly-review, investment-decision",
       });
*/
(function () {
  const { el, clear, toast, guard, confirmDo, todayISO } = window.ui;
  const api = window.api;

  const fmtDate = (d) => {
    if (!d) return "";
    const t = new Date(d + "T00:00:00");
    return isNaN(t) ? d : t.toLocaleDateString(undefined,
      { weekday: "short", day: "numeric", month: "short", year: "numeric" });
  };

  function card(d, reload, opts) {
    const titleIn = el("input.vlt-diary-title", { value: d.title || "", placeholder: "title (optional)" });
    titleIn.addEventListener("blur", () => guard(async () => {
      if ((titleIn.value || "") === (d.title || "")) return;
      await api.diary.update(d.id, { title: titleIn.value }); d.title = titleIn.value; toast("saved");
    }));

    const textIn = el("textarea.mform-input", { rows: "4" });
    textIn.value = d.text || "";
    textIn.addEventListener("blur", () => guard(async () => {
      if ((textIn.value || "") === (d.text || "")) return;
      await api.diary.update(d.id, { text: textIn.value }); d.text = textIn.value; toast("saved");
    }));

    const tagsIn = el("input", { value: (d.tags || []).join(", "),
      placeholder: "tags" + (opts.tagHint ? " — e.g. " + opts.tagHint : ""),
      style: "width:100%;font-size:11px" });
    tagsIn.addEventListener("blur", () => guard(async () => {
      const tags = tagsIn.value.split(",").map((x) => x.trim()).filter(Boolean);
      if (tags.join("|") === (d.tags || []).join("|")) return;
      await api.diary.update(d.id, { tags }); d.tags = tags; toast("saved");
    }));

    return el("div.vault-card", {}, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:6px" }, [
          el("span.sub", { text: fmtDate(d.date) }),
          /* Says how it got here. An entry you sorted out of a mind-dump reads
             differently from one you sat down and wrote, and the difference is
             worth keeping visible. */
          d.source === "dump"
            ? el("span.pulse-chip", { style: "font-size:9px;opacity:.7",
                title: "sorted here from a mind dump in the Mainframe diary", text: "from dump" })
            : null,
        ]),
        el("button.ord-btn", { title: "delete entry", text: "×",
          onclick: () => confirmDo("Delete this entry?", async () => {
            await api.diary.del(d.id); reload();
          }) }),
      ]),
      titleIn, textIn,
      el("div", { style: "margin-top:7px" }, [tagsIn]),
      (d.tags || []).length ? el("div.row", { style: "gap:4px;flex-wrap:wrap;margin-top:6px" },
        d.tags.map((t) => el("span.pulse-chip", { style: "font-size:10px", text: t }))) : null,
    ]);
  }

  window.makeSectionDiary = function (opts) {
    return {
      id: opts.id, label: opts.label || "Diary", scoped: false,
      async render(view) {
        clear(view);
        view.appendChild(el("div.view-head", {}, [el("div", {}, [
          el("h1", { text: opts.label || "Diary" }),
          el("div.sub", { text: opts.blurb || "" }),
        ])]));

        const dateIn = el("input", { type: "date", value: todayISO() });
        const titleIn = el("input", { placeholder: "title (optional)", style: "flex:1;min-width:170px" });
        const textIn = el("textarea", { rows: "3", placeholder: opts.placeholder || "what happened, what you decided, why…",
          style: "width:100%;margin-top:8px" });
        const add = () => guard(async () => {
          if (!textIn.value.trim()) return toast("write something first", true);
          await api.diary.create({
            date: dateIn.value, title: titleIn.value.trim(), text: textIn.value.trim(),
            module: opts.module, section: opts.id, source: "section",
          });
          titleIn.value = ""; textIn.value = "";
          toast("saved — also in the Mainframe diary"); reload();
        });
        view.appendChild(el("div.vault-card", { style: "margin-bottom:16px" }, [
          el("div.row", {}, [dateIn, titleIn]),
          textIn,
          el("div.spread", { style: "margin-top:8px;align-items:center" }, [
            el("span.sub", { style: "font-size:11px;opacity:.7",
              text: "↑ anything written here also shows in the Mainframe diary for that day" }),
            el("button.btn-primary", { onclick: add, text: "+ entry" }),
          ]),
        ]));

        const host = el("div"); view.appendChild(host);

        async function reload() {
          const entries = await guard(() => api.diary.list({ module: opts.module }));
          clear(host);
          if (!entries.length) {
            host.appendChild(el("div.empty", { text: opts.empty || "No entries yet." }));
            return;
          }
          entries.forEach((d) => host.appendChild(card(d, reload, opts)));
        }
        reload();
      },
    };
  };
})();

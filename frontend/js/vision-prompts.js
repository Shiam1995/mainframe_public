/* vision-prompts.js — Vision · YouTube § Prompt log (VISION_UPDATE_SPEC §3).

   Tracks which LLM you asked, what you asked, what came back, how this attempt
   differed from the others, and whether you approved or rejected it.

   MANUAL BY DESIGN — nothing here calls a model API. The user pastes the prompt
   and the response in. The spec is explicit about that, and it's also why the
   log is worth keeping: it's a record of your judgement, not of API traffic.

   An approved entry can be pushed into the script with one click. */
(function () {
  const { el, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;

  const STATUS = {
    draft:    { label: "draft",    color: "var(--dim)",   bg: "var(--raised)" },
    approved: { label: "approved", color: "var(--green)", bg: "var(--green-d)" },
    rejected: { label: "rejected", color: "var(--red)",   bg: "var(--red-d)" },
    edited:   { label: "edited",   color: "var(--amber)", bg: "var(--amber-d)" },
  };
  const open = new Set();     // expanded prompt entries, by id

  const dateFmt = (iso) => {
    if (!iso) return "";
    try { return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }); }
    catch { return String(iso).slice(0, 10); }
  };

  function addModal(v, reload) {
    const llm = el("input.mform-input", { placeholder: "e.g. Claude Opus, GPT-4o, Gemini" });
    const prompt = el("textarea.mform-input", { rows: "4", placeholder: "what you asked" });
    const response = el("textarea.mform-input", { rows: "6", placeholder: "what came back — paste it in" });
    const variation = el("input.mform-input", { placeholder: "how this differed — e.g. “asked for more humour”" });
    const status = el("select.mform-input", {}, Object.keys(STATUS).map((k) => el("option", { value: k, text: STATUS[k].label })));
    const notes = el("input.mform-input", { placeholder: "why you liked or didn't like this" });
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);

    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.appendChild(el("div.modal.vis-modal", {}, [
      el("div.modal-title", { text: "Log a prompt" }),
      el("div.mform-row", {}, [field("LLM", llm), field("Status", status)]),
      field("Prompt", prompt),
      field("Response", response),
      field("Variation", variation),
      field("Notes", notes),
      el("div.row", { style: "margin-top:16px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
          if (!llm.value.trim()) return toast("say which LLM this was", true);
          if (!prompt.value.trim()) return toast("paste the prompt", true);
          await V().addPrompt(v.id, {
            llm: llm.value.trim(), prompt: prompt.value.trim(), response: response.value,
            variation: variation.value.trim(), status: status.value, notes: notes.value.trim(),
          });
          close(); toast("prompt logged"); reload();
        }), text: "Save entry" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    llm.focus();
  }

  function entryCard(v, p, reload) {
    const st = STATUS[p.status] || STATUS.draft;
    const isOpen = open.has(p.id);
    const head = el("div.spread", { style: "cursor:pointer",
      onclick: () => { isOpen ? open.delete(p.id) : open.add(p.id); reload(); } }, [
      el("div.row", { style: "gap:8px;min-width:0" }, [
        el("span.vprompt-llm", { text: "🤖 " + p.llm }),
        el("span.vprompt-snip", { text: (p.prompt || "").slice(0, 74) }),
      ]),
      el("div.row", { style: "gap:6px;flex:0 0 auto" }, [
        el("span.vprompt-status", { style: "background:" + st.bg + ";color:" + st.color, text: st.label }),
        el("span.sub", { text: dateFmt(p.date) }),
        el("button.ord-btn", { text: isOpen ? "▾" : "▸" }),
      ]),
    ]);
    const card = el("div.vres-card", {}, [head]);
    if (!isOpen) return card;

    const body = el("div", { style: "margin-top:10px" });
    const block = (label, text) => {
      if (!text) return;
      body.appendChild(el("div.mform-label", { style: "margin-top:8px", text: label }));
      body.appendChild(el("div.vprompt-body", { text }));
    };
    block("Prompt", p.prompt);
    block("Response", p.response);
    if (p.variation) {
      body.appendChild(el("div.mform-label", { style: "margin-top:8px", text: "Variation" }));
      body.appendChild(el("div.sub", { text: p.variation }));
    }
    if (p.notes) {
      body.appendChild(el("div.mform-label", { style: "margin-top:8px", text: "Notes" }));
      body.appendChild(el("div.sub", { text: p.notes }));
    }

    const statusSel = el("select", {}, Object.keys(STATUS).map((k) => el("option", { value: k, text: STATUS[k].label })));
    statusSel.value = p.status || "draft";
    statusSel.addEventListener("change", () => guard(async () => {
      await V().updatePrompt(v.id, p.id, { status: statusSel.value }); reload();
    }));
    body.appendChild(el("div.row", { style: "gap:8px;margin-top:12px" }, [
      el("span.sub", { text: "status" }), statusSel,
      el("button.btn-sm", {
        disabled: !(p.response || "").trim(),
        title: (p.response || "").trim() ? "replace the script with this response" : "no response to use",
        onclick: () => confirmDo("Replace the script with this response?", async () => {
          await V().usePromptAsScript(v.id, p.id); toast("script updated"); reload();
        }), text: "→ use as script" }),
      el("button.btn-sm.btn-danger", { onclick: () => confirmDo("Delete this prompt entry?", async () => {
        await V().delPrompt(v.id, p.id); open.delete(p.id); reload();
      }), text: "delete" }),
    ]));
    card.appendChild(body);
    return card;
  }

  window.VID_SECTIONS = window.VID_SECTIONS || [];
  window.VID_SECTIONS.push({
    key: "prompts", label: "🤖 Prompt log", order: 30,
    render(host, v, reload) {
      host.appendChild(el("div.row", { style: "margin-bottom:10px" }, [
        el("button.btn-sm", { onclick: () => addModal(v, reload), text: "+ add prompt" }),
        el("span.sub", { text: "manual — paste what you asked and what came back" }),
      ]));
      if (!v.prompts.length) {
        host.appendChild(el("div.sub", { style: "font-style:italic", text: "No prompts logged yet." }));
        return;
      }
      v.prompts.forEach((p) => host.appendChild(entryCard(v, p, reload)));
    },
  });
})();

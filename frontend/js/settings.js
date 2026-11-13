/* settings.js — Settings: the moving parts of the Mainframe, in one place.

   Right now that means voice: the key you dictate with, the model that hears
   you, the model that thinks, and the voice that answers. Model choices are
   saved to ~/.mainframe/config/settings.yaml through /api/settings and applied
   to the running backend; the dictation preferences are this browser's, so they
   stay in localStorage and take effect the moment you change them.

   Everything offered here is already on this machine — Ollama's own tag list,
   the .onnx voices on disk, the whisper sizes faster-whisper can fetch. There is
   no cloud option to pick because there is no cloud in this app. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const MODES = [
    { id: "toggle", label: "press once to start, again to stop" },
    { id: "hold", label: "hold the key while you talk (push-to-talk)" },
  ];

  function card(title, sub, children) {
    return el("div.card.set-card", {}, [
      el("h3.set-title", { text: title }),
      sub ? el("div.sub", { text: sub }) : null,
      el("div.set-body", {}, children),
    ].filter(Boolean));
  }

  function field(label, control, note) {
    return el("div.field", {}, [
      el("label", { text: label }),
      control,
      note ? el("div.set-note", { text: note }) : null,
    ].filter(Boolean));
  }

  function select(options, value, onchange) {
    const s = el("select.set-select", { onchange: (e) => onchange(e.target.value) });
    options.forEach((o) => {
      s.appendChild(el("option", { value: o.id, text: o.label + (o.note ? " — " + o.note : "") }));
    });
    // A model chosen by hand in settings.yaml may not be in the list; show it
    // rather than silently snapping the dropdown to something else.
    if (value != null && !options.some((o) => o.id === value)) {
      s.appendChild(el("option", { value, text: value + " — set by hand" }));
    }
    s.value = value == null ? "" : value;
    return s;
  }

  function toggle(label, on, onchange) {
    const b = el("button.btn-sm" + (on ? ".opt-on" : ""), { text: (on ? "on" : "off") + " · " + label });
    b.addEventListener("click", () => {
      on = !on;
      b.className = "btn-sm" + (on ? " opt-on" : "");
      b.textContent = (on ? "on" : "off") + " · " + label;
      onchange(on);
    });
    return b;
  }

  window.Views = window.Views || {};
  window.Views.settings = {
    id: "settings", label: "Settings", scoped: false,

    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Settings" }),
        el("div.sub", { text: "Voice typing, and which local models hear, think and speak." }),
      ])]));

      const host = el("div.set-grid");
      viewEl.appendChild(host);

      const data = await guard(() => api.get("/api/settings"));
      const opts = data.options;
      const pending = {};                       // only what you actually changed is sent
      const change = (key) => (value) => { pending[key] = value; markDirty(); };

      let saveBtn = null;
      function markDirty() {
        if (!saveBtn) return;
        const n = Object.keys(pending).length;
        saveBtn.textContent = n ? `save ${n} change${n > 1 ? "s" : ""}` : "saved";
        saveBtn.classList.toggle("btn-primary", !!n);
        saveBtn.disabled = !n;
      }

      /* ------------------------------------------------------ voice typing */
      const vt = window.voiceType;
      const bindBtn = el("button.set-key", { text: vt ? vt.bindingLabel() : "F2" });
      bindBtn.addEventListener("click", () => {
        bindBtn.textContent = "press any key…";
        bindBtn.classList.add("listening");
        window.vtCapturing = true;              // stop voicetype.js acting on the keypress
        const grab = (e) => {
          e.preventDefault(); e.stopPropagation();
          // A modifier on its own isn't a shortcut, it's the start of one.
          if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
          const binding = { key: e.key, ctrl: e.ctrlKey, shift: e.shiftKey,
                            alt: e.altKey, meta: e.metaKey };
          window.removeEventListener("keydown", grab, true);
          window.vtCapturing = false;
          bindBtn.classList.remove("listening");
          vt.savePrefs({ binding });
          bindBtn.textContent = vt.bindingLabel();
          toast("dictation key is now " + vt.bindingLabel());
        };
        window.addEventListener("keydown", grab, true);
      });

      const testBox = el("textarea.set-test", {
        rows: 3, placeholder: "click in here and press the key above — the words land at the cursor",
      });

      host.appendChild(card("Voice typing", "Dictate into any box in the Mainframe. This browser's setting, applied immediately.", [
        field("dictation key", bindBtn,
              "Works in every text box in the app. Esc while listening throws the clip away."),
        field("how the key behaves",
              select(MODES, vt ? vt.prefs.mode : "toggle", (v) => vt.savePrefs({ mode: v }))),
        el("div.row", {}, [
          toggle("spacing", vt ? vt.prefs.spacing : true, (v) => vt.savePrefs({ spacing: v })),
          toggle("capital letter at the start", vt ? vt.prefs.capitalise : true, (v) => vt.savePrefs({ capitalise: v })),
        ]),
        el("div.set-note", { text: "Spacing puts a space between what's already there and what you said." }),
        field("try it", testBox),
      ]));

      /* ------------------------------------------------------- the ear */
      const ear = data.speech_in;
      const earState = el("div.set-state");
      function paintEar(extra) {
        clear(earState);
        const ok = !ear.error;
        earState.appendChild(el("span.set-dot" + (ear.loaded ? ".on" : ok ? ".idle" : ".bad")));
        earState.appendChild(el("span", {
          text: extra || (ear.error ? "not working: " + ear.error
                : ear.loaded ? "loaded and ready"
                : "not loaded yet — the first dictation will take a few seconds"),
        }));
      }
      paintEar();

      const warmBtn = el("button.btn-sm", { text: "load it now" });
      warmBtn.addEventListener("click", async () => {
        warmBtn.disabled = true;
        paintEar("loading…");
        try {
          const r = await api.post("/api/settings/speech-in/warm");
          ear.loaded = true; ear.error = null;
          paintEar(`ready — ${r.model} on ${r.device}, loaded in ${r.seconds}s`);
        } catch (err) {
          ear.error = err.message;
          paintEar("failed: " + err.message);
        }
        warmBtn.disabled = false;
      });

      host.appendChild(card("The ear — speech to text",
        "Whisper, running on this machine. A bigger model hears you better and costs more memory and time.", [
        field("model", select(opts.whisper_models.map((m) => ({
          id: m.id, label: m.label, note: `${m.size} · ${m.note}`,
        })), ear.model, change("whisper_model")),
              "Changing this downloads the model once (into ~/.cache), then it's local forever."),
        el("div.row", {}, [
          el("div.set-half", {}, [field("runs on", select(opts.devices, ear.device, change("whisper_device")))]),
          el("div.set-half", {}, [field("precision", select(opts.computes, ear.compute, change("whisper_compute")))]),
        ]),
        field("language", select(opts.languages, ear.language, change("whisper_language")),
              "Fixing the language is faster and more accurate than auto-detect."),
        el("div.row", {}, [warmBtn, earState]),
      ]));

      /* ----------------------------------------------------- the brain */
      const brainOpts = opts.ollama_models.map((m) => ({ id: m, label: m }));
      const nameInput = el("input", { value: data.assistant.name, style: "width:180px" });
      nameInput.addEventListener("input", () => change("assistant_name")(nameInput.value));

      host.appendChild(card("The brain — the assistant's model",
        "What the voice assistant (Ctrl+K) thinks with. Voice typing doesn't use this — dictation never goes near a language model.", [
        brainOpts.length
          ? field("model", select(brainOpts, data.brain.model, change("ollama_model")),
                  "Only models already pulled with `ollama pull` are listed.")
          : field("model", el("div.set-warn", {
              text: "Ollama isn't answering at " + data.brain.host + " — start it to change this.",
            })),
        field("what it's called", nameInput),
      ]));

      /* ----------------------------------------------------- the voice */
      const voices = opts.piper_voices;
      host.appendChild(card("The voice — spoken replies",
        "Piper, also local. Drop more .onnx voices in " + data.speech_out.folder + " and they appear here.", [
        voices.length
          ? field("voice", select(voices.map((v) => ({
              id: v.path, label: v.label, note: v.ok ? "" : "missing its .json — unusable",
            })), data.speech_out.voice, change("piper_voice")))
          : el("div.set-warn", { text: "No voices found in " + data.speech_out.folder + "." }),
      ]));

      /* --------------------------------------------------------- saving */
      saveBtn = el("button", { text: "saved", disabled: true });
      saveBtn.addEventListener("click", async () => {
        saveBtn.disabled = true;
        try {
          const out = await api.put("/api/settings", pending);
          Object.keys(pending).forEach((k) => delete pending[k]);
          markDirty();
          toast(out.notes.length ? out.notes.join(" · ") : "saved");
          this.render(viewEl);                  // redraw from what the backend now says
        } catch (err) {
          toast(err.message, true);
          saveBtn.disabled = false;
        }
      });

      const footer = el("div.set-footer", {}, [
        saveBtn,
        el("span.set-note", { text: "written to " + data.config_file }),
      ]);
      if (data.env_locked.length) {
        footer.appendChild(el("div.set-warn", {
          text: "Set in the environment, which wins over this file — changing "
                + data.env_locked.join(", ") + " here will not survive a restart.",
        }));
      }
      viewEl.appendChild(footer);
      markDirty();
    },
  };
})();

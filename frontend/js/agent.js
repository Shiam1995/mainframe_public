/* agent.js — the voice assistant, reachable from every view.

   It is mounted on <body>, not inside a view, which is what "works with every
   element" actually requires: whichever module you're in, the same assistant is
   one key away and can act on anything.

     Ctrl+K  (or the ◉ button)  open
     Space   hold to talk, release to send   — when the input isn't focused
     Enter   send typed text
     Esc     close

   The safety model, chosen by the user: **reads run, writes need a yes.**
   The backend never executes a write from /ask — it returns a described,
   pending action, and this panel is where a human approves it. A misheard
   command therefore cannot change anything on its own.

   Everything is local: whisper on the GPU for hearing, Ollama for thinking,
   piper for speaking. The browser's own speech API is deliberately unused —
   it uploads your microphone audio to Google. */
(function () {
  const { el, clear, toast } = window.ui;

  let panel = null, log = [], busy = false, status = null;
  let recorder = null, chunks = [], recording = false;
  let speakBack = localStorage.getItem("mf.agent.speak") === "1";
  // Filled from /status: the assistant's face and name, both configurable by
  // dropping a picture in ~/mAInframe/AI_assistant/. Nothing here hardcodes it.
  let avatar = { launch: "", chip: "" }, agentName = "Assistant";
  let playing = null;                 // the <audio> currently speaking, if any

  /* The assistant's face, drawn as a round chip. Falls back to a glyph if no picture has
     been dropped in yet, so the assistant is never invisible. */
  function face(size) {
    if (avatar[size]) {
      return el("img.ag-face." + size, { src: avatar[size], alt: agentName, title: agentName });
    }
    return el("span.ag-face.glyph." + size, { text: "◉", title: agentName });
  }

  /* ------------------------------------------------------------------ api */
  const post = async (path, body) => {
    const r = await fetch("/api/agent" + path, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error((await r.text()).slice(0, 200));
    return r.json();
  };

  /* --------------------------------------------------------------- speech */
  async function startRecording() {
    if (recording) return;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      // Denied, or no device. Typing still works, so say so and carry on.
      return toast("microphone unavailable — you can still type", true);
    }
    chunks = [];
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (blob.size < 1200) return draw();          // a tap, not speech
      setBusy("listening…");
      try {
        const fd = new FormData();
        fd.append("audio", blob, "clip.webm");
        const r = await fetch("/api/agent/listen", { method: "POST", body: fd });
        if (!r.ok) throw new Error((await r.text()).slice(0, 160));
        const { text } = await r.json();
        if (!text) { setBusy(null); return toast("didn't catch that"); }
        // The transcript is shown before it acts, so a mis-hear is visible.
        await send(text, true);
      } catch (err) {
        setBusy(null);
        toast("couldn't transcribe: " + err.message, true);
      }
    };
    recorder.start();
    recording = true;
    draw();
  }

  function stopRecording() {
    if (!recording) return;
    recording = false;
    try { recorder.stop(); } catch (_e) { /* already stopped */ }
    draw();
  }

  /* Speak a line aloud through piper. `force` is the speaker button being
     pressed, which must work whether or not auto-speak is switched on. */
  async function say(text, force) {
    if ((!speakBack && !force) || !text) return;
    // Only one voice at a time — pressing a second speaker cuts the first off
    // rather than talking over itself.
    if (playing) { try { playing.pause(); } catch (_e) {} playing = null; }
    try {
      const r = await fetch("/api/agent/speak", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!r.ok) {
        if (force) toast("can't speak: " + (await r.text()).slice(0, 90), true);
        return;
      }
      const clip = new Audio(URL.createObjectURL(await r.blob()));
      playing = clip;
      clip.onended = () => { if (playing === clip) playing = null; draw(); };
      // Autoplay can be blocked until the page has been interacted with; a
      // pressed button IS an interaction, so `force` should always get through.
      clip.play().catch(() => { if (force) toast("browser blocked audio playback", true); });
      draw();
    } catch (err) {
      if (force) toast("couldn't speak that", true);
    }
  }

  /* ------------------------------------------------------------ the turn */
  function setBusy(label) { busy = label; draw(); }

  async function send(text, heard) {
    if (!text.trim()) return;
    log.push({ role: "you", text: text.trim(), heard: !!heard });
    setBusy("thinking…");
    try {
      const out = await post("/ask", { text: text.trim() });
      log.push({ role: "agent", text: out.reply, pending: out.pending || [],
                 read: out.read || [] });
      say(out.reply);
    } catch (err) {
      log.push({ role: "error", text: err.message });
    }
    setBusy(null);
  }

  async function confirm(entry) {
    setBusy("doing it…");
    try {
      const out = await post("/confirm", { actions: entry.pending });
      entry.pending = [];
      entry.done = out.results;
      const failed = out.results.filter((r) => !r.ok);
      toast(failed.length ? `${failed.length} failed` : out.summary);
      // Whatever view is open is now stale — the agent just changed its data.
      if (window.Views && window.refreshActive) window.refreshActive();
    } catch (err) {
      log.push({ role: "error", text: err.message });
    }
    setBusy(null);
  }

  /* ------------------------------------------------------------- painting */
  function draw() {
    if (!panel) return;
    const body = panel.querySelector(".ag-body");
    clear(body);

    if (!log.length) {
      body.appendChild(el("div.ag-hint", {}, [
        el("div", { text: "Ask about anything, or tell me to do something." }),
        el("div.ag-egs", {}, [
          "what have I got on today?",
          "what's due this week?",
          "log 40 minutes on the report",
          "book two hours tomorrow morning for the website",
          "how many calories have I had?",
          "remind me to email the dentist — put it in the mind dump",
        ].map((s) => el("button.ag-eg", { text: s, onclick: () => send(s) }))),
      ]));
    }

    log.forEach((entry) => {
      if (entry.role === "you") {
        body.appendChild(el("div.ag-you", {}, [
          entry.heard ? el("span.ag-heard", { title: "heard by whisper", text: "🎤 " }) : null,
          el("span", { text: entry.text }),
        ].filter(Boolean)));
        return;
      }
      if (entry.role === "error") {
        body.appendChild(el("div.ag-err", { text: entry.text }));
        return;
      }
      const card = el("div.ag-agent", {}, [
        el("div.row", { style: "gap:6px;align-items:flex-start" }, [
          el("div", { style: "flex:1;min-width:0", text: entry.text }),
          // Press to hear this reply. Works whether or not auto-speak is on —
          // that's the point of it being a button rather than a setting.
          el("button.ag-say", {
            title: "hear this", text: playing ? "🔈" : "🔊",
            onclick: () => say(entry.text, true),
          }),
        ]),
      ]);
      // What it read, so an answer is never unattributable.
      if (entry.read && entry.read.length) {
        card.appendChild(el("div.ag-read", {
          text: "checked: " + entry.read.map((r) => r.tool).join(", ") }));
      }
      (entry.pending || []).forEach((p) => {
        card.appendChild(el("div.ag-pending", {}, [
          el("div.ag-pending-t", { text: p.describe }),
          el("div.row", { style: "gap:6px;margin-top:6px" }, [
            el("button.btn-sm.btn-primary", { text: "confirm",
              onclick: () => confirm(entry) }),
            el("button.btn-sm", { text: "cancel", onclick: () => {
              entry.pending = entry.pending.filter((x) => x !== p); draw(); } }),
          ]),
        ]));
      });
      (entry.done || []).forEach((r) => {
        card.appendChild(el("div.ag-done" + (r.ok ? "" : ".bad"), {
          text: (r.ok ? "✓ " : "✕ ") + (r.describe || r.tool || "")
              + (r.ok ? "" : " — " + (r.error || JSON.stringify(r.result))) }));
      });
      // The assistant's face sits beside what it says, so a reply is never anonymous.
      body.appendChild(el("div.ag-turn", {}, [face("chip"), card]));
    });

    const foot = panel.querySelector(".ag-status");
    foot.textContent = busy || (recording ? "● recording — release to send" : "");
    foot.className = "ag-status" + (recording ? " rec" : "");
    const mic = panel.querySelector(".ag-mic");
    if (mic) mic.classList.toggle("on", recording);
    body.scrollTop = body.scrollHeight;
  }

  /* ---------------------------------------------------------------- panel */
  function open() {
    if (panel) { panel.querySelector(".ag-input").focus(); return; }
    panel = el("div.ag-panel");

    const input = el("input.ag-input.mform-input", {
      placeholder: "ask, or hold space to talk…" });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { const v = input.value; input.value = ""; send(v); }
      if (e.key === "Escape") close();
    });

    const mic = el("button.ag-mic", { title: "hold to talk", text: "🎤" });
    // Hold-to-talk: press and hold, release to send. Mouse and touch both.
    mic.addEventListener("mousedown", startRecording);
    mic.addEventListener("mouseup", stopRecording);
    mic.addEventListener("mouseleave", () => recording && stopRecording());
    mic.addEventListener("touchstart", (e) => { e.preventDefault(); startRecording(); });
    mic.addEventListener("touchend", (e) => { e.preventDefault(); stopRecording(); });

    const speakToggle = el("button.btn-sm" + (speakBack ? ".btn-primary" : ""), {
      title: "speak replies aloud", text: "🔊",
      onclick: () => {
        speakBack = !speakBack;
        localStorage.setItem("mf.agent.speak", speakBack ? "1" : "0");
        speakToggle.className = "btn-sm" + (speakBack ? " btn-primary" : "");
      } });

    panel.appendChild(el("div.ag-head", {}, [
      face("chip"),
      el("span", { text: agentName }),
      el("span.ag-sub", { text: status
        ? `${status.brain.model} · ${status.capabilities.length} things it can do`
        : "local · nothing leaves this machine" }),
      el("div.row", { style: "gap:6px;margin-left:auto" }, [
        speakToggle,
        el("button.btn-sm", { text: "✕", onclick: close }),
      ]),
    ]));
    panel.appendChild(el("div.ag-body"));
    panel.appendChild(el("div.ag-status"));
    panel.appendChild(el("div.ag-foot", {}, [input, mic]));
    document.body.appendChild(panel);
    input.focus();
    draw();

    if (!status) loadStatus().then(draw);
  }

  /* Fetched once. Carries the assistant's name and face as well as what it can
     do, so renaming it or changing its picture needs no frontend change. */
  async function loadStatus() {
    try {
      const s = await (await fetch("/api/agent/status")).json();
      status = s;
      agentName = s.name || "Assistant";
      if (s.avatar && s.avatar.ok && s.avatar.sizes) avatar = s.avatar.sizes;
      paintLauncher();
      if (panel) {
        const sub = panel.querySelector(".ag-sub");
        if (sub) sub.textContent = `${s.brain.model} · ${s.capabilities.length} things it can do`;
        const nameEl = panel.querySelector(".ag-head > span:not(.ag-sub)");
        if (nameEl) nameEl.textContent = agentName;
        const oldFace = panel.querySelector(".ag-head .ag-face");
        if (oldFace) oldFace.replaceWith(face("chip"));
        if (!s.speech_in.ok) toast("speech recognition unavailable — typing still works", true);
      }
    } catch (_e) { /* the assistant still works without its portrait */ }
    return status;
  }

  function close() {
    if (recording) stopRecording();
    if (panel) panel.remove();
    panel = null;
  }

  /* ------------------------------------------------------------- bindings */
  const typing = (t) => t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA"
                              || t.tagName === "SELECT" || t.isContentEditable);

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      panel ? close() : open();
      return;
    }
    if (e.key === "Escape" && panel) return close();
    // Hold space to talk — but only when the panel is open and you aren't
    // typing, or space would stop working as a space.
    if (e.code === "Space" && panel && !typing(e.target) && !e.repeat) {
      e.preventDefault();
      startRecording();
    }
  });
  document.addEventListener("keyup", (e) => {
    if (e.code === "Space" && panel && !typing(e.target)) {
      e.preventDefault();
      stopRecording();
    }
  });

  /* The launcher IS the assistant's face — pressing it is what brings it up.
     Repainted once its picture has loaded. */
  function paintLauncher() {
    const btn = document.getElementById("ag-launch");
    if (!btn) return;
    clear(btn);
    btn.title = `${agentName}  (Ctrl+K)`;
    btn.appendChild(face("launch"));
  }

  // Always visible, so it's discoverable without knowing the shortcut.
  window.addEventListener("DOMContentLoaded", () => {
    // NOTE: `ui.el()` splits its spec on "." only — it has no `#id` syntax.
    // "button#ag-launch.ag-launch" therefore built an element whose tag name was
    // literally BUTTON#AG-LAUNCH: not a real <button>, and with no id, so
    // paintLauncher() could never find it again. The id goes in the attributes.
    document.body.appendChild(el("button.ag-launch", {
      id: "ag-launch",
      title: "Assistant  (Ctrl+K)", onclick: () => (panel ? close() : open()),
    }, [face("launch")]));
    // Fetch the face up front so the launcher shows the face before it's clicked.
    loadStatus();
  });

  // `name` comes from config, so anything referring to the assistant in the UI
  // reads it from here rather than hardcoding one.
  window.Agent = { open, close, ask: send, name: () => agentName };
})();

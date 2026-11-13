/* voicetype.js — dictation into whatever you were typing in.

   Separate from the assistant (agent.js) on purpose. The assistant *listens to
   act*: it hears you, decides, and proposes changes. This only listens to
   *type* — the words go into the box the cursor is in and nothing else happens.
   Different intent, different key, no chance of a stray sentence being read as
   a command.

     F2 (rebindable)   start / stop dictating into the focused field
     Esc               throw the clip away without inserting
     the ◉ mic button  same thing, for the field you were last in

   Same rule as everywhere else here: the audio goes to this machine's own
   whisper via /api/agent/listen and nowhere near a browser speech API, which
   would upload your microphone to Google. */
(function () {
  const { el, toast } = window.ui;

  const DEFAULTS = {
    binding: { key: "F2", ctrl: false, shift: false, alt: false, meta: false },
    mode: "toggle",        // "toggle" = press to start, press to stop; "hold" = push-to-talk
    spacing: true,         // add the space between what's there and what you said
    capitalise: true,      // capital letter when you're starting the field
  };

  function loadPrefs() {
    const p = Object.assign({}, DEFAULTS);
    try {
      const raw = JSON.parse(localStorage.getItem("mf.voicetype") || "{}");
      Object.assign(p, raw);
      p.binding = Object.assign({}, DEFAULTS.binding, raw.binding || {});
    } catch (_e) { /* corrupt or absent — the defaults are fine */ }
    return p;
  }
  let prefs = loadPrefs();

  function savePrefs(next) {
    prefs = Object.assign(prefs, next);
    try { localStorage.setItem("mf.voicetype", JSON.stringify(prefs)); } catch (_e) {}
    paintMic();
  }

  /* Human-readable binding, for the button's tooltip and the settings screen. */
  function bindingLabel(b) {
    b = b || prefs.binding;
    const parts = [];
    if (b.ctrl) parts.push("Ctrl");
    if (b.alt) parts.push("Alt");
    if (b.shift) parts.push("Shift");
    if (b.meta) parts.push("Meta");
    parts.push(b.key.length === 1 ? b.key.toUpperCase() : b.key);
    return parts.join("+");
  }

  /* ------------------------------------------------------------- the target */
  // The field to type into. Tracked on focus rather than read at trigger time,
  // because pressing the mic button would otherwise blur the very field you
  // meant to dictate into.
  let lastField = null;

  function isTypable(node) {
    if (!node || node.disabled || node.readOnly) return false;
    if (node.isContentEditable) return true;
    const tag = node.tagName;
    if (tag === "TEXTAREA") return true;
    if (tag !== "INPUT") return false;
    return /^(text|search|email|url|tel|password|number|)$/i.test(node.type || "text");
  }

  document.addEventListener("focusin", (e) => {
    if (isTypable(e.target)) lastField = e.target;
  }, true);

  function target() {
    const active = document.activeElement;
    if (isTypable(active)) return active;
    // still in the document? then it's the one you were in a moment ago
    if (lastField && lastField.isConnected) return lastField;
    return null;
  }

  /* ------------------------------------------------------------- inserting */
  function insert(field, text) {
    if (!text) return;
    field.focus();

    if (field.isContentEditable) {
      // execCommand is deprecated but it is the one insertion that lands in the
      // browser's own undo stack — Ctrl+Z after a mis-hear has to work.
      const ok = document.execCommand("insertText", false, text);
      if (!ok) field.textContent += text;
      field.dispatchEvent(new Event("input", { bubbles: true }));
      return;
    }

    // number/email inputs throw on selectionStart; fall back to appending.
    let start, end;
    try { start = field.selectionStart; end = field.selectionEnd; } catch (_e) { start = end = null; }
    const value = field.value || "";
    if (start == null) { start = end = value.length; }

    const before = value.slice(0, start);
    const after = value.slice(end);

    let piece = text;
    if (prefs.spacing) {
      if (before && !/[\s([{"'‘“\-]$/.test(before)) piece = " " + piece;
      if (after && !/^[\s.,;:!?)\]}]/.test(after)) piece = piece + " ";
    }
    if (prefs.capitalise && !before.trim()) {
      piece = piece.replace(/^(\s*)([a-z])/, (_m, ws, c) => ws + c.toUpperCase());
    }

    field.value = before + piece + after;
    const caret = start + piece.length;
    try { field.setSelectionRange(caret, caret); } catch (_e) {}
    // Views listen for these; a value set from script fires neither on its own,
    // and a form that never hears "input" is a form that never saves.
    field.dispatchEvent(new Event("input", { bubbles: true }));
    field.dispatchEvent(new Event("change", { bubbles: true }));
  }

  /* ------------------------------------------------------------- recording */
  let recorder = null, stream = null, chunks = [], recording = false, cancelled = false;
  let field = null, pill = null, timer = null, startedAt = 0;
  let audioCtx = null, analyser = null, levelRaf = 0;

  function pillUI() {
    const level = el("div.vt-level", {}, [el("i")]);
    const box = el("div.vt-pill", {}, [
      el("span.vt-dot"),
      el("span.vt-label", { text: "listening…" }),
      level,
      el("span.vt-time", { text: "0.0s" }),
      el("button.vt-stop", { onclick: () => stop(), text: prefs.mode === "hold" ? "release" : "stop" }),
      el("span.vt-esc", { text: "esc to cancel" }),
    ]);
    document.body.appendChild(box);
    return box;
  }

  /* A level bar, because the single most common failure is a microphone that
     is muted or pointed at the wrong device — and silence looks exactly like
     a working mic until the transcript comes back empty. */
  function meter(src) {
    try {
      audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      audioCtx.createMediaStreamSource(src).connect(analyser);
      const buf = new Uint8Array(analyser.frequencyBinCount);
      const bar = pill && pill.querySelector(".vt-level i");
      const tick = () => {
        if (!recording || !bar) return;
        analyser.getByteTimeDomainData(buf);
        let peak = 0;
        for (let i = 0; i < buf.length; i++) peak = Math.max(peak, Math.abs(buf[i] - 128));
        bar.style.width = Math.min(100, (peak / 60) * 100) + "%";
        levelRaf = requestAnimationFrame(tick);
      };
      tick();
    } catch (_e) { /* no meter is survivable; the transcript still works */ }
  }

  function teardownMeter() {
    cancelAnimationFrame(levelRaf);
    if (audioCtx) { try { audioCtx.close(); } catch (_e) {} }
    audioCtx = analyser = null;
  }

  async function start(explicitField) {
    if (recording) return;
    field = explicitField || target();
    if (!field) return toast("click into a box first, then press " + bindingLabel(), true);

    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (_err) {
      return toast("no microphone — check the browser's permission for this page", true);
    }

    chunks = []; cancelled = false;
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
    recorder.onstop = finish;
    recorder.start();
    recording = true;
    startedAt = Date.now();

    field.classList.add("vt-target");
    pill = pillUI();
    meter(stream);
    timer = setInterval(() => {
      const t = pill && pill.querySelector(".vt-time");
      if (t) t.textContent = ((Date.now() - startedAt) / 1000).toFixed(1) + "s";
    }, 100);
    paintMic();
  }

  function stop() {
    if (!recording) return;
    recording = false;
    clearInterval(timer);
    teardownMeter();
    try { recorder.stop(); } catch (_e) { /* already stopped */ }
    paintMic();
  }

  function cancel() {
    if (!recording) return;
    cancelled = true;
    stop();
    toast("dictation cancelled");
  }

  async function finish() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (field) field.classList.remove("vt-target");

    const blob = new Blob(chunks, { type: (recorder && recorder.mimeType) || "audio/webm" });
    if (cancelled) return done();
    if (blob.size < 1200) { done(); return toast("too short — hold on a moment longer"); }

    setPill("transcribing…", true);
    try {
      const fd = new FormData();
      fd.append("audio", blob, "dictation.webm");
      fd.append("mode", "dictate");     // punctuated prose, not a bare command
      const r = await fetch("/api/agent/listen", { method: "POST", body: fd });
      if (!r.ok) throw new Error((await r.text()).slice(0, 200));
      const { text } = await r.json();
      if (!text) { done(); return toast("didn't catch anything"); }
      if (field && field.isConnected) {
        insert(field, text);
        done();
      } else {
        // The view was re-rendered while whisper was thinking. Don't lose the
        // words — put them somewhere the user can get at them.
        done();
        try { await navigator.clipboard.writeText(text); toast("that box is gone — copied to the clipboard instead"); }
        catch (_e) { toast("that box is gone — heard: " + text.slice(0, 80), true); }
      }
    } catch (err) {
      done();
      toast("couldn't transcribe: " + err.message, true);
    }
  }

  function setPill(label, spin) {
    if (!pill) return;
    const l = pill.querySelector(".vt-label");
    if (l) l.textContent = label;
    pill.classList.toggle("thinking", !!spin);
  }

  function done() {
    if (pill) { pill.remove(); pill = null; }
    field = null;
    paintMic();
  }

  /* ------------------------------------------------------------------ keys */
  function matches(e, b) {
    if (!b || !b.key) return false;
    const key = (e.key || "").toLowerCase();
    return key === String(b.key).toLowerCase()
      && e.ctrlKey === !!b.ctrl && e.shiftKey === !!b.shift
      && e.altKey === !!b.alt && e.metaKey === !!b.meta;
  }

  window.addEventListener("keydown", (e) => {
    if (window.vtCapturing) return;          // the settings screen is rebinding the key
    if (e.key === "Escape" && recording) { e.preventDefault(); return cancel(); }
    if (!matches(e, prefs.binding)) return;
    if (e.repeat) { e.preventDefault(); return; }   // holding the key isn't ten presses
    e.preventDefault();
    if (prefs.mode === "hold") start();
    else if (recording) stop();
    else start();
  }, true);

  window.addEventListener("keyup", (e) => {
    if (prefs.mode !== "hold" || !recording) return;
    if ((e.key || "").toLowerCase() !== String(prefs.binding.key).toLowerCase()) return;
    e.preventDefault();
    stop();
  }, true);

  /* ------------------------------------------------------------ the button */
  function paintMic() {
    const btn = document.getElementById("vt-mic");
    if (!btn) return;
    btn.classList.toggle("on", recording);
    btn.title = recording
      ? "listening — click to stop (esc cancels)"
      : "dictate into the box you're typing in  ·  " + bindingLabel();
  }

  function wireMic() {
    const btn = document.getElementById("vt-mic");
    if (!btn) return;
    // mousedown default = blur the field you're dictating into. Not here.
    btn.addEventListener("mousedown", (e) => e.preventDefault());
    btn.addEventListener("click", () => (recording ? stop() : start()));
    paintMic();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wireMic);
  else wireMic();

  window.voiceType = {
    start, stop, cancel,
    get recording() { return recording; },
    get prefs() { return prefs; },
    savePrefs, bindingLabel, defaults: DEFAULTS,
  };
})();

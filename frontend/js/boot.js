/* boot.js — CRT boot screen (UPDATE_SPEC #9).
   Phosphor-green system text + Gojo ice-blue accents. Sequence:
   logo fade-in → system checks scroll → loading bar → [ENTER] pulse.
   Click anywhere / press Enter to drop into the dashboard.  The #boot element
   already covers the app from first paint (see index.html + .boot in main.css),
   so the dashboard never flashes underneath. */
(function () {
  const boot = document.getElementById("boot");
  if (!boot) return;
  const api = window.api;

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Fallback config if the API is unreachable — the boot screen still runs.
  const FALLBACK = {
    app: "Mainframe",
    checks: [
      { label: "neo4j graph store", path: "bolt://localhost:7687", ok: false },
      { label: "local llm", path: "ollama", ok: false },
      { label: "synapse module", path: "~/.mainframe/synapse", ok: true },
    ],
    wallpaper: null, sound: null, prefs: { skip: false, mute: false },
  };

  let dismissed = false;
  let audio = null;

  function buildScaffold() {
    boot.innerHTML =
      '<div class="crt-overlay"></div>' +
      '<div class="boot-inner">' +
      '  <div class="boot-logo">MAINFRAME</div>' +
      '  <div class="boot-tag">PERSONAL&nbsp;&nbsp;//&nbsp;&nbsp;KNOWLEDGE OPERATING SYSTEM</div>' +
      '  <div class="boot-log" id="bootLog"></div>' +
      '  <div class="boot-bar"><div class="boot-bar-fill" id="bootBar"></div></div>' +
      '  <div class="boot-enter" id="bootEnter">[ ENTER ]</div>' +
      "</div>";
  }

  function logLine(html, cls) {
    const el = document.createElement("div");
    el.className = "boot-line" + (cls ? " " + cls : "");
    el.innerHTML = html;
    document.getElementById("bootLog").appendChild(el);
    return el;
  }

  function dismiss(instant) {
    if (dismissed) return;
    dismissed = true;
    document.removeEventListener("keydown", onKey);
    boot.removeEventListener("click", onClick);
    if (audio) { fadeOutAudio(audio); }
    boot.classList.add("boot-gone");
    setTimeout(() => boot.remove(), instant ? 0 : 650);
  }

  function onKey(e) {
    if (e.key === "Enter" || e.key === "Escape" || e.key === " ") dismiss();
  }
  function onClick() { if (armed) dismiss(); }

  let armed = false;

  function fadeOutAudio(a) {
    const step = () => {
      if (a.volume > 0.05) { a.volume = Math.max(0, a.volume - 0.05); setTimeout(step, 40); }
      else { a.pause(); }
    };
    step();
  }

  function tryPlaySound(url) {
    audio = new Audio(url);
    audio.loop = true;
    audio.volume = 0.0;
    audio.play().then(() => {
      // ramp up gently
      const up = () => { if (audio && audio.volume < 0.4) { audio.volume = Math.min(0.4, audio.volume + 0.04); setTimeout(up, 60); } };
      up();
    }).catch(() => {
      // Autoplay blocked — start on the first user gesture instead.
      const start = () => { if (audio) audio.play().catch(() => {}); document.removeEventListener("pointerdown", start); document.removeEventListener("keydown", start); };
      document.addEventListener("pointerdown", start, { once: true });
      document.addEventListener("keydown", start, { once: true });
    });
  }

  async function run() {
    let cfg;
    try { cfg = await api.get("/api/synapse/boot/config"); }
    catch { cfg = FALLBACK; }

    // Preference: skip the animation entirely (settings.yaml → boot.skip).
    if (cfg.prefs && cfg.prefs.skip) { buildScaffold(); dismiss(true); return; }

    buildScaffold();

    if (cfg.wallpaper) {
      boot.style.backgroundImage =
        "linear-gradient(rgba(2,8,6,.82),rgba(2,8,6,.92)), url(" + cfg.wallpaper + ")";
      boot.classList.add("boot-has-wall");
    }
    if (cfg.sound && !(cfg.prefs && cfg.prefs.mute)) tryPlaySound(cfg.sound);

    // 1. logo + tagline fade (CSS-animated on scaffold insert).
    await sleep(900);

    // 2. system checks scroll in, one at a time.
    logLine("initializing " + (cfg.app || "Mainframe").toLowerCase() + " kernel…", "dim");
    await sleep(320);
    for (const c of cfg.checks || []) {
      const line = logLine(
        '<span class="bl-label">' + c.label + '</span>' +
        '<span class="bl-path">' + (c.path || "") + '</span>' +
        '<span class="bl-stat">····</span>'
      );
      await sleep(360);
      if (!boot.isConnected) return;  // dismissed early — stop touching the DOM
      const stat = line.querySelector(".bl-stat");
      stat.textContent = c.ok ? "[ OK ]" : "[ -- ]";
      stat.classList.add(c.ok ? "ok" : "warn");
    }
    await sleep(260);
    if (!boot.isConnected) return;

    // 3. loading bar (green→blue gradient) fills.
    logLine("mounting graph · loading modules…", "dim");
    document.getElementById("bootBar").classList.add("fill");
    await sleep(1550);
    if (!boot.isConnected) return;

    // 4. [ENTER] pulses; arm dismissal.
    // (the node-count tiles used to reveal here — dropped, they were noise on
    //  the way in; the same numbers live in the app itself)
    document.getElementById("bootEnter").classList.add("ready");
    armed = true;
    document.addEventListener("keydown", onKey);
    boot.addEventListener("click", onClick);
  }

  run();
})();

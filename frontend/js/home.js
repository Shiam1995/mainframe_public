/* home.js — the Mainframe home screen (built from the home-screen mockup).

   The landing screen: four tall module cards, a lifetime stat strip, a period
   snapshot, and a customisable background (gradient / image / video, dim,
   particles).

   Colours come from window.MODULES — the mockup used #00F5D4 for Synapse but
   the real accents are the ones already in the app, and those win.

   Everything numeric here is fetched live from /api/home; nothing is mocked.
   Preferences persist server-side so the home screen follows you between
   browsers. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const MOD = (k) => (window.MODULES || []).find((m) => m.key === k) || {};
  const rgba = (hex, a) => {
    const h = hex.replace("#", "");
    const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
  };
  // A card gradient derived from the module's own accent — no second palette.
  const cardGradient = (hex) =>
    `linear-gradient(150deg, ${hex} 0%, ${rgba(hex, .55)} 45%, rgba(11,15,20,.9) 100%)`;

  let prefs = { bg: { kind: "gradient", value: "" }, dim: 65, particles: true,
                images: [], videos: [], cards: {} };
  let root = null, snapPeriod = "weekly";
  // Artwork from ~/mAInframe/Imageformainframescreen, keyed by module — the
  // filename picks the module, so this never holds a list of them. A URL typed
  // into the customiser still wins over the folder.
  let cardArt = {};

  const savePrefs = () => guard(() => api.home.putPrefs(prefs));

  /* ---------- background layers ------------------------------------------ */
  const GRADIENTS = [
    "radial-gradient(ellipse at 20% 50%, rgba(0,212,170,.06) 0%, transparent 50%), radial-gradient(ellipse at 80% 20%, rgba(222,123,164,.05) 0%, transparent 50%), #0B0F14",
    "radial-gradient(ellipse at 30% 40%, rgba(139,126,200,.08) 0%, transparent 50%), radial-gradient(ellipse at 70% 70%, rgba(168,85,247,.06) 0%, transparent 50%), #0B0F14",
    "radial-gradient(ellipse at 50% 30%, rgba(255,71,87,.07) 0%, transparent 50%), #0B0F14",
    "radial-gradient(ellipse at 40% 60%, rgba(212,160,23,.07) 0%, transparent 50%), #0B0F14",
    "linear-gradient(135deg, #060612 0%, #0a0a1a 30%, #1a0a2e 60%, #0a0a1a 100%)",
    "#0B0F14",
  ];

  /* ---------- wallpaper slideshow ----------------------------------------
     Cycles the images in ~/mAInframe/Wallpapers (resized server-side).
     · random ORDER   — a fresh shuffle each pass, so every wallpaper is shown
                        once before any repeats, which plain random() won't do
     · random TIMING  — each slide holds for 5–30s, re-rolled per slide
     · manual advance — W (or →) skips to the next one immediately
     It only runs while the home screen is visible; opening a module stops the
     timer rather than leaving it burning in the background.                */
  const SLIDE_MIN_MS = 5000, SLIDE_MAX_MS = 30000;
  const slideDelay = () => SLIDE_MIN_MS + Math.random() * (SLIDE_MAX_MS - SLIDE_MIN_MS);
  const slide = { pool: [], order: [], i: 0, timer: null, layer: 0, last: null };

  function shuffled(list) {
    const a = list.slice();
    for (let i = a.length - 1; i > 0; i--) {          // Fisher–Yates
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function reshuffle() {
    slide.order = shuffled(slide.pool);
    // Two passes could otherwise butt the same image against itself across the
    // seam — the one place a shuffle can still look unshuffled.
    if (slide.order.length > 1 && slide.order[0] === slide.last) {
      [slide.order[0], slide.order[1]] = [slide.order[1], slide.order[0]];
    }
    slide.i = 0;
  }

  function paintSlide(url) {
    const layers = root.querySelectorAll(".hm-slide");
    if (!layers.length) return;
    const next = layers[slide.layer % layers.length];
    const prev = layers[(slide.layer + 1) % layers.length];
    next.style.backgroundImage = "url('" + url.replace(/'/g, "\\'") + "')";
    // Restart the drift animation on a layer that already ran it.
    next.classList.remove("active");
    void next.offsetWidth;                            // force reflow
    next.classList.add("active");
    prev.classList.remove("active");
    slide.layer++;
    slide.last = url;
  }

  function advanceSlide() {
    clearTimeout(slide.timer);
    if (!slide.pool.length) return;
    if (slide.i >= slide.order.length) reshuffle();
    paintSlide(slide.order[slide.i++]);
    // Decode the next one now so its cross-fade starts on a ready image.
    const upcoming = slide.order[slide.i] || (slide.order[0] || null);
    if (upcoming) { const pre = new Image(); pre.src = upcoming; }
    slide.timer = setTimeout(advanceSlide, slideDelay());
  }

  function stopSlideshow() {
    clearTimeout(slide.timer);
    slide.timer = null;
    if (root) root.querySelectorAll(".hm-slide").forEach((n) => n.classList.remove("active"));
  }

  async function startSlideshow() {
    stopSlideshow();
    if (!slide.pool.length) {
      const r = await api.wallpapers.list();
      slide.pool = (r.images || []).map((i) => i.url);
    }
    if (!slide.pool.length) {
      toast("no wallpapers found — drop images in the Wallpapers folder", "warn");
      return false;
    }
    reshuffle();
    advanceSlide();
    return true;
  }

  function applyBackground() {
    const grad = root.querySelector("#hm-grad");
    const img = root.querySelector("#hm-img");
    const vid = root.querySelector("#hm-vid");
    [grad, img, vid].forEach((n) => n.classList.remove("active"));
    try { vid.pause(); } catch { /* not playing */ }

    const b = prefs.bg || {};
    if (b.kind !== "slideshow") stopSlideshow();

    if (b.kind === "slideshow") {
      guard(startSlideshow);
    } else if (b.kind === "image" && b.value) {
      img.style.backgroundImage = "url(" + b.value + ")";
      img.classList.add("active");
    } else if (b.kind === "video" && b.value) {
      if (vid.getAttribute("src") !== b.value) vid.setAttribute("src", b.value);
      vid.classList.add("active");
      vid.play().catch(() => {});          // autoplay can be blocked; harmless
    } else {
      grad.style.background = b.value || GRADIENTS[0];
      grad.classList.add("active");
    }
    root.querySelector("#hm-dim").style.background = "rgba(11,15,20," + (prefs.dim / 100) + ")";
    root.querySelector("#hm-particles").style.display = prefs.particles ? "block" : "none";
  }

  function particles() {
    const host = el("div.hm-particles", { id: "hm-particles" });
    const cols = ["#00D4AA", "#DE7BA4", "#8B7EC8", "#D4A017"];
    for (let i = 0; i < 15; i++) {
      const s = Math.random() * 2.5 + 1;
      host.appendChild(el("div.hm-p", { style:
        `width:${s}px;height:${s}px;left:${Math.random() * 100}%;`
        + `background:${rgba(cols[i % 4], .4)};`
        + `animation-duration:${Math.random() * 20 + 15}s;`
        + `animation-delay:${Math.random() * 20}s` }));
    }
    return host;
  }

  /* ---------- background settings panel ---------------------------------- */
  function bgPanel() {
    const panel = el("div.hm-bg-panel", { id: "hm-bg-panel" });
    const section = (t) => panel.appendChild(el("div.hm-bg-sec", { text: t }));

    // Put the wallpaper folder first — it's the one people actually use daily.
    section("WALLPAPER SLIDESHOW");
    const on = prefs.bg.kind === "slideshow";
    const slideBtn = el("button.hm-btn" + (on ? ".on" : ""),
      { text: on ? "■ stop cycling" : "▶ cycle wallpapers" });
    // guard() RUNS its argument (it's not a wrapper) — the handler has to be a
    // plain closure, or the panel would fire it while building itself.
    slideBtn.addEventListener("click", () => guard(async () => {
      if (prefs.bg.kind === "slideshow") {
        prefs.bg = { kind: "gradient", value: GRADIENTS[0] };
      } else {
        prefs.bg = { kind: "slideshow", value: "" };
      }
      applyBackground(); savePrefs(); refreshPanel();
    }));
    const rescanBtn = el("button.hm-btn", { text: "↻ rescan folder" });
    rescanBtn.addEventListener("click", () => guard(async () => {
      const r = await api.wallpapers.rescan(false);
      slide.pool = (r.images || []).map((i) => i.url);
      toast(r.count + " wallpapers (" + r.built + " new)");
      if (prefs.bg.kind === "slideshow") { reshuffle(); advanceSlide(); }
      refreshPanel();
    }));
    panel.appendChild(el("div.row", { style: "gap:6px" }, [slideBtn, rescanBtn]));
    panel.appendChild(el("div.hm-hint", { text:
      "random order · each holds 5–30s · press W to skip" }));

    section("GRADIENTS");
    const gGrid = el("div.hm-bg-grid");
    GRADIENTS.forEach((g) => {
      const th = el("div.hm-thumb" + (prefs.bg.kind === "gradient" && prefs.bg.value === g ? ".active" : ""),
        { style: "background:" + g });
      th.addEventListener("click", () => {
        prefs.bg = { kind: "gradient", value: g };
        applyBackground(); savePrefs(); refreshPanel();
      });
      gGrid.appendChild(th);
    });
    panel.appendChild(gGrid);

    section("CUSTOM IMAGE");
    const imgIn = el("input.hm-input", { placeholder: "paste an image URL…" });
    const addImg = () => {
      const url = imgIn.value.trim();
      if (!url) return;
      if (!prefs.images.includes(url)) prefs.images.push(url);
      prefs.bg = { kind: "image", value: url };
      imgIn.value = ""; applyBackground(); savePrefs(); refreshPanel();
    };
    imgIn.addEventListener("keydown", (e) => { if (e.key === "Enter") addImg(); });
    panel.appendChild(imgIn);
    panel.appendChild(el("button.hm-btn", { onclick: addImg, text: "set as background" }));
    // upload straight into the Mainframe image service
    const file = el("input.img-file", { type: "file", accept: ".png,.jpg,.jpeg,.gif,.webp,.svg" });
    file.addEventListener("change", () => {
      const f = file.files && file.files[0];
      if (!f) return;
      window.Images.nameModal(f.name.replace(/\.[^.]+$/, ""), (name) => guard(async () => {
        const im = await api.images.upload(f, name, "home", null);
        const url = api.images.fileUrl(im.id);
        prefs.images.push(url);
        prefs.bg = { kind: "image", value: url };
        file.value = ""; applyBackground(); await savePrefs(); refreshPanel();
        toast("background set");
      }));
    });
    panel.appendChild(file);
    panel.appendChild(el("button.hm-btn", { style: "margin-left:6px",
      onclick: () => file.click(), text: "⤒ upload" }));
    const iGrid = el("div.hm-bg-grid", { style: "margin-top:8px" });
    prefs.images.forEach((url) => {
      const th = el("div.hm-thumb" + (prefs.bg.value === url ? ".active" : ""),
        { style: "background-image:url(" + url + ")" });
      th.addEventListener("click", () => {
        prefs.bg = { kind: "image", value: url }; applyBackground(); savePrefs(); refreshPanel();
      });
      th.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        prefs.images = prefs.images.filter((u) => u !== url);
        savePrefs(); refreshPanel();
      });
      iGrid.appendChild(th);
    });
    panel.appendChild(iGrid);

    section("VIDEO BACKGROUND");
    const vidIn = el("input.hm-input", { placeholder: "paste a video URL (.mp4)…" });
    const addVid = () => {
      const url = vidIn.value.trim();
      if (!url) return;
      if (!prefs.videos.includes(url)) prefs.videos.push(url);
      prefs.bg = { kind: "video", value: url };
      vidIn.value = ""; applyBackground(); savePrefs(); refreshPanel();
    };
    vidIn.addEventListener("keydown", (e) => { if (e.key === "Enter") addVid(); });
    panel.appendChild(vidIn);
    panel.appendChild(el("button.hm-btn", { onclick: addVid, text: "set video background" }));
    prefs.videos.forEach((url) => {
      panel.appendChild(el("div.spread", { style: "padding:4px 0" }, [
        el("span.hm-vid-name", { text: "🎬 " + (url.split("/").pop().split("?")[0] || "video") }),
        el("div.row", { style: "gap:4px" }, [
          el("button.hm-btn", { onclick: () => {
            prefs.bg = { kind: "video", value: url }; applyBackground(); savePrefs();
          }, text: "play" }),
          el("button.hm-btn", { onclick: () => {
            prefs.videos = prefs.videos.filter((u) => u !== url); savePrefs(); refreshPanel();
          }, text: "×" }),
        ]),
      ]));
    });

    section("OVERLAY");
    const dim = el("input", { type: "range", min: "0", max: "90", value: String(prefs.dim), style: "flex:1" });
    dim.addEventListener("input", () => {
      prefs.dim = Number(dim.value);
      root.querySelector("#hm-dim").style.background = "rgba(11,15,20," + (prefs.dim / 100) + ")";
    });
    dim.addEventListener("change", savePrefs);
    panel.appendChild(el("div.row", { style: "gap:10px;margin-top:4px" }, [
      el("span.hm-dim-lbl", { text: "dim" }), dim, el("span.hm-dim-lbl", { text: "dark" }),
    ]));
    const cb = el("input", { type: "checkbox" });
    cb.checked = !!prefs.particles;
    cb.addEventListener("change", () => {
      prefs.particles = cb.checked; applyBackground(); savePrefs();
    });
    panel.appendChild(el("label.row", { style: "gap:6px;margin-top:8px;cursor:pointer" }, [
      cb, el("span.hm-dim-lbl", { text: "particles" }),
    ]));

    section("MODULE CARDS");
    panel.appendChild(el("div.hm-dim-lbl", { style: "margin-bottom:6px",
      text: "artwork comes from ~/mAInframe/Imageformainframescreen, named per module "
          + "(synapse.jpg, pulse.jpg…). Paste a URL to override one; blank to go back to the folder." }));
    (window.MODULES || []).forEach((m) => {
      const inp = el("input.hm-input", { style: "margin-top:4px",
        placeholder: m.label.toLowerCase() + (cardArt[m.key] ? " — using the folder image" : " image URL"),
        value: prefs.cards[m.key] || "" });
      inp.addEventListener("change", () => {
        const v = inp.value.trim();
        if (v) prefs.cards[m.key] = v; else delete prefs.cards[m.key];
        savePrefs(); render();
      });
      panel.appendChild(inp);
    });
    return panel;
  }

  function refreshPanel() {
    const old = root.querySelector("#hm-bg-panel");
    if (!old) return;
    const open = old.classList.contains("open");
    const fresh = bgPanel();
    if (open) fresh.classList.add("open");
    old.replaceWith(fresh);
  }

  /* ---------- snapshot ---------------------------------------------------- */
  async function loadSnapshot(host, periodEl) {
    const s = await guard(() => api.home.snapshot(snapPeriod));
    periodEl.textContent = s.label;
    clear(host);
    s.sections.forEach((sec) => {
      const accent = MOD(sec.module).accent || "#8194a8";
      const box = el("div.hm-snap-sec", {}, [
        el("div.hm-snap-sec-t", { text: (MOD(sec.module).label || sec.module).toUpperCase() }),
      ]);
      sec.rows.forEach((r) => {
        const tone = r.tone === "good" ? "var(--green)" : r.tone === "bad" ? "var(--red)" : accent;
        box.appendChild(el("div.hm-snap-row", {}, [
          el("span.hm-snap-l", { text: r.label }),
          el("span.hm-snap-v", { style: "color:" + tone, text: String(r.value) }),
        ]));
      });
      host.appendChild(box);
    });
  }

  /* ---------- the screen -------------------------------------------------- */
  function render() {
    clear(root);

    // background stack
    root.appendChild(el("div.hm-bg", {}, [
      el("div.hm-grad.active", { id: "hm-grad" }),
      el("div.hm-img", { id: "hm-img" }),
      el("div.hm-slide", { id: "hm-slide-a" }),   // the two cross-fading
      el("div.hm-slide", { id: "hm-slide-b" }),   // slideshow layers

      el("video.hm-vid", { id: "hm-vid", muted: true, loop: true, playsinline: true }),
      el("div.hm-dim", { id: "hm-dim" }),
      particles(),
    ]));

    const screen = el("div.hm-screen");

    screen.appendChild(el("div.hm-title", { html:
      'm<span>a</span>infr<span>a</span>me' }));
    screen.appendChild(el("div.hm-sub", { text: "knowledge operating system" }));

    // --- top strip: lifetime stats + snapshot ---
    const statsBar = el("div.hm-tasks", { title: "open Tasks" });
    statsBar.addEventListener("click", () => window.openModule("synapse", "tasks"));
    const snapPeriodEl = el("div.hm-snap-period", { text: "…" });
    const snapDrop = el("div.hm-snap-drop");
    const snapBar = el("div.hm-snap", {}, [
      el("div.hm-snap-label", { text: "SNAPSHOT" }), snapPeriodEl,
      el("div.hm-snap-toggle", {}, ["daily", "weekly", "monthly"].map((p) => {
        const b = el("div.hm-snap-t" + (p === snapPeriod ? ".active" : ""), { text: p[0].toUpperCase() });
        b.addEventListener("click", (e) => {
          e.stopPropagation();
          snapPeriod = p;
          root.querySelectorAll(".hm-snap-t").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          loadSnapshot(snapDrop, snapPeriodEl);
        });
        return b;
      })),
      snapDrop,
    ]);
    snapBar.addEventListener("click", () => snapDrop.classList.toggle("open"));
    screen.appendChild(el("div.hm-strip", {}, [statsBar, snapBar]));

    // --- module cards ---
    const grid = el("div.hm-grid");
    (window.MODULES || []).forEach((m) => {
      const art = prefs.cards[m.key] || cardArt[m.key];
      // Each card is framed in its own module accent, so the four read as one
      // set even though the pictures share no palette.
      // A custom property, not an inline box-shadow — inline styles would beat
      // the :hover rule's shadow and the cards would stop lifting.
      const card = el("div.hm-card", { title: m.label, style: "--card-accent:" + m.accent });
      card.appendChild(el("div.hm-card-img", { style: art
        ? "background-image:url(" + art + ")"
        : "background:" + cardGradient(m.accent) }));
      card.appendChild(el("div.hm-card-ov"));
      card.appendChild(el("div.hm-card-glow", { style: "box-shadow:0 0 28px " + rgba(m.accent, .35) }));
      card.appendChild(el("div.hm-card-name", { style: "color:" + m.accent,
        text: m.label.charAt(0) + m.label.slice(1).toLowerCase() }));
      card.addEventListener("click", () => window.openModule(m.key));
      grid.appendChild(card);
    });
    screen.appendChild(grid);
    root.appendChild(screen);

    // --- background settings ---
    const btn = el("button.hm-bg-btn", { text: "🎨 background" });
    const panel = bgPanel();
    btn.addEventListener("click", (e) => { e.stopPropagation(); panel.classList.toggle("open"); });
    root.appendChild(btn);
    root.appendChild(panel);

    applyBackground();

    // populate live figures
    guard(async () => {
      const s = await api.home.stats();
      clear(statsBar);
      statsBar.appendChild(el("div.row", { style: "gap:10px;align-items:center" }, [
        el("div.hm-dot"),
        el("div", {}, [
          el("div.hm-tasks-label", { text: "Total Hours" }),
          el("div.hm-tasks-big", { text: s.hours.toLocaleString("en-GB") }),
        ]),
      ]));
      s.tiles.forEach((t) => {
        statsBar.appendChild(el("div.hm-sep"));
        statsBar.appendChild(el("div", { style: "text-align:center" }, [
          el("div.hm-tile-v", { text: String(t.value) }),
          el("div.hm-tile-l", { text: t.label }),
        ]));
      });
      // how much disk the whole Mainframe occupies — app + files + graph
      const z = await api.get("/api/home/size");
      const gb = (b) => (b / 1e9).toFixed(b >= 1e10 ? 0 : 1) + " GB";
      statsBar.appendChild(el("div.hm-sep"));
      statsBar.appendChild(el("div", { style: "text-align:center", title:
        "app " + gb(z.app_bytes) + " · files " + gb(z.files_bytes)
        + (z.graph_included ? " · graph " + gb(z.graph_bytes) : " · graph n/a") }, [
        el("div.hm-tile-v", { text: gb(z.total_bytes) }),
        el("div.hm-tile-l", { text: "TOTAL SIZE" }),
      ]));
    });
    loadSnapshot(snapDrop, snapPeriodEl);
  }

  /* ---------- module-card artwork ----------------------------------------- */
  /* Fetching the listing is what syncs the cache, so swapping a file in the
     folder and coming back to home is enough — no restart. Re-renders only when
     a URL actually changed (the URL carries the file's fingerprint), so the
     usual case costs nothing on screen. */
  async function loadCardArt(rerender) {
    let fresh = {};
    try {
      const r = await api.moduleCards.list();
      Object.keys(r.cards || {}).forEach((k) => { fresh[k] = r.cards[k].url; });
    } catch { return; }          // no folder / backend down → gradients stand in
    const changed = Object.keys(Object.assign({}, cardArt, fresh))
      .some((k) => cardArt[k] !== fresh[k]);
    cardArt = fresh;
    if (changed && rerender) render();
  }

  /* ---------- mount ------------------------------------------------------- */
  window.Home = {
    async mount() {
      root = document.getElementById("home");
      if (!root) return;
      try {
        const p = await api.home.prefs();
        prefs = Object.assign({ bg: { kind: "gradient", value: "" }, dim: 65,
                                particles: true, images: [], videos: [], cards: {} }, p || {});
        prefs.images = prefs.images || []; prefs.videos = prefs.videos || [];
        prefs.cards = prefs.cards || {};
      } catch { /* first run, or backend down — defaults are fine */ }
      await loadCardArt(false);
      render();
    },
    show() { if (root) { root.classList.add("open"); render(); loadCardArt(true); } },
    // Leaving home stops the timer — no point cross-fading images nobody sees.
    hide() { stopSlideshow(); if (root) root.classList.remove("open"); },
    nextWallpaper() {
      if (prefs.bg && prefs.bg.kind === "slideshow") { advanceSlide(); return true; }
      return false;
    },
  };

  // W (or →) skips to the next wallpaper. Only while home is on screen, and
  // never while typing — otherwise it eats the letter mid-word.
  document.addEventListener("keydown", (e) => {
    if (!root || !root.classList.contains("open")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && (t.matches("input, textarea, select") || t.isContentEditable)) return;
    if (e.key === "w" || e.key === "W" || e.key === "ArrowRight") {
      if (window.Home.nextWallpaper()) e.preventDefault();
    }
  });

  // clicking anywhere else closes the popovers
  document.addEventListener("click", (e) => {
    if (!root) return;
    if (!e.target.closest(".hm-snap")) root.querySelectorAll(".hm-snap-drop").forEach((d) => d.classList.remove("open"));
    if (!e.target.closest(".hm-bg-panel") && !e.target.closest(".hm-bg-btn")) {
      root.querySelectorAll(".hm-bg-panel").forEach((p) => p.classList.remove("open"));
    }
  });
})();

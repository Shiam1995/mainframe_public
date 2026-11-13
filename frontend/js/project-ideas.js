/* project-ideas.js — the References · Database · Graph sub-views of a project.

   All three read the same edge, (:Project)-[:HAS_IDEA]->(:Idea), and differ
   only in how they present it:

     References — a reading list. What's worth looking at, and why.
     Database   — the same ideas as a sortable table.
     Graph      — a canvas where you drag ideas around and connect them.

   Ideas themselves are global (the Ideas tab owns them), so detaching one here
   never deletes it — it just stops being this project's business. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const LOOK = [
    { v: "to-look-at", t: "to look at", c: "var(--amber)" },
    { v: "looking", t: "looking", c: "var(--blue)" },
    { v: "used", t: "used", c: "var(--green)" },
    { v: "parked", t: "parked", c: "var(--dim)" },
  ];
  const lookOf = (v) => LOOK.find((l) => l.v === v) || LOOK[0];

  // The project choice is shared by every sub-view (project-picker.js), so
  // switching tabs keeps you on the same project.
  const P = () => window.ProjectPicker;
  let projectId = "";

  function empty(host, text) {
    host.appendChild(el("div.empty", { text }));
  }

  /* ------------------------------------------------------------------ *
   * Adding an idea — either a brand new one, or one that already exists
   * in the Ideas tab. Both land on the same endpoint.
   * ------------------------------------------------------------------ */
  function addBar(reload) {
    const titleIn = el("input", { placeholder: "new idea to look at…",
                                  style: "flex:1;min-width:200px" });
    const noteIn = el("input", { placeholder: "why (optional)",
                                 style: "flex:1;min-width:160px" });
    const add = el("button.btn-primary", { text: "+ idea", onclick: () => guard(async () => {
      if (!titleIn.value.trim()) return toast("give the idea a title", true);
      await api.projects.attachIdea(projectId, {
        title: titleIn.value.trim(), note: noteIn.value.trim(), status: "to-look-at",
      });
      titleIn.value = noteIn.value = "";
      reload();
    }) });

    const existing = el("select", { style: "max-width:220px" },
      [el("option", { value: "", text: "attach an existing idea…" })]);
    guard(async () => {
      const all = await api.get("/api/synapse/ideas");
      all.forEach((i) => existing.appendChild(
        el("option", { value: i.id, text: i.title || "(untitled)" })));
    });
    existing.addEventListener("change", () => guard(async () => {
      if (!existing.value) return;
      await api.projects.attachIdea(projectId, { idea_id: existing.value });
      existing.value = "";
      reload();
      toast("attached");
    }));

    return el("div.row", { style: "margin-bottom:14px;flex-wrap:wrap" },
              [titleIn, noteIn, add, existing]);
  }

  function statusSelect(idea, reload) {
    const sel = el("select.pi-status", {}, LOOK.map((l) =>
      el("option", { value: l.v, text: l.t })));
    sel.value = idea.look_status;
    sel.style.color = lookOf(idea.look_status).c;
    sel.addEventListener("change", () => guard(async () => {
      await api.projects.updateIdea(projectId, idea.id, { status: sel.value });
      sel.style.color = lookOf(sel.value).c;
      if (reload) reload();
    }));
    return sel;
  }

  function detachBtn(idea, reload) {
    const b = el("button.pi-x", { title: "remove from this project", text: "×" });
    let armed = false;
    b.addEventListener("click", () => {
      if (!armed) {
        armed = true; b.textContent = "sure?"; b.classList.add("armed");
        setTimeout(() => { armed = false; b.textContent = "×"; b.classList.remove("armed"); }, 3000);
        return;
      }
      guard(async () => {
        await api.projects.detachIdea(projectId, idea.id);
        toast("detached — the idea itself is untouched");
        reload();
      });
    });
    return b;
  }

  /* ------------------------------------------------------------------ *
   * References — the reading list
   * ------------------------------------------------------------------ */
  async function renderReferences(host) {
    clear(host);
    const projects = await P().load();
    P().mount(host, () => renderReferences(host));
    if (!projects.length) return;
    projectId = P().id;
    host.appendChild(addBar(() => renderReferences(host)));

    const ideas = await api.projects.ideas(projectId);
    if (!ideas.length) {
      return empty(host, "Nothing to look at yet. Add an idea above, or attach one you already wrote down.");
    }
    // Grouped by status so "to look at" reads as an actual queue.
    LOOK.forEach((l) => {
      const group = ideas.filter((i) => i.look_status === l.v);
      if (!group.length) return;
      host.appendChild(el("div.pi-group", { style: "color:" + l.c,
                                            text: l.t + " · " + group.length }));
      group.forEach((idea) => {
        const note = el("input.pi-note", { value: idea.look_note || "",
                                           placeholder: "why this matters here" });
        note.addEventListener("change", () => guard(() =>
          api.projects.updateIdea(projectId, idea.id, { note: note.value })));
        host.appendChild(el("div.pi-row", { "data-eid": idea.id }, [
          el("div.pi-title", { text: idea.title || "(untitled)" }),
          note,
          statusSelect(idea, () => renderReferences(host)),
          detachBtn(idea, () => renderReferences(host)),
        ]));
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Database — the same ideas, as a table
   * ------------------------------------------------------------------ */
  let sortKey = "look_status", sortDir = "asc";

  async function renderDatabase(host) {
    clear(host);
    const projects = await P().load();
    P().mount(host, () => renderDatabase(host));
    if (!projects.length) return;
    projectId = P().id;
    host.appendChild(addBar(() => renderDatabase(host)));

    const ideas = await api.projects.ideas(projectId);
    if (!ideas.length) return empty(host, "No ideas attached to this project yet.");

    const COLS = [
      { k: "title", t: "Idea" },
      { k: "look_status", t: "Status" },
      { k: "look_note", t: "Why here" },
      { k: "category", t: "Kind" },
      { k: "priority", t: "Priority" },
      { k: "added_at", t: "Added" },
    ];
    const rows = ideas.slice().sort((a, b) => {
      const x = String(a[sortKey] == null ? "" : a[sortKey]).toLowerCase();
      const y = String(b[sortKey] == null ? "" : b[sortKey]).toLowerCase();
      const cmp = x < y ? -1 : x > y ? 1 : 0;
      return sortDir === "desc" ? -cmp : cmp;
    });

    const head = el("tr", {}, COLS.map((c) => el("th", {
      style: "cursor:pointer",
      onclick: () => {
        if (sortKey === c.k) sortDir = sortDir === "asc" ? "desc" : "asc";
        else { sortKey = c.k; sortDir = "asc"; }
        renderDatabase(host);
      },
      text: c.t + (sortKey === c.k ? (sortDir === "desc" ? " ↓" : " ↑") : ""),
    })).concat([el("th", { text: "" })]));

    const body = el("tbody");
    rows.forEach((idea) => {
      const tr = el("tr");
      tr.appendChild(el("td", { text: idea.title || "(untitled)" }));
      tr.appendChild(el("td", {}, [statusSelect(idea, () => renderDatabase(host))]));
      const note = el("input.pi-note", { value: idea.look_note || "" });
      note.addEventListener("change", () => guard(() =>
        api.projects.updateIdea(projectId, idea.id, { note: note.value })));
      tr.appendChild(el("td", {}, [note]));
      tr.appendChild(el("td", { text: idea.category || "" }));
      tr.appendChild(el("td", { text: idea.priority || "" }));
      tr.appendChild(el("td", { text: (idea.added_at || "").slice(0, 10) }));
      tr.appendChild(el("td", {}, [detachBtn(idea, () => renderDatabase(host))]));
      body.appendChild(tr);
    });

    host.appendChild(el("div.pi-tablewrap", {}, [
      el("table.pi-table", {}, [el("thead", {}, [head]), body])]));
    host.appendChild(el("div.sub", { style: "margin-top:8px",
      text: rows.length + " idea" + (rows.length === 1 ? "" : "s") + " attached to this project." }));
  }

  /* ------------------------------------------------------------------ *
   * Graph — the knowledge map
   *
   * Hand-rolled canvas, no libraries, same as the Reference Map. Nodes keep
   * their position AND their box size on the HAS_IDEA edge, so a layout you
   * arrange by hand is still there tomorrow.
   *
   * Three separate things can change size here, and they're deliberately not
   * the same control:
   *   the canvas   how much of the screen the map gets — drag its bottom edge
   *   the view     zoom and pan, which change what you're looking at
   *   a box        drag a node's corner, which changes the node itself and is
   *                saved; the S/M/L scale multiplies every box at once
   * ------------------------------------------------------------------ */
  const NODE_W = 150, NODE_H = 42;
  const MIN_W = 70, MIN_H = 28, MAX_W = 640, MAX_H = 400;
  const HANDLE = 13;                 // corner grab area, in screen pixels

  // How big the boxes are as a whole. A per-node width you dragged is a base
  // size that this multiplies, so "make them all bigger" doesn't throw away
  // the one box you widened to fit a long title.
  const SCALES = [
    { key: "s", label: "S", f: 0.72 },
    { key: "m", label: "M", f: 1 },
    { key: "l", label: "L", f: 1.4 },
    { key: "xl", label: "XL", f: 1.9 },
  ];
  const SCALE_KEY = "project.graphScale";
  const scaleOf = () => {
    let k;
    try { k = localStorage.getItem(SCALE_KEY); } catch { k = null; }
    return SCALES.find((s) => s.key === k) || SCALES[1];
  };
  const setScale = (k) => { try { localStorage.setItem(SCALE_KEY, k); } catch { /* ignore */ } };

  // Canvas height, remembered — the map is the whole point of this sub-view,
  // and how tall you want it is a habit rather than a per-visit decision.
  const HEIGHT_KEY = "project.graphHeight";
  const savedHeight = () => {
    const v = parseInt((() => { try { return localStorage.getItem(HEIGHT_KEY); } catch { return ""; } })(), 10);
    return v >= 220 ? v : null;
  };

  // Zoom and pan, per project: come back to a map and you're where you left it.
  const VIEW_KEY = "project.graphView";
  const loadViews = () => {
    try { return JSON.parse(localStorage.getItem(VIEW_KEY) || "{}"); } catch { return {}; }
  };
  const saveView = (pid, v) => {
    const all = loadViews();
    all[pid] = { z: v.z, ox: v.ox, oy: v.oy };
    try { localStorage.setItem(VIEW_KEY, JSON.stringify(all)); } catch { /* ignore */ }
  };

  async function renderGraph(host) {
    clear(host);
    const projects = await P().load();
    P().mount(host, () => renderGraph(host));
    if (!projects.length) return;
    projectId = P().id;

    let data = await api.projects.graph(projectId);
    if (!data.nodes.length) {
      host.appendChild(addBar(() => renderGraph(host)));
      return empty(host, "No ideas attached yet — add some in References, then connect them here.");
    }

    let connectFrom = null;                 // id of the node awaiting a partner
    const IDLE_HINT = "Drag to arrange · drag a box's bottom-right corner to resize it "
                    + "· scroll to zoom, drag the background to pan · click Connect then "
                    + "two ideas to link them · click a line to remove it.";
    const hint = el("div.pi-hint", { text: IDLE_HINT });
    const connectBtn = el("button.sh-act", { text: "🔗 connect" });

    // --- the toolbar: what's on screen, and how big it is ---
    const scaleBtns = el("div.wl-sizebtns");
    const paintScale = () => scaleBtns.querySelectorAll("button").forEach(
      (b) => b.classList.toggle("on", b.dataset.size === scaleOf().key));
    SCALES.forEach((s) => {
      const b = el("button.btn-sm.wl-sizebtn", {
        type: "button", title: "boxes at " + Math.round(s.f * 100) + "%",
        text: s.label,
        onclick: () => { setScale(s.key); paintScale(); draw(); },
      });
      b.dataset.size = s.key;
      scaleBtns.appendChild(b);
    });

    const bar = el("div.row", { style: "margin-bottom:10px;gap:8px;align-items:center;flex-wrap:wrap" }, [
      connectBtn,
      el("button.btn-sm", { title: "zoom out", onclick: () => zoomBy(1 / 1.2), text: "−" }),
      el("button.btn-sm", { title: "zoom in", onclick: () => zoomBy(1.2), text: "+" }),
      el("button.btn-sm", { title: "fit every idea on screen", onclick: () => { fit(); draw(); }, text: "fit" }),
      el("span.sub", { text: "│" }),
      el("span.sub", { text: "boxes" }), scaleBtns,
      hint,
    ]);
    host.appendChild(bar);
    paintScale();

    const canvas = el("canvas.pi-canvas");
    const wrap = el("div.pi-canvaswrap", {}, [canvas]);
    const h = savedHeight();
    if (h) wrap.style.height = h + "px";
    host.appendChild(wrap);
    host.appendChild(addBar(() => renderGraph(host)));

    const ctx = canvas.getContext("2d");
    let W = 0, H = 0;
    const view = Object.assign({ z: 1, ox: 0, oy: 0 }, loadViews()[projectId] || {});

    /* --- geometry -------------------------------------------------------
       Nodes live in world coordinates; the view is a scale + offset on top.
       Everything that hit-tests converts the pointer into world space first,
       so a click lands where it looks like it lands at any zoom. */
    const boxW = (n) => (n.w || NODE_W) * scaleOf().f;
    const boxH = (n) => (n.h || NODE_H) * scaleOf().f;
    const toWorld = (sx, sy) => ({ x: (sx - view.ox) / view.z, y: (sy - view.oy) / view.z });

    function zoomBy(f, at) {
      const p = at || { x: W / 2, y: H / 2 };
      const nz = Math.max(0.2, Math.min(4, view.z * f));
      // Keep whatever is under the pointer under the pointer.
      view.ox = p.x - (p.x - view.ox) * (nz / view.z);
      view.oy = p.y - (p.y - view.oy) * (nz / view.z);
      view.z = nz;
      saveView(projectId, view);
      draw();
    }

    function fit() {
      if (!data.nodes.length || !W) return;
      const xs = data.nodes.map((n) => n.x), ys = data.nodes.map((n) => n.y);
      const halfW = Math.max(...data.nodes.map(boxW)) / 2;
      const halfH = Math.max(...data.nodes.map(boxH)) / 2;
      const minX = Math.min(...xs) - halfW, maxX = Math.max(...xs) + halfW;
      const minY = Math.min(...ys) - halfH, maxY = Math.max(...ys) + halfH;
      const pad = 30;
      view.z = Math.max(0.2, Math.min(2,
        Math.min((W - pad * 2) / Math.max(1, maxX - minX),
                 (H - pad * 2) / Math.max(1, maxY - minY))));
      view.ox = W / 2 - ((minX + maxX) / 2) * view.z;
      view.oy = H / 2 - ((minY + maxY) / 2) * view.z;
      saveView(projectId, view);
    }

    /* Anything never dragged gets a spot on a circle — a readable starting
       point that the user can then rearrange, rather than a pile at 0,0. */
    function seedPositions() {
      const loose = data.nodes.filter((n) => n.x == null || n.y == null);
      if (!loose.length) return false;
      const r = Math.max(120, Math.min(W, H) / 2 - NODE_W);
      loose.forEach((n, i) => {
        const a = (i / Math.max(1, loose.length)) * Math.PI * 2;
        n.x = W / 2 + Math.cos(a) * r;
        n.y = H / 2 + Math.sin(a) * r;
      });
      return true;
    }

    function resize() {
      const dpr = window.devicePixelRatio || 1;
      W = wrap.clientWidth; H = wrap.clientHeight;
      if (!W || !H) return;
      canvas.width = W * dpr; canvas.height = H * dpr;
      canvas.style.width = W + "px"; canvas.style.height = H + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seedPositions();
      draw();
    }

    const nodeAt = (wx, wy) => {
      // Reversed, so the node drawn last (on top) is the one you grab.
      for (let i = data.nodes.length - 1; i >= 0; i--) {
        const n = data.nodes[i];
        if (Math.abs(wx - n.x) <= boxW(n) / 2 && Math.abs(wy - n.y) <= boxH(n) / 2) return n;
      }
      return null;
    };

    /* The resize corner. Measured in SCREEN pixels so it stays grabbable when
       you're zoomed out — a 13px handle at 0.3× would be four pixels wide. */
    function handleAt(wx, wy) {
      const slack = HANDLE / view.z;
      for (let i = data.nodes.length - 1; i >= 0; i--) {
        const n = data.nodes[i];
        const cx = n.x + boxW(n) / 2, cy = n.y + boxH(n) / 2;
        if (wx >= cx - slack && wx <= cx + slack / 2 && wy >= cy - slack && wy <= cy + slack / 2) return n;
      }
      return null;
    }

    // Distance from a point to a segment — used to hit-test the edges.
    function edgeAt(wx, wy) {
      for (const e of data.edges) {
        const a = data.nodes.find((n) => n.id === e.from_id);
        const b = data.nodes.find((n) => n.id === e.to_id);
        if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y;
        const len2 = dx * dx + dy * dy || 1;
        let t = ((wx - a.x) * dx + (wy - a.y) * dy) / len2;
        t = Math.max(0, Math.min(1, t));
        const px = a.x + t * dx, py = a.y + t * dy;
        if (Math.hypot(wx - px, wy - py) < 7 / view.z) return e;
      }
      return null;
    }

    function draw() {
      ctx.clearRect(0, 0, W, H);
      const accent = getComputedStyle(document.documentElement)
        .getPropertyValue("--accent").trim() || "#00D4AA";

      ctx.save();
      ctx.translate(view.ox, view.oy);
      ctx.scale(view.z, view.z);

      data.edges.forEach((e) => {
        const a = data.nodes.find((n) => n.id === e.from_id);
        const b = data.nodes.find((n) => n.id === e.to_id);
        if (!a || !b) return;
        ctx.strokeStyle = "#3a4657";
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        // Arrow head, so a connection reads as directional. It stops at the
        // edge of the TARGET's box, which is now per-node rather than fixed.
        const ang = Math.atan2(b.y - a.y, b.x - a.x);
        const ex = b.x - Math.cos(ang) * (boxW(b) / 2 + 4);
        const ey = b.y - Math.sin(ang) * (boxH(b) / 2 + 4);
        ctx.fillStyle = "#3a4657";
        ctx.beginPath();
        ctx.moveTo(ex, ey);
        ctx.lineTo(ex - Math.cos(ang - 0.4) * 9, ey - Math.sin(ang - 0.4) * 9);
        ctx.lineTo(ex - Math.cos(ang + 0.4) * 9, ey - Math.sin(ang + 0.4) * 9);
        ctx.closePath(); ctx.fill();
        if (e.label) {
          ctx.fillStyle = "#7B8BA3";
          ctx.font = "10px ui-monospace, monospace";
          ctx.textAlign = "center";
          ctx.fillText(e.label, (a.x + b.x) / 2, (a.y + b.y) / 2 - 5);
        }
      });

      data.nodes.forEach((n) => {
        const col = lookOf(n.look_status).c;
        const active = connectFrom === n.id;
        const w = boxW(n), h = boxH(n);
        ctx.fillStyle = "#1B2330";
        ctx.strokeStyle = active ? accent : col;
        ctx.lineWidth = active ? 2.5 : 1.5;
        const x = n.x - w / 2, y = n.y - h / 2;
        ctx.beginPath();
        ctx.roundRect(x, y, w, h, 8);
        ctx.fill(); ctx.stroke();

        // The resize corner, drawn so it can be found without being told.
        ctx.strokeStyle = col;
        ctx.globalAlpha = 0.55;
        ctx.lineWidth = 1;
        const g = Math.min(9, h / 3);
        ctx.beginPath();
        ctx.moveTo(x + w - g, y + h - 2); ctx.lineTo(x + w - 2, y + h - g);
        ctx.moveTo(x + w - g / 2, y + h - 2); ctx.lineTo(x + w - 2, y + h - g / 2);
        ctx.stroke();
        ctx.globalAlpha = 1;

        ctx.fillStyle = "#dfe6ee";
        // Text grows with the box: a box you made twice as tall to read a long
        // title is no use if the title is still 11px.
        const fs = Math.max(9, Math.min(22, 11 * scaleOf().f));
        ctx.font = fs + "px Inter, system-ui, sans-serif";
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        const lh = fs * 1.2;
        const maxLines = Math.max(1, Math.floor((h - 8) / lh));
        const words = String(n.title || "(untitled)").split(/\s+/);
        const lines = []; let line = "";
        words.forEach((wd) => {
          const test = line ? line + " " + wd : wd;
          if (ctx.measureText(test).width > w - 16 && line) { lines.push(line); line = wd; }
          else line = test;
        });
        if (line) lines.push(line);
        const show = lines.slice(0, maxLines);
        // A title too long for the box it's in is clipped, never overflowed —
        // make the box bigger and the rest appears.
        if (lines.length > maxLines) {
          show[maxLines - 1] = show[maxLines - 1].slice(0, Math.max(4, Math.floor(w / (fs * 0.55)))) + "…";
        }
        show.forEach((l, i) => ctx.fillText(l, n.x, n.y + (i - (show.length - 1) / 2) * lh));
      });
      ctx.restore();
    }

    connectBtn.addEventListener("click", () => {
      connectFrom = connectFrom ? null : "ARM";
      connectBtn.classList.toggle("armed", !!connectFrom);
      hint.textContent = connectFrom
        ? "Click the idea to connect FROM, then the one to connect TO."
        : IDLE_HINT;
      draw();
    });

    /* --- pointer: one handler, three jobs (resize / drag / pan) --------- */
    let dragging = null, sizing = null, panning = null, moved = false;

    const at = (ev) => {
      const r = canvas.getBoundingClientRect();
      return { x: ev.clientX - r.left, y: ev.clientY - r.top };
    };

    canvas.addEventListener("mousedown", (ev) => {
      const s = at(ev);
      const p = toWorld(s.x, s.y);
      if (connectFrom) return;                 // connecting is a click job, not a drag
      const grow = handleAt(p.x, p.y);
      if (grow) {
        sizing = { n: grow, w: boxW(grow), h: boxH(grow), x: p.x, y: p.y };
        moved = false;
        return;
      }
      const n = nodeAt(p.x, p.y);
      if (n) { dragging = n; moved = false; return; }
      panning = { x: s.x, y: s.y, ox: view.ox, oy: view.oy };
      moved = false;
    });

    const onMove = (ev) => {
      if (sizing) {
        const p = toWorld(at(ev).x, at(ev).y);
        const f = scaleOf().f;
        // The pointer sits on the corner, so the box is twice the offset from
        // the centre. Divided back out of the scale: what's stored is the base
        // size, and S/M/L multiplies it.
        sizing.n.w = Math.max(MIN_W, Math.min(MAX_W, ((p.x - sizing.n.x) * 2) / f));
        sizing.n.h = Math.max(MIN_H, Math.min(MAX_H, ((p.y - sizing.n.y) * 2) / f));
        moved = true;
        draw();
        return;
      }
      if (dragging) {
        const p = toWorld(at(ev).x, at(ev).y);
        dragging.x = p.x; dragging.y = p.y;
        moved = true;
        draw();
        return;
      }
      if (panning) {
        const s = at(ev);
        if (Math.abs(s.x - panning.x) > 3 || Math.abs(s.y - panning.y) > 3) moved = true;
        view.ox = panning.ox + (s.x - panning.x);
        view.oy = panning.oy + (s.y - panning.y);
        draw();
      }
    };
    window.addEventListener("mousemove", onMove);

    window.addEventListener("mouseup", () => {
      // Persist where it was dropped / how big it ended up, not every
      // intermediate pixel.
      if (sizing && moved) {
        const n = sizing.n;
        guard(() => api.projects.updateIdea(projectId, n.id,
          { w: Math.round(n.w), h: Math.round(n.h) }));
      } else if (dragging && moved) {
        const n = dragging;
        guard(() => api.projects.updateIdea(projectId, n.id,
          { x: Math.round(n.x), y: Math.round(n.y) }));
      } else if (panning && moved) {
        saveView(projectId, view);
      }
      sizing = null; dragging = null; panning = null;
    });

    canvas.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      zoomBy(ev.deltaY < 0 ? 1.12 : 1 / 1.12, at(ev));
    }, { passive: false });

    // A pointer over a corner should say so before you press it.
    canvas.addEventListener("mousemove", (ev) => {
      if (sizing || dragging || panning) return;
      const p = toWorld(at(ev).x, at(ev).y);
      canvas.style.cursor = handleAt(p.x, p.y) ? "nwse-resize"
        : nodeAt(p.x, p.y) ? "move" : "grab";
    });

    canvas.addEventListener("click", (ev) => {
      const p = toWorld(at(ev).x, at(ev).y);
      const n = nodeAt(p.x, p.y);

      if (connectFrom) {
        if (!n) return;
        if (connectFrom === "ARM") {
          connectFrom = n.id; draw();
          hint.textContent = "Now click the idea it connects TO.";
          return;
        }
        if (n.id === connectFrom) return;
        const from = connectFrom;
        connectFrom = null;
        connectBtn.classList.remove("armed");
        hint.textContent = IDLE_HINT;
        guard(async () => {
          await api.projects.connect(projectId, { from_id: from, to_id: n.id, label: "" });
          data = await api.projects.graph(projectId);
          seedPositions(); draw();
          toast("connected");
        });
        return;
      }
      if (moved) return;                     // a drag isn't a click
      const e = edgeAt(p.x, p.y);
      if (e) {
        guard(async () => {
          await api.projects.disconnect(projectId, e.id);
          data.edges = data.edges.filter((x2) => x2.id !== e.id);
          draw();
          toast("disconnected");
        });
      }
    });

    // The canvas has no size until it's in the document and laid out — and the
    // wrap is user-resizable, so its height changes without the window doing.
    requestAnimationFrame(() => {
      resize();
      if (!loadViews()[projectId]) fit();
      draw();
    });
    window.addEventListener("resize", resize);
    if (window.ResizeObserver) {
      let last = 0;
      new ResizeObserver(() => {
        resize();
        // Only remember a height the user chose, not one a re-layout produced.
        if (wrap.clientHeight && wrap.clientHeight !== last) {
          last = wrap.clientHeight;
          try { localStorage.setItem(HEIGHT_KEY, String(wrap.clientHeight)); } catch { /* ignore */ }
        }
      }).observe(wrap);
    }
  }

  /* ------------------------------------------------------------------ *
   * Register the three sub-views
   * ------------------------------------------------------------------ */
  window.PROJ_TABS = window.PROJ_TABS || [];
  window.PROJ_TABS.push(
    { key: "references", label: "References", render: renderReferences },
    { key: "database", label: "Database", render: renderDatabase },
    { key: "graph", label: "Knowledge Map", render: renderGraph },
  );
})();

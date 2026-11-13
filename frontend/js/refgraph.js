/* refgraph.js — Reference Map: a global citation graph on a hand-rolled <canvas>
   (zero graph libraries, per the local-first principle). Papers are hubs, their
   references are leaf nodes, plus manual nodes/edges.

   Layout: a force-directed sim with GRID (spatial-hash) repulsion — O(n) per
   tick, no recursion, no pathological blow-up — run under a per-frame time budget
   with a hard iteration cap, so the main thread never blocks even at thousands of
   nodes. Zoom/pan, hover-highlight, level-of-detail labels, filtering + search. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const COLOR = { paper: "#00D4AA", reference: "#5A9DE0", manual: "#F0A030" };
  // a work cited by more than one paper — the bridge between two clusters
  const SHARED_COLOR = "#DE7BA4";
  /* A starred reference. Deliberately brighter and colder than the amber of a
     manual link, because those are the only two warm edges on the map and they
     must not be mistaken for each other. Starred edges are also drawn thicker,
     so the distinction survives being read at a glance or in greyscale. */
  const STAR_COLOR = "#FFD426";
  /* A source is drawn as what it IS. Papers stay teal circles; a book, a video
     series or a course gets its own colour and shape, so a shelf of books
     doesn't read as a pile of papers. Shape carries the distinction as well as
     colour, which keeps it legible for anyone who can't separate the hues. */
  const KIND_STYLE = {
    paper:   { color: "#00D4AA", shape: "circle" },
    book:    { color: "#D4A017", shape: "square" },
    video:   { color: "#FF4757", shape: "triangle" },
    course:  { color: "#8B7EC8", shape: "diamond" },
    article: { color: "#5AC8E0", shape: "circle" },
    note:    { color: "#8194a8", shape: "diamond" },
    event:   { color: "#E0805A", shape: "square" },
  };
  const styleOf = (n) => (n.type === "paper" ? (KIND_STYLE[n.kind] || KIND_STYLE.paper) : null);

  /* Canvas has no "draw a polygon of radius r" — spell the four shapes out. */
  function nodePath(ctx, x, y, r, shape) {
    ctx.beginPath();
    if (shape === "square") { ctx.rect(x - r, y - r, r * 2, r * 2); return; }
    if (shape === "diamond") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y);
      ctx.closePath(); return;
    }
    if (shape === "triangle") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r, y + r * 0.8); ctx.lineTo(x - r, y + r * 0.8);
      ctx.closePath(); return;
    }
    ctx.arc(x, y, r, 0, Math.PI * 2);
  }
  const MONO = "11px ui-monospace, Menlo, monospace";
  const K = 55;            // ideal edge length
  const CELL = 120;        // repulsion grid cell (~2·K)
  const NEIGHBOR_CAP = 48; // max repulsion pairs considered per node/tick (bounds cost)
  const GRAVITY = 0.04;    // pull toward centre so clusters don't drift away
  const MAX_ITERS = 180;   // hard cap on layout ticks
  const FRAME_BUDGET_MS = 9; // main-thread budget per animation frame
  const ALPHA_MIN = 0.02;

  let CUR = null; // current runtime state (previous one is torn down)

  // deterministic RNG so the layout is stable across reloads
  function mulberry32(a) {
    return function () {
      a |= 0; a = a + 0x6D2B79F5 | 0;
      let t = Math.imul(a ^ a >>> 15, 1 | a);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
  }

  // ---------- one simulation tick (grid repulsion + edge springs + gravity) ----------
  function tick(S) {
    const nodes = S.nodes, rng = S.rng;
    // spatial hash
    const grid = new Map();
    for (const n of nodes) {
      n._dx = 0; n._dy = 0;
      const key = Math.floor(n.x / CELL) + "," + Math.floor(n.y / CELL);
      let a = grid.get(key); if (!a) { a = []; grid.set(key, a); } a.push(n);
    }
    // repulsion: only against nodes in the 3×3 neighbourhood, capped per node
    const reach2 = (CELL * 2) * (CELL * 2);
    for (const n of nodes) {
      const gx = Math.floor(n.x / CELL), gy = Math.floor(n.y / CELL);
      let cnt = 0;
      for (let ix = -1; ix <= 1 && cnt < NEIGHBOR_CAP; ix++) {
        for (let iy = -1; iy <= 1 && cnt < NEIGHBOR_CAP; iy++) {
          const arr = grid.get((gx + ix) + "," + (gy + iy)); if (!arr) continue;
          for (const m of arr) {
            if (m === n) continue;
            if (++cnt > NEIGHBOR_CAP) break;
            let dx = n.x - m.x, dy = n.y - m.y, d2 = dx * dx + dy * dy;
            if (d2 > reach2) continue;
            if (d2 < 0.01) { dx = rng() - 0.5; dy = rng() - 0.5; d2 = dx * dx + dy * dy + 0.01; }
            const f = K * K / d2;            // magnitude/dist already folded (dx*f is force·dir)
            n._dx += dx * f; n._dy += dy * f;
          }
        }
      }
    }
    // attraction along edges
    for (const e of S.edges) {
      const a = e.a, b = e.b; if (!a || !b) continue;
      let dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = d * d / K, ux = dx / d, uy = dy / d;
      a._dx += ux * f; a._dy += uy * f; b._dx -= ux * f; b._dy -= uy * f;
    }
    // gravity + integrate (temperature-limited, NaN-guarded)
    const temp = S.alpha * 60;
    for (const n of nodes) {
      if (n === S.dragNode) continue;
      n._dx -= n.x * GRAVITY; n._dy -= n.y * GRAVITY;
      let len = Math.sqrt(n._dx * n._dx + n._dy * n._dy);
      if (!(len > 0) || !isFinite(len)) continue;
      const step = Math.min(len, temp);
      const nx = n.x + n._dx / len * step, ny = n.y + n._dy / len * step;
      if (isFinite(nx) && isFinite(ny)) { n.x = nx; n.y = ny; }
    }
    S.alpha *= 0.96; S.iter++;
    if (S.alpha < ALPHA_MIN || S.iter >= MAX_ITERS) S.running = false;
  }

  // ---------- rendering ----------
  function visible(S, n) {
    const f = S.filters;
    // Sources are filtered per kind, so books can be shown without papers (or
    // the other way round); everything else is filtered by type.
    if (n.type === "paper") {
      if (f.kinds[n.kind || "paper"] === false) return false;
    } else if (!f.types[n.type]) {
      return false;
    }
    // "shared only" strips a reference cited by just one paper, leaving the
    // works that actually connect two clusters.
    if (n.type === "reference" && f.sharedOnly && !n.shared) return false;
    // "starred only" is the read-after list as a map: the works you marked,
    // plus the papers that made you mark them, and nothing else.
    if (f.starredOnly && !(S.starredSet && S.starredSet.has(n))) return false;
    const src = f.source;
    if (!src) return true;
    if (n.type === "manual") return true;
    if (n.type === "paper") return n.id === src;
    // a shared reference belongs to every paper that cites it
    return (n.paper_ids || [n.paper_id]).includes(src);
  }
  function project(S, n) { return { x: n.x * S.cam.scale + S.cam.tx, y: n.y * S.cam.scale + S.cam.ty }; }
  function radius(n) {
    if (n.type === "paper") return 6 + Math.min(n.deg, 60) * 0.22;
    if (n.type === "manual") return 5;
    // Shared works are the bridges between clusters — the whole point of the
    // map — so they're drawn larger, growing with how many papers cite them.
    if (n.shared) return 4.6 + Math.min((n.paper_ids || []).length, 8) * 0.9;
    return 3.4;
  }
  function render(S) {
    const ctx = S.ctx, W = S.cssW, H = S.cssH;
    ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const q = (S.filters.search || "").toLowerCase();
    const nb = S.hover ? S.neighbors : null;

    // Starred edges are drawn last so they sit on top of the grey mesh — the
    // whole point of the mark is that it survives a crowded map.
    const ordered = S.edges.filter((e) => !e.starred).concat(S.edges.filter((e) => e.starred));
    for (const e of ordered) {
      if (S.filters.starredOnly && !e.starred) continue;
      const a = e.a, b = e.b; if (!a || !b || !visible(S, a) || !visible(S, b)) continue;
      const pa = project(S, a), pb = project(S, b);
      if ((pa.x < 0 && pb.x < 0) || (pa.x > W && pb.x > W) || (pa.y < 0 && pb.y < 0) || (pa.y > H && pb.y > H)) continue;
      let alpha = 0.5;
      if (nb && !(nb.has(a) && nb.has(b))) alpha = 0.06;
      if (e.starred) {
        // A starred edge dims with the rest on hover, but never all the way to
        // invisible — you should still be able to see where your marks are.
        ctx.lineWidth = 2;
        ctx.strokeStyle = "rgba(255,212,38," + Math.max(alpha, 0.28) + ")";
      } else {
        ctx.lineWidth = 1;
        ctx.strokeStyle = e.kind === "manual" ? "rgba(240,160,48," + alpha + ")" : "rgba(90,120,150," + alpha + ")";
      }
      ctx.beginPath(); ctx.moveTo(pa.x, pa.y); ctx.lineTo(pb.x, pb.y); ctx.stroke();
    }
    ctx.lineWidth = 1;
    for (const n of S.nodes) {
      if (!visible(S, n)) continue;
      const p = project(S, n); const r = radius(n);
      if (p.x < -r || p.x > W + r || p.y < -r || p.y > H + r) continue;
      let a = 1;
      if (q) a = n.label && n.label.toLowerCase().includes(q) ? 1 : 0.12;
      else if (nb && !nb.has(n)) a = 0.18;
      ctx.globalAlpha = a;
      const st = styleOf(n);
      nodePath(ctx, p.x, p.y, r, st ? st.shape : "circle");
      ctx.fillStyle = st ? st.color
        : n.shared ? SHARED_COLOR
        : (COLOR[n.type] || "#888");
      ctx.fill();
      if (n.shared) { ctx.lineWidth = 1; ctx.strokeStyle = "#fff6"; ctx.stroke(); }
      // Zoomed out, the edge colour is a hairline — the ring is what makes a
      // starred work findable in the mass.
      if (n.starred) { ctx.lineWidth = 1.6; ctx.strokeStyle = STAR_COLOR; ctx.stroke(); }
      if (n === S.selected || n === S.hover) { ctx.lineWidth = 2; ctx.strokeStyle = "#fff"; ctx.stroke(); }
      ctx.globalAlpha = 1;
      // shared works get a label unprompted — they're what you're looking for
      const labeled = n.type === "paper" || n.shared || n.starred || n === S.selected || n === S.hover || (nb && nb.has(n)) || S.cam.scale > 1.25 || (q && a === 1);
      if (labeled && n.label) {
        ctx.font = MONO; ctx.fillStyle = "#c7d2de"; ctx.textAlign = "left";
        ctx.fillText(n.label.slice(0, n.type === "paper" ? 40 : 26), p.x + r + 3, p.y + 3.5);
      }
    }
  }

  // ---------- interaction helpers ----------
  function screenToWorld(S, mx, my) { return { x: (mx - S.cam.tx) / S.cam.scale, y: (my - S.cam.ty) / S.cam.scale }; }
  function hitTest(S, mx, my) {
    let best = null, bestD = Infinity;
    for (const n of S.nodes) {
      if (!visible(S, n)) continue;
      const p = project(S, n), r = radius(n) + 4;
      const d = (mx - p.x) ** 2 + (my - p.y) ** 2;
      if (d <= r * r && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }
  function computeNeighbors(S, n) {
    const set = new Set([n]);
    for (const e of S.edges) { if (e.a === n) set.add(e.b); else if (e.b === n) set.add(e.a); }
    return set;
  }
  function fit(S) {
    const vis = S.nodes.filter((n) => visible(S, n));
    if (!vis.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of vis) { minX = Math.min(minX, n.x); minY = Math.min(minY, n.y); maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y); }
    const w = maxX - minX || 1, h = maxY - minY || 1;
    const scale = Math.min(S.cssW / (w + 120), S.cssH / (h + 120), 2.5);
    S.cam.scale = Math.max(scale, 0.05);
    S.cam.tx = S.cssW / 2 - (minX + maxX) / 2 * S.cam.scale;
    S.cam.ty = S.cssH / 2 - (minY + maxY) / 2 * S.cam.scale;
    S.needsDraw = true;
  }

  // ---------- setup ----------
  function initPositions(S) {
    const rng = mulberry32(1337);
    const papers = S.nodes.filter((n) => n.type === "paper");
    const np = Math.max(papers.length, 1);
    const R = 160 + np * 45;
    const paperPos = {};
    papers.forEach((p, i) => {
      const ang = (i / np) * Math.PI * 2;
      p.x = Math.cos(ang) * R; p.y = Math.sin(ang) * R; paperPos[p.id] = p;
    });
    for (const n of S.nodes) {
      if (n.type === "paper") continue;
      const host = n.type === "reference" && paperPos[n.paper_id];
      const base = host || { x: 0, y: 0 };
      n.x = base.x + (rng() - 0.5) * 200;
      n.y = base.y + (rng() - 0.5) * 200;
    }
  }

  /* Every node a starred edge touches: the marked work AND the paper you
     starred it from. Recomputed on load and on reload — a star set in the
     Workspace only reaches the map through a fresh payload. */
  function computeStarred(S) {
    const set = new Set();
    for (const e of S.edges) { if (e.starred) { set.add(e.a); set.add(e.b); } }
    S.starredSet = set;
    return set;
  }

  function buildNodesEdges(data) {
    const nodes = data.nodes.map((n) => ({ ...n, x: 0, y: 0, deg: 0 }));
    const byId = {}; nodes.forEach((n) => (byId[n.id] = n));
    const edges = data.edges.map((e) => ({ ...e, a: byId[e.source], b: byId[e.target] })).filter((e) => e.a && e.b);
    edges.forEach((e) => { e.a.deg++; e.b.deg++; });
    return { nodes, edges, byId };
  }

  function buildState(canvas, stage, data) {
    const { nodes, edges, byId } = buildNodesEdges(data);
    const S = {
      canvas, ctx: canvas.getContext("2d"), stage, dpr: window.devicePixelRatio || 1,
      cssW: 800, cssH: 620, nodes, edges, byId, rng: mulberry32(99),
      cam: { scale: 1, tx: 400, ty: 310 },
      alpha: 1, iter: 0, running: true, needsDraw: true, destroyed: false,
      hover: null, selected: null, neighbors: null, dragNode: null, panning: false,
      down: null, moved: false, linkFrom: null,
      // `kinds` is keyed by source kind (paper/book/video…) and defaults to
      // shown — an unlisted kind must never disappear just because it's new.
      filters: { types: { paper: true, reference: true, manual: true },
                 kinds: {}, sharedOnly: false, starredOnly: false, source: "", search: "" },
      starredSet: new Set(),
      detailEl: null, onCounts: null, _mm: null, _mu: null, _resize: null,
    };
    computeStarred(S);
    initPositions(S);
    return S;
  }

  function sizeCanvas(S) {
    const w = S.stage.clientWidth || 800;
    S.cssW = w; S.cssH = 620; S.dpr = window.devicePixelRatio || 1;
    S.canvas.width = Math.round(w * S.dpr); S.canvas.height = Math.round(620 * S.dpr);
    S.canvas.style.width = w + "px"; S.canvas.style.height = "620px";
    S.needsDraw = true;
  }

  function teardown(S) {
    if (!S) return;
    S.destroyed = true;
    if (S._mm) window.removeEventListener("mousemove", S._mm);
    if (S._mu) window.removeEventListener("mouseup", S._mu);
    if (S._resize) window.removeEventListener("resize", S._resize);
  }

  function wire(S) {
    const c = S.canvas;
    function mpos(ev) { const r = c.getBoundingClientRect(); return { x: ev.clientX - r.left, y: ev.clientY - r.top }; }
    c.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const m = mpos(ev); const factor = Math.exp(-ev.deltaY * 0.0015);
      const ns = Math.max(0.05, Math.min(8, S.cam.scale * factor));
      const w = screenToWorld(S, m.x, m.y);
      S.cam.scale = ns; S.cam.tx = m.x - w.x * ns; S.cam.ty = m.y - w.y * ns; S.needsDraw = true;
    }, { passive: false });
    c.addEventListener("mousedown", (ev) => {
      const m = mpos(ev); const n = hitTest(S, m.x, m.y);
      S.down = m; S.moved = false;
      if (n) { S.dragNode = n; } else { S.panning = true; c.classList.add("grabbing"); }
    });
    S._mm = (ev) => {
      const m = mpos(ev);
      if (S.dragNode) {
        const w = screenToWorld(S, m.x, m.y); S.dragNode.x = w.x; S.dragNode.y = w.y;
        S.alpha = Math.max(S.alpha, 0.3); S.iter = Math.min(S.iter, MAX_ITERS - 30); S.running = true; S.moved = true; S.needsDraw = true;
      } else if (S.panning) {
        S.cam.tx += m.x - S.down.x; S.cam.ty += m.y - S.down.y; S.down = m; S.moved = true; S.needsDraw = true;
      } else {
        const n = hitTest(S, m.x, m.y);
        if (n !== S.hover) { S.hover = n; S.neighbors = n ? computeNeighbors(S, n) : null; S.needsDraw = true; }
      }
    };
    S._mu = (ev) => {
      const m = mpos(ev);
      const click = S.down && Math.hypot(m.x - S.down.x, m.y - S.down.y) < 4 && !S.moved;
      if (click) {
        const n = hitTest(S, m.x, m.y);
        if (S.linkFrom && n && n !== S.linkFrom) { createEdge(S, S.linkFrom, n); S.linkFrom = null; }
        else { select(S, n); }
      }
      S.dragNode = null; S.panning = false; S.down = null; S.moved = false; c.classList.remove("grabbing");
    };
    S._resize = () => sizeCanvas(S);
    window.addEventListener("mousemove", S._mm);
    window.addEventListener("mouseup", S._mu);
    window.addEventListener("resize", S._resize);
  }

  function startLoop(S) {
    function frame() {
      if (S.destroyed) return;
      if (S.running) {
        const start = performance.now();
        do { tick(S); } while (S.running && performance.now() - start < FRAME_BUDGET_MS);
        S.needsDraw = true;
      }
      if (S.needsDraw) { render(S); S.needsDraw = false; }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  // ---------- detail panel + mutations ----------
  function select(S, n) { S.selected = n; S.linkFrom = null; renderDetail(S); S.needsDraw = true; }
  function renderDetail(S) {
    const host = S.detailEl; clear(host);
    const n = S.selected;
    if (!n) { host.style.display = "none"; return; }
    host.style.display = "block";
    host.appendChild(el("h4", { text: n.label || "(untitled)" }));
    host.appendChild(el("div.rg-kv", { text: "type: "
      + (n.type === "paper" ? (n.kind || "paper") : n.type)
      + (n.year ? " · " + n.year : "") + " · " + n.deg + " links" }));
    if (n.link) host.appendChild(el("div.rg-kv", {}, [el("a", { href: n.link, target: "_blank", rel: "noopener noreferrer", text: n.link.slice(0, 42) })]));
    // The note is the reason the edge is yellow, so it reads before anything
    // else about the node — it's what you came here to be reminded of.
    (n.notes || []).forEach((x) => {
      const src = S.byId[x.paper_id];
      host.appendChild(el("div.rg-kv", { style: "color:" + STAR_COLOR + ";border-left:2px solid " + STAR_COLOR + ";padding-left:7px" },
        [el("div", { text: "★ " + x.note }),
         src ? el("div", { style: "color:var(--muted);margin-top:2px", text: "from " + src.label.slice(0, 30) }) : null]));
    });
    if (n.starred && !(n.notes || []).length) {
      host.appendChild(el("div.rg-kv", { style: "color:" + STAR_COLOR, text: "★ starred — no note yet" }));
    }
    if (n.type === "reference") {
      // Every paper that cites this work, not just the one it's parked next to.
      const ids = n.paper_ids || (n.paper_id ? [n.paper_id] : []);
      if (ids.length > 1) {
        host.appendChild(el("div.rg-kv", { style: "color:" + SHARED_COLOR,
          text: "cited by " + ids.length + " of your papers" }));
      }
      ids.forEach((pid) => {
        const src = S.byId[pid];
        host.appendChild(el("div.rg-kv", {}, [el("a", {
          href: "#", style: "color:var(--teal)",
          onclick: (e) => { e.preventDefault(); window.PM.selectPaper(pid); },
          text: "▸ from: " + (src ? src.label.slice(0, 30) : "paper"),
        })]));
      });
    }
    const acts = el("div.row", { style: "margin-top:10px;gap:6px" });
    acts.appendChild(el("button.btn-sm", { onclick: () => { S.linkFrom = n; toast("now click a target node to link"); }, text: "＋ link from here" }));
    if (n.type === "manual") acts.appendChild(el("button.btn-sm.btn-danger", { onclick: () => guard(async () => { await api.refgraph.delNode(n.id); reloadGraph(S); }), text: "× delete" }));
    host.appendChild(acts);
  }
  async function createEdge(S, a, b) {
    await guard(async () => { await api.refgraph.addEdge({ source_id: a.id, target_id: b.id, label: "relates" }); });
    toast("linked"); reloadGraph(S);
  }

  async function reloadGraph(S) {
    const data = await guard(() => api.refgraph.get());
    const oldPos = {}; S.nodes.forEach((n) => (oldPos[n.id] = { x: n.x, y: n.y }));
    const { nodes, edges, byId } = buildNodesEdges(data);
    S.nodes = nodes; S.edges = edges; S.byId = byId;
    computeStarred(S);
    let placed = 0;
    for (const n of nodes) { if (oldPos[n.id]) { n.x = oldPos[n.id].x; n.y = oldPos[n.id].y; placed++; } }
    if (placed < nodes.length) initPositions(S);
    S.selected = null; renderDetail(S); S.alpha = Math.max(S.alpha, 0.4); S.iter = 0; S.running = true; S.needsDraw = true;
    if (S.onCounts) S.onCounts(data.counts);
  }

  // ---------- view ----------
  window.Views = window.Views || {};
  window.Views.refgraph = {
    id: "refgraph", label: "Reference Map", scoped: false,
    async render(view) {
      teardown(CUR); // stop any prior loop + listeners
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Reference Map" }),
        el("div.sub", { text: "Every paper and its references as a graph — scroll to zoom, drag to pan, click a node." }),
      ])]));

      const data = await guard(() => api.refgraph.get());
      const toolbar = el("div.rg-toolbar"); view.appendChild(toolbar);

      const stage = el("div.rg-stage");
      const canvas = el("canvas.rg-canvas");
      const detail = el("div.rg-detail", { style: "display:none" });
      stage.appendChild(canvas);
      stage.appendChild(el("div.rg-hint", { text: "scroll = zoom · drag = pan · drag node = move · click = details" }));
      stage.appendChild(detail);
      view.appendChild(stage);

      const S = buildState(canvas, stage, data);
      S.detailEl = detail;
      CUR = S;

      // Legend counts each kind that's actually present, with its own glyph, so
      // the shapes on the canvas are readable without guessing.
      const GLYPH = { circle: "●", square: "■", triangle: "▲", diamond: "◆" };
      const countsEl = el("span.rg-legend");
      const paintCounts = (c) => {
        clear(countsEl);
        const byKind = {};
        S.nodes.filter((n) => n.type === "paper")
          .forEach((n) => { const k = n.kind || "paper"; byKind[k] = (byKind[k] || 0) + 1; });
        Object.keys(byKind).sort().forEach((k) => {
          const st = KIND_STYLE[k] || KIND_STYLE.paper;
          countsEl.appendChild(el("b", { style: "color:" + st.color,
            text: GLYPH[st.shape] + " " + k + (byKind[k] === 1 ? "" : "s") + " " + byKind[k] }));
        });
        // .append() is not el()'s children list — a null here would render the
        // literal text "null", so drop them first.
        countsEl.append(...[
          el("b", { style: "color:" + COLOR.reference, text: "● refs " + c.references }),
          c.shared ? el("b", { style: "color:" + SHARED_COLOR,
            title: "works cited by more than one of your papers — the bridges between clusters",
            text: "● shared " + c.shared }) : null,
          c.resolved_to_papers ? el("b", { style: "color:" + COLOR.paper,
            title: "references that resolved to a paper you hold, so they link paper→paper",
            text: "↳ resolved " + c.resolved_to_papers }) : null,
          c.starred ? el("b", { style: "color:" + STAR_COLOR,
            title: "starred in the Workspace — the yellow edges; click one's node to read the note",
            text: "★ starred " + c.starred }) : null,
          el("b", { style: "color:" + COLOR.manual, text: "● manual " + c.manual }),
          el("b", { text: c.edges + " links" }),
        ].filter(Boolean));
      };
      S.onCounts = paintCounts; paintCounts(data.counts);

      /* One toggle per kind actually present — books can be shown without
         papers, or on their own — plus references, shared-only, and manual.
         Built from the data so a new kind appears here without a code change. */
      const kindsPresent = [...new Set(S.nodes.filter((n) => n.type === "paper")
        .map((n) => n.kind || "paper"))].sort();
      const kindToggles = kindsPresent.map((k) => {
        const st = KIND_STYLE[k] || KIND_STYLE.paper;
        const cb = el("input", { type: "checkbox", checked: true });
        cb.addEventListener("change", () => { S.filters.kinds[k] = cb.checked; S.needsDraw = true; });
        return el("label.rg-toggle", { title: "show/hide " + k + " nodes" },
          [cb, el("span", { style: "color:" + st.color, text: k + (k.endsWith("s") ? "" : "s") })]);
      });

      const otherToggles = ["reference", "manual"].map((t) => {
        const cb = el("input", { type: "checkbox", checked: true });
        cb.addEventListener("change", () => { S.filters.types[t] = cb.checked; S.needsDraw = true; });
        return el("label.rg-toggle", {}, [cb, el("span", { style: "color:" + COLOR[t], text: t + "s" })]);
      });

      // Shared-only is the "just the connections" view: strip every reference
      // cited by a single paper and what's left is exactly the shared ground.
      const sharedCb = el("input", { type: "checkbox" });
      sharedCb.addEventListener("change", () => { S.filters.sharedOnly = sharedCb.checked; S.needsDraw = true; });
      const sharedToggle = el("label.rg-toggle", { title: "hide references only one paper cites, leaving the works that connect them" },
        [sharedCb, el("span", { style: "color:" + SHARED_COLOR, text: "shared only" })]);

      // The read-after view: only the edges you starred, and their two ends.
      const starCb = el("input", { type: "checkbox" });
      starCb.addEventListener("change", () => { S.filters.starredOnly = starCb.checked; S.needsDraw = true; fit(S); });
      const starToggle = el("label.rg-toggle", { title: "show only the works you starred in the Workspace, and the papers you starred them from" },
        [starCb, el("span", { style: "color:" + STAR_COLOR, text: "★ starred only" })]);

      const typeToggles = [...kindToggles, ...otherToggles, sharedToggle, starToggle];

      const sourceSel = el("select", { style: "max-width:180px" }, [el("option", { value: "", text: "all papers" }),
        ...S.nodes.filter((n) => n.type === "paper").map((p) => el("option", { value: p.id, text: p.label.slice(0, 34) }))]);
      sourceSel.addEventListener("change", () => { S.filters.source = sourceSel.value; fit(S); });

      const searchIn = el("input", { placeholder: "search…", style: "width:130px" });
      searchIn.addEventListener("input", () => { S.filters.search = searchIn.value.trim(); S.needsDraw = true; });

      toolbar.append(
        countsEl,
        el("span", { style: "flex:1" }),
        ...typeToggles,
        sourceSel, searchIn,
        el("button.btn-sm", { onclick: () => fit(S), text: "fit" }),
        el("button.btn-sm", { onclick: () => { S.alpha = 1; S.iter = 0; S.running = true; }, text: "re-run layout" }),
        el("button.btn-sm", { onclick: () => addNodeFlow(S), text: "＋ node" }),
      );

      view.appendChild(paperSheet());

      sizeCanvas(S); wire(S); startLoop(S);
      setTimeout(() => { if (!S.destroyed) fit(S); }, 500);
    },
  };

  /* ---- the sheet underneath the map -----------------------------------
     One row per paper: how well you understand it, where you are with it,
     and how wired into the library it is. Collapsed by default so the map
     stays the main event. */
  const READ_STATES = ["unread", "reading", "read", "revisit", "shelved"];
  const READ_LABEL = { unread: "unread", reading: "reading", read: "read", revisit: "go over again", shelved: "shelved" };
  const READ_COLOR = { unread: "var(--muted)", reading: "var(--amber)", read: "var(--teal)", revisit: "var(--red)", shelved: "var(--purple)" };
  // 0-10 → red through amber to teal
  function scoreColor(v) {
    if (v == null) return "var(--muted)";
    return v <= 3 ? "var(--red)" : v <= 6 ? "var(--amber)" : "var(--teal)";
  }

  function paperSheet() {
    const wrap = el("div.card", { style: "margin-top:14px" });
    const body = el("div");
    let open = false;
    const btn = el("button.btn-sm", { onclick: () => { open = !open; draw(); }, text: "▸ open" });
    wrap.appendChild(el("div.spread", {}, [
      el("div", {}, [
        el("h3", { style: "margin:0", text: "Papers sheet" }),
        el("div.sub", { text: "Understanding score, read state, and how connected each paper is" }),
      ]),
      btn,
    ]));
    wrap.appendChild(body);

    function draw() {
      clear(body);
      btn.textContent = open ? "▾ close" : "▸ open";
      if (!open) return;
      body.appendChild(el("div.sub", { style: "margin-top:10px", text: "loading…" }));
      guard(async () => {
        const rows = await api.get("/api/synapse/refs/table");
        clear(body);
        const t = el("table.wk-table");
        t.appendChild(el("tr", {}, ["score", "paper", "read state", "links", "nodes", "refs", "passes", "highlights", "time"]
          .map((h) => el("th", { text: h }))));
        rows.forEach((r) => {
          // score first, as asked — editable 0-10
          const score = el("input.wk-cell", {
            type: "number", min: "0", max: "10", style: "width:46px;font-weight:700;color:" + scoreColor(r.understanding),
            value: r.understanding == null ? "" : String(r.understanding),
          });
          score.addEventListener("change", () => guard(async () => {
            const v = score.value === "" ? null : Math.max(0, Math.min(10, Number(score.value)));
            await api.papers.update(r.id, { understanding: v });
            score.style.color = scoreColor(v);
            toast("understanding → " + (v == null ? "—" : v + "/10"));
          }));
          const state = el("select.wk-cell", { style: "color:" + READ_COLOR[r.status] },
            READ_STATES.map((s) => {
              const o = el("option", { value: s, text: READ_LABEL[s] });
              if (s === r.status) o.setAttribute("selected", "");
              return o;
            }));
          state.addEventListener("change", () => guard(async () => {
            await api.papers.update(r.id, { status: state.value });
            state.style.color = READ_COLOR[state.value];
            toast(READ_LABEL[state.value]);
          }));
          const num = (v, hint) => el("td", { class: "mono", style: "font-size:11px;text-align:center;color:" + (v ? "var(--text)" : "var(--muted)"), title: hint || "", text: String(v || 0) });
          t.appendChild(el("tr.wk-row", {}, [
            el("td", {}, [score]),
            el("td", { style: "min-width:230px", text: r.title }),
            el("td", { style: "min-width:120px" }, [state]),
            num(r.links, "citations in + out + references that resolved to a paper you own"),
            num(r.nodes, "KG nodes + concepts introduced"),
            num(r.refs), num(r.passes), num(r.highlights),
            el("td", { class: "mono", style: "font-size:11px;text-align:center;color:var(--dim)", text: window.WorkLog ? window.WorkLog.fmtMins(r.mins) : String(r.mins) }),
          ]));
        });
        body.appendChild(el("div.wk-scroll", { style: "margin-top:10px" }, [t]));
        const csv = ["score,paper,read_state,links,nodes,refs,passes,highlights,mins"]
          .concat(rows.map((r) => [r.understanding == null ? "" : r.understanding,
            '"' + (r.title || "").replace(/"/g, '""') + '"', r.status,
            r.links, r.nodes, r.refs, r.passes, r.highlights, r.mins].join(",")));
        body.appendChild(el("div.row", { style: "margin-top:8px" }, [
          el("a.btn-sm", {
            style: "text-decoration:none",
            href: "data:text/csv;charset=utf-8," + encodeURIComponent(csv.join("\n")),
            download: "papers.csv", text: "⬇ CSV",
          }),
        ]));
      });
    }
    draw();
    return wrap;
  }

  function addNodeFlow(S) {
    const label = window.prompt("New manual node label:");
    if (!label || !label.trim()) return;
    guard(async () => { await api.refgraph.addNode({ label: label.trim(), type: "note" }); reloadGraph(S); });
  }
})();

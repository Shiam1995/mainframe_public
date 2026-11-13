/* framework.js — the approach I'm taking, and why.

   Four pieces of prose (title · approach · why · what I ruled out), a simple
   box diagram, and any ideas worth keeping next to the reasoning.

   The diagram is deliberately crude: coloured rectangles you type into, drag
   around, and optionally join with arrows. That is what "simple box diagram"
   means, and the alternative — a real diagramming tool — is a project in
   itself. Boxes snap to a grid so a drawing made in thirty seconds still
   lines up. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const STATUSES = [
    { v: "current", t: "current", c: "var(--green)" },
    { v: "considering", t: "considering", c: "var(--amber)" },
    { v: "superseded", t: "superseded", c: "var(--dim)" },
  ];
  // Deliberately few. A palette of forty makes every diagram a colour choice.
  const COLOURS = ["#00D4AA", "#5A9DE0", "#DE7BA4", "#F0A030", "#8B7EC8",
                   "#4ADE80", "#E05A5A", "#7B8BA3"];
  const GRID = 10;
  const BOX_W = 132, BOX_H = 56;

  let list = [];
  let current = null;
  let listHost = null, paneHost = null;

  const snap = (n) => Math.round(n / GRID) * GRID;
  const statusOf = (v) => STATUSES.find((s) => s.v === v) || STATUSES[0];

  /* ------------------------------------------------------------------ *
   * The diagram
   * ------------------------------------------------------------------ */
  function diagram(f, host) {
    const wrap = el("div.fw-canvas");
    let boxes = (f.boxes || []).map((b) => ({ ...b }));
    let arrows = (f.arrows || []).map((a) => ({ ...a }));
    let linkFrom = null;
    let dirty = false;

    const save = () => guard(async () => {
      await api.framework.saveDiagram(f.id, { boxes, arrows });
      dirty = false;
      toast("diagram saved");
    });

    // Autosave shortly after you stop fiddling, so a drag isn't a write each.
    let timer = null;
    const queueSave = () => {
      dirty = true;
      clearTimeout(timer);
      timer = setTimeout(() => { if (dirty) save(); }, 900);
    };

    function draw() {
      clear(wrap);

      // Arrows first, so boxes sit on top of their own connections.
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("class", "fw-arrows");
      arrows.forEach((a) => {
        const from = boxes.find((b) => b.id === a.from);
        const to = boxes.find((b) => b.id === a.to);
        if (!from || !to) return;
        const x1 = from.x + BOX_W / 2, y1 = from.y + BOX_H / 2;
        const x2 = to.x + BOX_W / 2, y2 = to.y + BOX_H / 2;
        const ang = Math.atan2(y2 - y1, x2 - x1);
        // Stop the line at the edge of the target box, not its centre.
        const ex = x2 - Math.cos(ang) * (BOX_W / 2 + 6);
        const ey = y2 - Math.sin(ang) * (BOX_H / 2 + 6);
        const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
        line.setAttribute("x1", x1); line.setAttribute("y1", y1);
        line.setAttribute("x2", ex); line.setAttribute("y2", ey);
        line.setAttribute("class", "fw-arrow");
        line.addEventListener("click", () => {
          arrows = arrows.filter((z) => z !== a);
          queueSave(); draw();
        });
        svg.appendChild(line);
        const head = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
        head.setAttribute("points", [
          [ex, ey],
          [ex - Math.cos(ang - 0.4) * 10, ey - Math.sin(ang - 0.4) * 10],
          [ex - Math.cos(ang + 0.4) * 10, ey - Math.sin(ang + 0.4) * 10],
        ].map((p) => p.join(",")).join(" "));
        head.setAttribute("class", "fw-arrowhead");
        svg.appendChild(head);
      });
      wrap.appendChild(svg);

      boxes.forEach((b) => {
        const node = el("div.fw-box" + (linkFrom === b.id ? ".linking" : ""), {
          style: `left:${b.x}px;top:${b.y}px;width:${BOX_W}px;height:${BOX_H}px;`
               + `border-color:${b.colour};box-shadow:inset 0 0 0 999px ${b.colour}1a`,
        });

        const text = el("textarea.fw-box-t", { spellcheck: false });
        text.value = b.text || "";
        text.addEventListener("input", () => { b.text = text.value; queueSave(); });
        node.appendChild(text);

        const tools = el("div.fw-box-tools", {}, [
          el("button.fw-box-btn", { title: "colour", text: "◧",
            onclick: (e) => {
              e.stopPropagation();
              b.colour = COLOURS[(COLOURS.indexOf(b.colour) + 1) % COLOURS.length];
              queueSave(); draw();
            } }),
          el("button.fw-box-btn", { title: "draw an arrow from here", text: "→",
            onclick: (e) => {
              e.stopPropagation();
              if (linkFrom && linkFrom !== b.id) {
                arrows.push({ from: linkFrom, to: b.id });
                linkFrom = null;
              } else {
                linkFrom = linkFrom === b.id ? null : b.id;
              }
              queueSave(); draw();
            } }),
          el("button.fw-box-btn.fw-box-del", { title: "delete", text: "×",
            onclick: (e) => {
              e.stopPropagation();
              boxes = boxes.filter((z) => z.id !== b.id);
              arrows = arrows.filter((a) => a.from !== b.id && a.to !== b.id);
              queueSave(); draw();
            } }),
        ]);
        node.appendChild(tools);

        /* Drag and type have to share the same surface: the textarea fills the
           box, so if it swallowed mousedown you could only drag by the 2px
           border. Instead, a press starts a *potential* drag — move past a few
           pixels and it becomes one (and the caret is dropped); release
           without moving and it's an ordinary click that focuses the text. */
        node.addEventListener("mousedown", (ev) => {
          if (linkFrom) {
            ev.preventDefault();
            if (linkFrom !== b.id) { arrows.push({ from: linkFrom, to: b.id }); }
            linkFrom = null; queueSave(); draw();
            return;
          }
          const startX = ev.clientX, startY = ev.clientY;
          const ox = b.x, oy = b.y;
          let dragging = false;
          const move = (e2) => {
            const dx = e2.clientX - startX, dy = e2.clientY - startY;
            if (!dragging) {
              if (Math.hypot(dx, dy) < 4) return;
              dragging = true;
              if (document.activeElement) document.activeElement.blur();
            }
            b.x = Math.max(0, snap(ox + dx));
            b.y = Math.max(0, snap(oy + dy));
            node.style.left = b.x + "px";
            node.style.top = b.y + "px";
            draw();
          };
          const up = () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", up);
            if (dragging) queueSave();
          };
          window.addEventListener("mousemove", move);
          window.addEventListener("mouseup", up);
        });

        wrap.appendChild(node);
      });
    }

    const addBox = el("button.fw-act", { text: "＋ box", onclick: () => {
      // New boxes cascade instead of stacking exactly on top of each other.
      const n = boxes.length;
      boxes.push({
        id: "b" + Date.now() + n,
        text: "", colour: COLOURS[n % COLOURS.length],
        x: snap(40 + (n % 5) * (BOX_W + 24)),
        y: snap(40 + Math.floor(n / 5) * (BOX_H + 34)),
      });
      queueSave(); draw();
    } });
    const saveNow = el("button.fw-act", { text: "save", onclick: () => save() });

    host.appendChild(el("div.row", { style: "gap:6px;align-items:center;margin-bottom:8px" }, [
      addBox, saveNow,
      el("span.sub", { style: "font-size:11px",
        text: "drag to move · → then another box draws an arrow · click a line to delete it" }),
    ]));
    host.appendChild(wrap);
    draw();
  }

  /* ------------------------------------------------------------------ *
   * The editor
   * ------------------------------------------------------------------ */
  function field(label, value, placeholder, onSave, rows) {
    const ta = el("textarea.fw-text", { rows: rows || 3, placeholder });
    ta.value = value || "";
    ta.addEventListener("change", () => onSave(ta.value));
    return el("label.fw-field", {}, [el("span.fw-label", { text: label }), ta]);
  }

  async function renderPane() {
    clear(paneHost);
    if (!current) {
      paneHost.appendChild(el("div.fw-empty", {}, [
        el("div", { style: "font-size:15px;margin-bottom:6px", text: "No framework open" }),
        el("div.sub", { text: "Write down the approach you're taking — and why you chose it over the alternative." }),
      ]));
      return;
    }
    const f = current;

    const titleIn = el("input.fw-title", { value: f.title || "" });
    titleIn.addEventListener("change", () => guard(async () => {
      await api.framework.update(f.id, { title: titleIn.value.trim() || "Untitled" });
      await reloadList();
    }));

    const statusSel = el("select.fw-mini", {}, STATUSES.map((s) =>
      el("option", { value: s.v, text: s.t })));
    statusSel.value = f.status || "current";
    statusSel.style.color = statusOf(statusSel.value).c;
    statusSel.addEventListener("change", () => guard(async () => {
      await api.framework.update(f.id, { status: statusSel.value });
      statusSel.style.color = statusOf(statusSel.value).c;
      await reloadList();
    }));

    const del = el("button.fw-act.danger", { text: "🗑 delete" });
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) { armed = true; del.textContent = "click again"; del.classList.add("armed"); return; }
      guard(async () => {
        await api.framework.del(f.id);
        current = null;
        await reloadList();
        renderPane();
      });
    });

    paneHost.appendChild(el("div.fw-head", {}, [titleIn, statusSel, del]));

    const patch = (k) => (v) => guard(() => api.framework.update(f.id, { [k]: v }));
    paneHost.appendChild(field("the approach", f.approach,
      "what I'm actually doing", patch("approach"), 3));
    paneHost.appendChild(field("why", f.why,
      "the reasoning — what makes this the right call right now", patch("why"), 4));
    paneHost.appendChild(field("ruled out", f.rejected,
      "what I chose against, and why — so I don't relitigate it in a month",
      patch("rejected"), 3));

    /* --- ideas kept beside the reasoning --- */
    paneHost.appendChild(el("div.fw-label", { style: "margin-top:14px", text: "ideas" }));
    const ideas = el("div.fw-ideas");
    (f.ideas || []).forEach((i) => {
      ideas.appendChild(el("span.fw-idea", {}, [
        document.createTextNode(i.title || "(untitled)"),
        el("button.fw-idea-x", { text: "×", onclick: () => guard(async () => {
          await api.framework.detachIdea(f.id, i.id);
          current = await api.framework.get(f.id);
          renderPane();
        }) }),
      ]));
    });
    const ideaIn = el("input.fw-idea-new", { placeholder: "+ an idea…" });
    ideaIn.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || !ideaIn.value.trim()) return;
      guard(async () => {
        current = await api.framework.attachIdea(f.id, { title: ideaIn.value.trim() });
        ideaIn.value = "";
        renderPane();
      });
    });
    ideas.appendChild(ideaIn);
    paneHost.appendChild(ideas);

    /* --- the drawing --- */
    paneHost.appendChild(el("div.fw-label", { style: "margin-top:16px", text: "diagram" }));
    diagram(f, paneHost);
  }

  async function reloadList() {
    list = await api.framework.list();
    clear(listHost);
    if (!list.length) {
      listHost.appendChild(el("div.sub", { style: "padding:12px 4px",
                                           text: "no frameworks yet" }));
      return;
    }
    list.forEach((f) => {
      const s = statusOf(f.status);
      listHost.appendChild(el("button.fw-item" + (current && f.id === current.id ? ".active" : ""), {
        onclick: () => guard(async () => {
          current = await api.framework.get(f.id);
          await reloadList();
          renderPane();
        }),
      }, [
        el("div.fw-item-t", { text: f.title }),
        el("div.fw-item-m", {}, [
          el("span", { style: "color:" + s.c, text: s.t }),
          f.box_count ? el("span", { text: " · " + f.box_count + " boxes" }) : null,
        ]),
      ]));
    });
  }

  window.Views = window.Views || {};
  window.Views.framework = {
    id: "framework", label: "Framework", scoped: false,
    async render(viewEl) {
      clear(viewEl);
      viewEl.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Framework" }),
        el("div.sub", { text: "The approach you're taking, and why — the part you can't reconstruct later." }),
      ])]));

      const newBtn = el("button.btn-primary", { text: "+ new", onclick: () => guard(async () => {
        const f = await api.framework.create({ title: "New approach" });
        current = await api.framework.get(f.id);
        await reloadList();
        renderPane();
      }) });

      listHost = el("div.fw-list");
      paneHost = el("div.fw-pane");
      viewEl.appendChild(el("div.fw-wrap", {}, [
        el("div.fw-rail", {}, [el("div.row", {}, [newBtn]), listHost]),
        paneHost,
      ]));

      await reloadList();
      if (!current && list.length) current = await api.framework.get(list[0].id);
      else if (current) current = await api.framework.get(current.id).catch(() => null);
      await reloadList();
      renderPane();
    },
  };
})();

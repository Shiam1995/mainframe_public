/* vision-storyboard.js — Vision · YouTube § Storyboard (VISION_UPDATE_SPEC §4).

   A comic-panel grid of the PLAN: what each shot looks like, what's said, how
   long it lasts. Never video files — the spec is explicit that those live in
   your editor, not here.

   Panel images can be a pasted URL (from an external AI tool) or uploaded
   through the Mainframe image service; either way `panel.image` ends up a URL
   string, so nothing downstream has to care which it was. */
(function () {
  const { el, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;
  const api = window.api;

  let dragFrom = null;   // index being dragged

  function panelModal(v, p, reload) {
    const caption = el("input.mform-input", { placeholder: "what happens in this panel" });
    const dialog = el("input.mform-input", { placeholder: "what is said (optional)" });
    const duration = el("input.mform-input", { placeholder: "e.g. 0:00-0:15, 15 sec" });
    const image = el("input.mform-input", { placeholder: "image URL — or upload below" });
    caption.value = p.caption || ""; dialog.value = p.dialog || "";
    duration.value = p.duration || ""; image.value = p.image || "";
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);

    // upload straight into the image service, then point the panel at the file
    const fileIn = el("input.img-file", { type: "file", accept: ".png,.jpg,.jpeg,.gif,.webp,.svg" });
    fileIn.addEventListener("change", () => {
      const f = fileIn.files && fileIn.files[0];
      if (!f) return;
      window.Images.nameModal(f.name.replace(/\.[^.]+$/, ""), (name) => guard(async () => {
        const img = await api.images.upload(f, name, "vision", p.id);
        image.value = api.images.fileUrl(img.id);
        fileIn.value = ""; toast("image attached — save the panel");
      }));
    });

    const overlay = el("div.modal-overlay");
    // notes rows save on Enter, so even Cancel reloads to show them on the card
    const close = () => { overlay.remove(); reload(); };
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.appendChild(el("div.modal.vis-modal", {}, [
      el("div.modal-title", { text: "Panel " + ((p.order || 0) + 1) }),
      field("Caption", caption),
      field("Dialog", dialog),
      el("div.mform-row", {}, [field("Duration", duration), field("Image", image)]),
      el("div.row", { style: "margin:-4px 0 10px" }, [
        fileIn, el("button.btn-sm", { onclick: () => fileIn.click(), text: "⤒ upload image" }),
        el("span.sub", { text: "or paste a URL above" }),
      ]),
      window.RowBox({ label: "notes", placeholder: "camera angle, b-roll, effects", parentId: p.id }).node,
      el("div.row", { style: "margin-top:16px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-danger", { style: "margin-right:auto",
          onclick: () => confirmDo("Delete this panel?", async () => {
            await V().delPanel(v.id, p.id); close();
          }), text: "delete" }),
        el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
          await V().updatePanel(v.id, p.id, {
            caption: caption.value, dialog: dialog.value, duration: duration.value,
            image: image.value.trim(),
          });
          close(); toast("panel saved");
        }), text: "Save panel" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    caption.focus();
  }

  function panelCard(v, p, i, reload) {
    const move = (dir) => guard(async () => {
      const ids = v.panels.map((x) => x.id);
      const j = i + dir;
      if (j < 0 || j >= ids.length) return;
      const t = ids[i]; ids[i] = ids[j]; ids[j] = t;
      await V().reorderPanels(v.id, ids); reload();
    });

    const shot = el("div.vsb-shot", p.image ? { style: "background-image:url(" + p.image + ")" } : {});
    if (!p.image) shot.appendChild(el("div.vsb-empty", { text: String(i + 1) }));
    if (p.duration) shot.appendChild(el("div.vsb-dur", { text: p.duration }));

    const card = el("div.vsb-panel", { draggable: "true" }, [
      el("div.spread", { style: "margin-bottom:6px" }, [
        el("span.vsb-num", { text: "#" + (i + 1) }),
        el("div.row", { style: "gap:2px" }, [
          el("button.ord-btn", { title: "move earlier", text: "◀", onclick: () => move(-1), disabled: i === 0 }),
          el("button.ord-btn", { title: "move later", text: "▶", onclick: () => move(1), disabled: i === v.panels.length - 1 }),
          el("button.ord-btn", { title: "edit panel", text: "✎", onclick: () => panelModal(v, p, reload) }),
        ]),
      ]),
      shot,
      el("div.vsb-cap", { text: p.caption || "—" }),
      p.dialog ? el("div.vsb-dialog", { text: "“" + p.dialog + "”" }) : null,
      window.RowBox({ label: "notes", placeholder: "camera angle, b-roll, effects", parentId: p.id }).node,
    ]);
    shot.addEventListener("click", () => panelModal(v, p, reload));

    // native HTML5 drag — no libraries. The ◀▶ buttons do the same job for
    // anyone not dragging (and are what the automated tests exercise).
    card.addEventListener("dragstart", (e) => {
      dragFrom = i; card.classList.add("dragging");
      try { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", p.id); } catch { /* ignore */ }
    });
    card.addEventListener("dragend", () => { dragFrom = null; card.classList.remove("dragging"); });
    card.addEventListener("dragover", (e) => { e.preventDefault(); card.classList.add("dragover"); });
    card.addEventListener("dragleave", () => card.classList.remove("dragover"));
    card.addEventListener("drop", (e) => {
      e.preventDefault(); card.classList.remove("dragover");
      if (dragFrom === null || dragFrom === i) return;
      const ids = v.panels.map((x) => x.id);
      const [moved] = ids.splice(dragFrom, 1);
      ids.splice(i, 0, moved);
      dragFrom = null;
      guard(async () => { await V().reorderPanels(v.id, ids); reload(); });
    });
    return card;
  }

  window.VID_SECTIONS = window.VID_SECTIONS || [];
  window.VID_SECTIONS.push({
    key: "storyboard", label: "🎬 Storyboard", order: 40,
    render(host, v, reload) {
      host.appendChild(el("div.row", { style: "margin-bottom:10px" }, [
        el("button.btn-sm", { onclick: () => guard(async () => {
          await V().addPanel(v.id, {}); reload();
        }), text: "+ add panel" }),
        el("span.sub", { text: v.panels.length
          ? "drag a panel, or use ◀ ▶ — click the frame to edit"
          : "the plan for each shot: image, caption, dialog, timing" }),
      ]));
      if (!v.panels.length) {
        host.appendChild(el("div.sub", { style: "font-style:italic", text: "No panels yet." }));
        return;
      }
      const grid = el("div.vsb-grid");
      v.panels.forEach((p, i) => grid.appendChild(panelCard(v, p, i, reload)));
      host.appendChild(grid);
    },
  });
})();

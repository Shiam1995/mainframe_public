/* images.js — the shared image widget used by EVERY module (VISION_SPEC).

   One line drops images onto any card, panel or modal:

       Images.mount(hostEl, { module: "pulse", contextId: habit.id });

   It knows nothing about what it's attached to — the backend links the image
   to whatever node carries `contextId`. Design rules from the spec:
     · every save prompts for a name first — no auto-names, no defaults
     · when an entity has no images the widget is a single small 📷 button, so
       putting it on surfaces you never use costs nothing visually
     · any surface can be hidden entirely (Images.setHidden) and the widget
       disappears without the host view changing

   Hidden surfaces are remembered in localStorage under `mf.images.hidden`. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;

  const HIDE_KEY = "mf.images.hidden";
  function hiddenSet() {
    try { return new Set(JSON.parse(localStorage.getItem(HIDE_KEY) || "[]")); }
    catch { return new Set(); }
  }
  function setHidden(surface, hide) {
    const s = hiddenSet();
    hide ? s.add(surface) : s.delete(surface);
    localStorage.setItem(HIDE_KEY, JSON.stringify([...s]));
  }
  const isHidden = (surface) => !!surface && hiddenSet().has(surface);

  /* --- name modal: the required step before any save --------------------- */
  function nameModal(suggested, onName) {
    const input = el("input.mform-input", { placeholder: "name this image…", value: suggested || "" });
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const submit = () => {
      const v = input.value.trim();
      if (!v) return toast("give the image a name", true);
      close(); onName(v);
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
    overlay.appendChild(el("div.modal", {}, [
      el("div.modal-title", { text: "Name this image" }),
      el("div.mform-full", {}, [
        el("div.mform-label", { text: "Name (required)" }), input,
        el("div.sub", { style: "margin-top:6px", text: "Saved under this name — the filename is derived from it." }),
      ]),
      el("div.row", { style: "margin-top:18px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-primary", { onclick: submit, text: "Save image" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    input.focus(); input.select();
  }

  /* --- batch name modal: one dialog for however many files were picked ----
     The spec's rule is that no image is ever saved without the user naming it.
     With a batch that has to stay true without becoming ten dialogs, so this is
     one dialog with one pre-filled row per file (plus a thumbnail, because
     "IMG_4471" tells you nothing about which shot it is). */
  function namesModal(files, onNames) {
    const overlay = el("div.modal-overlay");
    const urls = [];
    const close = () => { urls.forEach(URL.revokeObjectURL); overlay.remove(); };
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    const inputs = files.map((f) => {
      const input = el("input.mform-input", { value: f.name.replace(/\.[^.]+$/, "") });
      const url = URL.createObjectURL(f);
      urls.push(url);
      return { input, row: el("div.img-namerow", {}, [
        el("img.img-namethumb", { src: url, alt: "" }),
        el("div", { style: "flex:1;min-width:0" }, [input,
          el("div.sub", { style: "margin-top:3px", text: f.name + " · " + Math.round(f.size / 1024) + " KB" })]),
      ]) };
    });
    const submit = () => {
      const names = inputs.map((x) => x.input.value.trim());
      if (names.some((n) => !n)) return toast("every image needs a name", true);
      close(); onNames(names);
    };
    inputs.forEach((x) => x.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    }));

    overlay.appendChild(el("div.modal.img-namemodal", {}, [
      el("div.modal-title", { text: files.length === 1 ? "Name this image" : "Name these " + files.length + " images" }),
      el("div.sub", { style: "margin-bottom:10px", text: "Each is saved under its name — filenames are derived from them." }),
      el("div.img-namelist", {}, inputs.map((x) => x.row)),
      el("div.row", { style: "margin-top:18px;gap:8px;justify-content:flex-end" }, [
        el("button.btn-sm.btn-primary", { onclick: submit, text: files.length === 1 ? "Save image" : "Save " + files.length + " images" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
    inputs[0].input.focus(); inputs[0].input.select();
  }

  /* --- lightbox: pages through the whole set, ← → or the on-screen arrows -- */
  function lightbox(list, index) {
    if (!Array.isArray(list)) { list = [list]; index = 0; }   // single-image callers
    let i = Math.max(0, Math.min(index || 0, list.length - 1));

    const overlay = el("div.modal-overlay.img-lightbox");
    const img = el("img.img-full", { alt: "" });
    const caption = el("div.sub", { style: "margin-top:10px" });
    const counter = el("div.img-count");
    const prev = el("button.img-nav", { title: "previous (←)", text: "‹" });
    const next = el("button.img-nav", { title: "next (→)", text: "›" });

    function show(n) {
      i = (n + list.length) % list.length;      // wraps at both ends
      const cur = list[i];
      img.src = "/api/images/" + cur.id + "/file";
      img.alt = cur.name;
      caption.textContent = cur.name;
      counter.textContent = (i + 1) + " / " + list.length;
      const solo = list.length < 2;
      prev.style.visibility = next.style.visibility = solo ? "hidden" : "visible";
      counter.style.visibility = solo ? "hidden" : "visible";
    }
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
    function onKey(e) {
      if (e.key === "Escape") return close();
      if (e.key === "ArrowLeft") { e.preventDefault(); show(i - 1); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(i + 1); }
    }
    prev.addEventListener("click", (e) => { e.stopPropagation(); show(i - 1); });
    next.addEventListener("click", (e) => { e.stopPropagation(); show(i + 1); });
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    document.addEventListener("keydown", onKey);

    overlay.appendChild(el("div.img-stage", {}, [
      prev,
      el("div", { style: "text-align:center;min-width:0" }, [img, caption, counter]),
      next,
    ]));
    document.body.appendChild(overlay);
    show(i);
  }

  /* --- the widget -------------------------------------------------------- */
  function mount(host, opts) {
    const o = opts || {};
    const surface = o.surface || o.module;
    const wrap = el("div.img-widget");
    host.appendChild(wrap);
    if (isHidden(surface)) return { reload: () => {}, el: wrap };

    // The file input lives in the DOM for the widget's lifetime rather than
    // being created per click — no DOM churn, and the picker stays a plain
    // <input type=file> that anything can drive.
    const fileIn = el("input.img-file", {
      type: "file", multiple: true, accept: ".png,.jpg,.jpeg,.gif,.webp,.svg",
      "data-img-module": o.module || "", "data-img-context": o.contextId || "",
    });
    fileIn.addEventListener("change", () => {
      const files = Array.from(fileIn.files || []);
      if (!files.length) return;
      namesModal(files, (names) => guard(async () => {
        // sequential: keeps the order stable and the progress honest
        for (let n = 0; n < files.length; n++) {
          if (files.length > 1) toast("uploading " + (n + 1) + "/" + files.length + "…");
          await api.images.upload(files[n], names[n], o.module, o.contextId);
        }
        fileIn.value = "";
        toast(files.length === 1 ? "image saved" : files.length + " images saved");
        reload();
      }));
    });
    wrap.appendChild(fileIn);

    async function reload() {
      const list = await guard(() => api.images.list(o.module, o.contextId));
      // keep the persistent file input; replace everything else
      while (wrap.lastChild && wrap.lastChild !== fileIn) wrap.removeChild(wrap.lastChild);
      while (wrap.firstChild !== fileIn) wrap.removeChild(wrap.firstChild);

      const addBtn = el("button.btn-sm", { title: "Attach an image", text: "📷 add image",
        onclick: () => fileIn.click() });
      if (!list.length) {
        // empty state stays as small as possible — one button, no gallery box
        wrap.appendChild(el("div.row", { style: "gap:8px" }, [
          o.title ? el("span.sub", { text: o.title }) : null, addBtn,
        ]));
        return;
      }

      wrap.appendChild(el("div.row", { style: "gap:8px;margin-bottom:8px" }, [
        el("span.sub", { text: (o.title || "Images") + " · " + list.length }), addBtn,
      ]));
      const strip = el("div.img-strip");
      list.forEach((img, idx) => {
        const thumb = el("div.img-thumb", { title: img.name, draggable: "true" }, [
          // opens on this image but can page through the whole set
          el("img", { src: "/api/images/" + img.id + "/file", alt: img.name,
            onclick: () => lightbox(list, idx) }),
          el("div.img-thumb-bar", {}, [
            // manual order — arrows swap with the neighbour; works in every module
            el("button.img-x", { title: "move left", text: "◀", disabled: idx === 0, onclick: (e) => {
              e.stopPropagation();
              if (idx === 0) return;
              guard(async () => { await api.images.reorder([img.id, list[idx - 1].id]); reload(); });
            } }),
            el("button.img-x", { title: "move right", text: "▶", disabled: idx === list.length - 1, onclick: (e) => {
              e.stopPropagation();
              if (idx === list.length - 1) return;
              guard(async () => { await api.images.reorder([list[idx + 1].id, img.id]); reload(); });
            } }),
            el("span.img-thumb-name", { text: img.name }),
            el("button.img-x", { title: "rename", text: "✎", onclick: (e) => {
              e.stopPropagation();
              nameModal(img.name, (nv) => guard(async () => {
                await api.images.rename(img.id, nv); toast("renamed"); reload();
              }));
            } }),
            el("button.img-x", { title: "delete", text: "×", onclick: (e) => {
              e.stopPropagation();
              confirmDo("Delete image “" + img.name + "”?", async () => {
                await api.images.del(img.id); reload();
              });
            } }),
          ]),
        ]);
        /* Drag to reorder — the arrows do the same job, this is the direct
           gesture. Dropping on a thumb moves the dragged image into that slot;
           the server reorders by the id list, so a full-strip send is safest. */
        thumb.addEventListener("dragstart", (ev) => {
          ev.dataTransfer.effectAllowed = "move";
          ev.dataTransfer.setData("text/plain", img.id);
          thumb.classList.add("img-dragging");
        });
        thumb.addEventListener("dragend", () => thumb.classList.remove("img-dragging"));
        thumb.addEventListener("dragover", (ev) => {
          ev.preventDefault();
          ev.dataTransfer.dropEffect = "move";
          thumb.classList.add("img-drop");
        });
        thumb.addEventListener("dragleave", () => thumb.classList.remove("img-drop"));
        thumb.addEventListener("drop", (ev) => {
          ev.preventDefault();
          thumb.classList.remove("img-drop");
          const movedId = ev.dataTransfer.getData("text/plain");
          if (!movedId || movedId === img.id) return;
          const ids = list.map((x) => x.id);
          const from = ids.indexOf(movedId);
          const to = ids.indexOf(img.id);
          if (from < 0 || to < 0) return;
          ids.splice(to, 0, ids.splice(from, 1)[0]);
          guard(async () => { await api.images.reorder(ids); reload(); });
        });
        strip.appendChild(thumb);
      });
      wrap.appendChild(strip);
    }

    reload();
    return { reload, el: wrap };
  }

  /* ---- cycling a cover through several images ----------------------------
     For anything that shows ONE picture but owns several (a video's thumbnail
     options, a portfolio project's images): ‹ › arrows on hover, a dot per
     image, and ←/→ while the pointer is over it. Arrow clicks stop there, so a
     cover that opens something on click still does. `autoplay` steps on its
     own while hovered, the way YouTube previews; a manual step stops that.   */
  function cycle(cover, urls, opts) {
    opts = opts || {};
    urls = (urls || []).filter(Boolean);
    if (!urls.length) return null;
    let k = 0, timer = null;
    const dots = el("div.img-cyc-dots", {}, urls.map((_, j) => el("span" + (j ? "" : ".on"))));
    const show = (n) => {
      k = (n + urls.length) % urls.length;
      cover.style.backgroundImage = "url(" + urls[k] + ")";
      [...dots.children].forEach((d, j) => d.classList.toggle("on", j === k));
      if (opts.onShow) opts.onShow(k);
    };
    cover.style.backgroundImage = "url(" + urls[0] + ")";
    if (urls.length < 2) return { show, get index() { return 0; } };
    cover.classList.add("img-cyc");
    const stop = () => { clearInterval(timer); timer = null; };
    const step = (d) => (e) => { e.stopPropagation(); e.preventDefault(); stop(); show(k + d); };
    cover.appendChild(el("button.img-cyc-arrow.prev", { title: "previous image", text: "‹", onclick: step(-1) }));
    cover.appendChild(el("button.img-cyc-arrow.next", { title: "next image", text: "›", onclick: step(1) }));
    cover.appendChild(dots);
    const hoverHost = opts.hoverHost || cover;
    const onKey = (e) => {
      if (e.target.closest && e.target.closest("input,textarea,select,[contenteditable]")) return;
      if (e.key === "ArrowLeft") step(-1)(e); else if (e.key === "ArrowRight") step(1)(e);
    };
    hoverHost.addEventListener("mouseenter", () => {
      document.addEventListener("keydown", onKey);
      if (opts.autoplay) { show(k + 1); timer = setInterval(() => show(k + 1), 1100); }
    });
    hoverHost.addEventListener("mouseleave", () => {
      document.removeEventListener("keydown", onKey);
      stop();
      if (opts.resetOnLeave) show(0);
    });
    return { show, get index() { return k; } };
  }

  window.Images = { mount, setHidden, isHidden, hiddenSet, nameModal, namesModal, lightbox, cycle };
})();

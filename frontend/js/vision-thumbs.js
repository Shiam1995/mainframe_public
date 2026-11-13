/* vision-thumbs.js — Vision · YouTube § Thumbnails (VISION_UPDATE_SPEC §5).

   Make several thumbnail options and pick the best. Exactly one can be chosen;
   the chosen one becomes the video's thumbnail and shows on its card.

   Like storyboard panels, an option's image is either a pasted URL (from
   Midjourney/SDXL/wherever) or an upload through the Mainframe image service.

   Each option carries a FEEDBACK thread (:ThumbFeedback, dated, newest first,
   optional 👍/👎) rather than one overwritable note, so a critique survives
   the option being revised. The viewer (window.ThumbViewer) cycles through all
   options full-size with ←/→ and shows each one at YouTube-feed size beside
   the video title — that's the size it actually gets judged at. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;
  const api = window.api;

  const VERDICT = { like: "👍", dislike: "👎", "": "💬" };
  const dateFmt = (iso) => {
    try { return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" }); }
    catch { return String(iso || "").slice(0, 10); }
  };
  const bg = (url) => url ? { style: "background-image:url(" + url + ")" } : {};

  /* --- full-size viewer: cycle options, read + write feedback -------------- */
  function openViewer(v, start, reload) {
    let i = Math.max(0, Math.min(start || 0, v.thumbs.length - 1));
    let dirty = false;
    let verdict = "";

    const overlay = el("div.modal-overlay.vthv-overlay");
    const stage = el("div.vthv-stage");
    const side = el("div.vthv-side");
    const strip = el("div.vthv-strip");

    const close = () => {
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      if (dirty) reload();
    };
    const go = (d) => { i = (i + d + v.thumbs.length) % v.thumbs.length; verdict = ""; paint(); };
    function onKey(e) {
      const typing = /^(TEXTAREA|INPUT|SELECT)$/.test(e.target.tagName);
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
      else if (!typing && e.key === "ArrowLeft") { e.preventDefault(); go(-1); }
      else if (!typing && e.key === "ArrowRight") { e.preventDefault(); go(1); }
    }
    document.addEventListener("keydown", onKey, true);
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });

    function paint() {
      const t = v.thumbs[i];
      const many = v.thumbs.length > 1;

      clear(stage);
      const big = el("div.vthv-big" + (t.chosen ? ".chosen" : ""), bg(t.image));
      if (!t.image) big.appendChild(el("div.vsb-empty", { text: "🖼️ no image yet" }));
      if (t.chosen) big.appendChild(el("div.vth-check", { text: "✓ chosen" }));
      if (many) {
        big.appendChild(el("button.vthv-nav.prev", { title: "previous (←)", text: "‹", onclick: () => go(-1) }));
        big.appendChild(el("button.vthv-nav.next", { title: "next (→)", text: "›", onclick: () => go(1) }));
      }
      stage.appendChild(big);
      // in-feed preview: the size a viewer actually meets it at
      stage.appendChild(el("div.vthv-feed", {}, [
        el("div.sub", { text: "as it'll look in the feed" }),
        el("div.vthv-feedcard", {}, [
          el("div.vthv-feedimg", bg(t.image)),
          el("div.vthv-feedtitle", { text: v.title }),
          el("div.vthv-feedmeta", { text: (v.stage || "draft") + " · option " + (i + 1) }),
        ]),
      ]));

      clear(strip);
      v.thumbs.forEach((x, k) => {
        const s = el("div.vthv-mini" + (k === i ? ".on" : "") + (x.chosen ? ".chosen" : ""), bg(x.image));
        if (!x.image) s.appendChild(el("span", { text: k + 1 }));
        if (x.feedback.length) s.appendChild(el("span.vthv-minicount", { text: x.feedback.length }));
        s.addEventListener("click", () => { i = k; verdict = ""; paint(); });
        strip.appendChild(s);
      });

      clear(side);
      side.appendChild(el("div.spread", {}, [
        el("div", {}, [
          el("div.vthv-count", { text: "option " + (i + 1) + " / " + v.thumbs.length }),
          el("div.sub", { text: t.style || "no style label" }),
        ]),
        el("button.ord-btn", { title: "close (Esc)", text: "×", onclick: close }),
      ]));
      side.appendChild(t.chosen
        ? el("div.vthv-chosen", { text: "✓ this is the video's thumbnail" })
        : el("button.btn-sm.btn-primary", { style: "margin-top:10px;width:100%",
            onclick: () => guard(async () => {
              await V().updateThumb(v.id, t.id, { chosen: true });
              v.thumbs.forEach((x) => { x.chosen = x.id === t.id; });
              v.thumbnail = t.image; dirty = true; toast("chosen"); paint();
            }), text: "✓ choose this one" }));

      side.appendChild(el("div.vid-sec-head", { style: "margin-top:16px", text: "Feedback" }));
      const ta = el("input.mform-input", { placeholder: "what works, what doesn't — readable at small size? face? text?" });
      const vbtn = (k, label) => el("button.btn-sm.vthv-verdict" + (verdict === k ? ".on" : ""), {
        title: k ? k : "neutral", text: label,
        onclick: () => { verdict = verdict === k ? "" : k; paint(); },
      });
      const submit = () => guard(async () => {
        if (!ta.value.trim()) return toast("write something first", true);
        const f = await V().addThumbFeedback(v.id, t.id, { text: ta.value.trim(), verdict });
        t.feedback.unshift(f); verdict = ""; dirty = true; paint();
      });
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); submit(); }
      });
      side.appendChild(ta);
      side.appendChild(el("div.row", { style: "gap:5px;margin-top:6px" }, [
        vbtn("like", "👍"), vbtn("dislike", "👎"),
        el("button.btn-sm", { style: "margin-left:auto", onclick: submit, text: "+ add  (↵)" }),
      ]));

      const list = el("div.vthv-fblist");
      if (!t.feedback.length) list.appendChild(el("div.sub", { style: "font-style:italic", text: "No feedback on this option yet." }));
      t.feedback.forEach((f) => list.appendChild(el("div.vthv-fb", {}, [
        el("div.spread", {}, [
          el("span.sub", { text: VERDICT[f.verdict || ""] + "  " + dateFmt(f.date) }),
          el("button.ord-btn", { title: "delete", text: "×", onclick: () => guard(async () => {
            await V().delThumbFeedback(v.id, t.id, f.id);
            t.feedback = t.feedback.filter((x) => x.id !== f.id); dirty = true; paint();
          }) }),
        ]),
        el("div", { style: "white-space:pre-wrap;margin-top:2px", text: f.text }),
      ])));
      side.appendChild(list);
      if (many) side.appendChild(el("div.sub", { style: "margin-top:10px", text: "← → to cycle · Esc to close" }));
    }

    overlay.appendChild(el("div.modal.vthv", {}, [
      el("div.vthv-main", {}, [stage, strip]), side,
    ]));
    document.body.appendChild(overlay);
    paint();
  }
  window.ThumbViewer = { open: openViewer };

  /* --- option card in the section row ------------------------------------- */
  function optionCard(v, t, idx, reload) {
    const shot = el("div.vth-shot" + (t.chosen ? ".chosen" : ""), bg(t.image));
    if (!t.image) shot.appendChild(el("div.vsb-empty", { text: "🖼️" }));
    if (t.chosen) shot.appendChild(el("div.vth-check", { text: "✓ chosen" }));
    if (t.feedback.length) shot.appendChild(el("div.vth-fbcount", { text: "💬 " + t.feedback.length }));
    shot.title = "open — cycle options and write feedback";
    shot.addEventListener("click", () => openViewer(v, idx, reload));

    const style = el("input", { value: t.style || "", placeholder: "style — e.g. face close-up", style: "width:100%;font-size:11px" });
    style.addEventListener("blur", () => guard(async () => {
      if ((style.value || "") === (t.style || "")) return;
      await V().updateThumb(v.id, t.id, { style: style.value }); t.style = style.value; toast("saved");
    }));
    const image = el("input", { value: t.image || "", placeholder: "image URL", style: "width:100%;font-size:10px" });
    image.addEventListener("blur", () => guard(async () => {
      if ((image.value || "") === (t.image || "")) return;
      await V().updateThumb(v.id, t.id, { image: image.value.trim() }); reload();
    }));

    const fileIn = el("input.img-file", { type: "file", accept: ".png,.jpg,.jpeg,.gif,.webp,.svg" });
    fileIn.addEventListener("change", () => {
      const f = fileIn.files && fileIn.files[0];
      if (!f) return;
      window.Images.nameModal(f.name.replace(/\.[^.]+$/, ""), (name) => guard(async () => {
        const img = await api.images.upload(f, name, "vision", t.id);
        await V().updateThumb(v.id, t.id, { image: api.images.fileUrl(img.id) });
        fileIn.value = ""; toast("image set"); reload();
      }));
    });

    const latest = t.feedback[0];
    return el("div.vth-card", {}, [
      shot, image,
      el("div.row", { style: "gap:4px;margin-top:4px" }, [
        fileIn,
        el("button.btn-sm", { style: "font-size:9px;padding:3px 7px", onclick: () => fileIn.click(), text: "⤒ upload" }),
        t.chosen ? null : el("button.btn-sm", { style: "font-size:9px;padding:3px 7px", title: "make this the video's thumbnail",
          onclick: () => guard(async () => { await V().updateThumb(v.id, t.id, { chosen: true }); toast("chosen"); reload(); }),
          text: "✓ choose" }),
        el("button.ord-btn", { style: "margin-left:auto", title: "delete option",
          text: "×", onclick: () => confirmDo("Delete this thumbnail option and its feedback?", async () => {
            await V().delThumb(v.id, t.id); reload();
          }) }),
      ]),
      style,
      latest ? el("div.vth-latest", { title: "latest feedback — click the image for the full thread",
        text: VERDICT[latest.verdict || ""] + " " + latest.text }) : null,
    ]);
  }

  window.VID_SECTIONS = window.VID_SECTIONS || [];
  window.VID_SECTIONS.push({
    key: "thumbnails", label: "🖼️ Thumbnails", order: 50,
    render(host, v, reload) {
      host.appendChild(el("div.row", { style: "margin-bottom:10px;gap:8px" }, [
        el("button.btn-sm", { onclick: () => guard(async () => {
          await V().addThumb(v.id, {}); reload();
        }), text: "+ add option" }),
        v.thumbs.length > 1 ? el("button.btn-sm", { onclick: () => openViewer(v, 0, reload), text: "▶ review all" }) : null,
        el("span.sub", { text: v.thumbs.length
          ? "click an option to view it full-size, cycle with ← →, and write feedback"
          : "make a few options, then pick the best" }),
      ]));
      if (!v.thumbs.length) {
        host.appendChild(el("div.sub", { style: "font-style:italic", text: "No thumbnail options yet." }));
        return;
      }
      const row = el("div.vth-row");
      v.thumbs.forEach((t, k) => row.appendChild(optionCard(v, t, k, reload)));
      host.appendChild(row);
    },
  });
})();

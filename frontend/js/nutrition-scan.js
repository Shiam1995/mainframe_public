/* nutrition-scan.js — point the camera at a packet, get the food.

   The catalogue already holds ~4M products carrying a barcode (Open Food Facts
   alone covers 2.2M, most of a British supermarket). Until now the only way to
   reach one by code was to type thirteen digits off the back of the bag. This
   is the camera doing that instead: hold up a bag of crisps, and the packet
   identifies itself.

   How it works
   -----------
   The frame never leaves the machine. A still is grabbed from the video every
   ~600ms, posted to /catalog/scan, decoded there by zxing-cpp and dropped. No
   cloud vision API, no image on disk, and nothing is written to the graph until
   you pick a portion — scanning is a search, adopting is the write.

   Two ways in, because both are needed:
     * **live camera** — desktop, or a phone on https/localhost.
     * **a photo** — the file picker. On a phone this opens the camera app, and
       it is the only route that works over plain http on the LAN, where the
       browser refuses getUserMedia outright.

   Zero libraries, like the rest of the app. */
(function () {
  const { el, clear, toast } = window.ui;
  const P = window.PULSE;

  const FRAME_MS = 600;         // fast enough to feel live, slow enough to decode
  const MAX_EDGE = 1280;        // a barcode is legible far below a 4K frame

  /* Grab the current video frame as a JPEG blob, scaled down. Sending the raw
     1080p frame would be ~10× the bytes for no extra decode accuracy. */
  function frameBlob(video) {
    return new Promise((resolve) => {
      const w = video.videoWidth, h = video.videoHeight;
      if (!w || !h) return resolve(null);
      const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
      const c = el("canvas");
      c.width = Math.round(w * scale);
      c.height = Math.round(h * scale);
      c.getContext("2d").drawImage(video, 0, 0, c.width, c.height);
      c.toBlob((b) => resolve(b), "image/jpeg", 0.72);
    });
  }

  async function scan(blob, name) {
    const fd = new FormData();
    fd.append("image", blob, name || "frame.jpg");
    return window.NUT.N().catalogScan(fd);
  }

  /* ------------------------------------------------------------------ modal */
  /* `onDone(food)` fires with the newly adopted :Food, so a caller can pick it
     up mid-flow — the food log uses that to log what you just scanned.

     `opts.onCode(code)` switches to code-only mode: the first barcode read wins
     and the modal closes, whether or not the catalogue knows it. That's what the
     barcode field on a food wants — there, the digits ARE the answer. */
  function scanModal(onDone, opts) {
    opts = opts || {};
    let handle = null;
    const status = el("div.sub", { style: "font-size:11.5px;min-height:18px" });
    const stage = el("div", {
      style: "margin-top:10px;background:#000;border-radius:8px;overflow:hidden;"
           + "display:none;max-height:46vh",
    });
    const video = el("video", {
      autoplay: true, muted: true, playsinline: true,
      style: "width:100%;max-height:46vh;object-fit:contain;display:block",
    });
    video.setAttribute("playsinline", "");       // iOS refuses to inline without it
    video.muted = true;
    stage.appendChild(video);

    const results = el("div", { style: "margin-top:10px;max-height:38vh;overflow:auto" });
    const file = el("input", { type: "file", accept: "image/*", style: "display:none" });
    file.setAttribute("capture", "environment");  // a phone opens the camera here

    let stream = null, timer = null, busy = false, done = false;

    function stop() {
      done = true;
      clearTimeout(timer);
      if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
      stage.style.display = "none";
    }

    /* What a scan came back with. A frame with no barcode is the normal case
       while you're lining the packet up, so it never counts as an error. */
    function show(res, fromStill) {
      clear(results);
      const codes = (res && res.codes) || [];
      const matches = (res && res.matches) || [];

      if (codes.length && opts.onCode) {
        stop();
        opts.onCode(codes[0].code);
        toast("scanned " + codes[0].code);
        if (handle) handle.close();
        return true;
      }

      if (matches.length) {
        stop();
        status.textContent = "Found " + codes.map((c) => c.code).join(", ")
          + " — " + matches.length + " product" + (matches.length === 1 ? "" : "s")
          + " in the catalogue. Add one to My Foods:";
        const row = window.NUT.catalogRow;
        matches.forEach((f) => results.appendChild(
          row(f, (created) => { toast("in My Foods now"); if (onDone) onDone(created); })));
        return true;
      }

      if (codes.length) {
        // Read the code but nothing matched it — worth stopping for, because
        // re-scanning the same packet will keep saying the same thing.
        stop();
        const code = codes[0].code;
        status.textContent = "Read " + codes[0].format + " " + code
          + ", but no product in the catalogue carries it.";
        results.appendChild(el("div.empty", { style: "text-align:left" }, [
          el("div.sub", { style: "font-size:11px;line-height:1.6",
            text: "Open Food Facts is crowd-sourced, so a very new or very local "
                + "product may simply not be in it yet. You can add it by hand — the "
                + "barcode is filled in, so the next scan of this packet finds it." }),
          el("button.btn-sm.btn-primary", { style: "margin-top:10px", text: "add it by hand",
            onclick: () => window.NUT.foodModal(null, () => { if (onDone) onDone(null); },
                                                { barcode: code }) }),
        ]));
        return true;
      }

      if (fromStill) {
        status.textContent = "No barcode in that photo. Get the whole barcode in "
          + "frame, straight on and in focus, then try again.";
      }
      return false;
    }

    async function tick() {
      if (done) return;
      // The modal can be closed by the backdrop or Esc, which this never hears
      // about — so check we're still on screen before touching the camera again.
      if (!document.body.contains(stage)) return stop();
      if (!busy) {
        busy = true;
        try {
          const blob = await frameBlob(video);
          if (blob) {
            const res = await scan(blob);
            if (show(res, false)) { busy = false; return; }
          }
        } catch (err) {
          stop();
          status.textContent = "Scan failed: " + err.message;
          return;
        }
        busy = false;
      }
      timer = setTimeout(tick, FRAME_MS);
    }

    async function startCamera() {
      clear(results);
      done = false;
      status.textContent = "Starting the camera…";
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        status.textContent = "This browser won't give a page the camera here. "
          + "Use “choose a photo” — on a phone that opens the camera app.";
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          // `ideal`, not `exact`: a laptop has no rear camera and exact would
          // fail outright rather than falling back to the one it has.
          video: { facingMode: { ideal: "environment" },
                   width: { ideal: 1280 }, height: { ideal: 720 } },
        });
      } catch (err) {
        status.textContent = "No camera: " + (err.message || err.name)
          + ". Use “choose a photo” instead.";
        return;
      }
      video.srcObject = stream;
      stage.style.display = "block";
      try { await video.play(); } catch (_e) { /* autoplay policy — the frame grab still works */ }
      status.textContent = "Point it at the barcode — hold the packet steady, "
        + "barcode filling about a third of the frame.";
      tick();
    }

    file.addEventListener("change", async () => {
      const f = file.files && file.files[0];
      if (!f) return;
      stop();
      clear(results);
      status.textContent = "Reading " + f.name + "…";
      try {
        show(await scan(f, f.name), true);
      } catch (err) {
        status.textContent = "Scan failed: " + err.message;
      }
      file.value = "";        // so choosing the same photo twice re-scans it
    });

    handle = P.modal("Scan a barcode", [
      el("div.sub", { style: "font-size:11px;line-height:1.6",
        text: "Hold a packet up to the camera, or pick a photo of one. The barcode is "
            + "decoded on this machine and matched against the catalogue — the image is "
            + "never stored and never leaves it. Nothing joins My Foods until you choose "
            + "a portion." }),
      el("div.row", { style: "gap:8px;margin-top:10px" }, [
        el("button.btn-sm.btn-primary", { text: "📷 use the camera", onclick: startCamera }),
        el("button.btn-sm", { text: "🖼 choose a photo", onclick: () => file.click() }),
      ]),
      file, stage,
      el("div", { style: "margin-top:8px" }, [status]),
      results,
    ], [{ label: "Done", onClick: (close) => { stop(); close(); } }]);

    startCamera();
  }

  window.NUT = window.NUT || {};
  window.NUT.scanModal = scanModal;
  // A plain button any tab can drop next to its search box.
  window.NUT.scanButton = (onDone, label, opts) => el("button.btn-sm", {
    text: label || "📷 scan", title: "scan a barcode with the camera or a photo",
    onclick: () => scanModal(onDone, opts),
  });
})();

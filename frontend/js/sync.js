/* sync.js — "has this actually been pushed to the database?"

   Every write in the Mainframe goes through one function (api.js `req`), so
   this hooks that single point and gets all ~420 routes for free. It answers
   the question in two places at once:

     · the topbar pill  — the state of the app as a whole: saving / saved / not
       saved. Always visible, so you never have to wonder.
     · a mark on the item itself — anything rendered with `data-eid="<id>"`
       gets a ✓ when its write lands, and a red ▲ that STAYS until you retry
       if it didn't.

   The important case is the third state. A write that fails currently shows a
   toast and disappears; the row on screen then disagrees with the database and
   nothing says so. Failures are kept here, marked on the row, listed in a tray
   with a retry button, and mirrored into localStorage so closing the tab
   doesn't quietly discard them. */
(function () {
  const STORE = "mainframe.sync.failures";
  const FLASH_MS = 1400;

  let inflight = 0;
  let lastSaved = null;
  let failures = [];            // {id, method, path, body, label, error, at, eid}
  let seq = 0;

  /* Entity id for a write, so the right row can be marked. The response body
     is the authority (a POST invents the id); the URL is the fallback for
     PATCH/DELETE, where the id is the last non-verb path segment. */
  function entityId(path, data) {
    if (data && typeof data === "object" && typeof data.id === "string") return data.id;
    const parts = String(path).split("?")[0].split("/").filter(Boolean);
    for (let i = parts.length - 1; i >= 0; i--) {
      if (/^[0-9a-f-]{8,}$/i.test(parts[i])) return parts[i];
    }
    return null;
  }

  function label(method, path) {
    const clean = String(path).split("?")[0].replace(/^\/api\//, "");
    return method + " " + clean;
  }

  /* ---------------------------------------------------------------- *
   * Persistence — a failed write must survive a reload, or "not saved"
   * silently becomes "lost".
   * ---------------------------------------------------------------- */
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify(
        failures.filter((f) => f.retryable).slice(-40)));
    } catch { /* private mode / quota — the in-memory list still works */ }
  }
  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || "[]");
      if (Array.isArray(raw)) {
        failures = raw.map((f) => ({ ...f, id: ++seq }));
      }
    } catch { failures = []; }
  }

  /* ---------------------------------------------------------------- *
   * The topbar pill
   * ---------------------------------------------------------------- */
  function pill() { return document.getElementById("sync-pill"); }

  function render() {
    const p = pill();
    if (!p) return;
    p.className = "sync";
    /* Deliberately tiny. This sits in the header beside the tab strip, and an
       indicator that pushes the tabs into overflow to say "everything is fine"
       is a bad trade. Only the failure state — the one you must not miss —
       spends horizontal space, on the count. Everything else is a glyph with
       the detail in the tooltip. */
    if (failures.length) {
      p.classList.add("bad");
      p.textContent = "▲ " + failures.length;
      p.title = failures.length + " change" + (failures.length === 1 ? "" : "s")
        + " never reached the database. Click to review and retry.";
    } else if (inflight > 0) {
      p.classList.add("busy");
      p.textContent = "●";
      p.title = "Saving… " + inflight + " write" + (inflight === 1 ? "" : "s") + " in flight";
    } else if (lastSaved) {
      p.classList.add("ok");
      p.textContent = "✓";
      p.title = "All changes pushed to the database — last write at "
        + lastSaved.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    } else {
      p.textContent = "✓";
      p.title = "No unsaved changes.";
    }
    paint();
  }

  /* ---------------------------------------------------------------- *
   * Per-item marks
   * ---------------------------------------------------------------- */
  function markEl(eid, cls, glyph, title) {
    if (!eid) return;
    document.querySelectorAll('[data-eid="' + CSS.escape(eid) + '"]').forEach((node) => {
      let dot = node.querySelector(":scope > .sync-mark");
      if (!dot) {
        dot = document.createElement("span");
        dot.className = "sync-mark";
        node.insertBefore(dot, node.firstChild);
      }
      dot.className = "sync-mark " + cls;
      dot.textContent = glyph;
      dot.title = title;
    });
  }

  function clearMark(eid) {
    document.querySelectorAll('[data-eid="' + CSS.escape(eid) + '"] > .sync-mark')
      .forEach((d) => d.remove());
  }

  /* Views re-render constantly, which would wipe a failure mark off a row that
     is still genuinely unsaved. Re-apply after every DOM change instead of
     asking eighty view files to remember. */
  function paint() {
    const bad = new Set(failures.map((f) => f.eid).filter(Boolean));
    bad.forEach((eid) =>
      markEl(eid, "bad", "▲", "This change never reached the database — click the topbar to retry."));
  }

  let queued = false;
  function watch() {
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; paint(); });
    }).observe(document.body, { childList: true, subtree: true });
  }

  /* ---------------------------------------------------------------- *
   * The failure tray
   * ---------------------------------------------------------------- */
  let tray = null;
  function closeTray() { if (tray) { tray.remove(); tray = null; } }

  function openTray() {
    closeTray();
    if (!failures.length) return;
    tray = document.createElement("div");
    tray.className = "sync-tray";

    const head = document.createElement("div");
    head.className = "sync-tray-head";
    head.textContent = failures.length + " change"
      + (failures.length === 1 ? "" : "s") + " not saved";
    tray.appendChild(head);

    const note = document.createElement("div");
    note.className = "sync-tray-note";
    note.textContent = "These never reached Neo4j. What's on screen may not match "
      + "the database. Retrying replays the original write.";
    tray.appendChild(note);

    failures.slice().reverse().forEach((f) => {
      const row = document.createElement("div");
      row.className = "sync-tray-row";
      const what = document.createElement("div");
      what.innerHTML = "<div class='sync-tray-what'></div><div class='sync-tray-err'></div>";
      what.querySelector(".sync-tray-what").textContent = f.label;
      what.querySelector(".sync-tray-err").textContent = f.error;
      row.appendChild(what);
      if (f.retryable) {
        const go = document.createElement("button");
        go.className = "sync-tray-btn";
        go.textContent = "retry";
        go.onclick = () => retry(f.id);
        row.appendChild(go);
      } else {
        const no = document.createElement("span");
        no.className = "sync-tray-err";
        no.textContent = "re-do by hand (file upload)";
        row.appendChild(no);
      }
      const drop = document.createElement("button");
      drop.className = "sync-tray-btn";
      drop.textContent = "dismiss";
      drop.onclick = () => dismiss(f.id);
      row.appendChild(drop);
      tray.appendChild(row);
    });

    const acts = document.createElement("div");
    acts.className = "sync-tray-acts";
    const all = document.createElement("button");
    all.className = "sync-tray-btn primary";
    all.textContent = "retry all";
    all.onclick = () => retryAll();
    const clear = document.createElement("button");
    clear.className = "sync-tray-btn";
    clear.textContent = "dismiss all";
    clear.onclick = () => {
      failures.forEach((f) => f.eid && clearMark(f.eid));
      failures = []; save(); render(); closeTray();
    };
    acts.appendChild(all);
    acts.appendChild(clear);
    tray.appendChild(acts);

    document.body.appendChild(tray);
    const r = pill().getBoundingClientRect();
    tray.style.top = (r.bottom + window.scrollY + 6) + "px";
    tray.style.right = Math.max(8, window.innerWidth - r.right) + "px";
  }

  document.addEventListener("click", (e) => {
    if (tray && !tray.contains(e.target) && e.target.id !== "sync-pill") closeTray();
  });

  function dismiss(id) {
    const f = failures.find((x) => x.id === id);
    if (f && f.eid) clearMark(f.eid);
    failures = failures.filter((x) => x.id !== id);
    save(); render();
    failures.length ? openTray() : closeTray();
  }

  async function retry(id) {
    const f = failures.find((x) => x.id === id);
    if (!f || !f.retryable) return;
    try {
      await window.api[
        { POST: "post", PUT: "put", PATCH: "patch", DELETE: "del" }[f.method]
      ](f.path, f.body);
      // The success path already removed the mark and re-rendered the pill.
      failures = failures.filter((x) => x.id !== id);
      if (f.eid) clearMark(f.eid);
      save(); render();
      failures.length ? openTray() : closeTray();
      if (window.ui) window.ui.toast("saved");
      if (window.refreshActive) window.refreshActive();
    } catch (err) {
      if (window.ui) window.ui.toast("still failing: " + (err.message || err), true);
    }
  }

  async function retryAll() {
    for (const f of failures.slice()) {
      if (f.retryable) await retry(f.id);   // sequential: order can matter
    }
  }

  /* ---------------------------------------------------------------- *
   * The hook api.js calls
   * ---------------------------------------------------------------- */
  window.sync = {
    begin(method, path, body, isForm) {
      inflight += 1;
      render();
      return {
        ok: (data) => {
          inflight -= 1;
          lastSaved = new Date();
          const eid = entityId(path, data);
          // A successful write clears any earlier failure for the same entity —
          // the row now matches the database again.
          if (eid) {
            const had = failures.some((f) => f.eid === eid);
            failures = failures.filter((f) => f.eid !== eid);
            if (had) save();
            clearMark(eid);
            if (method !== "DELETE") {
              markEl(eid, "ok", "✓", "Pushed to the database just now.");
              setTimeout(() => {
                // Don't wipe a mark that a later failure has since put back.
                if (!failures.some((f) => f.eid === eid)) clearMark(eid);
              }, FLASH_MS);
            }
          }
          render();
        },
        fail: (err) => {
          inflight -= 1;
          failures.push({
            id: ++seq, method, path,
            body: isForm ? null : body,
            retryable: !isForm && method !== "POST_FORM",
            label: label(method, path),
            error: (err && err.message) || String(err),
            at: new Date().toISOString(),
            eid: entityId(path, null),
          });
          save();
          render();
        },
      };
    },
    // Views can flag "edited but not sent yet" (the Docs editor uses this).
    pending(eid) { markEl(eid, "busy", "●", "Unsaved — not pushed to the database yet."); },
    settled(eid) { if (!failures.some((f) => f.eid === eid)) clearMark(eid); },
    failures: () => failures.slice(),
    retryAll,
  };

  function mount() {
    const host = document.getElementById("status-pill");
    if (!host) return;
    const p = document.createElement("button");
    p.id = "sync-pill";
    p.className = "sync";
    p.onclick = (e) => { e.stopPropagation(); tray ? closeTray() : openTray(); };
    host.insertBefore(p, host.firstChild);
    load();
    render();
    watch();
    if (failures.length && window.ui) {
      window.ui.toast(failures.length + " change(s) from earlier were never saved", true);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();

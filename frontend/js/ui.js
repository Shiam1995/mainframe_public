/* ui.js — tiny DOM + helper toolkit shared by every view.
   No framework; just enough sugar to keep the view code readable. */
(function () {
  // el("div.card", {onclick: fn}, [children|strings])
  function el(spec, attrs, children) {
    const [tag, ...classes] = spec.split(".");
    const node = document.createElement(tag || "div");
    if (classes.length) node.className = classes.join(" ");
    if (attrs) {
      for (const k in attrs) {
        const v = attrs[k];
        if (k === "html") node.innerHTML = v;
        else if (k === "text") node.textContent = v;
        else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
        else if (v === true) node.setAttribute(k, "");
        else if (v !== false && v != null) node.setAttribute(k, v);
      }
    }
    (children || []).forEach((c) => {
      if (c == null) return;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  /* Emptying a section inside the scrolling view (#view) to redraw it used to
     throw you back to the top: for a moment the page is short, the browser
     clamps the scroll to 0, and the redraw never puts it back. So when a
     section INSIDE #view is cleared, it keeps its old height until the redraw
     has painted, then the scroll is put back where it was (2026-11-08).
     Clearing #view itself — switching tab — is left alone: a new tab starts
     at the top. */
  function holdScroll(node) {
    const sc = node.id !== "view" && node.closest ? node.closest("#view") : null;
    if (!sc || sc.scrollTop <= 0 || node.__holding) return;
    const top = sc.scrollTop, prev = node.style.minHeight;
    node.__holding = true;
    node.style.minHeight = node.offsetHeight + "px";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      node.style.minHeight = prev;
      node.__holding = false;
      sc.scrollTop = Math.min(top, sc.scrollHeight - sc.clientHeight);
    }));
  }
  function clear(node) {
    holdScroll(node);
    while (node.firstChild) node.removeChild(node.firstChild);
    return node;
  }

  let toastTimer = null;
  function toast(msg, isErr) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.className = "toast" + (isErr ? " err" : "");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.add("hidden"), 2600);
  }

  async function guard(fn) {
    try { return await fn(); }
    catch (e) { toast(e.message || String(e), true); throw e; }
  }

  // familiarity 0-10 → class + label per spec (red 0-3, amber 4-6, teal 7-10)
  function famClass(v) { return v <= 3 ? "fam-lo" : v <= 6 ? "fam-mid" : "fam-hi"; }

  function fmtDate(iso) {
    if (!iso) return "";
    return String(iso).slice(0, 10);
  }

  function confirmDo(msg, fn) {
    if (window.confirm(msg)) return guard(fn);
  }

  /* ---- stamping the current time -------------------------------------------
     Logging when you started and stopped is the most repeated action in the
     app, and typing 14:35 into a picker is the most tedious. Every date/time
     input gets a one-press "now" button, and start/end pairs get a single
     button that walks start → end like a stopwatch.

     Local time throughout: `new Date().toISOString()` is UTC and would write
     yesterday's date to anyone west of Greenwich after 00:00 UTC.             */
  const pad2 = (n) => String(n).padStart(2, "0");

  function nowHM(d) {
    d = d || new Date();
    return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
  }
  function todayISO(d) {
    d = d || new Date();
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }
  function nowFor(input) {
    const t = (input.getAttribute("type") || "text").toLowerCase();
    if (t === "date") return todayISO();
    if (t === "datetime-local") return todayISO() + "T" + nowHM();
    if (t === "month") return todayISO().slice(0, 7);
    return nowHM();
  }

  // Fire the events listeners are actually bound to. Setting .value in script
  // fires nothing, so a duration that syncs on "change" would never update.
  function setValue(input, value) {
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function stampNow(input) { setValue(input, nowFor(input)); return input.value; }

  /* A single button that stamps `input` with the current time/date. */
  function nowBtn(input, label) {
    const isDate = (input.getAttribute("type") || "") === "date";
    const b = el("button.now-btn", {
      type: "button",
      title: isDate ? "set to today" : "set to the time right now",
      text: label || (isDate ? "today" : "now"),
    });
    b.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); stampNow(input); });
    return b;
  }

  /* One button that walks a start/end pair: press to start, press again to
     stop. Reflects whatever the inputs already hold, so it stays right when a
     saved session is reopened or a time is typed by hand. */
  function stampPair(startInput, endInput, opts) {
    opts = opts || {};
    const b = el("button.now-btn.now-btn-go", { type: "button" });
    const sync = () => {
      const s = startInput.value, e = endInput.value;
      b.textContent = !s ? "▶ start" : (!e ? "■ end" : "↺ again");
      b.title = !s ? "stamp the start time as right now"
        : (!e ? "stamp the end time as right now" : "clear both and start again");
      b.classList.toggle("running", !!s && !e);
    };
    b.addEventListener("click", (ev) => {
      ev.preventDefault(); ev.stopPropagation();
      if (!startInput.value) stampNow(startInput);
      else if (!endInput.value) stampNow(endInput);
      else { setValue(startInput, ""); setValue(endInput, ""); }
      sync();
      if (opts.onChange) opts.onChange();
    });
    // A time typed by hand must move the button too.
    [startInput, endInput].forEach((i) => i.addEventListener("change", sync));
    sync();
    return b;
  }

  /* Give every date/time input a now button, including ones rendered later.
     Opt a field out with data-no-now (see .wl-table, where the row is a grid
     and an extra child would break the columns). */
  function decorate(root) {
    (root.querySelectorAll ? root.querySelectorAll(
      'input[type="time"],input[type="date"],input[type="datetime-local"]') : []
    ).forEach((input) => {
      if (input.dataset.nowDone || input.closest("[data-no-now]") || input.dataset.noNow != null) return;
      if (input.disabled || input.readOnly) return;
      input.dataset.nowDone = "1";
      input.insertAdjacentElement("afterend", nowBtn(input));
    });
  }

  /* Clicking a date field should open the calendar.

     Chrome only opens the native picker when you hit the little glyph at the
     right-hand edge — a ~16px target — so the rest of the field silently means
     "type it yourself". One delegated listener fixes every date input in the
     app at once, including the ones inside modals that mount straight onto
     <body> after this runs.

     Deliberately click-only: opening on focus would fire the picker at anyone
     tabbing through a form. Typing still works — the field keeps focus while
     the picker is up, and Escape dismisses it. Opt a field out with
     data-no-picker. `time` inputs are left alone; a clock is not a calendar,
     and their pickers are more nuisance than help. */
  const PICKER_TYPES = ["date", "datetime-local", "month", "week"];

  function openPicker(e) {
    const input = e.target;
    if (!input || input.tagName !== "INPUT") return;
    if (!PICKER_TYPES.includes(input.type)) return;
    if (input.disabled || input.readOnly) return;
    if (input.dataset.noPicker != null || input.closest("[data-no-picker]")) return;
    if (typeof input.showPicker !== "function") return;   // Firefox, older Safari
    try {
      input.showPicker();
    } catch {
      /* Already open, or the click wasn't treated as user activation. Either
         way the field still works by hand — never let this break input. */
    }
  }

  function autoNow() {
    document.addEventListener("click", openPicker);
    decorate(document.body);
    // Views re-render constantly and modals mount straight onto <body>, so
    // watch rather than decorating at each call site.
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => { queued = false; decorate(document.body); });
    }).observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", autoNow);
  else autoNow();

  /* ---- textareas you can size ------------------------------------------
     A box that grows over weeks — "to look into later", a project note, a
     pass write-up — is unreadable at three rows and in the way at thirty, and
     which one it should be is a habit rather than a per-entry decision. So the
     field carries an S/M/L/XL toggle and remembers the choice per FIELD, under
     `prefKey`. Dragging the corner still works and overrides the row count
     until the next toggle press.

     Lives here rather than in the reading workspace it started in, because it
     turned out to have nothing to do with reading. */
  const AREA_SIZES = [
    { key: "s", label: "S", rows: 3 },
    { key: "m", label: "M", rows: 10 },
    { key: "l", label: "L", rows: 20 },
    { key: "xl", label: "XL", rows: 36 },
  ];
  const AREA_DEFAULT = "m";

  function sizePref(key, dflt) {
    try { return localStorage.getItem("synapse.areaSize." + key) || dflt; }
    catch (_) { return dflt; }
  }

  /* The S/M/L/XL row itself. `apply` receives the chosen size and does whatever
     that means for the thing being sized — rows for a textarea, height and text
     size for a read pane. */
  function sizeButtons(sizes, prefKey, dflt, apply, titleOf) {
    const btns = el("div.wl-sizebtns");
    const set = (key, remember) => {
      const s = sizes.find((x) => x.key === key) || sizes.find((x) => x.key === dflt);
      apply(s);
      if (remember) { try { localStorage.setItem("synapse.areaSize." + prefKey, s.key); } catch (_) {} }
      btns.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.size === s.key));
    };
    sizes.forEach((s) => {
      const b = el("button.btn-sm.wl-sizebtn", {
        type: "button", title: titleOf(s), text: s.label, onclick: () => set(s.key, true),
      });
      b.dataset.size = s.key;
      btns.appendChild(b);
    });
    set(sizePref(prefKey, dflt), false);
    return btns;
  }

  function sizedArea(area, prefKey, opts) {
    opts = opts || {};
    // `dflt` is the size this field opens at before you've ever pressed a
    // button — a project note wants to be a couple of lines, a "to look into
    // later" wants to be a page. Once you choose, your choice is what sticks.
    const btns = sizeButtons(AREA_SIZES, prefKey, opts.dflt || AREA_DEFAULT,
      (s) => { area.rows = s.rows; area.style.height = ""; },   // drop any manual drag so the toggle wins
      (s) => "show about " + s.rows + " lines");
    return el("div.wl-sized", {}, [
      el("div.wl-sizebar", {}, [
        el("span.wl-label", { text: opts.label || "" }),
        btns,
      ]),
      area,
    ]);
  }

  /* ---- rename in place --------------------------------------------------
     A title you can click and type over. The alternative is a modal, and a
     modal for one field costs more attention than correcting a typo is worth
     — the same reasoning the project colour picker is built on.

     Enter or blur commits, Escape puts the old text back. The save is awaited
     before the input is swapped back out, so a rejected rename (an empty title,
     a dead connection) leaves you in the box with your text still there rather
     than silently reverting. */
  function inlineRename(text, onSave, opts) {
    const o = opts || {};
    const span = el("span" + (o.cls ? "." + o.cls : ""), {
      text: text || o.placeholder || "untitled",
      title: o.title || "click to rename",
      style: "cursor:text;border-bottom:1px dashed var(--dim)" + (o.style ? ";" + o.style : ""),
    });
    if (!text && o.placeholder) span.style.color = "var(--muted)";

    span.addEventListener("click", () => {
      const input = el("input", {
        value: text || "",
        placeholder: o.placeholder || "",
        style: "font:inherit;color:inherit;background:var(--bg2,transparent);"
             + "border:1px solid var(--teal);border-radius:4px;padding:1px 5px;"
             + "min-width:" + Math.max(120, span.offsetWidth + 24) + "px"
             + (o.inputStyle ? ";" + o.inputStyle : ""),
      });
      let done = false;
      const revert = () => {
        if (done) return;
        done = true;
        input.replaceWith(span);
        // Some callers put the label where a button used to be (the pass ✎),
        // and leaving the label behind on cancel strands a control the caller
        // needs back. They say what to do instead of guessing here.
        if (o.onCancel) o.onCancel(span);
      };
      const commit = async () => {
        if (done) return;
        const v = input.value.trim();
        if (v === (text || "")) return revert();
        if (!v && !o.allowEmpty) { toast("can't be empty", true); input.focus(); return; }
        done = true;
        input.disabled = true;
        try { await onSave(v); }
        catch (e) { done = false; input.disabled = false; input.focus(); return; }
      };
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); commit(); }
        else if (e.key === "Escape") { e.preventDefault(); revert(); }
        e.stopPropagation();
      });
      input.addEventListener("blur", commit);
      // Clicking the label of a chip that also selects something shouldn't
      // select it as well.
      input.addEventListener("click", (e) => e.stopPropagation());
      span.replaceWith(input);
      input.focus();
      input.select();
    });
    return span;
  }

  /* ---- pick a border colour ---------------------------------------------
     Generalised from the Projects tree, which had this first: a dot you click
     for a small palette, positioned against the dot rather than centred as a
     dialog. `data-color` on the target is what the stylesheet reads, so a
     caller only has to store the name. "" is always first and means "no colour
     chosen" — whatever the thing looked like before. */
  const SWATCH_COLORS = ["", "yellow", "purple", "blue", "green", "red", "pink", "teal"];
  const SWATCH_LABEL = {
    "": "no colour", yellow: "yellow", purple: "purple", blue: "blue",
    green: "green", red: "red", pink: "pink", teal: "teal",
    orange: "orange", amber: "amber", gold: "gold", lime: "lime",
    mint: "mint", emerald: "emerald", cyan: "cyan", sky: "sky",
    navy: "navy", indigo: "indigo", violet: "violet", lavender: "lavender",
    magenta: "magenta", rose: "rose", coral: "coral", crimson: "crimson",
    brown: "brown", sand: "sand", olive: "olive", slate: "slate",
    silver: "silver", white: "white",
  };
  /* The long palette, for surfaces where colour is a filing system rather than
     an accent — the Repository, where there are enough papers that seven
     colours run out. Cut from 30 to 20 on 2026-10-28 for contrast: the old set
     had pairs only ~9 apart (navy/indigo, yellow/gold, teal/emerald) and
     every pair here is ≥25 apart (CIELAB ΔE). Every name a paper already used
     was kept, so no card loses its colour. These names are repainted for the
     Repository only (the `.wide` swatch rules in main.css) — a yellow project
     or Workspace box keeps the old yellow. */
  const SWATCH_COLORS_WIDE = [
    "", "yellow", "orange", "red", "crimson", "pink", "magenta", "violet",
    "lavender", "navy", "blue", "cyan", "teal", "mint", "green", "lime",
    "olive", "brown", "sand", "silver", "white",
  ];

  function colorSwatch(current, onPick, opts) {
    const o = opts || {};
    const cur = current || "";
    const colors = o.colors || SWATCH_COLORS;
    const next = colors[(colors.indexOf(cur) + 1) % colors.length];
    const dot = el("button.ui-swatch" + (colors.length > 12 ? ".wide" : ""), {
      "data-color": cur,
      title: (o.title || "border colour") + ": " + (SWATCH_LABEL[cur] || cur)
           + (colors.length > 12 ? " — click to pick"
              : " — click for " + SWATCH_LABEL[next] + ", right-click to pick"),
    });

    /* Click steps to the next colour. Choosing a border is usually "not that
       one, the next one" rather than a decision about purple specifically, and
       a menu for that costs more attention than the choice is worth — so the
       dot IS the control and the palette is the escape hatch on right-click,
       for when you do want a particular colour.

       The caller rebuilds the dot from the saved value after each pick, so the
       new dot computes its own next step. While that round trip is in flight
       the dot ignores further clicks: a second click would be read off the
       stale value and land on the colour you just left. */
    function openPalette() {
      const open = document.querySelector(".ui-palette");
      if (open) open.remove();
      const pal = el("div.ui-palette" + (colors.length > 12 ? ".wide" : ""), {}, colors.map((c) =>
        el("button.ui-swatch" + (c === cur ? ".on" : ""), {
          "data-color": c, title: SWATCH_LABEL[c],
          onclick: (ev) => { ev.stopPropagation(); pal.remove(); onPick(c); },
        })));
      const r = dot.getBoundingClientRect();
      pal.style.left = (r.left + window.scrollX) + "px";
      pal.style.top = (r.bottom + window.scrollY + 4) + "px";
      document.body.appendChild(pal);
      const away = (ev) => {
        if (pal.contains(ev.target)) return;
        pal.remove(); document.removeEventListener("mousedown", away);
      };
      setTimeout(() => document.addEventListener("mousedown", away), 0);
    }

    const wide = colors.length > 12;
    let busy = false;
    dot.addEventListener("click", (e) => {
      e.stopPropagation();
      e.preventDefault();
      /* Thirty colours is past the point where stepping through them is
         quicker than looking — a wide palette opens on the first click. */
      if (wide) { openPalette(); return; }
      if (busy) return;
      busy = true;
      dot.classList.add("is-saving");
      Promise.resolve(onPick(next)).catch(() => {}).then(() => {
        busy = false;
        dot.classList.remove("is-saving");
      });
    });

    dot.addEventListener("contextmenu", (e) => {
      e.stopPropagation();
      e.preventDefault();
      openPalette();
    });
    return dot;
  }

  window.ui = { el, clear, toast, guard, famClass, fmtDate, confirmDo,
                nowHM, todayISO, stampNow, nowBtn, stampPair,
                inlineRename, colorSwatch, SWATCH_COLORS, SWATCH_COLORS_WIDE, SWATCH_LABEL,
                sizeButtons, sizedArea, sizePref, AREA_SIZES, AREA_DEFAULT };
})();

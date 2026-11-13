/* kbdnav.js — hover something, then steer with the arrow keys (2026-11-08).

   Put the mouse over a row or card and it becomes the current one (outlined).
   The arrow keys then move to the nearest item of the same kind in that
   direction, so one rule serves a list (↑ ↓) and a grid of cards (← → too).
   In a list, where there is nothing to the side, → opens the row (its ▸
   caret) and ← closes it. Enter clicks the item's main action: the caret on
   an Inbox row, "open" on a Repository card, the card on a Project card.

   Covered: Inbox to-do + archive rows, Questions rows, + note rows,
   Repository cards, Project tree rows and project cards, and the Phases
   "◆ To do this phase" list. A new list joins by giving its items
   `data-nav` and adding its class to KINDS.

   Keys are ignored while you are typing in a box, so arrows still move the
   text cursor there. Moving the mouse picks again; a mouseover caused by the
   page scrolling under a still mouse does not, or the selection would jump
   every time an arrow scrolled the page.

   A redraw replaces the elements, so the current item is remembered by its
   `data-nav` id and found again on the next key. */
(function () {
  const KINDS = [".ib-row", ".lb-row", ".repo-card", ".pj-row", ".pj-card", ".ph-inbox-row"];
  const SEL = KINDS.map((k) => k + "[data-nav]").join(",");
  let cur = null, curKind = null, curId = null;
  let lastMouse = { x: -1, y: -1 }, mouseMoved = false;

  const kindOf = (node) => KINDS.find((k) => node.matches(k));
  function set(node) {
    if (cur === node) return;
    if (cur) cur.classList.remove("kbd-cur");
    cur = node; curKind = node ? kindOf(node) : null;
    curId = node ? node.getAttribute("data-nav") : null;
    if (node) node.classList.add("kbd-cur");
  }
  function live() {
    if (cur && document.body.contains(cur)) return cur;
    if (!curId) return null;
    const again = document.querySelector(curKind + '[data-nav="' + CSS.escape(curId) + '"]');
    if (again) { cur = null; set(again); }
    return again;
  }

  document.addEventListener("mousemove", (e) => {
    mouseMoved = e.clientX !== lastMouse.x || e.clientY !== lastMouse.y;
    lastMouse = { x: e.clientX, y: e.clientY };
  }, true);
  document.addEventListener("mouseover", (e) => {
    if (!mouseMoved) return;
    const hit = e.target.closest && e.target.closest(SEL);
    if (hit && hit.offsetParent !== null) set(hit);
  }, true);

  // Nearest visible item of the same kind in a direction, by centre points:
  // mostly-in-line beats close-but-diagonal.
  function nearest(from, dx, dy) {
    const a = from.getBoundingClientRect();
    const ax = a.left + a.width / 2, ay = a.top + a.height / 2;
    let best = null, bestScore = Infinity;
    document.querySelectorAll(curKind + "[data-nav]").forEach((n) => {
      if (n === from || n.offsetParent === null) return;
      const b = n.getBoundingClientRect();
      const bx = b.left + b.width / 2, by = b.top + b.height / 2;
      const along = (bx - ax) * dx + (by - ay) * dy;
      if (along <= 2) return;
      const across = Math.abs((bx - ax) * dy) + Math.abs((by - ay) * dx);
      const score = along + across * 3;
      if (score < bestScore) { bestScore = score; best = n; }
    });
    return best;
  }

  // Enter: the row's caret (Inbox), the card's "open" button (Repository), or
  // the card itself when the whole card is the link (Project cards).
  function mainAction(node) {
    return node.querySelector(".ib-caret")
      || [...node.querySelectorAll("button")].find((b) => b.textContent.trim() === "open")
      || (node.matches(".pj-card") ? node : null);
  }

  document.addEventListener("keydown", (e) => {
    const DIR = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
    if (!DIR[e.key] && e.key !== "Enter") return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))) return;
    if (document.querySelector(".modal-overlay")) return;   // a popup owns the keys
    const node = live();
    if (!node) return;
    e.preventDefault();
    if (e.key === "Enter") { const b = mainAction(node); if (b) b.click(); return; }
    const [dx, dy] = DIR[e.key];
    const next = nearest(node, dx, dy);
    if (next) {
      set(next);
      next.scrollIntoView({ block: "nearest", inline: "nearest" });
      mouseMoved = false;
      return;
    }
    // nothing to the side in a list: → opens the row, ← closes it
    const caret = node.querySelector(".ib-caret");
    if (caret && dx) {
      const isOpen = caret.textContent.trim() === "▾";
      if ((dx > 0 && !isOpen) || (dx < 0 && isOpen)) caret.click();
    }
  });
})();

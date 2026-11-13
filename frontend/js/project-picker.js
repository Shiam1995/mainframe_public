/* project-picker.js — choosing which project you're looking at.

   Every project sub-view needs the same answer to "which project?", so the
   control lives here once. It was a <select>, which is fine for five projects
   and miserable for fifty: you can't see how much work is in one, and you
   can't search.

   Collapsed it's a chip showing the current project and its totals. Press it
   and it opens into a grid of cards you can search and click. Type to filter,
   Enter takes the first match — so it's fast by keyboard and browsable by
   mouse, without making you choose which one you are today. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;
  const KEY = "project.selected";

  let selected = (() => {
    try { return localStorage.getItem(KEY) || ""; } catch { return ""; }
  })();
  let cache = [];

  function setSelected(id) {
    selected = id;
    try { localStorage.setItem(KEY, id); } catch { /* ignore */ }
  }

  function fmtHours(mins) {
    const h = (mins || 0) / 60;
    return (h >= 10 ? h.toFixed(0) : h.toFixed(1)) + "h";
  }

  function when(iso) {
    if (!iso) return "never worked";
    const d = new Date(iso + "T00:00:00");
    const days = Math.round((Date.now() - d.getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 30) return days + "d ago";
    if (days < 365) return Math.round(days / 30) + "mo ago";
    return Math.round(days / 365) + "y ago";
  }

  async function load(force) {
    if (force || !cache.length) cache = await api.projects.list();
    if (!cache.some((p) => p.id === selected)) {
      setSelected(cache.length ? cache[0].id : "");
    }
    return cache;
  }

  function card(p, onPick) {
    const active = p.id === selected;
    // A real <button>: pressable by mouse, reachable by Tab, fires on Enter.
    return el("button.pp-card" + (active ? ".active" : ""), {
      onclick: () => onPick(p.id),
      title: p.note || p.name,
    }, [
      el("div.pp-card-name", { text: p.name }),
      el("div.pp-card-meta", {}, [
        el("span", { text: fmtHours(p.total_mins) }),
        el("span", { text: (p.sessions ? p.sessions.length : 0) + " inst" }),
        p.push_count ? el("span.pp-push", { text: p.push_count + " ★" }) : null,
      ]),
      el("div.pp-card-when", { text: when(p.last_worked) }),
      p.note ? el("div.pp-card-note", { text: p.note }) : null,
    ]);
  }

  /* Mount the picker into `host`. `onChange` fires only when the selection
     actually changes, so a view can re-render without looping. */
  function mount(host, onChange) {
    const box = el("div.pp");
    host.appendChild(box);
    let open = false;

    function pick(id) {
      const changed = id !== selected;
      setSelected(id);
      open = false;
      draw();
      if (changed) onChange(id);
    }

    function draw() {
      clear(box);
      const current = cache.find((p) => p.id === selected);

      if (!cache.length) {
        box.appendChild(el("div.empty", {
          text: "No projects yet — make one on the Projects tab." }));
        return;
      }

      // --- collapsed: the chip ---
      const chip = el("button.pp-chip" + (open ? ".open" : ""), {
        onclick: () => { open = !open; draw(); },
      }, [
        el("span.pp-chip-label", { text: "project" }),
        el("span.pp-chip-name", { text: current ? current.name : "choose…" }),
        current ? el("span.pp-chip-meta", {
          text: fmtHours(current.total_mins) + " · " + when(current.last_worked),
        }) : null,
        el("span.pp-chip-caret", { text: open ? "▴" : "▾" }),
      ]);
      box.appendChild(chip);
      if (!open) return;

      // --- expanded: search + cards ---
      const search = el("input.pp-search", {
        type: "search", placeholder: "search projects…", autocomplete: "off",
      });
      const grid = el("div.pp-grid");

      function paint() {
        const q = search.value.trim().toLowerCase();
        const hits = cache.filter((p) =>
          !q || (p.name || "").toLowerCase().includes(q)
             || (p.note || "").toLowerCase().includes(q));
        clear(grid);
        if (!hits.length) {
          grid.appendChild(el("div.sub", { style: "padding:10px 2px",
                                           text: "nothing matches “" + q + "”" }));
          return;
        }
        hits.forEach((p) => grid.appendChild(card(p, pick)));
      }

      search.addEventListener("input", paint);
      search.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { open = false; draw(); return; }
        // Enter picks the first match — the whole point of typing a name.
        if (e.key === "Enter") {
          const first = grid.querySelector(".pp-card");
          if (first) first.click();
        }
      });

      box.appendChild(search);
      box.appendChild(grid);
      paint();
      search.focus();
    }

    draw();
    return { redraw: draw };
  }

  window.ProjectPicker = {
    get id() { return selected; },
    set id(v) { setSelected(v); },
    load,
    mount,
    // The Projects tab creates and deletes projects, so it needs to invalidate.
    refresh: () => guard(() => load(true)),
  };
})();

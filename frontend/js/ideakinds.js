/* ideakinds.js — the kinds of idea and the colour that marks each one.

   The colour lives on the KIND, not the idea, so every idea of a kind reads the
   same everywhere it appears. Kinds are user-extensible: add one with a colour
   and it shows up in the table, the quick-add, and the filters.

   Shared by ideas.js (the table) and quickidea.js (the floating capture). */
(function () {
  const { el, toast, guard } = window.ui;
  const api = window.api;

  const NEUTRAL = "#7FA8C8";              // a kind with no colour set yet
  let kinds = [];                          // [{name, color}]
  let loaded = null;                       // in-flight/settled load promise

  function load(force) {
    if (!force && loaded) return loaded;
    loaded = api.get("/api/synapse/ideas/categories")
      .then((rows) => { kinds = rows || []; return kinds; })
      .catch(() => { kinds = []; return kinds; });
    return loaded;
  }

  const all = () => kinds;
  const names = () => kinds.map((k) => k.name);
  function colorOf(name) {
    const k = kinds.find((x) => x.name === name);
    return (k && k.color) || NEUTRAL;
  }

  async function save(name, color) {
    const saved = await api.put("/api/synapse/ideas/categories", { name: name, color: color });
    const existing = kinds.find((k) => k.name === saved.name);
    if (existing) existing.color = saved.color;
    else kinds.push(saved);
    kinds.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    return saved;
  }

  async function remove(name) {
    await api.del("/api/synapse/ideas/categories/" + encodeURIComponent(name));
    kinds = kinds.filter((k) => k.name !== name);
  }

  /* A coloured chip for a kind — the visual mark used in tables and lists. */
  function chip(name, opts) {
    const o = opts || {};
    const c = colorOf(name);
    return el("span.kind-chip", {
      style: "color:" + c + ";border-color:" + c + "44;background:" + c + "1f"
        + (o.style ? ";" + o.style : ""),
      title: name || "no kind",
      text: name || "—",
    });
  }

  /* A <select> of kinds, each option tinted its colour. */
  function select(current, onChange, cls) {
    const sel = el("select" + (cls ? "." + cls : ""), {});
    sel.appendChild(el("option", { value: "", text: "—" }));
    kinds.forEach((k) => {
      const o = el("option", { value: k.name, text: k.name });
      o.style.color = k.color;
      if (k.name === current) o.setAttribute("selected", "");
      sel.appendChild(o);
    });
    // a kind that was typed before it existed as a row still shows
    if (current && !kinds.some((k) => k.name === current)) {
      const o = el("option", { value: current, text: current });
      o.setAttribute("selected", "");
      sel.appendChild(o);
    }
    const tint = () => { sel.style.color = sel.value ? colorOf(sel.value) : ""; };
    tint();
    sel.addEventListener("change", () => { tint(); if (onChange) onChange(sel.value); });
    return sel;
  }

  /* The kinds manager — add a kind, recolour it, delete it. */
  function manager(onChanged) {
    const wrap = el("div.card", { style: "margin-bottom:12px" });
    const list = el("div.kind-list");

    function draw() {
      clear(list);
      if (!kinds.length) list.appendChild(el("div.sub", { text: "No kinds yet — add one below." }));
      kinds.forEach((k) => {
        const swatch = el("input.kind-swatch", { type: "color", value: k.color || NEUTRAL });
        swatch.addEventListener("change", () => guard(async () => {
          await save(k.name, swatch.value);
          toast(k.name + " recoloured");
          draw(); if (onChanged) onChanged();
        }));
        list.appendChild(el("div.kind-row", {}, [
          swatch,
          chip(k.name),
          el("button.btn-sm.btn-danger", {
            title: "remove this kind (ideas keep the text, they just lose the colour)",
            onclick: () => guard(async () => {
              await remove(k.name); toast(k.name + " removed"); draw(); if (onChanged) onChanged();
            }),
            text: "×",
          }),
        ]));
      });
    }

    const nameIn = el("input", { placeholder: "new kind", style: "width:150px" });
    const colIn = el("input.kind-swatch", { type: "color", value: "#2DE2FF" });
    wrap.appendChild(el("div.spread", {}, [
      el("h3", { style: "margin:0", text: "Kinds" }),
      el("span.sub", { text: "the colour marks every idea of that kind" }),
    ]));
    wrap.appendChild(list);
    wrap.appendChild(el("div.row", { style: "gap:6px;margin-top:10px" }, [
      colIn, nameIn,
      el("button.btn-sm", {
        onclick: () => guard(async () => {
          const n = nameIn.value.trim();
          if (!n) return toast("name the kind", true);
          await save(n, colIn.value);
          nameIn.value = "";
          toast("kind added"); draw(); if (onChanged) onChanged();
        }),
        text: "+ kind",
      }),
    ]));
    draw();
    return wrap;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  window.IdeaKinds = { load, all, names, colorOf, save, remove, chip, select, manager, NEUTRAL };
})();

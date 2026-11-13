/* sheets.js — Sheets: databases you design yourself (Mainframe-level).

   A rail of sheets on the left, a spreadsheet grid on the right. Columns are
   typed, cells edit in place, formulas recompute after every write, and the
   filter/sort state can be saved as a named view.

   Formula values are NOT computed here — they come from the server
   (backend/formula.py), the same engine the CSV and JSON exports use. After a
   cell write the grid asks for /compute rather than doing its own arithmetic,
   because an aggregate like SUM() means one edit can change every other row. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const TYPES = [
    { v: "text", t: "Text" },
    { v: "longtext", t: "Long text" },
    { v: "number", t: "Number" },
    { v: "date", t: "Date" },
    { v: "checkbox", t: "Checkbox" },
    { v: "select", t: "Select" },
    { v: "multiselect", t: "Multi-select" },
    { v: "url", t: "URL" },
    { v: "email", t: "Email" },
    { v: "formula", t: "Formula" },
    { v: "link", t: "Link to…" },
  ];
  const LINK_KINDS = ["task", "paper", "project", "idea", "document"];
  const SUMMARIES = [
    { v: "", t: "—" }, { v: "sum", t: "Sum" }, { v: "avg", t: "Average" },
    { v: "min", t: "Min" }, { v: "max", t: "Max" }, { v: "count", t: "Count" },
    { v: "filled", t: "Filled" }, { v: "empty", t: "Empty" },
  ];
  // Which comparisons make sense for a column, by type.
  const OPS = {
    number: ["=", "≠", ">", "≥", "<", "≤", "is empty", "not empty"],
    date: ["=", "≠", ">", "≥", "<", "≤", "is empty", "not empty"],
    checkbox: ["is checked", "is unchecked"],
    select: ["=", "≠", "is empty", "not empty"],
    multiselect: ["has", "has not", "is empty", "not empty"],
    _default: ["contains", "not contains", "=", "≠", "is empty", "not empty"],
  };
  const opsFor = (type) => OPS[type] || OPS._default;

  let sheets = [], sheet = null, sheetId = null;
  // Every project, for the "for <project>" picker on a sheet.
  let projects = [];
  let railHost = null, mainHost = null;
  let filters = [], sorts = [], hidden = new Set();
  let sel = { row: 0, col: 0 };            // selected cell, in VISIBLE coordinates
  let editing = null;                      // {rowId, key} while a cell editor is open
  let menuOpen = null;

  const visibleCols = () => (sheet ? sheet.columns.filter((c) => !hidden.has(c.key)) : []);

  /* ------------------------------------------------------------------ *
   * Values
   * ------------------------------------------------------------------ */
  function raw(row, col) {
    if (col.type === "formula") return (row.computed || {})[col.key];
    if (col.type === "link") return (row.links || {})[col.key];
    return (row.cells || {})[col.key];
  }

  function display(row, col) {
    const v = raw(row, col);
    if (v === undefined || v === null || v === "") return "";
    if (col.type === "link") return v.label || "";
    if (col.type === "checkbox") return v ? "✓" : "";
    if (col.type === "multiselect") return Array.isArray(v) ? v.join(", ") : String(v);
    if (col.type === "number" && typeof v === "number") {
      // Trim float noise without imposing a fixed number of decimals.
      return Number.isInteger(v) ? String(v) : String(Math.round(v * 1e6) / 1e6);
    }
    return String(v);
  }

  const asNumber = (v) => {
    if (typeof v === "number") return v;
    const n = parseFloat(String(v == null ? "" : v).replace(/,/g, ""));
    return Number.isNaN(n) ? null : n;
  };

  /* ------------------------------------------------------------------ *
   * Filter + sort (client-side: a personal sheet is hundreds of rows,
   * and doing it here keeps every keystroke instant)
   * ------------------------------------------------------------------ */
  function passes(row) {
    return filters.every((f) => {
      const col = sheet.columns.find((c) => c.key === f.key);
      if (!col) return true;
      const v = raw(row, col);
      const text = String(display(row, col)).toLowerCase();
      const target = String(f.value == null ? "" : f.value).toLowerCase();
      const blank = v === undefined || v === null || v === "" ||
                    (Array.isArray(v) && !v.length);
      switch (f.op) {
        case "is empty": return blank;
        case "not empty": return !blank;
        case "is checked": return !!v;
        case "is unchecked": return !v;
        case "contains": return text.includes(target);
        case "not contains": return !text.includes(target);
        case "has": return (Array.isArray(v) ? v : String(v || "").split(","))
          .some((x) => String(x).trim().toLowerCase() === target);
        case "has not": return !(Array.isArray(v) ? v : String(v || "").split(","))
          .some((x) => String(x).trim().toLowerCase() === target);
        case "=": return text === target;
        case "≠": return text !== target;
        default: {
          const a = asNumber(v), b = asNumber(f.value);
          const cmp = (a !== null && b !== null)
            ? (a < b ? -1 : a > b ? 1 : 0)
            : (text < target ? -1 : text > target ? 1 : 0);
          return { ">": cmp > 0, "≥": cmp >= 0, "<": cmp < 0, "≤": cmp <= 0 }[f.op] || true;
        }
      }
    });
  }

  function ordered() {
    const rows = (sheet.rows || []).filter(passes);
    if (!sorts.length) return rows;
    return rows.slice().sort((r1, r2) => {
      for (const s of sorts) {
        const col = sheet.columns.find((c) => c.key === s.key);
        if (!col) continue;
        const a = raw(r1, col), b = raw(r2, col);
        const na = asNumber(col.type === "link" ? (a || {}).label : a);
        const nb = asNumber(col.type === "link" ? (b || {}).label : b);
        let cmp;
        if (na !== null && nb !== null) cmp = na - nb;
        else {
          const sa = display(r1, col).toLowerCase(), sb = display(r2, col).toLowerCase();
          // Blanks sink to the bottom whichever way the sort runs — an empty
          // cell isn't "smallest", it's absent.
          if (!sa && sb) return 1;
          if (sa && !sb) return -1;
          cmp = sa < sb ? -1 : sa > sb ? 1 : 0;
        }
        if (cmp) return s.dir === "desc" ? -cmp : cmp;
      }
      return 0;
    });
  }

  function summarise(col, rows) {
    if (!col.summary) return "";
    const vals = rows.map((r) => raw(r, col));
    const filled = vals.filter((v) => v !== undefined && v !== null && v !== "" &&
                                      !(Array.isArray(v) && !v.length));
    if (col.summary === "filled") return String(filled.length);
    if (col.summary === "empty") return String(vals.length - filled.length);
    if (col.summary === "count") return String(vals.length);
    const nums = vals.map(asNumber).filter((n) => n !== null);
    if (!nums.length) return "—";
    const round = (n) => (Number.isInteger(n) ? String(n) : String(Math.round(n * 100) / 100));
    if (col.summary === "sum") return round(nums.reduce((a, b) => a + b, 0));
    if (col.summary === "avg") return round(nums.reduce((a, b) => a + b, 0) / nums.length);
    if (col.summary === "min") return round(Math.min(...nums));
    if (col.summary === "max") return round(Math.max(...nums));
    return "";
  }

  /* ------------------------------------------------------------------ *
   * Loading + writing
   * ------------------------------------------------------------------ */
  async function reloadRail() {
    sheets = await api.sheets.list();
    // For the "for <project>" picker. Failing to load it must not stop the
    // sheets from opening, so an error here leaves the list empty.
    try { projects = await api.projects.list(); } catch { projects = []; }
    renderRail();
  }

  async function openSheet(id) {
    sheetId = id;
    sheet = await api.sheets.get(id);
    filters = []; sorts = []; hidden = new Set();
    sel = { row: 0, col: 0 };
    renderRail();
    renderMain();
  }

  async function recompute() {
    // Cheap next to refetching the sheet, and it's the only thing an edit can
    // change beyond the cell you touched.
    const map = await api.sheets.compute(sheetId);
    sheet.rows.forEach((r) => { r.computed = map[r.id] || {}; });
  }

  async function writeCell(row, col, value) {
    const updated = await api.sheets.updateRow(sheetId, row.id, { [col.key]: value });
    row.cells = updated.cells;
    row.links = updated.links;
    if (sheet.columns.some((c) => c.type === "formula")) await recompute();
    renderGrid();
  }

  /* ------------------------------------------------------------------ *
   * Rail
   * ------------------------------------------------------------------ */
  function renderRail() {
    if (!railHost) return;
    clear(railHost);
    if (!sheets.length) {
      railHost.appendChild(el("div.sub", { style: "padding:14px 4px", text: "no sheets yet" }));
      return;
    }
    sheets.forEach((s) => {
      railHost.appendChild(el("button.sh-item" + (s.id === sheetId ? ".active" : ""), {
        onclick: () => guard(() => openSheet(s.id)),
      }, [
        el("div.sh-item-t", { text: s.name || "Untitled sheet" }),
        // Which project this table belongs to — the rail's "project column".
        // Resolved live on the server, so renaming a project renames it here.
        el("div.sh-item-m", { text: `${s.rows} rows · ${s.cols} cols`
          + (s.project_name ? " · " + s.project_name : "") }),
      ]));
    });
  }

  /* ------------------------------------------------------------------ *
   * Column menu
   * ------------------------------------------------------------------ */
  function closeMenu() {
    if (menuOpen) { menuOpen.remove(); menuOpen = null; }
  }
  document.addEventListener("click", (e) => {
    if (menuOpen && !menuOpen.contains(e.target) && !e.target.closest(".sh-col-btn")) closeMenu();
  });

  function columnMenu(col, anchor) {
    closeMenu();
    const menu = el("div.sh-menu");
    const field = (label, node) => el("label.sh-field", {}, [el("span.sub", { text: label }), node]);
    const commit = (patch) => guard(async () => {
      const updated = await api.sheets.updateColumn(sheetId, col.id, patch);
      Object.assign(col, updated);
      // A rename rewrites formulas elsewhere in the sheet, and a type change
      // re-reads every cell — either way the truth is on the server now.
      sheet = await api.sheets.get(sheetId);
      closeMenu();
      renderMain();
    });

    const nameIn = el("input", { value: col.name });
    nameIn.addEventListener("change", () => commit({ name: nameIn.value.trim() || "Column" }));
    menu.appendChild(field("Name", nameIn));

    const typeSel = el("select", {}, TYPES.map((t) => el("option", { value: t.v, text: t.t })));
    typeSel.value = col.type;
    typeSel.addEventListener("change", () => commit({ type: typeSel.value }));
    menu.appendChild(field("Type", typeSel));

    if (col.type === "select" || col.type === "multiselect") {
      const opts = el("textarea", { rows: 4, placeholder: "one option per line" });
      opts.value = (col.options || []).join("\n");
      opts.addEventListener("change", () => commit({
        options: opts.value.split("\n").map((s) => s.trim()).filter(Boolean),
      }));
      menu.appendChild(field("Options", opts));
    }
    if (col.type === "link") {
      const kind = el("select", {}, LINK_KINDS.map((k) => el("option", { value: k, text: k })));
      kind.value = col.link_kind || "task";
      kind.addEventListener("change", () => commit({ link_kind: kind.value }));
      menu.appendChild(field("Links to", kind));
    }
    if (col.type === "formula") {
      const f = el("textarea.mono", { rows: 3, placeholder: "=[Price] * [Qty]" });
      f.value = col.formula || "";
      f.addEventListener("change", () => commit({ formula: f.value.trim() }));
      menu.appendChild(field("Formula", f));
      menu.appendChild(el("div.sh-hint", {
        text: "Refer to columns by name in [brackets]. SUM · AVG · MIN · MAX · COUNT "
            + "work down a whole column. Also IF, ROUND, LEN, UPPER, CONCAT, TODAY, DAYS.",
      }));
    }

    const sum = el("select", {}, SUMMARIES.map((s) => el("option", { value: s.v, text: s.t })));
    sum.value = col.summary || "";
    sum.addEventListener("change", () => commit({ summary: sum.value }));
    menu.appendChild(field("Footer summary", sum));

    const act = (label, fn) => el("button.sh-menu-act", { text: label, onclick: fn });
    menu.appendChild(el("div.sh-menu-acts", {}, [
      act("↑ sort A→Z", () => { sorts = [{ key: col.key, dir: "asc" }]; closeMenu(); renderMain(); }),
      act("↓ sort Z→A", () => { sorts = [{ key: col.key, dir: "desc" }]; closeMenu(); renderMain(); }),
      act("⊘ filter", () => {
        filters.push({ key: col.key, op: opsFor(col.type)[0], value: "" });
        closeMenu(); renderMain();
      }),
      act("👁 hide", () => { hidden.add(col.key); closeMenu(); renderMain(); }),
      act("＋ column right", () => guard(async () => {
        await api.sheets.addColumn(sheetId, { name: "Column", type: "text" });
        const ids = sheet.columns.map((c) => c.id);
        sheet = await api.sheets.get(sheetId);
        // addColumn appends; slot it next to the column the menu belongs to.
        const added = sheet.columns.find((c) => !ids.includes(c.id));
        const order = sheet.columns.filter((c) => c.id !== added.id).map((c) => c.id);
        order.splice(order.indexOf(col.id) + 1, 0, added.id);
        await api.sheets.reorderColumns(sheetId, order);
        sheet = await api.sheets.get(sheetId);
        closeMenu(); renderMain();
      })),
    ]));

    const del = el("button.sh-menu-act.danger", { text: "🗑 delete column" });
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) { armed = true; del.textContent = "click again — deletes its data"; return; }
      guard(async () => {
        await api.sheets.delColumn(sheetId, col.id);
        sheet = await api.sheets.get(sheetId);
        closeMenu(); renderMain();
      });
    });
    menu.appendChild(del);

    document.body.appendChild(menu);
    const r = anchor.getBoundingClientRect();
    menu.style.top = (r.bottom + window.scrollY + 4) + "px";
    // Keep the menu on screen when the column is near the right edge.
    menu.style.left = Math.min(r.left + window.scrollX,
                               window.innerWidth - menu.offsetWidth - 12) + "px";
    menuOpen = menu;
  }

  /* ------------------------------------------------------------------ *
   * Cell editing
   * ------------------------------------------------------------------ */
  function beginEdit(td, row, col) {
    if (col.type === "formula") { toast("formula columns are computed — edit the formula in the column menu"); return; }
    if (editing) return;
    editing = { rowId: row.id, key: col.key };
    clear(td);
    td.classList.add("editing");

    const done = (value, move) => {
      editing = null;
      guard(async () => {
        await writeCell(row, col, value);
        if (move) moveSel(move.dr, move.dc);
      });
    };
    const cancel = () => { editing = null; renderGrid(); };

    let input;
    if (col.type === "checkbox") {
      // Nothing to type: flip it and be done.
      editing = null;
      td.classList.remove("editing");
      writeCell(row, col, !raw(row, col));
      return;
    } else if (col.type === "select") {
      input = el("select", {}, [el("option", { value: "", text: "—" })]
        .concat((col.options || []).map((o) => el("option", { value: o, text: o }))));
      input.value = raw(row, col) || "";
      input.addEventListener("change", () => done(input.value));
    } else if (col.type === "multiselect") {
      input = el("select", { multiple: true, size: Math.min(6, (col.options || []).length || 2) },
        (col.options || []).map((o) => el("option", { value: o, text: o })));
      const cur = raw(row, col) || [];
      [...input.options].forEach((o) => { o.selected = cur.includes(o.value); });
      input.addEventListener("change", () =>
        done([...input.selectedOptions].map((o) => o.value)));
    } else if (col.type === "link") {
      input = el("select", {}, [el("option", { value: "", text: "—" })]);
      const cur = raw(row, col);
      if (cur) input.appendChild(el("option", { value: cur.id, text: cur.label }));
      input.value = cur ? cur.id : "";
      guard(async () => {
        const targets = await api.sheets.linkTargets(col.link_kind || "task");
        const keep = input.value;
        clear(input);
        input.appendChild(el("option", { value: "", text: "—" }));
        targets.forEach((t) => input.appendChild(el("option", { value: t.id, text: t.label })));
        input.value = keep;
      });
      input.addEventListener("change", () => done(input.value));
    } else if (col.type === "longtext") {
      input = el("textarea.sh-edit", { rows: 3 });
      input.value = raw(row, col) || "";
      input.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.preventDefault(); cancel(); }
        // Enter makes a new line here; Ctrl/Cmd+Enter or blur commits.
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); done(input.value); }
      });
      input.addEventListener("blur", () => { if (editing) done(input.value); });
    } else {
      const kind = col.type === "date" ? "date" : col.type === "number" ? "number"
        : col.type === "url" ? "url" : col.type === "email" ? "email" : "text";
      input = el("input.sh-edit", { type: kind, step: kind === "number" ? "any" : null });
      input.value = raw(row, col) == null ? "" : raw(row, col);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.preventDefault(); cancel(); }
        else if (e.key === "Enter") { e.preventDefault(); done(input.value, { dr: 1, dc: 0 }); }
        else if (e.key === "Tab") { e.preventDefault(); done(input.value, { dr: 0, dc: e.shiftKey ? -1 : 1 }); }
      });
      input.addEventListener("blur", () => { if (editing) done(input.value); });
    }

    td.appendChild(input);
    input.focus();
    if (input.select) input.select();
  }

  function moveSel(dr, dc) {
    const rows = ordered(), cols = visibleCols();
    sel.row = Math.max(0, Math.min(rows.length - 1, sel.row + dr));
    sel.col = Math.max(0, Math.min(cols.length - 1, sel.col + dc));
    paintSelection();
  }

  function paintSelection() {
    const grid = document.getElementById("sh-grid");
    if (!grid) return;
    grid.querySelectorAll("td.sel").forEach((td) => td.classList.remove("sel"));
    const td = grid.querySelector(`td[data-r="${sel.row}"][data-c="${sel.col}"]`);
    if (td) {
      td.classList.add("sel");
      td.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function onGridKey(e) {
    if (editing) return;
    const rows = ordered(), cols = visibleCols();
    if (!rows.length || !cols.length) return;
    const nav = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
    if (nav) { e.preventDefault(); moveSel(nav[0], nav[1]); return; }
    if (e.key === "Tab") { e.preventDefault(); moveSel(0, e.shiftKey ? -1 : 1); return; }
    if (e.key === "Enter" || e.key === "F2") {
      e.preventDefault();
      const td = document.querySelector(`#sh-grid td[data-r="${sel.row}"][data-c="${sel.col}"]`);
      if (td) beginEdit(td, rows[sel.row], cols[sel.col]);
      return;
    }
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      const col = cols[sel.col];
      if (col.type !== "formula") guard(() => writeCell(rows[sel.row], col, ""));
      return;
    }
    // Any printable character starts editing, like a real spreadsheet.
    if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const td = document.querySelector(`#sh-grid td[data-r="${sel.row}"][data-c="${sel.col}"]`);
      const col = cols[sel.col];
      if (td && col.type !== "formula" && col.type !== "checkbox") {
        beginEdit(td, rows[sel.row], col);
        const input = td.querySelector("input,textarea");
        if (input) { input.value = e.key; e.preventDefault(); }
      }
    }
  }

  /* ------------------------------------------------------------------ *
   * Grid
   * ------------------------------------------------------------------ */
  function renderGrid() {
    const host = document.getElementById("sh-grid-host");
    if (!host) return;
    clear(host);
    const cols = visibleCols();
    const rows = ordered();

    const table = el("table.sh-table", { id: "sh-grid" });
    const colgroup = el("colgroup", {}, [el("col", { style: "width:44px" })]
      .concat(cols.map((c) => el("col", { style: "width:" + (c.width || 160) + "px" })))
      .concat([el("col", { style: "width:40px" })]));
    table.appendChild(colgroup);

    // --- header ---
    const head = el("tr", {}, [el("th.sh-rownum", { text: "" })]);
    cols.forEach((c) => {
      const sort = sorts.find((s) => s.key === c.key);
      const btn = el("button.sh-col-btn", { title: "column options", text: "▾" });
      btn.addEventListener("click", (e) => { e.stopPropagation(); columnMenu(c, btn); });
      head.appendChild(el("th", {}, [
        el("div.sh-col", {}, [
          el("span.sh-col-name", { text: c.name }),
          c.type === "formula" ? el("span.sh-col-fx", { title: c.formula, text: "fx" }) : null,
          sort ? el("span.sh-col-sort", { text: sort.dir === "desc" ? "↓" : "↑" }) : null,
          btn,
        ]),
      ]));
    });
    head.appendChild(el("th", {}, [
      el("button.sh-col-btn", { title: "add a column", text: "＋",
        onclick: () => guard(async () => {
          await api.sheets.addColumn(sheetId, { name: "Column", type: "text" });
          sheet = await api.sheets.get(sheetId);
          renderMain();
        }) }),
    ]));
    table.appendChild(el("thead", {}, [head]));

    // --- body ---
    const body = el("tbody");
    rows.forEach((row, ri) => {
      const tr = el("tr", {}, [
        el("td.sh-rownum", { "data-eid": row.id, text: String(ri + 1) })]);
      cols.forEach((col, ci) => {
        const td = el("td", { "data-r": ri, "data-c": ci, "data-type": col.type });
        const v = raw(row, col);
        if (col.type === "checkbox") {
          td.appendChild(el("span.sh-check" + (v ? ".on" : ""), { text: v ? "✓" : "" }));
        } else if (col.type === "link" && v) {
          td.appendChild(el("span.sh-link", { text: v.label || "" }));
        } else if (col.type === "select" && v) {
          td.appendChild(el("span.sh-pill", { text: String(v) }));
        } else if (col.type === "multiselect" && Array.isArray(v) && v.length) {
          v.forEach((x) => td.appendChild(el("span.sh-pill", { text: x })));
        } else if (col.type === "url" && v) {
          td.appendChild(el("a.sh-url", { href: String(v), target: "_blank",
                                          rel: "noopener", text: String(v) }));
        } else {
          const text = display(row, col);
          td.appendChild(el("span" + (String(text).startsWith("#ERROR") ? ".sh-err" : ""),
                            { text }));
        }
        td.addEventListener("click", () => {
          sel = { row: ri, col: ci };
          paintSelection();
        });
        td.addEventListener("dblclick", () => beginEdit(td, row, col));
        tr.appendChild(td);
      });
      const del = el("button.sh-rowdel", { title: "delete row", text: "×" });
      let armed = false;
      del.addEventListener("click", () => {
        if (!armed) { armed = true; del.textContent = "✓?"; del.classList.add("armed");
                      setTimeout(() => { armed = false; del.textContent = "×"; del.classList.remove("armed"); }, 3000);
                      return; }
        guard(async () => {
          await api.sheets.delRow(sheetId, row.id);
          sheet.rows = sheet.rows.filter((r) => r.id !== row.id);
          if (sheet.columns.some((c) => c.type === "formula")) await recompute();
          renderGrid();
        });
      });
      tr.appendChild(el("td", {}, [del]));
      body.appendChild(tr);
    });
    table.appendChild(body);

    // --- footer summaries ---
    if (cols.some((c) => c.summary)) {
      const foot = el("tr", {}, [el("td.sh-rownum", { text: "Σ" })]);
      cols.forEach((c) => foot.appendChild(el("td.sh-sum", { text: summarise(c, rows) })));
      foot.appendChild(el("td"));
      table.appendChild(el("tfoot", {}, [foot]));
    }

    const count = document.getElementById("sh-count");
    if (count) count.textContent =
      `${rows.length} of ${sheet.rows.length} rows · `
      + `${cols.length} of ${sheet.columns.length} columns`;

    host.appendChild(table);
    host.appendChild(el("button.sh-addrow", { text: "＋ new row",
      onclick: () => guard(async () => {
        const row = await api.sheets.addRow(sheetId);
        sheet.rows.push({ ...row, computed: {} });
        if (sheet.columns.some((c) => c.type === "formula")) await recompute();
        renderGrid();
        sel = { row: ordered().length - 1, col: 0 };
        paintSelection();
      }) }));
    paintSelection();
  }

  /* ------------------------------------------------------------------ *
   * Filter / view bars
   * ------------------------------------------------------------------ */
  function filterBar() {
    const bar = el("div.sh-filters");
    filters.forEach((f, i) => {
      const col = sheet.columns.find((c) => c.key === f.key);
      if (!col) return;
      const colSel = el("select.sh-mini", {}, sheet.columns.map((c) =>
        el("option", { value: c.key, text: c.name })));
      colSel.value = f.key;
      colSel.addEventListener("change", () => {
        f.key = colSel.value;
        const nc = sheet.columns.find((c) => c.key === f.key);
        if (!opsFor(nc.type).includes(f.op)) f.op = opsFor(nc.type)[0];
        renderMain();
      });
      const opSel = el("select.sh-mini", {}, opsFor(col.type).map((o) =>
        el("option", { value: o, text: o })));
      opSel.value = f.op;
      opSel.addEventListener("change", () => { f.op = opSel.value; renderMain(); });

      const needsValue = !["is empty", "not empty", "is checked", "is unchecked"].includes(f.op);
      let valIn = null;
      if (needsValue) {
        if (col.type === "select" || col.type === "multiselect") {
          valIn = el("select.sh-mini", {}, [el("option", { value: "", text: "—" })]
            .concat((col.options || []).map((o) => el("option", { value: o, text: o }))));
        } else {
          valIn = el("input.sh-mini", {
            type: col.type === "date" ? "date" : col.type === "number" ? "number" : "text",
            placeholder: "value",
          });
        }
        valIn.value = f.value || "";
        // Re-render on input would steal focus every keystroke; repaint the grid only.
        valIn.addEventListener("input", () => { f.value = valIn.value; renderGrid(); });
      }
      bar.appendChild(el("span.sh-chip", {}, [
        colSel, opSel, valIn,
        el("button.sh-chip-x", { text: "×",
          onclick: () => { filters.splice(i, 1); renderMain(); } }),
      ]));
    });
    bar.appendChild(el("button.sh-act", { text: "＋ filter",
      onclick: () => {
        const c = sheet.columns[0];
        if (!c) return;
        filters.push({ key: c.key, op: opsFor(c.type)[0], value: "" });
        renderMain();
      } }));
    if (sorts.length) {
      bar.appendChild(el("span.sh-chip", {}, [
        el("span.sub", { text: "sorted by " +
          sorts.map((s) => (sheet.columns.find((c) => c.key === s.key) || {}).name +
                           (s.dir === "desc" ? " ↓" : " ↑")).join(", ") }),
        el("button.sh-chip-x", { text: "×", onclick: () => { sorts = []; renderMain(); } }),
      ]));
    }
    [...hidden].forEach((key) => {
      const c = sheet.columns.find((x) => x.key === key);
      if (!c) return;
      bar.appendChild(el("button.sh-act", { text: "👁 show " + c.name,
        onclick: () => { hidden.delete(key); renderMain(); } }));
    });
    return bar;
  }

  function viewBar() {
    const bar = el("div.sh-views");
    (sheet.views || []).forEach((v) => {
      bar.appendChild(el("button.sh-view", {
        text: v.name,
        onclick: () => {
          filters = JSON.parse(JSON.stringify(v.filters || []));
          sorts = JSON.parse(JSON.stringify(v.sorts || []));
          hidden = new Set(v.hidden || []);
          renderMain();
        },
      }));
      bar.appendChild(el("button.sh-view-x", { title: "delete view", text: "×",
        onclick: () => guard(async () => {
          await api.sheets.delView(sheetId, v.id);
          sheet = await api.sheets.get(sheetId);
          renderMain();
        }) }));
    });
    const nameIn = el("input.sh-mini", { placeholder: "save current as…" });
    nameIn.addEventListener("change", () => guard(async () => {
      if (!nameIn.value.trim()) return;
      await api.sheets.saveView(sheetId, {
        name: nameIn.value.trim(), filters, sorts, hidden: [...hidden],
      });
      sheet = await api.sheets.get(sheetId);
      toast("view saved");
      renderMain();
    }));
    bar.appendChild(nameIn);
    return bar;
  }

  /* ------------------------------------------------------------------ *
   * Main pane
   * ------------------------------------------------------------------ */
  function renderMain() {
    if (!mainHost) return;
    clear(mainHost);
    if (!sheet) {
      mainHost.appendChild(el("div.sh-empty", {}, [
        el("div", { style: "font-size:15px;margin-bottom:6px", text: "No sheet open" }),
        el("div.sub", { text: "Make one on the left, or import a CSV." }),
      ]));
      return;
    }

    const nameIn = el("input.sh-name", { value: sheet.name || "" });
    nameIn.addEventListener("change", () => guard(async () => {
      await api.sheets.update(sheetId, { name: nameIn.value.trim() || "Untitled sheet" });
      await reloadRail();
      toast("renamed");
    }));
    const descIn = el("input.sh-desc", { value: sheet.description || "",
                                         placeholder: "what this table is for" });
    descIn.addEventListener("change", () => guard(() =>
      api.sheets.update(sheetId, { description: descIn.value })));

    const del = el("button.sh-act.danger", { text: "🗑 delete sheet" });
    let armed = false;
    del.addEventListener("click", () => {
      if (!armed) { armed = true; del.textContent = "click again to delete"; del.classList.add("armed"); return; }
      guard(async () => {
        await api.sheets.del(sheetId);
        sheetId = null; sheet = null;
        await reloadRail();
        renderMain();
        toast("deleted");
      });
    });

    /* Which project this table belongs to. The same edge the project page
       reads, editable from either end — a table that turned out to belong to
       a project should not have to be rebuilt there. */
    const forSel = el("select.sh-act", { title: "the project this table belongs to" },
      [el("option", { value: "", text: "for: no project" })]);
    (projects || []).forEach((p) => {
      const o = el("option", { value: p.id, text: "for: " + p.name });
      if (p.id === sheet.project_id) o.setAttribute("selected", "");
      forSel.appendChild(o);
    });
    forSel.addEventListener("change", () => guard(async () => {
      await api.sheets.update(sheetId, { project_id: forSel.value });
      await reloadRail();
      sheet = await api.sheets.get(sheetId);
      toast(forSel.value ? "table moved" : "table has no project");
    }));

    mainHost.appendChild(el("div.sh-head", {}, [
      el("div.sh-head-l", {}, [nameIn, descIn]),
      el("div.sh-head-r", {}, [forSel]),
      el("div.sh-head-r", {}, [
        el("a.sh-act", { href: api.sheets.exportUrl(sheetId, "csv"), download: "", text: "↓ csv" }),
        el("a.sh-act", { href: api.sheets.exportUrl(sheetId, "json"), download: "", text: "↓ json" }),
        del,
      ]),
    ]));
    mainHost.appendChild(viewBar());
    mainHost.appendChild(filterBar());

    const gridHost = el("div.sh-grid-host", { id: "sh-grid-host", tabindex: "0" });
    gridHost.addEventListener("keydown", onGridKey);
    mainHost.appendChild(gridHost);
    // Filled in by renderGrid, which is what runs when a filter changes.
    mainHost.appendChild(el("div.sh-foot", {}, [el("span.sub", { id: "sh-count" })]));
    renderGrid();
  }

  /* ------------------------------------------------------------------ *
   * View
   * ------------------------------------------------------------------ */
  /* "open in Sheets" from a project page: name the sheet, then switch tabs.
     The view's own render opens whatever `sheetId` holds, so this is all the
     handoff needs to be. */
  window.SheetsTab = { open(id) { sheetId = id; } };

  window.Views = window.Views || {};
  window.Views.sheets = {
    id: "sheets",
    label: "Sheets",
    scoped: false,
    async render(viewEl) {
      /* A new sheet inherits the project of the one you are looking at. Made
         from inside a project's table, the next table is almost always for the
         same project, and the picker in the head is there to say otherwise. */
      const newBtn = el("button.btn-primary", { text: "+ New sheet",
        onclick: () => guard(async () => {
          const s = await api.sheets.create({
            name: "Untitled sheet",
            project_id: (sheet && sheet.project_id) || "",
          });
          await reloadRail();
          await openSheet(s.id);
        }) });

      const importIn = el("input", { type: "file", accept: ".csv,.tsv,.txt", style: "display:none" });
      importIn.addEventListener("change", () => guard(async () => {
        if (!importIn.files.length) return;
        const form = new FormData();
        form.append("file", importIn.files[0]);
        const s = await api.sheets.importCsv(form);
        importIn.value = "";
        await reloadRail();
        await openSheet(s.id);
        toast(`imported ${s.rows.length} rows`);
      }));

      railHost = el("div.sh-list");
      mainHost = el("div.sh-main");

      viewEl.appendChild(el("div.sh-wrap", {}, [
        el("div.sh-rail", {}, [
          el("div.sh-rail-top", {}, [
            newBtn,
            el("button.sh-act", { text: "↑ csv", title: "import a CSV as a new sheet",
                                  onclick: () => importIn.click() }),
            importIn,
          ]),
          railHost,
        ]),
        mainHost,
      ]));

      await reloadRail();
      if (sheetId && sheets.some((s) => s.id === sheetId)) await openSheet(sheetId);
      else if (sheets.length) await openSheet(sheets[0].id);
      else renderMain();
    },
  };
})();

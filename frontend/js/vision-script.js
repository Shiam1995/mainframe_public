/* vision-script.js — Vision · YouTube § Script + markers (VISION_UPDATE_SPEC §2).

   The spec's flagged key feature. The script shows as a numbered text block and
   you annotate LINE RANGES with labelled markers, drawn as coloured bars in a
   left gutter like code-editor annotations. The point: at a glance you can see
   "the hook is here, the abstraction is on line 12, the CTA is at the end" — a
   visual map of the script's structure.

   Overlapping markers get their own gutter lane, so two ranges covering the
   same lines both stay readable.

   Markers store line numbers, and the script is free text — so editing the
   script can strand a marker past the last line. Those aren't dropped (that
   would silently lose your annotations); they're listed as out-of-range so you
   can move or delete them. */
(function () {
  const { el, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;

  const LABELS = [
    { key: "hook",        icon: "🎯", label: "Hook",          color: "#FF4757", desc: "the opening that grabs attention" },
    { key: "key-point",   icon: "💡", label: "Key Point",     color: "var(--amber)", desc: "a core point being made" },
    { key: "abstraction", icon: "🧠", label: "Abstraction",   color: "var(--purple)", desc: "where you simplify a complex idea" },
    { key: "data",        icon: "📊", label: "Data/Evidence", color: "var(--blue)", desc: "where you present data or proof" },
    { key: "transition",  icon: "🔄", label: "Transition",    color: "var(--dim)", desc: "shift between sections" },
    { key: "climax",      icon: "💥", label: "Climax",        color: "#DE7BA4", desc: "the highest-impact moment" },
    { key: "cta",         icon: "📣", label: "CTA",           color: "var(--green)", desc: "call to action" },
    { key: "broll",       icon: "🎬", label: "B-Roll Cue",    color: "var(--teal)", desc: "where the visual should change" },
  ];
  const labelOf = (k) => LABELS.find((l) => l.key === k) || LABELS[1];

  let editing = false;        // script edit mode (plain textarea)
  let pending = null;         // first line clicked while picking a range

  /* Assign each marker a gutter lane so overlapping ranges stay readable. */
  function laneOf(markers) {
    const lanes = [];                       // lanes[i] = last line used
    const out = new Map();
    markers.slice()
      .sort((a, b) => a.line_start - b.line_start || a.line_end - b.line_end)
      .forEach((m) => {
        let lane = lanes.findIndex((last) => last < m.line_start);
        if (lane === -1) { lanes.push(m.line_end); lane = lanes.length - 1; }
        else lanes[lane] = m.line_end;
        out.set(m.id, lane);
      });
    return { lane: out, count: Math.max(1, lanes.length) };
  }

  function markerModal(v, marker, range, reload) {
    const editingMarker = !!marker;
    const start = el("input.mform-input", { type: "number", min: "1",
      value: String(editingMarker ? marker.line_start : range[0]) });
    const end = el("input.mform-input", { type: "number", min: "1",
      value: String(editingMarker ? marker.line_end : range[1]) });
    const sel = el("select.mform-input", {}, LABELS.map((l) => el("option", { value: l.key, text: l.icon + " " + l.label })));
    sel.value = editingMarker ? marker.label : "key-point";
    const hint = el("div.sub", { style: "margin-top:4px", text: labelOf(sel.value).desc });
    sel.addEventListener("change", () => { hint.textContent = labelOf(sel.value).desc; });
    const note = el("input.mform-input", { placeholder: "why this moment matters (optional)" });
    note.value = editingMarker ? (marker.note || "") : "";
    const field = (l, n) => el("div.mform-full", {}, [el("div.mform-label", { text: l }), n]);

    const overlay = el("div.modal-overlay");
    const close = () => { pending = null; overlay.remove(); };
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    overlay.appendChild(el("div.modal", {}, [
      el("div.modal-title", { text: editingMarker ? "Edit marker" : "New marker" }),
      el("div.mform-row", {}, [field("From line", start), field("To line", end)]),
      el("div.mform-full", {}, [el("div.mform-label", { text: "Label" }), sel, hint]),
      field("Note", note),
      el("div.row", { style: "margin-top:16px;gap:8px;justify-content:flex-end" }, [
        editingMarker ? el("button.btn-sm.btn-danger", { style: "margin-right:auto",
          onclick: () => confirmDo("Delete this marker?", async () => {
            await V().delMarker(v.id, marker.id); close(); reload();
          }), text: "delete" }) : null,
        el("button.btn-sm.btn-primary", { onclick: () => guard(async () => {
          const body = {
            line_start: parseInt(start.value) || 1, line_end: parseInt(end.value) || 1,
            label: sel.value, note: note.value.trim(),
          };
          if (editingMarker) await V().updateMarker(v.id, marker.id, body);
          else await V().addMarker(v.id, body);
          close(); toast(editingMarker ? "marker saved" : "marker added"); reload();
        }), text: editingMarker ? "Save" : "Add marker" }),
        el("button.btn-sm", { onclick: close, text: "Cancel" }),
      ]),
    ]));
    document.body.appendChild(overlay);
  }

  function render(host, v, reload) {
    const lines = (v.script || "").split("\n");
    const hasScript = (v.script || "").trim().length > 0;

    // --- toolbar ---
    const bar = el("div.row", { style: "margin-bottom:10px;gap:8px" }, [
      el("button.btn-sm" + (editing ? ".btn-primary" : ""), {
        onclick: () => { editing = !editing; pending = null; reload(); },
        text: editing ? "▤ done editing" : "✎ edit script" }),
      !editing && hasScript ? el("span.sub", {
        text: pending ? "click a second line to finish the marker (or click the same line again)"
                      : "click a line number to start a marker" }) : null,
      hasScript ? el("span.sub", { style: "margin-left:auto", text: lines.length + " lines · " + v.markers.length + " markers" }) : null,
    ]);
    host.appendChild(bar);

    if (editing) {
      const ta = el("textarea.mform-input", { rows: "18", placeholder: "paste or write the script — one line per line",
        style: "font-family:var(--mono);font-size:12px;line-height:1.7" });
      ta.value = v.script || "";
      ta.addEventListener("blur", () => guard(async () => {
        if ((ta.value || "") === (v.script || "")) return;
        await V().updateVideo(v.id, { script: ta.value }); v.script = ta.value; toast("script saved");
      }));
      host.appendChild(ta);
      host.appendChild(el("div.sub", { style: "margin-top:6px",
        text: "Markers point at line numbers — if you add or remove lines, check the markers still line up." }));
      return;
    }

    if (!hasScript) {
      host.appendChild(el("div.sub", { style: "font-style:italic",
        text: "No script yet. Write one with ✎ edit script, or push an approved response across from the prompt log." }));
      return;
    }

    // --- legend of labels actually in use ---
    const used = LABELS.filter((l) => v.markers.some((m) => m.label === l.key));
    if (used.length) {
      host.appendChild(el("div.row", { style: "gap:6px;flex-wrap:wrap;margin-bottom:8px" },
        used.map((l) => el("span.vmk-tag", { style: "background:transparent;border:1px solid " + l.color + ";color:" + l.color,
          text: l.icon + " " + l.label }))));
    }

    // --- the numbered script with gutter lanes ---
    const { lane, count } = laneOf(v.markers);
    const byStart = {};
    v.markers.forEach((m) => { (byStart[m.line_start] = byStart[m.line_start] || []).push(m); });

    const block = el("div.vmk-block");
    lines.forEach((text, i) => {
      const n = i + 1;
      const row = el("div.vmk-row");

      const gutter = el("div.vmk-gutter", { style: "width:" + (count * 7) + "px" });
      for (let L = 0; L < count; L++) {
        const m = v.markers.find((x) => lane.get(x.id) === L && x.line_start <= n && x.line_end >= n);
        const cell = el("div.vmk-lane");
        if (m) {
          const c = labelOf(m.label).color;
          cell.style.background = c;
          cell.title = labelOf(m.label).icon + " " + labelOf(m.label).label
            + " (L" + m.line_start + "–" + m.line_end + ")" + (m.note ? " — " + m.note : "");
          if (m.line_start === n) cell.classList.add("top");
          if (m.line_end === n) cell.classList.add("bottom");
          cell.addEventListener("click", () => markerModal(v, m, null, reload));
        }
        gutter.appendChild(cell);
      }

      const num = el("div.vmk-num" + (pending === n ? ".picking" : ""), { text: String(n) });
      num.addEventListener("click", () => {
        if (pending === null) { pending = n; reload(); return; }
        const range = [Math.min(pending, n), Math.max(pending, n)];
        markerModal(v, null, range, reload);
      });

      row.appendChild(gutter);
      row.appendChild(num);
      row.appendChild(el("div.vmk-text", { text: text || " " }));

      // marker tags sit inline on the line the marker starts on
      (byStart[n] || []).forEach((m) => {
        const l = labelOf(m.label);
        row.appendChild(el("span.vmk-tag", {
          style: "background:transparent;border:1px solid " + l.color + ";color:" + l.color,
          title: m.note || "click to edit", text: l.icon + " " + l.label,
          onclick: () => markerModal(v, m, null, reload),
        }));
      });
      block.appendChild(row);
    });
    host.appendChild(block);

    // --- markers pointing past the end of the script ---
    const stale = v.markers.filter((m) => m.line_start > lines.length);
    if (stale.length) {
      host.appendChild(el("div.sub", { style: "margin-top:10px;color:var(--amber)",
        text: "⚠ " + stale.length + " marker" + (stale.length === 1 ? "" : "s") + " point past the end of the script — the script got shorter. Click to fix:" }));
      host.appendChild(el("div.row", { style: "gap:6px;flex-wrap:wrap;margin-top:5px" },
        stale.map((m) => {
          const l = labelOf(m.label);
          return el("span.vmk-tag", { style: "background:transparent;border:1px solid var(--amber);color:var(--amber)",
            text: l.icon + " " + l.label + " L" + m.line_start + "–" + m.line_end,
            onclick: () => markerModal(v, m, null, reload) });
        })));
    }
  }

  window.VID_SECTIONS = window.VID_SECTIONS || [];
  window.VID_SECTIONS.push({ key: "script", label: "📝 Script", order: 20, render });
})();

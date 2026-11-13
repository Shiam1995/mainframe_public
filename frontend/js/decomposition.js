/* decomposition.js — break complex things into hierarchies of simpler things.

   Educational, not verificational. Code blocks here are CONTENT — written,
   read, displayed, never run. There is no runner, no status, no pass/fail, and
   nothing checks whether a breakdown is "correct".

   The graph is a DAG: the same child can sit under several parents, and depth
   is computed from whichever node you're viewing as the top rather than stored.
   Typing a child name that doesn't exist yet creates a stub — that's the
   primary authoring flow, not an error. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const API = "/api/decomposition";

  const LANGS = ["c", "c++", "python", "asm", "pseudo", "other"];
  let sel = null;          // selected node id
  let view = "main";       // which named breakdown we're looking at

  const get = (p) => api.get(API + p);

  window.Views = window.Views || {};
  window.Views.decomposition = {
    id: "decomposition", label: "Decomposition", scoped: false,
    async render(host) {
      clear(host);
      host.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Decomposition" }),
        el("div.sub", { text: "Break a paper, algorithm or system into simpler pieces. Type a name that doesn't exist and it becomes a stub." }),
      ])]));

      const bar = el("div.row", { style: "gap:8px;margin-bottom:10px;flex-wrap:wrap" });
      const cols = el("div.dec-cols");
      const listCol = el("div");
      const workCol = el("div");
      cols.append(listCol, workCol);
      host.append(bar, cols);

      async function reload() {
        const [nodes, tops] = await guard(() => Promise.all([get("/nodes"), get("/tops")]));
        drawBar(nodes);
        drawList(nodes, tops);
        await drawWork();
      }

      // ---- toolbar: new node, snapshots, architectures, transfer ----
      function drawBar(nodes) {
        clear(bar);
        const name = el("input", { placeholder: "new node name", style: "width:190px" });
        bar.append(
          name,
          el("button.btn-primary", {
            onclick: () => guard(async () => {
              if (!name.value.trim()) return toast("name it", true);
              const n = await api.post(API + "/nodes", { label: name.value.trim() });
              name.value = ""; sel = n.id; view = "main"; toast("created"); reload();
            }), text: "+ node",
          }),
          el("span.sub", { text: "│" }),
          el("button.btn-sm", { onclick: () => snapshotsPanel(), text: "snapshots" }),
          el("button.btn-sm", { onclick: () => architecturesPanel(), text: "architectures" }),
          el("a.btn-sm", { style: "text-decoration:none;margin-left:auto", href: API + "/export", download: "decomposition.json", text: "⬇ export" }),
          el("button.btn-sm", { onclick: () => importPanel(), text: "⬆ import" }),
          el("span.sub", { style: "font-size:11px", text: nodes.length + " nodes" }),
        );
      }

      // ---- left column: tops + everything ----
      function drawList(nodes, tops) {
        clear(listCol);
        const q = el("input", { placeholder: "search…", style: "width:100%" });
        const body = el("div");
        const paint = () => {
          clear(body);
          const term = q.value.trim().toLowerCase();
          const show = (arr, title) => {
            const items = arr.filter((n) => !term || (n.label || "").toLowerCase().includes(term) || n.id.includes(term));
            if (!items.length) return;
            body.appendChild(el("div.sub", { style: "margin:10px 0 4px;text-transform:uppercase;letter-spacing:1px;font-size:10px", text: title }));
            items.forEach((n) => body.appendChild(el("div.dec-item" + (n.id === sel ? ".on" : ""), {
              onclick: () => { sel = n.id; view = "main"; reload(); },
            }, [
              el("div", {}, [
                el("span", { style: "font-size:13px", text: n.label || n.id }),
                n.tag ? el("span.pill", { style: "margin-left:6px", text: n.tag }) : null,
              ]),
              el("span.sub", { style: "font-size:10px", text: (n.children || 0) + "↓ " + (n.parents || 0) + "↑" }),
            ])));
          };
          show(tops, "Tops — nothing breaks into these");
          show(nodes, "All nodes");
          if (!nodes.length) body.appendChild(el("div.empty", { text: "Nothing yet. Create a node above." }));
        };
        q.addEventListener("input", paint);
        listCol.append(el("div.card", {}, [q, body]));
        paint();
      }

      // ---- right column: the selected node ----
      async function drawWork() {
        clear(workCol);
        if (!sel) {
          workCol.appendChild(el("div.card", {}, [el("div.empty", { text: "Pick a node, or create one." })]));
          return;
        }
        let n;
        try { n = await get("/nodes/" + sel); }
        catch { sel = null; return drawWork(); }

        const card = el("div.card");
        const field = (l, node) => el("label.wl-field", {}, [el("span.wl-label", { text: l }), node]);
        const label = el("input", { value: n.label || "", style: "width:100%" });
        const tag = el("input", { value: n.tag || "", placeholder: "free-form grouping", style: "width:100%" });
        const ref = el("input", { value: n.ref || "", placeholder: "mylib/attn.h : attention()", style: "width:100%" });
        const summary = el("input.mform-input", { placeholder: "roughly what it does", style: "width:100%", value: n.summary || "" });
        const notes = el("textarea.mform-input", { rows: "4", placeholder: "longer prose", style: "width:100%" });
        notes.value = n.notes || "";
        const save = () => guard(async () => {
          await api.patch(API + "/nodes/" + n.id, {
            label: label.value, tag: tag.value, ref: ref.value,
            summary: summary.value, notes: notes.value,
          });
          toast("saved"); reload();
        });
        [label, tag, ref, summary, notes].forEach((x) => x.addEventListener("change", save));

        card.appendChild(el("div.spread", {}, [
          el("div", {}, [
            el("h3", { style: "margin:0", text: n.label || n.id }),
            el("div.sub", { style: "font-family:var(--mono);font-size:10px", text: n.id }),
          ]),
          el("button.btn-sm.btn-danger", {
            onclick: () => confirmDo("Delete “" + (n.label || n.id) + "”? Children are shared and are left alone.", async () => {
              await api.del(API + "/nodes/" + n.id); sel = null; reload();
            }), text: "delete",
          }),
        ]));
        card.appendChild(el("div.row", { style: "gap:10px;margin-top:8px;flex-wrap:wrap" }, [field("label", label), field("tag", tag)]));
        card.appendChild(el("div", { style: "margin-top:8px" }, [field("ref — a pointer into your code library, never resolved", ref)]));
        card.appendChild(el("div", { style: "margin-top:8px" }, [field("summary", summary)]));
        card.appendChild(el("div", { style: "margin-top:8px" }, [field("notes", notes)]));

        // --- views + children ---
        const viewNames = Object.keys(n.views);
        if (!viewNames.includes(view)) view = viewNames[0] || "main";
        const vbar = el("div.row", { style: "gap:6px;margin-top:14px;flex-wrap:wrap" }, [
          el("span.sub", { style: "font-size:10px;text-transform:uppercase;letter-spacing:1px", text: "Breakdown" }),
          ...viewNames.map((v) => el("button.btn-sm" + (v === view ? ".heat-on" : ""), {
            onclick: () => { view = v; drawWork(); }, text: v + " (" + n.views[v].length + ")",
          })),
          el("button.btn-sm", {
            onclick: () => guard(async () => {
              const nm = (window.prompt("Name the breakdown (e.g. detailed):") || "").trim();
              if (!nm) return;
              await api.post(API + "/nodes/" + n.id + "/views", { name: nm });
              view = nm; drawWork();
            }), text: "+ view",
          }),
          viewNames.length > 1 && view !== "main"
            ? el("button.btn-sm.btn-danger", {
                onclick: () => confirmDo("Remove the “" + view + "” breakdown?", async () => {
                  await api.del(API + "/nodes/" + n.id + "/views/" + encodeURIComponent(view));
                  view = "main"; drawWork();
                }), text: "× view" })
            : null,
        ]);
        card.appendChild(vbar);

        const kids = el("div", { style: "margin-top:6px" });
        (n.views[view] || []).forEach((cid) => {
          const c = n.children[cid] || { id: cid, label: cid };
          kids.appendChild(el("div.dec-child", {}, [
            el("span", { style: "cursor:pointer", onclick: () => { sel = cid; view = "main"; reload(); },
              text: c.label || cid }),
            c.summary ? el("span.sub", { style: "font-size:11px", text: c.summary.slice(0, 60) }) : el("span"),
            el("button.btn-sm.btn-danger", {
              onclick: () => guard(async () => {
                await api.del(API + "/nodes/" + n.id + "/children/" + cid + "?view=" + encodeURIComponent(view));
                drawWork();
              }), text: "×" }),
          ]));
        });
        if (!(n.views[view] || []).length) kids.appendChild(el("div.sub", { text: "Nothing under this breakdown yet." }));
        const childIn = el("input", { placeholder: "child name — creates it if new", style: "flex:1;min-width:170px" });
        kids.appendChild(el("div.row", { style: "gap:6px;margin-top:8px" }, [
          childIn,
          el("button.btn-sm", {
            onclick: () => guard(async () => {
              if (!childIn.value.trim()) return;
              await api.post(API + "/nodes/" + n.id + "/children", { view, child_id: childIn.value.trim() });
              childIn.value = ""; reload();
            }), text: "+ child" }),
        ]));
        card.appendChild(kids);

        // --- code blocks: content, never executed ---
        card.appendChild(el("div.sub", { style: "margin:14px 0 6px;text-transform:uppercase;letter-spacing:1px;font-size:10px",
          text: "Code — stored and displayed, never run" }));
        (n.blocks || []).forEach((b, i) => {
          const code = el("textarea.mform-input", { rows: "6", style: "width:100%;font-family:var(--mono);font-size:11px" });
          code.value = b.code || "";
          const lang = el("select", {}, LANGS.map((l) => {
            const o = el("option", { value: l, text: l }); if (l === b.lang) o.setAttribute("selected", ""); return o;
          }));
          const path = el("input", { value: b.path || "", placeholder: "path (optional, not resolved)", style: "flex:1;min-width:150px" });
          const put = () => guard(async () => {
            await api.patch(API + "/nodes/" + n.id + "/blocks/" + i, { lang: lang.value, path: path.value, code: code.value });
            toast("block saved");
          });
          [code, lang, path].forEach((x) => x.addEventListener("change", put));
          card.appendChild(el("div.dec-block", {}, [
            el("div.row", { style: "gap:6px" }, [lang, path,
              el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
                await api.del(API + "/nodes/" + n.id + "/blocks/" + i); drawWork();
              }), text: "×" })]),
            code,
          ]));
        });
        card.appendChild(el("div.row", { style: "margin-top:6px" }, [
          el("button.btn-sm", { onclick: () => guard(async () => {
            await api.post(API + "/nodes/" + n.id + "/blocks", { lang: "c", path: "", code: "" }); drawWork();
          }), text: "+ code block" }),
        ]));

        // --- capture ---
        card.appendChild(el("div.row", { style: "gap:6px;margin-top:14px;flex-wrap:wrap" }, [
          el("button.btn-sm", { onclick: () => guard(async () => {
            const nm = (window.prompt("Snapshot name:", n.label || n.id) || "").trim();
            if (!nm) return;
            const s = await api.post(API + "/snapshots", { root: n.id, name: nm });
            toast("snapshot saved — " + Object.keys(s.nodes).length + " nodes frozen");
          }), text: "📷 snapshot" }),
          el("button.btn-sm", { onclick: () => guard(async () => {
            const nm = (window.prompt("Architecture name:", n.label || n.id) || "").trim();
            if (!nm) return;
            await api.post(API + "/architectures", { root: n.id, name: nm });
            toast("architecture saved");
          }), text: "⧉ save as architecture" }),
        ]));
        workCol.appendChild(card);

        // --- the tree, with computed depths ---
        const t = await get("/tree/" + n.id + "?view=" + encodeURIComponent(view));
        const tree = el("div.card", { style: "margin-top:12px" });
        tree.appendChild(el("div.spread", {}, [
          el("h3", { style: "margin:0", text: "Tree" }),
          el("span.sub", { text: t.nodes.length + " nodes · depth computed from here, not stored" }),
        ]));
        t.nodes.forEach((x) => tree.appendChild(el("div.row", {
          style: "gap:8px;padding:3px 0;padding-left:" + (x.depth * 18) + "px;cursor:pointer",
          onclick: () => { sel = x.id; view = "main"; reload(); },
        }, [
          el("span.mono", { style: "font-size:10px;color:var(--muted)", text: "d" + x.depth }),
          el("span", { style: "font-size:12px", text: x.label || x.id }),
          x.tag ? el("span.pill", { text: x.tag }) : null,
        ])));
        workCol.appendChild(tree);
      }

      // ---- snapshots ----
      function snapshotsPanel() {
        guard(async () => {
          const snaps = await get("/snapshots");
          const body = el("div");
          if (!snaps.length) body.appendChild(el("div.sub", { text: "No snapshots yet — open a node and press 📷." }));
          snaps.forEach((s) => body.appendChild(el("div.row", { style: "gap:8px;padding:6px 0;border-bottom:1px solid var(--border)" }, [
            el("span", { style: "flex:1", text: s.name }),
            el("span.sub", { style: "font-size:11px", text: s.saved + " · " + s.node_count + " nodes" }),
            el("a.btn-sm", { href: API + "/snapshots/" + s.id + "/markdown", target: "_blank", style: "text-decoration:none", text: "markdown" }),
            el("button.btn-sm", { onclick: () => guard(async () => {
              const p = (window.prompt("Restore as new nodes with prefix:", "restored") || "").trim();
              if (!p) return;
              const r = await api.post(API + "/snapshots/" + s.id + "/restore", { prefix: p });
              toast("restored " + Object.keys(r.created).length + " nodes"); reload();
            }), text: "restore" }),
            el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
              await api.del(API + "/snapshots/" + s.id); toast("deleted"); snapshotsPanel();
            }), text: "×" }),
          ])));
          panel("Snapshots — frozen records; editing live nodes never changes them", body);
        });
      }

      function architecturesPanel() {
        guard(async () => {
          const arch = await get("/architectures");
          const body = el("div");
          if (!arch.length) body.appendChild(el("div.sub", { text: "No architectures yet — open a node and press ⧉." }));
          arch.forEach((a) => body.appendChild(el("div.row", { style: "gap:8px;padding:6px 0;border-bottom:1px solid var(--border)" }, [
            el("span", { style: "flex:1", text: a.name }),
            el("span.sub", { style: "font-size:11px", text: a.node_count + " nodes" }),
            el("button.btn-sm", { onclick: () => guard(async () => {
              const p = (window.prompt("Insert with prefix:", "copy") || "").trim();
              if (!p) return;
              const r = await api.post(API + "/architectures/" + a.id + "/insert", { prefix: p });
              toast("inserted " + Object.keys(r.created).length + " nodes"); reload();
            }), text: "insert" }),
            el("button.btn-sm.btn-danger", { onclick: () => guard(async () => {
              await api.del(API + "/architectures/" + a.id); architecturesPanel();
            }), text: "×" }),
          ])));
          panel("Architectures — reusable shapes; inserting leaves the stored copy untouched", body);
        });
      }

      function importPanel() {
        const ta = el("textarea.mform-input", { rows: "8", placeholder: "paste the export JSON", style: "width:100%;font-family:var(--mono);font-size:11px" });
        const merge = el("input", { type: "checkbox" });
        merge.checked = true;
        const body = el("div", {}, [
          ta,
          el("div.row", { style: "gap:8px;margin-top:8px" }, [
            el("label.wl-check", {}, [merge, el("span", { text: " merge (keep what's already here)" })]),
            el("button.btn-primary", { onclick: () => guard(async () => {
              let payload;
              try { payload = JSON.parse(ta.value); }
              catch { return toast("that isn't valid JSON", true); }
              const r = await api.post(API + "/import?merge=" + merge.checked, payload);
              toast("added " + r.added + ", kept " + r.kept); reload();
            }), text: "import" }),
          ]),
        ]);
        panel("Import — the reference client's export shape", body);
      }

      function panel(title, body) {
        const old = host.querySelector(".dec-panel");
        if (old) old.remove();
        const p = el("div.card.dec-panel", { style: "margin-bottom:10px" }, [
          el("div.spread", {}, [
            el("h3", { style: "margin:0", text: title }),
            el("button.btn-sm", { onclick: () => p.remove(), text: "close" }),
          ]),
          body,
        ]);
        cols.insertAdjacentElement("beforebegin", p);
      }

      await reload();
    },
  };
})();

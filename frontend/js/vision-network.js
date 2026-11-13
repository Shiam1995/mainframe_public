/* vision-network.js — Vision · Network (VISION_SPEC §5).

   Content-world contacts as a TABLE — who, where you know them from, when you
   first got in touch and when you last did. Click a row for the person's own
   page: every field editable, notes, a dated contact log (each time you were
   in touch — "last contacted" is read from it), and images.
   Avatar falls back to the initial letter when there's no image. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const V = () => window.api.vision;
  const api = window.api;

  let openId = null;                       // null = table, otherwise that person's page
  let sortKey = "name", sortDir = 1, query = "";

  const today = () => {
    const d = new Date();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  };
  const dateFmt = (iso) => {
    if (!iso) return "";
    const d = new Date(String(iso).slice(0, 10) + "T00:00:00");
    return isNaN(d) ? String(iso) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  };
  const ago = (iso) => {
    if (!iso) return "";
    const days = Math.round((new Date(today()) - new Date(String(iso).slice(0, 10))) / 864e5);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 31) return days + "d ago";
    if (days < 365) return Math.round(days / 30.4) + "mo ago";
    return (days / 365).toFixed(1).replace(/\.0$/, "") + "y ago";
  };
  // Urgency "!" — click to cycle none → red → blue → green → none.
  // Sorting ranks red first, then blue, green, none.
  const URG = ["", "red", "blue", "green"];
  const URG_TITLE = { "": "no urgency", red: "urgent", blue: "soon", green: "whenever" };
  const urgRank = (u) => ({ red: 0, blue: 1, green: 2 }[u] ?? 3);
  function urgBang(c, after) {
    const b = el("button.vnet-urg.u-" + (c.urgency || "none"), {
      title: URG_TITLE[c.urgency || ""] + " — click to cycle", text: "!",
      onclick: (e) => {
        e.stopPropagation();
        guard(async () => {
          const next = URG[(URG.indexOf(c.urgency || "") + 1) % URG.length];
          await V().updateContact(c.id, { urgency: next });
          c.urgency = next;
          b.className = "vnet-urg u-" + (next || "none");
          b.title = URG_TITLE[next] + " — click to cycle";
          if (after) after();
        });
      },
    });
    return b;
  }

  // last contact = newest logged interaction, else the first-contact date
  const lastOf = (c) => c.last_contact || c.first_contact || "";

  function avatar(c, big) {
    const cls = "div.vnet-avatar" + (big ? ".big" : "");
    return c.avatar
      ? el(cls, { style: "background-image:url(" + c.avatar + ")" })
      : el(cls + ".initial", { text: (c.name || "?").trim().charAt(0).toUpperCase() });
  }

  /* --- table ---------------------------------------------------------------- */
  const COLS = [
    { key: "urgency", label: "!" },
    { key: "name", label: "Name" },
    { key: "known_from", label: "Known from" },
    { key: "first_contact", label: "First contacted" },
    { key: "last", label: "Last contacted" },
    { key: "platform", label: "Platform" },
    { key: "role", label: "Role" },
    { key: "count", label: "Touches" },
  ];
  const sortVal = (c, k) =>
    k === "urgency" ? urgRank(c.urgency) : k === "last" ? lastOf(c) : k === "count" ? c.interactions.length : String(c[k] || "").toLowerCase();

  function table(items, reload) {
    const needle = query.trim().toLowerCase();
    const rows = items
      .filter((c) => !needle || [c.name, c.known_from, c.platform, c.role, c.notes]
        .join(" ").toLowerCase().includes(needle))
      .sort((a, b) => {
        const x = sortVal(a, sortKey), y = sortVal(b, sortKey);
        if (x === y) return 0;
        if (x === "" || x == null) return 1;           // blanks always sink
        if (y === "" || y == null) return -1;
        return (x < y ? -1 : 1) * sortDir;
      });

    const head = el("tr", {}, COLS.map((col) => el("th.vnet-th" + (sortKey === col.key ? ".on" : ""), {
      title: "sort", text: col.label + (sortKey === col.key ? (sortDir > 0 ? " ▲" : " ▼") : ""),
      onclick: () => {
        if (sortKey === col.key) sortDir = -sortDir;
        else { sortKey = col.key; sortDir = (col.key === "last" || col.key === "count" || col.key === "first_contact") ? -1 : 1; }
        reload();
      },
    })));
    head.appendChild(el("th.vnet-th", { style: "cursor:default" }));     // row delete column
    const body = el("tbody");
    if (!rows.length) body.appendChild(el("tr", {}, [el("td.sub", { colspan: String(COLS.length + 1), style: "padding:14px;font-style:italic", text: needle ? "No one matches." : "No contacts yet." })]));
    rows.forEach((c) => {
      const last = lastOf(c);
      body.appendChild(el("tr.vnet-row", { title: "open " + c.name, onclick: () => { openId = c.id; reload(); } }, [
        el("td", { style: "width:1%;text-align:center" }, [urgBang(c, () => { if (sortKey === "urgency") reload(); })]),
        el("td", {}, [el("div.row", { style: "gap:9px;flex-wrap:nowrap" }, [avatar(c), el("span", { style: "font-weight:600", text: c.name })])]),
        el("td", { text: c.known_from || "" }),
        el("td.mono", { text: dateFmt(c.first_contact) }),
        el("td", {}, last ? [el("span.mono", { text: dateFmt(last) }), el("span.sub", { text: "  " + ago(last) })] : []),
        el("td", { text: c.platform || "" }),
        el("td", { text: c.role || "" }),
        el("td.mono", { style: "text-align:center", text: c.interactions.length ? String(c.interactions.length) : "" }),
        el("td", { style: "width:1%;text-align:center" }, [el("button.ord-btn.vnet-del", {
          title: "delete " + c.name, text: "×",
          onclick: (e) => {
            e.stopPropagation();                     // the row click opens the person
            confirmDo("Delete “" + c.name + "” and their contact log?", async () => {
              await V().delContact(c.id); toast("deleted"); reload();
            });
          },
        })]),
      ]));
    });
    return el("div.vnet-tablewrap", {}, [el("table.vnet-table", {}, [el("thead", {}, [head]), body])]);
  }

  /* --- one person's page -------------------------------------------------- */
  function detail(c, reload) {
    const wrap = el("div");
    wrap.appendChild(el("button.btn-sm", { style: "margin-bottom:14px",
      onclick: () => { openId = null; reload(); }, text: "← back to network" }));

    const save = async (key, val) => {
      const nc = await V().updateContact(c.id, { [key]: val });
      Object.assign(c, nc); toast("saved");
    };
    const bind = (input, key) => {
      const ev = input.type === "date" ? "change" : "blur";
      input.addEventListener(ev, () => guard(async () => {
        if ((input.value || "") === (c[key] || "")) return;
        if (key === "name" && !input.value.trim()) { input.value = c.name; return toast("a contact needs a name", true); }
        await save(key, key === "name" ? input.value.trim() : input.value);
        if (key === "name" || key === "avatar") reload();
      }));
      return input;
    };
    const field = (label, node) => el("label.md-field", {}, [el("span.sub", { text: label }), node]);

    const fileIn = el("input.img-file", { type: "file", accept: ".png,.jpg,.jpeg,.gif,.webp,.svg" });
    fileIn.addEventListener("change", () => {
      const f = fileIn.files && fileIn.files[0];
      if (!f) return;
      window.Images.nameModal(f.name.replace(/\.[^.]+$/, ""), (name) => guard(async () => {
        const img = await api.images.upload(f, name, "vision", c.id);
        await V().updateContact(c.id, { avatar: api.images.fileUrl(img.id) });
        fileIn.value = ""; toast("avatar set"); reload();
      }));
    });
    const av = avatar(c, true);
    av.title = "upload a photo"; av.style.cursor = "pointer";
    av.addEventListener("click", () => fileIn.click());

    const last = lastOf(c);
    wrap.appendChild(el("div.vision-card", {}, [
      el("div.row", { style: "gap:16px;align-items:flex-start;flex-wrap:wrap" }, [
        el("div", {}, [av, fileIn]),
        el("div", { style: "flex:1;min-width:260px" }, [
          el("div.row", { style: "gap:10px;flex-wrap:nowrap" }, [
            urgBang(c), bind(el("input.vis-title", { value: c.name, style: "flex:1" }), "name"),
          ]),
          el("div.sub", { style: "margin:4px 0 10px", text: [
            c.known_from ? "known from " + c.known_from : null,
            last ? "last contacted " + ago(last) : "never contacted",
            c.interactions.length ? c.interactions.length + " touch" + (c.interactions.length > 1 ? "es" : "") + " logged" : null,
          ].filter(Boolean).join(" · ") }),
          el("div.md-grid", {}, [
            field("known from", bind(el("input", { value: c.known_from || "", placeholder: "where you know them from" }), "known_from")),
            field("first contacted", bind(el("input", { type: "date", value: (c.first_contact || "").slice(0, 10) }), "first_contact")),
            field("role", bind(el("input", { value: c.role || "", placeholder: "e.g. AI YouTuber" }), "role")),
            field("platform", bind(el("input", { value: c.platform || "", placeholder: "where you connect" }), "platform")),
            field("link", bind(el("input", { value: c.link || "", placeholder: "profile URL" }), "link")),
            field("email", bind(el("input", { value: c.email || "", placeholder: "email" }), "email")),
            field("avatar URL", bind(el("input", { value: c.avatar || "", placeholder: "image URL — or click the photo" }), "avatar")),
          ]),
          el("div.row", { style: "gap:6px;margin-top:12px" }, [
            c.link ? el("a.btn-sm", { href: c.link, target: "_blank", rel: "noopener noreferrer",
              style: "text-decoration:none", text: "open profile ↗" }) : null,
            c.email ? el("a.btn-sm", { href: "mailto:" + c.email, style: "text-decoration:none", text: "✉ email" }) : null,
            el("button.btn-sm.btn-danger", { style: "margin-left:auto",
              onclick: () => confirmDo("Delete “" + c.name + "” and their contact log?", async () => {
                await V().delContact(c.id); openId = null; reload();
              }), text: "delete" }),
          ]),
        ]),
      ]),
    ]));

    // notes
    const notesBox = el("div.vid-section");
    notesBox.appendChild(el("div.vid-sec-head", { text: "📝 Notes" }));
    notesBox.appendChild(window.RowBox({ label: "notes", placeholder: "who they are, what you talked about, an idea, something to remember", parentId: c.id }).node);
    wrap.appendChild(notesBox);

    // contact log
    const logBox = el("div.vid-section");
    logBox.appendChild(el("div.vid-sec-head", { text: "📅 Contact log" }));
    const dIn = el("input", { type: "date", value: today() });
    const chIn = el("input", { placeholder: "how — email, DM, call, met…", style: "flex:0 1 200px" });
    const noteIn = el("input", { placeholder: "what about", style: "flex:1;min-width:160px" });
    const addLog = () => guard(async () => {
      if (!dIn.value) return toast("pick a date", true);
      await V().addInteraction(c.id, { date: dIn.value, channel: chIn.value.trim(), note: noteIn.value.trim() });
      toast("logged"); reload();
    });
    noteIn.addEventListener("keydown", (e) => { if (e.key === "Enter") addLog(); });
    logBox.appendChild(el("div.row", { style: "gap:8px;flex-wrap:wrap" }, [
      dIn, chIn, noteIn, el("button.btn-sm.btn-primary", { onclick: addLog, text: "+ log contact" }),
    ]));
    if (!c.interactions.length) {
      logBox.appendChild(el("div.sub", { style: "margin-top:10px;font-style:italic", text: "Nothing logged yet — add each time you're in touch." }));
    }
    c.interactions.forEach((i) => logBox.appendChild(el("div.vid-entry.vnet-log", {}, [
      el("span.mono", { style: "flex:0 0 105px", text: dateFmt(i.date) }),
      el("span.vnet-chan", { text: i.channel || "—" }),
      el("span", { style: "flex:1;white-space:pre-wrap", text: i.note || "" }),
      el("button.ord-btn", { title: "delete", text: "×", onclick: () => guard(async () => {
        await V().delInteraction(c.id, i.id); reload();
      }) }),
    ])));
    wrap.appendChild(logBox);

    const imgs = el("div.vid-section");
    imgs.appendChild(el("div.vid-sec-head", { text: "📷 Images" }));
    window.Images.mount(imgs, { module: "vision", contextId: c.id, surface: "vision-contact" });
    wrap.appendChild(imgs);
    return wrap;
  }

  window.Views = window.Views || {};
  window.Views.network = {
    id: "network", label: "Network", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Network" }),
        el("div.sub", { text: "People in the content world — where you know them from and when you were last in touch. Click someone to open their page." }),
      ])]));
      const bar = el("div"); view.appendChild(bar);
      const host = el("div"); view.appendChild(host);

      async function reload() {
        const scroller = view.closest(".view") || view;
        clear(bar); clear(host);
        if (openId) {
          let c;
          try { c = await V().contact(openId); }
          catch { openId = null; return reload(); }
          host.appendChild(detail(c, reload));
          return;
        }

        // add row: name · known from · when you contacted them
        const nameIn = el("input", { placeholder: "name", style: "flex:1 1 160px" });
        const fromIn = el("input", { placeholder: "known from — e.g. Twitter, course cohort", style: "flex:1 1 220px" });
        const dateIn = el("input", { type: "date", value: today(), title: "when you first contacted them" });
        const add = () => guard(async () => {
          if (!nameIn.value.trim()) return toast("a contact needs a name", true);
          await V().createContact({ name: nameIn.value.trim(), known_from: fromIn.value.trim(), first_contact: dateIn.value || "" });
          toast("added"); reload();
        });
        [nameIn, fromIn].forEach((n) => n.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); }));
        const search = el("input", { type: "search", placeholder: "search", value: query, style: "flex:0 1 220px;margin-left:auto" });
        bar.appendChild(el("div.row", { style: "margin-bottom:14px;gap:8px;flex-wrap:wrap" }, [
          nameIn, fromIn,
          el("label.row", { style: "gap:6px" }, [el("span.sub", { text: "first contacted" }), dateIn]),
          el("button.btn-primary", { onclick: add, text: "+ contact" }),
          search,
        ]));

        const items = await guard(() => V().network());
        const holder = el("div"); host.appendChild(holder);
        const paint = () => { clear(holder); holder.appendChild(table(items, reload)); };
        search.addEventListener("input", () => { query = search.value; paint(); });
        paint();
        scroller.scrollTop = 0;
      }
      reload();
    },
  };
})();

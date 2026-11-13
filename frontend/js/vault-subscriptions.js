/* vault-subscriptions.js — Vault → Subscriptions (2026-11-10, from
   the subscriptions mockup).

   What you pay for, where it comes out of, what you get, and when it renews.

   Not a second list: a subscription IS a :Recurring. This tab reads and writes
   /api/vault/recurring with a few extra fields (what, gets, area, status,
   start, cancel_by, worth, paid_from), so anything added here is also in the
   Transactions → Recurring strip, gets its reminder, and "mark paid" mints a
   real transaction exactly as it does there.

   Area is guessed from the name/what/gets by keyword (longest match wins)
   until you pick one yourself; `area_manual` remembers which it was. */
(function () {
  const { el, clear, toast, guard } = window.ui;
  const api = window.api;

  const AREAS = {
    synapse: { label: "SYNAPSE", sub: "learning and tools", color: "#00D4AA" },
    pulse: { label: "PULSE", sub: "health and fitness", color: "#DE7BA4" },
    vision: { label: "VISION", sub: "content and creative", color: "#FF4757" },
    vault: { label: "VAULT", sub: "bills and essentials", color: "#D4A017" },
    fun: { label: "FUN", sub: "entertainment", color: "#8B7EC8" },
    other: { label: "OTHER", sub: "not sorted", color: "#7B8BA3" },
  };
  // keyword → area. Longest matching keyword wins.
  const RULES = {
    synapse: ["chatgpt", "openai", "claude", "anthropic", "copilot", "github", "cursor", "coursera", "udemy", "edx", "brilliant", "datacamp", "leetcode", "neetcode", "tensortonic", "kindle unlimited", "kindle", "audible", "o'reilly", "oreilly", "blinkist", "duolingo", "skillshare", "masterclass", "notion", "obsidian", "readwise", "zotero", "overleaf", "grammarly", "perplexity", "gemini", "huggingface", "hugging face", "colab", "paperspace", "runpod", "lambda", "aws", "gcp", "azure", "digitalocean", "vercel", "domain", "hosting", "jetbrains", "pluralsight", "frontend masters", "scrimba", "course", "book", "journal", "ieee", "acm", "learning", "study", "tutor"],
    pulse: ["gym", "puregym", "the gym group", "david lloyd", "nuffield", "fitness", "strava", "myfitnesspal", "cronometer", "whoop", "oura", "garmin", "fitbod", "hevy", "strong app", "peloton", "zwift", "headspace", "calm", "sleep", "physio", "protein", "supplement", "yoga", "climbing", "boxing", "swim", "dentist", "health", "bupa", "vitality", "meal", "gousto", "hellofresh", "mindful"],
    vision: ["youtube premium", "adobe", "premiere", "photoshop", "lightroom", "after effects", "canva", "capcut", "davinci", "final cut", "epidemic sound", "artlist", "envato", "storyblocks", "motion array", "descript", "riverside", "streamyard", "tubebuddy", "vidiq", "patreon", "substack", "figma", "frame.io", "elevenlabs", "midjourney", "runway", "camera", "mic", "studio", "creator", "podcast", "video", "music production", "splice"],
    vault: ["insurance", "phone", "mobile", "sim", "ee", "o2", "vodafone", "three", "giffgaff", "broadband", "virgin media", "bt ", "sky broadband", "plusnet", "energy", "octopus", "british gas", "edf", "water", "council tax", "tv licence", "rent", "mortgage", "icloud", "google one", "dropbox", "onedrive", "microsoft 365", "1password", "bitwarden", "lastpass", "nordvpn", "proton", "vpn", "bank", "monzo", "revolut", "amex", "credit", "railcard", "oyster", "travel", "car", "aa ", "rac", "mot", "breakdown", "amazon prime", "prime", "costco", "backup", "storage"],
    fun: ["netflix", "disney", "prime video", "now tv", "now ", "apple tv", "paramount", "crunchyroll", "spotify", "apple music", "tidal", "deezer", "xbox", "game pass", "playstation", "ps plus", "nintendo", "steam", "twitch", "discord nitro", "dazn", "tnt sports", "sky sports", "sky ", "cinema", "odeon", "cineworld", "vue", "game", "gaming", "anime", "manga", "comic", "magazine", "newspaper", "times", "guardian", "economist"],
  };
  const FREQ = {
    monthly: { m: 1, label: "/mo", name: "monthly" },
    yearly: { m: 1 / 12, label: "/yr", name: "yearly" },
    quarterly: { m: 1 / 3, label: "/qtr", name: "every 3 months" },
    weekly: { m: 52 / 12, label: "/wk", name: "weekly" },
    fortnightly: { m: 26 / 12, label: "/2wk", name: "every 2 weeks" },
    "4weekly": { m: 13 / 12, label: "/4wk", name: "every 4 weeks" },
    once: { m: 0, label: " once", name: "one-off / fixed term" },
  };
  const STATUS_TAG = { active: "green", trial: "amber", paused: "grey", cancelled: "grey", ended: "grey" };

  function guessArea(text) {
    const t = " " + (text || "").toLowerCase() + " ";
    let best = null;
    for (const [area, words] of Object.entries(RULES))
      for (const w of words)
        if (t.includes(w) && (!best || w.length > best.w.length)) best = { area, w: w.trim() };
    return best;
  }

  const gbp = (n) => "£" + (Math.round((n || 0) * 100) / 100)
    .toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const fmtDate = (d) => d ? new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";
  const shortDate = (d) => new Date(d + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const iso = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const daysTo = (d) => Math.round((new Date(d + "T00:00:00") - today()) / 864e5);

  // `active` is the truth (a paid one-off goes inactive); status is the label.
  const live = (s) => s.active !== false;
  const statusOf = (s) => {
    const st = s.status || (live(s) ? "active" : "paused");
    if (!live(s) && (st === "active" || st === "trial")) return "ended";
    return st;
  };
  const monthly = (s) => live(s) ? (+s.amount || 0) * (FREQ[s.cadence]?.m ?? 1) : 0;
  const areaOf = (s) => AREAS[s.area] ? s.area : "other";

  let subs = [], accounts = [];
  let filterStatus = "live", query = "", sortBy = "renew";
  let root = null;

  const fromOf = (s) => s.paid_from
    || (accounts.find((a) => a.id === s.account_id) || {}).name || "";

  /* ---------------------------------------------------------------- render */
  function tile(k, v, s, gold) {
    return el("div.vsub-tile" + (gold ? ".gold" : ""), {}, [
      el("div.k", { text: k }), el("div.v", { text: String(v) }), el("div.s", { text: s || "" })]);
  }

  function render() {
    const host = root.querySelector(".vsub-body");
    clear(host);
    const all = subs;
    const act = all.filter(live);
    const mo = act.reduce((a, s) => a + monthly(s), 0);
    const soon = act.filter((s) => s.next_due && daysTo(s.next_due) >= 0)
      .sort((a, b) => a.next_due.localeCompare(b.next_due));
    const trials = all.filter((s) => live(s) && s.status === "trial");
    const flagged = act.filter((s) => s.worth === "no" || s.worth === "unsure");
    const flaggedMo = flagged.reduce((a, s) => a + monthly(s), 0);
    const overdue = act.filter((s) => s.overdue);
    const nx = soon[0];

    host.appendChild(el("div.vsub-tiles", {}, [
      tile("per month", gbp(mo), act.length + " active", true),
      tile("per year", gbp(mo * 12), "at today's prices"),
      tile("next renewal", nx ? nx.name : "none",
        nx ? (daysTo(nx.next_due) === 0 ? "today" : "in " + daysTo(nx.next_due) + " days") + " · " + gbp(+nx.amount) : ""),
      tile("trials running", trials.length,
        trials.length ? "ends " + trials.map((s) => shortDate(s.cancel_by || s.next_due || iso(today()))).join(", ") : "none"),
      tile("could save", gbp(flaggedMo * 12) + "/yr", flagged.length + " marked unsure or no"),
    ]));

    if (overdue.length) {
      host.appendChild(el("div.vsub-overdue", {}, [
        el("span", { text: overdue.length + " past the renewal date and not marked paid: " }),
        el("span", { text: overdue.map((s) => s.name).join(", ") }),
        el("span.vsub-dim", { text: " — open one and press “mark paid” to log it and roll the date on." }),
      ]));
    }

    // area bar
    const byArea = {};
    act.forEach((s) => { byArea[areaOf(s)] = (byArea[areaOf(s)] || 0) + monthly(s); });
    const bar = el("div.vsub-bar"), leg = el("div.vsub-legend");
    Object.keys(AREAS).forEach((a) => {
      if (!byArea[a]) return;
      bar.appendChild(el("span", { style: `background:${AREAS[a].color};width:${byArea[a] / mo * 100}%`,
        title: AREAS[a].label + " " + gbp(byArea[a]) }));
      leg.appendChild(el("span", {}, [el("i.vsub-dot", { style: "background:" + AREAS[a].color }),
        AREAS[a].label + " ", el("b", { text: gbp(byArea[a]) })]));
    });
    host.appendChild(el("div.vsub-panel", {}, [
      el("div.vsub-ph", {}, [el("span", { text: "monthly spend by area" }), el("span", { text: gbp(mo) + " / month" })]),
      bar, leg]));

    // list
    let rows = all.filter((s) => filterStatus === "all" ? true
      : filterStatus === "live" ? live(s) : statusOf(s) === filterStatus);
    if (query) rows = rows.filter((s) => [s.name, s.what, s.gets, fromOf(s), s.notes].join(" ").toLowerCase().includes(query));
    rows.sort((a, b) => sortBy === "cost" ? monthly(b) - monthly(a)
      : sortBy === "name" ? (a.name || "").localeCompare(b.name || "")
      : (a.next_due || "9").localeCompare(b.next_due || "9"));

    const list = el("div");
    if (!all.length) list.appendChild(el("div.vsub-empty", { text: "Nothing here yet. Add your first subscription and it'll be sorted into an area from its name and what it is. You can change the area if it guesses wrong." }));
    else if (!rows.length) list.appendChild(el("div.vsub-empty", { text: "No matches." }));
    Object.keys(AREAS).forEach((a) => {
      const g = rows.filter((s) => areaOf(s) === a);
      if (!g.length) return;
      const gm = g.reduce((x, s) => x + monthly(s), 0);
      list.appendChild(el("div.vsub-group", {}, [
        el("div.vsub-gh", {}, [
          el("b", { style: "color:" + AREAS[a].color }, [AREAS[a].label + " ", el("span", { text: "· " + AREAS[a].sub })]),
          el("span", { text: gbp(gm) + "/mo · " + gbp(gm * 12) + "/yr" })]),
        ...g.map(card)]));
    });

    const chips = el("div.vsub-chips", {}, [["live", "active + trial"], ["all", "all"], ["trial", "trials"], ["cancelled", "cancelled"]]
      .map(([k, l]) => el("button.vsub-chip" + (filterStatus === k ? ".on" : ""), { text: l,
        onclick: () => { filterStatus = k; render(); } })));
    const q = el("input", { placeholder: "search name, what, paid from…", value: query });
    q.addEventListener("input", () => { query = q.value.trim().toLowerCase(); render();
      const nq = root.querySelector(".vsub-toolbar input"); nq.focus(); nq.setSelectionRange(nq.value.length, nq.value.length); });
    const sort = el("select", {}, [["renew", "sort: next renewal"], ["cost", "sort: monthly cost"], ["name", "sort: name"]]
      .map(([v, t]) => el("option", { value: v, text: t })));
    sort.value = sortBy;
    sort.addEventListener("change", () => { sortBy = sort.value; render(); });

    // timeline — next 60 days
    const events = [];
    act.forEach((s) => {
      if (s.next_due && daysTo(s.next_due) <= 60 && daysTo(s.next_due) >= 0)
        events.push({ d: s.next_due, s, kind: s.cadence === "once" ? "ends" : "renews" });
      if (s.cancel_by && daysTo(s.cancel_by) <= 60 && daysTo(s.cancel_by) >= 0)
        events.push({ d: s.cancel_by, s, kind: "cancel by" });
    });
    events.sort((a, b) => a.d.localeCompare(b.d));
    const tl = el("ul.vsub-tl");
    if (!events.length) tl.appendChild(el("li.static", {}, [el("span"), el("span.vsub-dim", { text: "nothing due" }), el("span")]));
    events.forEach((e) => {
      const n = daysTo(e.d);
      tl.appendChild(el("li", { onclick: () => openDlg(e.s) }, [
        el("span.d", { text: shortDate(e.d) }),
        el("span", {}, [el("i.vsub-dot", { style: "background:" + AREAS[areaOf(e.s)].color }), e.s.name + " ",
          el("span.vsub-tag." + (e.kind === "cancel by" ? "red" : n <= 7 ? "amber" : "grey"), { text: e.kind })]),
        el("span.p", { text: e.kind === "cancel by" ? "" : gbp(+e.s.amount) })]));
    });

    // by account
    const acc = {};
    act.forEach((s) => { const k = fromOf(s).trim() || "not set"; acc[k] = (acc[k] || 0) + monthly(s); });
    const al = el("ul.vsub-tl");
    Object.entries(acc).sort((a, b) => b[1] - a[1]).forEach(([k, v]) =>
      al.appendChild(el("li.static", {}, [el("span.d", { text: gbp(v) }), el("span", { text: k }), el("span.d", { text: "/mo" })])));
    if (!Object.keys(acc).length) al.appendChild(el("li.static", {}, [el("span"), el("span.vsub-dim", { text: "—" }), el("span")]));

    host.appendChild(el("div.vsub-cols", {}, [
      el("div.vsub-panel", {}, [el("div.vsub-toolbar", {}, [q, sort, chips]), list]),
      el("div", {}, [
        el("div.vsub-panel", {}, [el("div.vsub-ph", {}, [el("span", { text: "next 60 days" })]), tl]),
        el("div.vsub-panel", {}, [el("div.vsub-ph", {}, [el("span", { text: "by account" })]), al]),
      ]),
    ]));
  }

  function card(s) {
    const st = statusOf(s);
    const meta = el("div.meta", {}, [el("span.vsub-tag." + STATUS_TAG[st], { text: st })]);
    if (s.next_due && live(s)) {
      const n = daysTo(s.next_due);
      meta.appendChild(el("span.vsub-tag." + (n < 0 || n <= 7 ? "red" : n <= 30 ? "amber" : "grey"), {
        text: n < 0 ? "overdue since " + shortDate(s.next_due)
          : (s.cadence === "once" ? "ends " : "renews ") + fmtDate(s.next_due) + (n <= 30 ? " (" + (n === 0 ? "today" : n + "d") + ")" : "") }));
    }
    if (s.cancel_by && live(s)) meta.appendChild(el("span.vsub-tag.red", { text: "cancel by " + shortDate(s.cancel_by) }));
    if (fromOf(s)) meta.appendChild(el("span", { text: "from " + fromOf(s) }));
    if (s.worth) meta.appendChild(el("span", {
      text: s.worth === "yes" ? "✓ worth it" : s.worth === "no" ? "✗ cancel" : "? unsure",
      style: "color:" + (s.worth === "yes" ? "var(--green)" : s.worth === "no" ? "var(--red)" : "var(--amber)") }));
    return el("div.vsub-card" + (live(s) ? "" : ".off"), {
      style: "border-left-color:" + AREAS[areaOf(s)].color, onclick: () => openDlg(s) }, [
      el("div", {}, [
        el("div.n", { text: s.name }),
        s.what ? el("div.w", { text: s.what }) : null,
        s.gets ? el("div.g", { text: "→ " + s.gets }) : null]),
      el("div.price", {}, [
        el("b", { text: gbp(+s.amount) }), el("span.vsub-dim", { text: FREQ[s.cadence]?.label || "" }),
        el("div", { text: s.cadence !== "monthly" && s.cadence !== "once" ? gbp(monthly(s)) + "/mo" : "" })]),
      meta]);
  }

  /* ---------------------------------------------------------------- dialog */
  function openDlg(s) {
    const editing = !!s;
    s = s || {};
    let areaTouched = !!s.area_manual;
    const f = {};
    const inp = (name, attrs) => (f[name] = el("input", { name, ...attrs }));
    const sel = (name, opts) => (f[name] = el("select", { name }, opts.map(([v, t]) => el("option", { value: v, text: t }))));
    inp("name", { required: true, placeholder: "e.g. Spotify" });
    inp("what", { placeholder: "e.g. music streaming" });
    f.gets = el("textarea", { name: "gets", rows: 2, placeholder: "e.g. ad-free music, offline downloads, Duo plan" });
    inp("amount", { type: "number", step: "0.01", min: "0", required: true, placeholder: "10.99" });
    sel("cadence", ["monthly", "yearly", "quarterly", "weekly", "fortnightly", "4weekly", "once"].map((k) => [k, FREQ[k].name]));
    inp("paid_from", { list: "vsub-from", placeholder: "e.g. Monzo, Amex, PayPal" });
    sel("status", [["active", "active"], ["trial", "free trial"], ["paused", "paused"], ["cancelled", "cancelled"]]);
    inp("start", { type: "date" });
    inp("next_due", { type: "date" });
    inp("cancel_by", { type: "date" });
    sel("worth", [["", "not rated"], ["yes", "yes, keep"], ["unsure", "unsure"], ["no", "no, cancel"]]);
    inp("notes", { placeholder: "login email, student discount ends, shared with…" });
    const areaSel = el("select", {}, [el("option", { value: "auto", text: "auto" })]
      .concat(Object.entries(AREAS).map(([k, a]) => el("option", { value: k, text: a.label + " · " + a.sub }))));
    const autoNote = el("span.vsub-auto");
    const fromNames = [...new Set(accounts.map((a) => a.name).concat(subs.map((x) => x.paid_from)).filter(Boolean))];
    const dl = el("datalist", { id: "vsub-from" }, fromNames.map((n) => el("option", { value: n })));

    function updateAuto() {
      if (areaTouched && areaSel.value !== "auto") return;
      const g = guessArea(f.name.value + " " + f.what.value + " " + f.gets.value);
      autoNote.textContent = g ? 'auto: "' + g.w + '"' : "auto: no match";
      areaSel.value = "auto";
      areaSel.dataset.guess = g ? g.area : "other";
      areaSel.options[0].textContent = "auto → " + AREAS[g ? g.area : "other"].label;
    }
    ["name", "what", "gets"].forEach((k) => f[k].addEventListener("input", updateAuto));
    areaSel.addEventListener("change", () => {
      areaTouched = areaSel.value !== "auto";
      autoNote.textContent = areaTouched ? "set by you" : "";
      if (!areaTouched) updateAuto();
    });

    if (editing) {
      for (const k of Object.keys(f)) f[k].value = s[k] ?? "";
      f.paid_from.value = fromOf(s);
      f.status.value = ["active", "trial", "paused", "cancelled"].includes(s.status) ? s.status : (live(s) ? "active" : "paused");
      if (s.area_manual && AREAS[s.area]) { areaSel.value = s.area; autoNote.textContent = "set by you"; }
      else updateAuto();
    } else { f.start.value = iso(today()); updateAuto(); }

    const field = (label, node, opts = {}) => el("div" + (opts.full ? ".full" : ""), {}, [
      el("label", { text: label }), node, opts.hint ? el("div.vsub-hint", { text: opts.hint }) : null]);
    const form = el("form.vsub-form", { autocomplete: "off" }, [
      field("Name", f.name),
      field("Area", el("div.vsub-arearow", {}, [areaSel, autoNote])),
      field("What it is", f.what, { full: true }),
      field("What I get", f.gets, { full: true }),
      field("Cost (£)", f.amount),
      field("How often", f.cadence),
      field("Paid from", el("div", {}, [f.paid_from, dl])),
      field("Status", f.status),
      field("Started", f.start),
      field("Next renewal / expires", f.next_due, { hint: "left blank, worked out from start date" }),
      field("Cancel by (optional)", f.cancel_by, { hint: "e.g. trial end, notice period" }),
      field("Worth it?", f.worth),
      field("Notes", f.notes, { full: true }),
    ]);

    const mask = el("div.vsub-mask");
    const close = () => { mask.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", onKey);
    mask.addEventListener("click", (e) => { if (e.target === mask) close(); });

    const saveBtn = el("button.btn-primary", { type: "button", text: "save" });
    saveBtn.addEventListener("click", async () => {
      if (!form.reportValidity()) return;
      const body = {};
      for (const k of ["name", "what", "gets", "cadence", "status", "start", "next_due", "cancel_by", "worth", "notes"])
        body[k] = f[k].value.trim();
      body.amount = Math.round(parseFloat(f.amount.value) * 100) / 100;
      body.area_manual = areaSel.value !== "auto";
      body.area = body.area_manual ? areaSel.value : (areaSel.dataset.guess || "other");
      // "Paid from" naming a Vault account links it, so "mark paid" lands the
      // transaction in that account; anything else (PayPal…) stays as text.
      const from = f.paid_from.value.trim();
      const acct = accounts.find((a) => (a.name || "").toLowerCase() === from.toLowerCase());
      body.account_id = acct ? acct.id : null;
      body.paid_from = acct ? "" : from;
      if (!editing) body.category = "Subscriptions";
      saveBtn.disabled = true;
      try {
        await guard(() => editing ? api.recurring.update(s.id, body) : api.recurring.create(body));
        close(); await reload();
      } catch { /* toasted */ } finally { saveBtn.disabled = false; }
    });

    let armed = false;
    const delBtn = el("button.vsub-danger", { type: "button", text: "delete" });
    delBtn.addEventListener("click", async () => {
      if (!armed) { armed = true; delBtn.textContent = "delete — sure?"; setTimeout(() => { armed = false; delBtn.textContent = "delete"; }, 3000); return; }
      await guard(() => api.recurring.del(s.id)); close(); await reload();
    });
    const paidBtn = el("button.btn-sm", { type: "button", text: "mark paid",
      title: "log a transaction for the due date and roll the renewal on" });
    paidBtn.addEventListener("click", async () => {
      const r = await guard(() => api.recurring.pay(s.id));
      toast("logged " + gbp(+s.amount) + " · next " + (r.recurring.next_due || "—"));
      close(); await reload();
    });

    mask.appendChild(el("div.vsub-dlg", { role: "dialog", "aria-modal": "true" }, [
      el("h2", { text: editing ? "Edit subscription" : "Add subscription" }),
      form,
      el("div.vsub-foot", {}, [
        editing ? delBtn : el("span"),
        el("div", { style: "display:flex;gap:8px;margin-left:auto" }, [
          editing && live(s) && s.next_due ? paidBtn : null,
          el("button.btn-sm", { type: "button", text: "cancel", onclick: close }),
          saveBtn])]),
    ]));
    document.body.appendChild(mask);
    setTimeout(() => f.name.focus(), 30);
  }

  async function copyCSV() {
    const cols = ["name", "area", "what", "gets", "amount", "cadence", "paid_from", "status", "start", "next_due", "cancel_by", "worth", "notes"];
    const csv = [cols.join(",")].concat(subs.map((s) => cols.map((c) => {
      const v = c === "paid_from" ? fromOf(s) : c === "status" ? statusOf(s) : s[c];
      return '"' + String(v ?? "").replace(/"/g, '""') + '"';
    }).join(","))).join("\n");
    try { await navigator.clipboard.writeText(csv); toast("copied CSV to clipboard"); }
    catch { toast("couldn't copy here", true); }
  }

  async function reload() {
    [subs, accounts] = await Promise.all([
      guard(() => api.recurring.list()),
      guard(() => api.vault.accounts()).catch(() => []),
    ]);
    if (root && root.isConnected) render();
  }

  window.Views = window.Views || {};
  window.Views.subscriptions = {
    id: "subscriptions", label: "Subscriptions", scoped: false,
    async render(view) {
      clear(view);
      root = el("div.vsub");
      root.appendChild(el("div.view-head", {}, [
        el("div", {}, [
          el("h1", { text: "Subscriptions" }),
          el("div.sub", { text: "what you pay for, where it comes out of, what you get, and when it renews" })]),
        el("div.row", { style: "gap:8px" }, [
          el("button.btn-sm", { text: "copy CSV", title: "copy all as CSV", onclick: copyCSV }),
          el("button.btn-primary", { text: "+ add subscription", onclick: () => openDlg(null) })]),
      ]));
      root.appendChild(el("div.vsub-body", {}, [el("div.vsub-empty", { text: "loading…" })]));
      view.appendChild(root);
      await reload();
    },
  };
})();

/* vault-inventory.js — Vault · Inventory (VAULT_SPEC §7).

   Three ways of looking at the same set of things, chosen with the sub-tab bar
   (the choice sticks in localStorage, like the Transactions tabs):

     HAVE      — what you own, grouped by category, plus retired kit at the end
     NEED      — the two buy lists. Still two lists: "need" and "want" are
                 deliberately NOT merged (spec), the tab just puts them
                 together because they answer the same question.
     LOCATIONS — the same owned things, grouped by where they are instead of
                 what they are. Answers "what's in the loft?", which category
                 grouping can't.

   Prices on the buy lists are a RANGE, not a figure: `value` is the low end and
   `value_max` the optional high end (0 = single figure). Totals for those
   sections therefore read "£120 – £180", because pretending you know the exact
   cost of something you haven't bought is the thing that makes a wishlist total
   useless.

   Age works the same way — see ageOf() below. You record what you actually
   remember ("2019", "2019-06", or a full date) and the display admits how much
   it is guessing. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  const CATS = [
    { key: "tech", icon: "🖥" }, { key: "books", icon: "📚" }, { key: "gaming", icon: "🎮" },
    { key: "tools", icon: "🛠" }, { key: "clothing", icon: "👕" },
    { key: "furniture", icon: "🪑" }, { key: "other", icon: "📌" },
  ];
  const icon = (k) => (CATS.find((c) => c.key === k) || CATS[6]).icon;

  const STATUS = {
    active: "var(--green)", "in-use": "var(--teal)", owned: "var(--dim)",
    stored: "var(--dim)", need: "var(--red)", want: "var(--purple)",
    broken: "var(--red)", sold: "var(--muted)",
  };
  const ALL_STATUS = Object.keys(STATUS);
  const HAVE = ["active", "in-use", "owned", "stored"];
  const WISHLIST = ["need", "want"];

  const TABS = [
    { key: "have", label: "What I have" },
    { key: "need", label: "What I need" },
    { key: "loc", label: "By location" },
  ];
  let sub = (() => {
    try { return localStorage.getItem("vault.inv.sub") || "have"; } catch { return "have"; }
  })();

  /* ---- age -------------------------------------------------------------
     `acquired` is stored at whatever precision the user actually remembers:
     "2019", "2019-06" or "2019-06-15". To turn that into one number we take
     the MIDPOINT of what the string could mean — a bare year means some time
     in that year, so 1 July is the least wrong single day to measure from —
     and mark the result approximate so "~7y" never reads as a hard fact. */
  function ageOf(acq) {
    const m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$/.exec((acq || "").trim());
    if (!m) return null;
    const y = +m[1], mo = m[2] ? +m[2] : 0, d = m[3] ? +m[3] : 0;
    const prec = d ? "d" : mo ? "m" : "y";
    const from = d ? new Date(y, mo - 1, d)
      : mo ? new Date(y, mo - 1, 15)     // mid-month
        : new Date(y, 6, 1);             // mid-year
    const now = new Date();
    /* Months are counted off the calendar, not by dividing days by 30.44 —
       that rounding is what turns a thing bought exactly a year ago into
       "11m". The part-month borrow only applies to a real date; on an invented
       midpoint it would be arithmetic on a fact we do not have. */
    let months = (now.getFullYear() - y) * 12 + (now.getMonth() - (mo ? mo - 1 : 6));
    if (prec === "d" && now.getDate() < d) months -= 1;
    return {
      days: Math.max(Math.floor((now - from) / 86400000), 0),
      months: Math.max(months, 0), prec,
    };
  }

  /* Precision follows both magnitude and confidence: days for the first month,
     months for the first year, years-and-months up to five, then years alone —
     nobody needs "8y 3m" about a wardrobe. A bare year on record never gets a
     months component, so "3y" typed in reads back as "~3y" and not "~3y 1m". */
  function ageText(a) {
    if (!a) return "";
    const t = a.prec === "d" ? "" : "~";
    if (a.prec === "d" && a.days < 31) return a.days <= 1 ? "new" : a.days + "d";
    if (a.months < 1) return t + "new";
    if (a.prec === "y") {
      const years = Math.round(a.months / 12);
      if (years) return t + years + "y";
      return t + a.months + "m";       // a year stamp can still be recent
    }
    if (a.months < 12) return t + a.months + "m";
    const years = Math.floor(a.months / 12), rem = a.months % 12;
    return years < 5 && rem ? t + years + "y " + rem + "m" : t + years + "y";
  }

  /* Old things earn a warmer colour, so a list of ages skims as a heat map
     rather than as a column of identical grey chips. */
  function ageColor(a) {
    const y = a.days / 365.25;
    return y >= 8 ? "var(--red)" : y >= 4 ? "var(--amber)" : y >= 1 ? "var(--dim)" : "var(--teal)";
  }

  /* What the age box accepts. A date is kept verbatim; "3y" and "6m" are
     shorthand for "about that old" and resolve to the COARSEST date that means
     it — "3y" typed in 2026 becomes "2023", never a fabricated exact day. */
  function parseAge(input) {
    const s = (input || "").trim().toLowerCase();
    if (!s) return "";
    if (/^\d{4}(-\d{2}(-\d{2})?)?$/.test(s)) return s;
    const pad = (n) => String(n).padStart(2, "0");
    if (s === "new" || s === "today") {
      const n = new Date();
      return n.getFullYear() + "-" + pad(n.getMonth() + 1) + "-" + pad(n.getDate());
    }
    const rel = /^(\d+(?:\.\d+)?)\s*(d|w|m|y)$/.exec(s);
    if (!rel) return null;              // unparseable — complain, don't store junk
    const n = parseFloat(rel[1]), unit = rel[2];
    if (unit === "y") return String(new Date().getFullYear() - Math.round(n));
    const days = unit === "d" ? n : unit === "w" ? n * 7 : n * 30.44;
    const then = new Date(Date.now() - days * 86400000);
    const ym = then.getFullYear() + "-" + pad(then.getMonth() + 1);
    return unit === "d" ? ym + "-" + pad(then.getDate()) : ym;
  }

  /* A list where some items are ranges and some are exact still has a range as
     its total: the exact ones just contribute the same number to both ends. */
  function totalRange(items) {
    return items.reduce((t, i) => {
      const lo = Number(i.value || 0);
      return { lo: t.lo + lo, hi: t.hi + Math.max(lo, Number(i.value_max || 0)) };
    }, { lo: 0, hi: 0 });
  }

  const rangeText = (t) => (t.hi > t.lo ? V.money(t.lo) + " – " + V.money(t.hi) : V.money(t.lo));

  /* The oldest thing in a group is the interesting one, so groups advertise it
     in their header. Items with no date recorded simply don't compete. */
  function oldest(items) {
    return items.reduce((best, i) => {
      const a = ageOf(i.acquired);
      return a && (!best || a.days > best.a.days) ? { a, i } : best;
    }, null);
  }

  function itemRow(it, reload) {
    const statusSel = el("select.cellinput", { style: "color:" + (STATUS[it.status] || "var(--dim)") },
      ALL_STATUS.map((s) => el("option", { value: s, text: s })));
    statusSel.value = it.status;
    statusSel.addEventListener("change", () => guard(async () => {
      await api.vault.updateItem(it.id, { status: statusSel.value }); toast("status changed"); reload();
    }));
    const nameIn = el("input", { value: it.name, style: "flex:1;min-width:120px;background:transparent;border:none;padding:0" });
    nameIn.addEventListener("blur", () => guard(async () => {
      const nv = nameIn.value.trim();
      if (!nv || nv === it.name) { nameIn.value = it.name; return; }
      await api.vault.updateItem(it.id, { name: nv }); it.name = nv; toast("saved");
    }));
    const locIn = el("input", { value: it.location || "", placeholder: "where?", style: "width:130px" });
    locIn.addEventListener("blur", () => guard(async () => {
      if ((locIn.value || "") === (it.location || "")) return;
      await api.vault.updateItem(it.id, { location: locIn.value }); it.location = locIn.value;
      toast("saved");
      if (sub === "loc") reload();     // it just moved shelf — regroup
    }));

    /* The chip is the answer ("~7y"); the box is the evidence ("2019"). Both
       are shown because the chip is what you read and the date is what you
       correct. */
    const chip = el("span.vlt-age");
    const ageIn = el("input", { value: it.acquired || "", placeholder: "age?",
      title: "when you got it — 2019, 2019-06, 2019-06-15, or shorthand like 3y / 6m / new",
      style: "width:88px" });
    const paintAge = () => {
      const a = ageOf(it.acquired);
      chip.textContent = a ? ageText(a) : "";
      chip.style.display = a ? "" : "none";
      if (a) { chip.style.color = ageColor(a); chip.style.borderColor = ageColor(a);
               chip.title = "acquired " + it.acquired; }
    };
    paintAge();
    ageIn.addEventListener("blur", () => guard(async () => {
      if ((ageIn.value || "").trim() === (it.acquired || "")) return;
      const parsed = parseAge(ageIn.value);
      if (parsed === null) { ageIn.value = it.acquired || ""; return toast("try 2019, 2019-06 or 3y", true); }
      const saved = await api.vault.updateItem(it.id, { acquired: parsed });
      it.acquired = saved.acquired || "";
      ageIn.value = it.acquired; paintAge(); toast("saved");
    }));

    /* An owned thing has one value; a thing you haven't bought has a guess,
       and a guess is honest only as a range. So the second box appears on the
       buy lists — or on anything that already carries a range. */
    const ranged = WISHLIST.includes(it.status) || Number(it.value_max || 0) > 0;
    const valIn = el("input", { type: "number", step: "0.01", value: String(it.value || 0),
      title: ranged ? "low estimate" : "value",
      style: "width:" + (ranged ? "76px" : "92px") + ";text-align:right" });
    const maxIn = ranged ? el("input", { type: "number", step: "0.01", placeholder: "to £",
      title: "high estimate — leave blank if you know the price",
      value: Number(it.value_max || 0) > 0 ? String(it.value_max) : "",
      style: "width:76px;text-align:right" }) : null;
    const saveRange = () => guard(async () => {
      const lo = parseFloat(valIn.value);
      const hi = maxIn ? parseFloat(maxIn.value) : NaN;
      const patch = {};
      if (!isNaN(lo) && lo !== Number(it.value)) patch.value = lo;
      if (maxIn) {
        const hiNum = isNaN(hi) ? 0 : hi;
        if (hiNum !== Number(it.value_max || 0)) patch.value_max = hiNum;
      }
      if (!Object.keys(patch).length) return;
      const saved = await api.vault.updateItem(it.id, patch);
      // The server may swap the ends if they were typed the wrong way round,
      // so redraw from what it actually stored rather than from what was typed.
      it.value = saved.value; it.value_max = saved.value_max;
      valIn.value = String(saved.value || 0);
      if (maxIn) maxIn.value = Number(saved.value_max || 0) > 0 ? String(saved.value_max) : "";
      toast("saved");
    });
    valIn.addEventListener("blur", saveRange);
    if (maxIn) maxIn.addEventListener("blur", saveRange);

    return el("div.vlt-item", {}, [
      el("div.row", { style: "gap:8px;min-width:0;flex:1" }, [
        el("span", { style: "font-size:14px", text: icon(it.category) }), nameIn, chip,
      ]),
      el("div.row", { style: "gap:6px;flex:0 0 auto" }, [
        ageIn, locIn, statusSel, valIn,
        maxIn ? el("span.sub", { style: "opacity:.5", text: "–" }) : null, maxIn,
        it.link ? el("a.btn-sm", { href: it.link, target: "_blank", rel: "noopener noreferrer",
          style: "text-decoration:none", text: "↗" }) : null,
        el("button.ord-btn", { title: "delete", text: "×",
          onclick: () => confirmDo("Delete “" + it.name + "”?", async () => {
            await api.vault.delItem(it.id); reload();
          }) }),
      ]),
    ]);
  }

  function header(title, items, extra) {
    const total = totalRange(items);
    return el("div.spread", { style: "margin-bottom:8px" }, [
      el("div.row", { style: "gap:8px" }, [
        el("span.sub", { text: title + " · " + items.length }), extra || null,
      ]),
      total.hi ? el("span.vlt-figure", { text: rangeText(total) }) : null,
    ]);
  }

  function section(title, items, cls, reload, note) {
    const box = el("div.vault-card" + (cls ? "." + cls : ""));
    box.appendChild(header(title, items));
    if (note) box.appendChild(el("div.sub", { style: "margin-bottom:8px;font-style:italic", text: note }));
    if (!items.length) {
      box.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing here." }));
      return box;
    }
    items.forEach((it) => box.appendChild(itemRow(it, reload)));
    return box;
  }

  /* ---- the three views -------------------------------------------------- */

  function viewHave(items, host, reload) {
    const have = items.filter((i) => HAVE.includes(i.status));
    const rest = items.filter((i) => ["broken", "sold"].includes(i.status));
    const box = el("div.vault-card");
    const old = oldest(have);
    box.appendChild(header("WHAT YOU HAVE", have,
      old ? el("span.sub", { style: "opacity:.7",
        text: "oldest: " + old.i.name + " (" + ageText(old.a) + ")" }) : null));
    if (!have.length) box.appendChild(el("div.sub", { style: "font-style:italic", text: "Nothing here." }));
    CATS.forEach((c) => {
      const inCat = have.filter((i) => i.category === c.key);
      if (!inCat.length) return;
      box.appendChild(el("div.sub", { style: "margin:10px 0 3px", text: c.icon + " " + c.key.toUpperCase() }));
      inCat.forEach((it) => box.appendChild(itemRow(it, reload)));
    });
    host.appendChild(box);
    if (rest.length) host.appendChild(section("BROKEN / SOLD", rest, "", reload));
  }

  function viewNeed(items, host, reload) {
    // Two lists, not one: an essential you're missing and a thing you fancy are
    // different decisions, and merging them is how a wishlist eats a budget.
    host.appendChild(section("NEED TO BUY", items.filter((i) => i.status === "need"),
      "vlt-need", reload, "essentials you're missing"));
    host.appendChild(section("WANT TO BUY", items.filter((i) => i.status === "want"),
      "vlt-want", reload, "the wishlist"));
  }

  function viewLoc(items, host, reload) {
    /* Only things that physically exist somewhere: a wishlist item isn't in the
       loft, and a sold one isn't anywhere. Broken things stay — they're still
       taking up the space, which is usually the point of asking. */
    const placed = items.filter((i) => HAVE.includes(i.status) || i.status === "broken");
    if (!placed.length) {
      host.appendChild(el("div.empty", { text: "Nothing owned yet — add items on “What I have”." }));
      return;
    }
    // Grouped case-insensitively so "Loft" and "loft" are one shelf, labelled
    // with whichever spelling was used first.
    const groups = new Map();
    placed.forEach((i) => {
      const raw = (i.location || "").trim();
      const key = raw.toLowerCase();
      if (!groups.has(key)) groups.set(key, { label: raw, items: [] });
      groups.get(key).items.push(i);
    });
    const unplaced = groups.get("");
    groups.delete("");
    const ordered = [...groups.values()].sort((a, b) => a.label.localeCompare(b.label));
    if (unplaced) ordered.push({ label: "", items: unplaced.items });

    host.appendChild(el("div.sub", { style: "margin-bottom:10px;font-style:italic",
      text: "Owned things by where they are. Edit the “where?” box to move one." }));
    ordered.forEach((g) => {
      const box = el("div.vault-card");
      const old = oldest(g.items);
      box.appendChild(header("📍 " + (g.label ? g.label.toUpperCase() : "NO LOCATION RECORDED"), g.items,
        old ? el("span.sub", { style: "opacity:.7", text: "oldest " + ageText(old.a) }) : null));
      g.items.forEach((it) => box.appendChild(itemRow(it, reload)));
      host.appendChild(box);
    });
  }

  window.Views = window.Views || {};
  window.Views.inventory = {
    id: "inventory", label: "Inventory", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Inventory" }),
        el("div.sub", { text: "What you own, how old it is, where it is, and what you still need or want to buy." }),
      ])]));

      const host = el("div");

      const bar = el("div.fit-subtabs.vlt-subtabs");
      TABS.forEach((t) => bar.appendChild(el("button.fit-subtab" + (t.key === sub ? ".active" : ""), {
        onclick: () => {
          if (sub === t.key) return;
          sub = t.key;
          try { localStorage.setItem("vault.inv.sub", sub); } catch { /* ignore */ }
          window.Views.inventory.render(view);
        },
        text: t.label,
      })));
      view.appendChild(bar);

      const nameIn = el("input", { placeholder: "item name", style: "flex:1;min-width:160px" });
      const catSel = el("select", {}, CATS.map((c) => el("option", { value: c.key, text: c.icon + " " + c.key })));
      const statusSel = el("select", {}, ALL_STATUS.map((s) => el("option", { value: s, text: s })));
      // The tab you're on is the list you're adding to, so it picks the default.
      statusSel.value = sub === "need" ? "need" : "owned";
      const ageIn = el("input", { placeholder: "age (3y / 2019)", style: "width:120px",
        title: "when you got it — 2019, 2019-06, 2019-06-15, or shorthand like 3y / 6m / new" });
      const locIn = el("input", { placeholder: "location", style: "width:140px" });
      const valIn = el("input", { type: "number", step: "0.01", placeholder: "£ from", style: "width:88px" });
      const maxIn = el("input", { type: "number", step: "0.01", placeholder: "£ to (opt)", style: "width:88px" });
      const add = () => guard(async () => {
        if (!nameIn.value.trim()) return toast("name the item", true);
        const acquired = parseAge(ageIn.value);
        if (acquired === null) return toast("age: try 2019, 2019-06 or 3y", true);
        await api.vault.createItem({ name: nameIn.value.trim(), category: catSel.value,
          status: statusSel.value, location: locIn.value.trim(), acquired,
          value: parseFloat(valIn.value) || 0, value_max: parseFloat(maxIn.value) || 0 });
        nameIn.value = locIn.value = valIn.value = maxIn.value = ageIn.value = "";
        toast("added"); reload();
      });
      [nameIn, ageIn, valIn, maxIn].forEach((box) =>
        box.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); }));
      view.appendChild(el("div.row", { style: "margin-bottom:16px" }, [
        nameIn, catSel, statusSel, ageIn, locIn, valIn, maxIn,
        el("button.btn-primary", { onclick: add, text: "+ item" }),
      ]));

      view.appendChild(host);

      async function reload() {
        const items = await guard(() => api.vault.inventory());
        clear(host);
        if (!items.length) {
          host.appendChild(el("div.empty", { text: "Nothing tracked yet." }));
          return;
        }
        if (sub === "need") viewNeed(items, host, reload);
        else if (sub === "loc") viewLoc(items, host, reload);
        else viewHave(items, host, reload);
      }
      reload();
    },
  };
})();

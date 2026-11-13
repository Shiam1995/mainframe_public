/* vault-investments.js — Vault · Investments (VAULT_SPEC §5).

   Portfolio positions. Values are SNAPSHOTS you update by hand — nothing here
   calls a broker API, by design. The schema allows extra fields so a future
   api_source / ticker / last_api_sync can be added without a migration. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  const TYPES = ["ETF", "Stock", "Crypto", "Bond", "Property", "Other"];
  const STRATEGIES = ["Monthly DCA", "Lump sum", "Opportunistic", "Hold"];

  function card(iv, reload) {
    const pl = Number(iv.current_value || 0) - Number(iv.amount_invested || 0);
    const plPct = iv.amount_invested ? (100 * pl / iv.amount_invested) : 0;
    const up = pl >= 0;

    const nameIn = el("input.vis-title", { style: "font-size:15px", value: iv.name });
    nameIn.addEventListener("blur", () => guard(async () => {
      const nv = nameIn.value.trim();
      if (!nv || nv === iv.name) { nameIn.value = iv.name; return; }
      await api.vault.updateInvestment(iv.id, { name: nv }); iv.name = nv; toast("renamed");
    }));
    const valIn = el("input.vlt-balance", { type: "number", step: "0.01",
      style: "color:var(--teal)", value: String(iv.current_value ?? 0) });
    valIn.addEventListener("blur", () => guard(async () => {
      const nv = parseFloat(valIn.value);
      if (isNaN(nv) || nv === Number(iv.current_value)) { valIn.value = String(iv.current_value ?? 0); return; }
      await api.vault.updateInvestment(iv.id, { current_value: nv }); toast("value updated"); reload();
    }));
    const invIn = el("input", { type: "number", step: "0.01", value: String(iv.amount_invested ?? 0) });
    invIn.addEventListener("blur", () => guard(async () => {
      const nv = parseFloat(invIn.value);
      if (isNaN(nv) || nv === Number(iv.amount_invested)) return;
      await api.vault.updateInvestment(iv.id, { amount_invested: nv }); reload();
    }));
    const sel = (opts, val, key) => {
      const s = el("select", {}, opts.map((o) => el("option", { value: o, text: o })));
      s.value = val;
      s.addEventListener("change", () => guard(async () => {
        await api.vault.updateInvestment(iv.id, { [key]: s.value }); reload();
      }));
      return s;
    };
    const platIn = el("input", { value: iv.platform || "", placeholder: "platform" });
    platIn.addEventListener("blur", () => guard(async () => {
      if ((platIn.value || "") === (iv.platform || "")) return;
      await api.vault.updateInvestment(iv.id, { platform: platIn.value }); iv.platform = platIn.value; toast("saved");
    }));
    const notes = window.RowBox({ label: "notes", noun: "note",
      placeholder: "thesis, targets, triggers", parentId: iv.id });

    return el("div.vlt-inv-card", {}, [
      el("div.spread", {}, [
        nameIn,
        el("button.ord-btn", { title: "delete position", text: "×",
          onclick: () => confirmDo("Delete “" + iv.name + "”?", async () => {
            await api.vault.delInvestment(iv.id); reload();
          }) }),
      ]),
      el("div.row", { style: "gap:5px;flex-wrap:wrap;margin-top:5px" }, [
        el("span.vw-tag", { text: iv.type }),
        iv.platform ? el("span.vw-tag", { style: "color:var(--blue)", text: iv.platform }) : null,
        el("span.vw-tag", { style: "color:var(--purple)", text: iv.strategy }),
      ]),
      el("div.vlt-bal-row", {}, [el("span.sub", { text: "£" }), valIn]),
      el("div.row", { style: "gap:6px;margin-top:3px" }, [
        el("span.vlt-pl", { style: "color:" + (up ? "var(--green)" : "var(--red)"),
          text: (up ? "↑ " : "↓ ") + V.money(pl) + "  (" + (up ? "+" : "") + plPct.toFixed(1) + "%)" }),
      ]),
      el("div.md-grid", { style: "margin-top:10px" }, [
        el("label.md-field", {}, [el("span.sub", { text: "invested" }), invIn]),
        el("label.md-field", {}, [el("span.sub", { text: "type" }), sel(TYPES, iv.type, "type")]),
        el("label.md-field", {}, [el("span.sub", { text: "platform" }), platIn]),
        el("label.md-field", {}, [el("span.sub", { text: "strategy" }), sel(STRATEGIES, iv.strategy, "strategy")]),
      ]),
      el("div", { style: "margin-top:8px" }, [notes.node]),
      el("div.sub", { style: "margin-top:6px", text: "valued " + (iv.updated_at || "").slice(0, 10) }),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.investments = {
    id: "investments", label: "Investments", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Investments" }),
        el("div.sub", { text: "Positions and what they're worth. Values are snapshots you update — nothing here talks to a broker." }),
      ])]));

      const nameIn = el("input", { placeholder: "e.g. Vanguard S&P 500 ETF", style: "flex:1;min-width:180px" });
      const typeSel = el("select", {}, TYPES.map((t) => el("option", { value: t, text: t })));
      const platIn = el("input", { placeholder: "platform", style: "width:140px" });
      const invIn = el("input", { type: "number", step: "0.01", placeholder: "invested £", style: "width:110px" });
      const valIn = el("input", { type: "number", step: "0.01", placeholder: "value £", style: "width:110px" });
      const add = () => guard(async () => {
        if (!nameIn.value.trim()) return toast("name the position", true);
        await api.vault.createInvestment({ name: nameIn.value.trim(), type: typeSel.value,
          platform: platIn.value.trim(), amount_invested: parseFloat(invIn.value) || 0,
          current_value: parseFloat(valIn.value) || 0 });
        nameIn.value = platIn.value = invIn.value = valIn.value = ""; toast("added"); reload();
      });
      nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      view.appendChild(el("div.row", { style: "margin-bottom:16px" }, [
        nameIn, typeSel, platIn, invIn, valIn,
        el("button.btn-primary", { onclick: add, text: "+ position" }),
      ]));

      const summary = el("div"); view.appendChild(summary);
      const host = el("div.vlt-grid"); view.appendChild(host);

      async function reload() {
        const [items, s] = await guard(() => Promise.all([
          api.vault.investments(), api.vault.investmentsSummary(),
        ]));
        clear(summary); clear(host);
        if (!items.length) {
          host.appendChild(el("div.empty", { text: "No positions yet." }));
          return;
        }
        const up = s.pl >= 0;
        summary.appendChild(el("div.vlt-stat-grid", { style: "margin-bottom:14px" }, [
          el("div.vlt-stat", {}, [
            el("div.vlt-stat-val", { text: V.money(s.invested) }),
            el("div.vlt-stat-lbl", { text: "TOTAL INVESTED" }),
          ]),
          el("div.vlt-stat", {}, [
            el("div.vlt-stat-val", { style: "color:var(--teal)", text: V.money(s.current) }),
            el("div.vlt-stat-lbl", { text: "CURRENT VALUE" }),
          ]),
          el("div.vlt-stat", {}, [
            el("div.vlt-stat-val", { style: "color:" + (up ? "var(--green)" : "var(--red)"),
              text: (up ? "↑ " : "↓ ") + V.money(s.pl) }),
            el("div.vlt-stat-lbl", { text: "TOTAL P&L · " + (up ? "+" : "") + s.pl_pct + "%" }),
          ]),
        ]));
        items.forEach((iv) => host.appendChild(card(iv, reload)));
      }
      reload();
    },
  };
})();

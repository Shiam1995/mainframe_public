/* vault-accounts.js — Vault · Accounts (VAULT_SPEC §2).
   Where money sits. Balances are manually updated — nothing here talks to a bank. */
(function () {
  const { el, clear, toast, guard, confirmDo } = window.ui;
  const api = window.api;
  const V = window.VAULT;

  function card(a, reload) {
    const nameIn = el("input.vis-title", { style: "font-size:15px", value: a.name });
    nameIn.addEventListener("blur", () => guard(async () => {
      const nv = nameIn.value.trim();
      if (!nv || nv === a.name) { nameIn.value = a.name; return; }
      await api.vault.updateAccount(a.id, { name: nv }); a.name = nv; toast("renamed");
    }));

    const balIn = el("input.vlt-balance", { type: "number", step: "0.01", value: String(a.balance ?? 0) });
    balIn.addEventListener("blur", () => guard(async () => {
      const nv = parseFloat(balIn.value);
      if (isNaN(nv) || nv === Number(a.balance)) { balIn.value = String(a.balance ?? 0); return; }
      await api.vault.updateAccount(a.id, { balance: nv });
      toast("balance updated"); reload();
    }));

    const typeSel = el("select", {}, V.ACCOUNT_TYPES.map((t) => el("option", { value: t.key, text: t.icon + " " + t.key })));
    typeSel.value = a.type;
    typeSel.addEventListener("change", () => guard(async () => {
      await api.vault.updateAccount(a.id, { type: typeSel.value }); reload();
    }));
    const provIn = el("input", { value: a.provider || "", placeholder: "provider" });
    provIn.addEventListener("blur", () => guard(async () => {
      if ((provIn.value || "") === (a.provider || "")) return;
      await api.vault.updateAccount(a.id, { provider: provIn.value }); a.provider = provIn.value; toast("saved");
    }));

    return el("div.vault-card", {}, [
      el("div.spread", {}, [
        el("div.row", { style: "gap:9px;min-width:0;flex:1" }, [
          el("span", { style: "font-size:19px", text: V.acctIcon(a.type) }), nameIn,
        ]),
        el("button.ord-btn", { title: "delete account", text: "×",
          onclick: () => confirmDo("Delete “" + a.name + "”? Its transactions are kept.", async () => {
            await api.vault.delAccount(a.id); reload();
          }) }),
      ]),
      el("div.vlt-bal-row", {}, [
        el("span.sub", { text: a.currency || "GBP" }), balIn,
      ]),
      el("div.md-grid", { style: "margin-top:10px" }, [
        el("label.md-field", {}, [el("span.sub", { text: "type" }), typeSel]),
        el("label.md-field", {}, [el("span.sub", { text: "provider" }), provIn]),
      ]),
      el("div.sub", { style: "margin-top:8px", text: "updated " + (a.updated_at || "").slice(0, 10) }),
    ]);
  }

  window.Views = window.Views || {};
  window.Views.accounts = {
    id: "accounts", label: "Accounts", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "Accounts" }),
        el("div.sub", { text: "Where the money sits. Balances are yours to update — nothing here connects to a bank." }),
      ])]));

      const nameIn = el("input", { placeholder: "account name", style: "flex:1;min-width:170px" });
      const typeSel = el("select", {}, V.ACCOUNT_TYPES.map((t) => el("option", { value: t.key, text: t.icon + " " + t.key })));
      const provIn = el("input", { placeholder: "provider (optional)", style: "flex:1;min-width:140px" });
      const balIn = el("input", { type: "number", step: "0.01", placeholder: "balance", style: "width:110px" });
      const add = () => guard(async () => {
        if (!nameIn.value.trim()) return toast("the account needs a name", true);
        await api.vault.createAccount({ name: nameIn.value.trim(), type: typeSel.value,
          provider: provIn.value.trim(), balance: parseFloat(balIn.value) || 0 });
        nameIn.value = provIn.value = balIn.value = ""; toast("account added"); reload();
      });
      nameIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
      view.appendChild(el("div.row", { style: "margin-bottom:16px" }, [
        nameIn, typeSel, provIn, balIn, el("button.btn-primary", { onclick: add, text: "+ account" }),
      ]));

      const totalBox = el("div"); view.appendChild(totalBox);
      const host = el("div.vlt-grid"); view.appendChild(host);

      async function reload() {
        const accounts = await guard(() => api.vault.accounts());
        clear(totalBox); clear(host);
        if (!accounts.length) {
          host.appendChild(el("div.empty", { text: "No accounts yet. Add where your money sits." }));
          return;
        }
        const total = accounts.reduce((s, a) => s + Number(a.balance || 0), 0);
        totalBox.appendChild(el("div.vault-card", { style: "margin-bottom:14px" }, [
          el("div.spread", {}, [
            el("span.sub", { text: "TOTAL ACROSS " + accounts.length + " ACCOUNT" + (accounts.length === 1 ? "" : "S") }),
            el("span.vlt-total", { text: V.money(total) }),
          ]),
        ]));
        accounts.forEach((a) => host.appendChild(card(a, reload)));
      }
      reload();
    },
  };
})();

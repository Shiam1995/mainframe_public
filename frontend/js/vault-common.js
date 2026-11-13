/* vault-common.js — shared bits for the Vault module: money formatting, the
   transaction category list, verdict config, account types. Loaded before the
   Vault views, same as pulse-common.js. */
(function () {
  const GOLD = "#D4A017";

  // Transaction categories from the spec. These are the defaults offered in
  // dropdowns — a user can still type a custom one (budget categories are
  // explicitly user-defined, and the two need to be able to line up).
  const CATEGORIES = [
    { key: "Rent", icon: "🏠" }, { key: "Food & Drink", icon: "🍕" },
    { key: "Transport", icon: "🚌" }, { key: "Subscriptions", icon: "📱" },
    { key: "Learning", icon: "📚" }, { key: "Fun & Social", icon: "🎮" },
    { key: "Tech & Gear", icon: "🛠" }, { key: "Medical", icon: "🏥" },
    { key: "Investing", icon: "💰" }, { key: "Savings", icon: "🏦" },
    { key: "Transfer", icon: "💸" }, { key: "Income", icon: "💰" },
    { key: "Other", icon: "📌" },
  ];
  const catIcon = (k) => (CATEGORIES.find((c) => c.key === k) || { icon: "📌" }).icon;

  const ACCOUNT_TYPES = [
    { key: "current", icon: "🏦" }, { key: "savings", icon: "💰" },
    { key: "digital", icon: "💳" }, { key: "cash", icon: "💵" },
    { key: "investment", icon: "📈" }, { key: "crypto", icon: "🪙" },
  ];
  const acctIcon = (k) => (ACCOUNT_TYPES.find((a) => a.key === k) || { icon: "🏦" }).icon;

  // Verdict cycles unset → needed → wanted → wasteful → unset
  const VERDICTS = [
    { key: "", label: "? unset", color: "var(--dim)", bg: "var(--raised)" },
    { key: "needed", label: "✓ needed", color: "var(--green)", bg: "var(--green-d)" },
    { key: "wanted", label: "~ wanted", color: "var(--amber)", bg: "var(--amber-d)" },
    { key: "wasteful", label: "✗ wasteful", color: "var(--red)", bg: "var(--red-d)" },
  ];
  const verdictOf = (k) => VERDICTS.find((v) => v.key === (k || "")) || VERDICTS[0];
  const nextVerdict = (k) => VERDICTS[(VERDICTS.findIndex((v) => v.key === (k || "")) + 1) % VERDICTS.length].key;

  /* Money. Amounts are stored signed (expense negative); most displays want the
     magnitude plus a colour, so `money` formats the absolute value and callers
     pick the colour from the sign. */
  function money(n, opts) {
    const o = opts || {};
    const v = o.signed ? Number(n || 0) : Math.abs(Number(n || 0));
    const s = v.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (o.signed && v > 0 ? "+£" : v < 0 ? "-£" : "£") + s.replace("-", "");
  }
  const amountColor = (n) => (Number(n) > 0 ? "var(--green)" : Number(n) < 0 ? "var(--red)" : "var(--dim)");

  const pad = (n) => String(n).padStart(2, "0");
  const monthKey = (d) => d.getFullYear() + "-" + pad(d.getMonth() + 1);
  const thisMonth = () => monthKey(new Date());
  function monthLabel(key) {
    const [y, m] = (key || "").split("-");
    const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return names[Number(m) - 1] ? names[Number(m) - 1] + " " + y : key;
  }
  // The last n month keys, newest first.
  function recentMonths(n) {
    const out = [];
    const d = new Date();
    for (let i = 0; i < n; i++) out.push(monthKey(new Date(d.getFullYear(), d.getMonth() - i, 1)));
    return out;
  }
  function dateFmt(iso) {
    if (!iso) return "";
    try { return new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }); }
    catch { return iso; }
  }
  const todayStr = () => {
    const d = new Date();
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
  };

  /* Stable colour per category — charts must keep the same colour for the same
     category across every view, so this is a fixed map plus a deterministic
     fallback for user-defined categories. */
  const PALETTE = ["#D4A017", "#00D4AA", "#5A9DE0", "#8B7EC8", "#DE7BA4",
                   "#4ADE80", "#F0A030", "#E05A5A", "#7B8BA3", "#00BFFF",
                   "#FF8C42", "#9BE564"];
  const FIXED = {
    "Rent": "#D4A017", "Food & Drink": "#00D4AA", "Transport": "#5A9DE0",
    "Subscriptions": "#8B7EC8", "Learning": "#4ADE80", "Fun & Social": "#DE7BA4",
    "Tech & Gear": "#F0A030", "Medical": "#E05A5A", "Investing": "#00BFFF",
    "Savings": "#9BE564", "Transfer": "#7B8BA3", "Income": "#4ADE80",
    "Other": "#FF8C42",
  };
  function catColor(name) {
    if (FIXED[name]) return FIXED[name];
    let h = 0;
    for (let i = 0; i < (name || "").length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }

  window.VAULT = {
    catColor,
    GOLD, CATEGORIES, catIcon, ACCOUNT_TYPES, acctIcon,
    VERDICTS, verdictOf, nextVerdict,
    money, amountColor, monthKey, thisMonth, monthLabel, recentMonths, dateFmt, todayStr,
  };
})();

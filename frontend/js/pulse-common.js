/* pulse-common.js — shared bits for the Pulse module: category icons, log levels,
   streak calc, a small modal helper, date utils. Loaded before the Pulse views. */
(function () {
  const { el, clear } = window.ui;
  const DAY = 86400000;

  // Habit categories (spec §1) and routine categories (spec §4).
  const HABIT_CATS = [
    { key: "sleep", icon: "😴" }, { key: "fitness", icon: "💪" }, { key: "nutrition", icon: "🥗" },
    { key: "learning", icon: "📚" }, { key: "mindfulness", icon: "🧘" }, { key: "productivity", icon: "⚡" },
    { key: "social", icon: "👥" }, { key: "creative", icon: "🎨" }, { key: "health", icon: "❤️" }, { key: "recovery", icon: "🌿" },
    { key: "other", icon: "📌" },
  ];
  const ROUTINE_CATS = [
    { key: "cleaning", icon: "🧹" }, { key: "fitness", icon: "💪" }, { key: "morning", icon: "🌅" },
    { key: "evening", icon: "🌙" }, { key: "weekly", icon: "📅" }, { key: "learning", icon: "📚" },
    { key: "creative", icon: "🎨" }, { key: "other", icon: "📌" },
  ];
  // Log intensity levels (spec §2). Index 0 = empty.
  const LEVELS = [
    { label: "Empty", color: "var(--raised)" },
    { label: "Barely", color: "rgba(222,123,164,0.2)" },
    { label: "Okay", color: "rgba(222,123,164,0.4)" },
    { label: "Good", color: "rgba(222,123,164,0.65)" },
    { label: "Crushed it", color: "#DE7BA4" },
  ];

  const pad = (n) => String(n).padStart(2, "0");
  function dateStr(d) { return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()); }
  function today() { return dateStr(new Date()); }
  function fmtDay(iso) { try { return new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" }); } catch { return iso; } }

  function catIcon(cats, key) { const c = cats.find((x) => x.key === key); return c ? c.icon : "📌"; }

  // Streak: consecutive days back from today with a log level>0. Today may be
  // un-logged (streak counts up to yesterday then).
  function streak(logs) {
    const set = new Set((logs || []).filter((l) => (l.level || 0) > 0).map((l) => l.date));
    let d = new Date();
    if (!set.has(dateStr(d))) d = new Date(d.getTime() - DAY);
    let n = 0;
    while (set.has(dateStr(d))) { n++; d = new Date(d.getTime() - DAY); }
    return n;
  }

  // Minimal modal using the global .modal-overlay / .modal / .mform-* styles.
  function modal(title, bodyNodes, actions) {
    const overlay = el("div.modal-overlay");
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const card = el("div.modal", {}, [
      el("div.modal-title", { text: title }),
      ...bodyNodes,
      el("div.row", { style: "margin-top:18px;gap:8px;justify-content:flex-end" },
        (actions || []).map((a) => el("button.btn-sm" + (a.primary ? ".btn-primary" : "") + (a.danger ? ".btn-danger" : ""),
          { onclick: () => a.onClick(close), text: a.label }))),
    ]);
    overlay.appendChild(card);
    document.body.appendChild(overlay);
    const first = card.querySelector("input,select,textarea");
    if (first) first.focus();
    return { close, card };
  }

  // Medical + medication section config (spec §5, §6) — icon/label/description.
  const MEDICAL_SECTIONS = [
    { key: "history", icon: "📋", label: "Medical History", desc: "General medical history, past diagnoses, ongoing conditions" },
    { key: "conditions", icon: "🩺", label: "Conditions", desc: "Current and past medical conditions" },
    { key: "symptoms", icon: "🌡️", label: "Symptoms", desc: "Symptoms experienced" },
    { key: "pain", icon: "⚡", label: "Pain", desc: "Pain tracking — location, intensity, triggers, patterns" },
    { key: "allergies", icon: "🚫", label: "Allergies", desc: "Medications, food, environmental" },
    { key: "surgeries", icon: "🔪", label: "Surgeries", desc: "Past and upcoming surgical procedures" },
    { key: "hospital", icon: "🏥", label: "Hospital Visits", desc: "A&E, admissions, outpatient appointments" },
    { key: "vaccinations", icon: "💉", label: "Vaccinations", desc: "Records and schedules" },
    { key: "blood", icon: "🩸", label: "Blood Tests", desc: "Results, dates, values" },
    { key: "imaging", icon: "📷", label: "Imaging", desc: "X-rays, MRIs, CT scans, ultrasounds" },
    { key: "family", icon: "👪", label: "Family History", desc: "Genetic risks, hereditary conditions" },
  ];
  const MED_SECTIONS = [
    { key: "current", icon: "💊", label: "Current Medications", desc: "Medications currently being taken" },
    { key: "dose", icon: "⚖️", label: "Dose", desc: "Dosage details and adjustments over time" },
    { key: "schedule", icon: "🕐", label: "Schedule", desc: "When and how each medication is taken" },
    { key: "adherence", icon: "✅", label: "Adherence", desc: "How consistently medications are taken" },
    { key: "side-effects", icon: "⚠️", label: "Side Effects", desc: "Side effects experienced" },
    { key: "prn", icon: "🆘", label: "PRN Medications", desc: "As-needed medications — when taken and why" },
    { key: "supplements", icon: "🌿", label: "Supplements", desc: "Vitamins, minerals, other supplements" },
    { key: "previous", icon: "📦", label: "Previous Medications", desc: "Medications no longer taken and why" },
    { key: "effectiveness", icon: "📊", label: "Effectiveness", desc: "How well each medication works over time" },
  ];
  const SEVERITY_COLOR = {
    mild: "var(--teal)", moderate: "var(--amber)", severe: "var(--red)", active: "#DE7BA4",
    resolved: "var(--green)", chronic: "var(--purple)", monitoring: "var(--blue)",
  };
  const MED_STATUS_COLOR = {
    active: "var(--green)", "as-needed": "var(--blue)", paused: "var(--amber)", stopped: "var(--dim)",
    effective: "var(--teal)", ineffective: "var(--red)", "side-effects": "var(--red)",
  };

  window.PULSE = {
    DAY, HABIT_CATS, ROUTINE_CATS, LEVELS, MEDICAL_SECTIONS, MED_SECTIONS,
    SEVERITY_COLOR, MED_STATUS_COLOR, dateStr, today, fmtDay, catIcon, streak, modal,
  };
})();

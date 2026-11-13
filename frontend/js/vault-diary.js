/* vault-diary.js — Vault · Diary (VAULT_SPEC §8).
   Financial reflections, reviews and decisions. Its own tab, deliberately not
   folded into transaction notes (spec).

   The tab is now a thin call on the shared section-diary: Vault's diary and the
   Mainframe diary are the same :DiaryEntry store filtered to module "vault", so
   an entry written here shows up in the day view without being copied anywhere,
   and a line the Mainframe mind-dump routed to Vault shows up here. */
(function () {
  window.Views = window.Views || {};
  window.Views.findiary = window.makeSectionDiary({
    id: "findiary",
    label: "Diary",
    module: "vault",
    blurb: "Financial reflections, monthly reviews, decisions and why you made them.",
    placeholder: "what happened, what you decided, why…",
    tagHint: "monthly-review, investment-decision",
    empty: "No entries yet. Reviews and decisions go here.",
  });
})();

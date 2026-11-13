/* modules.js — THE MASTER MANIFEST of the Mainframe.
   Every module of the personal-OS is declared here in one place: its identity,
   accent colour, topbar text, and which tabs it owns. The shell (app.js) reads
   this to build the module switcher, swap the theme, and render the nav.

   To add a new module later: add one entry here + its tab view files. That's it.
   All modules share one Neo4j graph + the Mainframe activity log, so they can
   cross-link and "talk" to each other. */
(function () {
  window.MODULES = [
    {
      key: "synapse",
      label: "SYNAPSE",
      accent: "#00D4AA",                 // teal
      topbar: "MAINFRAME <span class='brand-accent'>/ SYNAPSE</span>",
      // Removed from this bar 2026-09-29 by request: scanner, kg (Knowledge
      // Graph), deepdive (labelled "Project" here) and framework; 2026-09-30:
      // decomposition and lattice. Views, routes and data are untouched; add a
      // key back to show the tab again. 2026-10-28: planner moved up to the
      // shared Mainframe bar (it already plans across every module); timeline
      // (Paper Timeline) removed — the shared Timeline covers every module;
      // headers (Sections) removed too.
      tabs: ["repo", "workspace", "dictionary", "refgraph"],
    },
    {
      key: "pulse",
      label: "PULSE",
      accent: "#DE7BA4",                 // warm pink
      topbar: "<span class='brand-accent'>PULSE</span> / habits",
      // pulsedive (Deep Dive) removed 2026-10-28; view and data untouched.
      tabs: ["benchmark", "habits", "tracking", "experiments", "routines", "fitness", "nutrition", "recovery", "medical", "medications"],
    },
    {
      key: "vision",
      label: "VISION",
      accent: "#FF4757",                 // red
      topbar: "<span class='brand-accent'>VISION</span> / content",
      // Tabs appear as they're built — app.js filters out any not yet
      // registered in window.Views, so listing the full set here is safe.
      tabs: ["blueprint", "youtube", "writing", "portfolio", "network", "sandbox"],
    },
    {
      key: "vault",
      label: "VAULT",
      accent: "#D4A017",                 // gold
      topbar: "<span class='brand-accent'>VAULT</span> / finance",
      tabs: ["overview", "accounts", "transactions", "subscriptions", "budget", "months", "investments",
             "analytics", "inventory", "findiary"],
    },
  ];

  // Mainframe-level tabs — shared services visible in every module.
  //
  // The strip reads as four runs, and the order is the order the work moves in:
  //
  //   Snapshot, Phases          where you are. Today, and the fourteen weeks
  //                             today is a day of.
  //   Inbox, Project            where work comes from, and where it ends up.
  //                             Everything is written into the Inbox as an idea
  //                             or a task; giving it to a project puts it in the
  //                             tree. Two tabs, because writing something down
  //                             and deciding where it belongs are two moments.
  //   Calendar, Planner,        the doing, and the record of it. The calendar is
  //   Timeline, Diary,          where tasks meet time, the Planner is where the
  //   Database                  time is budgeted, the Timeline is every module
  //                             on one axis, and Database is the work log
  //                             underneath them.
  //   Docs, Sheets, Reasoning,  what you wrote down. Reasoning is every "why"
  //   Lessons, Activity,        you have given, Lessons is what went wrong and
  //   Journal, Log, Settings    what you would do instead.
  //
  // Settings sits at the end, beside the log: both are about the machine itself
  // rather than anything you're working on.
  // Gantt is gone. It drew one bar per task on a time axis and nothing else read
  // from it; the Calendar answers the same question with data you are already
  // keeping up to date.
  // Ideas and Tasks are gone too, merged into Inbox: they were two tables over
  // one kind of row, and moving something between them meant retyping it. Goals
  // went with them — a phase claims a project directly now.
  // Progress went the same way. It was a third table over those same :Task
  // nodes, reading a done/horizon schema they stopped having in the merge, so
  // it listed every Inbox row as an untouched task. Its stats, its priority
  // editor and its journal are in the Inbox now; its "completed" section is the
  // Inbox's `done` chip.
  window.SHARED_TABS = ["snapshot", "phases", "inbox", "questions", "project",
                       "calendar", "planner", "mtimeline", "diary", "work", "docs", "sheets",
                       "reasoning", "assumptions", "learning", "activity", "mind", "gratitude", "log", "settings",
                       "help"];
})();

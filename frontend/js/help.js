/* help.js — the plain-English guide to the whole Mainframe.

   Written for someone who has never opened the app: what it is, what each part
   is for, and — the bit that's hardest to work out on your own — WHAT FEEDS
   WHAT. Every arrow below is a connection that actually exists in the code, not
   an aspiration.

   The module list is read from window.MODULES so names and colours can never
   drift from the real thing, and the counts are fetched live so the examples
   use your actual library rather than made-up numbers. */
(function () {
  const { el, clear, guard } = window.ui;
  const api = window.api;

  const MOD = (k) => (window.MODULES || []).find((m) => m.key === k) || {};

  /* One line per module, in words a newcomer can act on. */
  const WHAT_FOR = {
    synapse: "Everything you read. Papers, books, video series — plus the notes, terms and graphs that come out of them.",
    pulse: "Everything about your body. Habits, workouts, food, sleep-adjacent things, medical records, recovery.",
    vision: "Everything you make. Videos, writing, portfolio pieces, and the people you make them with.",
    vault: "Everything about money and things. Accounts, spending, budget, investments, what you own.",
  };

  /* The Mainframe-level tabs — the ones in the TOP bar, present in every module. */
  const SHARED = [
    ["Tasks", "What you need to do. The spine of the whole app — every module can make one."],
    ["Progress", "How the tasks are going."],
    ["Database", "Every block of work you've logged, from every module, in one table."],
    ["Ideas", "Ideas, in a spreadsheet. The “+ idea” button in the bottom-right adds one from anywhere."],
    ["Learning", "Mistakes and things to improve. Groups repeats so you can see a habit forming."],
    ["Activity", "A timeline of what you did and when."],
    ["Gantt", "Your tasks as bars across a calendar."],
    ["Mind Dump", "A single inbox for thoughts you don't want to lose yet."],
    ["Project", "Projects and their files, plus the green contribution grid."],
    ["Log", "The raw record of every change the app has made."],
    ["FAQ", "This page. What everything is for, and what feeds what."],
  ];

  /* WHAT FEEDS WHAT. Each row: from → to → why it matters. All real. */
  const FLOWS = [
    { from: "You read a paper", to: "Workspace → Master Instance",
      why: "Every note, highlight and idea from every reading pass collects into one document for that paper." },
    { from: "A distraction while reading", to: "Learning",
      why: "Push it across and repeated distractions group together, so you can see the pattern." },
    { from: "An idea while reading", to: "Ideas + that paper's Master Instance",
      why: "The “+ idea” button links it to the paper you're on, so it shows up in both places." },
    { from: "Time you log anywhere", to: "Database → Project contribution grid",
      why: "Every session lands in one table, and the green squares are drawn from it." },
    { from: "A paper's references", to: "Reference Map",
      why: "Works cited by two papers become one shared node — that's where your reading overlaps." },
    { from: "A reference that's a paper you own", to: "a direct paper-to-paper link",
      why: "The map connects them instead of showing a dead-end copy." },
    { from: "Terms you meet", to: "Dictionary → Knowledge Graph",
      why: "A concept found in several papers is one that keeps coming back." },
    { from: "Food you log", to: "Nutrition Dashboard",
      why: "The calorie ring, macro bars and streak are all counted from the food log." },
    { from: "A recipe", to: "one tap into today's food log",
      why: "Build the meal once; log it in a click after that." },
    { from: "Weight and measurements", to: "trends + BMI",
      why: "Daily weight bounces, so the graph also draws a smoothed weekly line." },
    { from: "Anything you do to a paper", to: "the ⏱ banner in its Workspace",
      why: "If you did things but never logged time, it tells you — and offers to log it." },
  ];

  const FAQ = [
    ["What is this thing?",
     "A personal operating system. One place for what you read, your body, what you make, and your money — all sharing one database so they can point at each other."],
    ["Where do I start?",
     "Repository — put a paper, book or video series in. Then open it (Workspace) and start writing while you read."],
    ["Repository vs Workspace?",
     "Repository is the shelf: everything you own. Workspace is the desk: one thing open, with your notes around it."],
    ["What's a “reading instance”?",
     "One pass through something. Read it again next month and that's a second pass, kept separately — so you can see how your understanding changed."],
    ["What's the Master Instance?",
     "Every pass merged into one document, made for you automatically. You never write in it; it assembles itself."],
    ["What does “generate auto KG” do?",
     "Reads the PDF with the local AI on your own machine and draws a first knowledge graph from it. It's frozen — to change it you make an editable copy."],
    ["What does “+ log time” do?",
     "Records that you worked on this, for this long. It's the same button everywhere, and everything lands in the Database tab."],
    ["Does anything leave my computer?",
     "No. The database, the files and the AI all run locally. There are no cloud accounts and no API keys."],
    ["Why is my food list empty?",
     "On purpose. It fills with the foods you actually eat, so searching stays fast and every number is one you checked."],
    ["Something disappeared — where did it go?",
     "Check the toggles. Finished papers, completed tasks and resolved learning entries hide by default; each has a button to show them again."],
    ["How do I move things around?",
     "The ◀ ▶ arrows. Repository cards, reading passes, images and ideas can all be reordered."],
  ];

  function section(title, sub) {
    return el("div", { style: "margin:22px 0 10px" }, [
      el("h3", { style: "margin:0", text: title }),
      sub ? el("div.sub", { style: "margin-top:2px", text: sub }) : null,
    ]);
  }

  window.Views = window.Views || {};
  window.Views.help = {
    id: "help", label: "FAQ", scoped: false,
    async render(view) {
      clear(view);
      view.appendChild(el("div.view-head", {}, [el("div", {}, [
        el("h1", { text: "How this works" }),
        el("div.sub", { text: "The whole app in plain words — what each part is for, and what feeds what." }),
      ])]));

      view.appendChild(el("div.card", {}, [
        el("div", { style: "font-size:14px;line-height:1.6" , text:
          "Mainframe is one place for four sides of your life. Everything lives in a single database on this machine, "
          + "which is why the parts can point at each other: a paper you read can produce a task, an idea and a "
          + "learning note, and all of them stay connected." }),
      ]));

      // --- the four modules, straight from the manifest ---
      view.appendChild(section("The four modules", "The coloured buttons at the very top-left switch between them."));
      const grid = el("div.cards");
      (window.MODULES || []).forEach((m) => {
        grid.appendChild(el("div.card", { style: "border-left:3px solid " + m.accent }, [
          el("h3", { style: "margin:0 0 4px;color:" + m.accent, text: m.label }),
          el("div", { style: "font-size:13px", text: WHAT_FOR[m.key] || "" }),
          el("div.sub", { style: "margin-top:8px;font-size:10.5px",
            text: (m.tabs || []).length + " tabs · " + (m.tabs || []).slice(0, 6).join(" · ")
              + ((m.tabs || []).length > 6 ? " …" : "") }),
        ]));
      });
      view.appendChild(grid);

      // --- shared tabs ---
      view.appendChild(section("The tabs at the top", "These stay put whichever module you're in — they belong to all of them."));
      const shared = el("div.card");
      SHARED.forEach(([name, what]) => shared.appendChild(el("div.hl-row", {}, [
        el("strong", { style: "min-width:96px", text: name }),
        el("span", { style: "flex:1", text: what }),
      ])));
      view.appendChild(shared);

      // --- the important bit ---
      view.appendChild(section("What feeds what",
        "The connections are the point of the app. Each of these is real — the arrow means information actually moves."));
      const flows = el("div.card");
      FLOWS.forEach((f) => flows.appendChild(el("div.hl-flow", {}, [
        el("div.row", { style: "gap:8px;align-items:baseline;flex-wrap:wrap" }, [
          el("span", { style: "font-weight:600", text: f.from }),
          el("span.hl-arrow", { text: "→" }),
          el("span", { style: "color:var(--accent)", text: f.to }),
        ]),
        el("div.sub", { style: "font-size:11.5px;margin-top:2px", text: f.why }),
      ])));
      view.appendChild(flows);

      // --- FAQ ---
      view.appendChild(section("Questions"));
      const faq = el("div");
      FAQ.forEach(([q, a]) => {
        const ans = el("div.sub", { style: "display:none;margin-top:6px;font-size:12.5px;line-height:1.55", text: a });
        const caret = el("span.dd-caret", { text: "▸" });
        const card = el("div.card", { style: "margin-bottom:8px;cursor:pointer" }, [
          el("div.row", { style: "gap:8px;align-items:baseline" }, [caret, el("strong", { text: q })]),
          ans,
        ]);
        card.addEventListener("click", () => {
          const open = ans.style.display === "none";
          ans.style.display = open ? "block" : "none";
          caret.textContent = open ? "▾" : "▸";
        });
        faq.appendChild(card);
      });
      view.appendChild(faq);

      // --- live counts, so the guide describes YOUR app, not a demo ---
      const counts = el("div.card", { style: "margin-top:14px" }, [
        el("div.sub", { text: "counting what you have…" }),
      ]);
      view.appendChild(counts);
      guard(async () => {
        const [papers, tasks] = await Promise.all([
          api.papers.list().catch(() => []),
          api.get("/api/tasks").catch(() => []),
        ]);
        clear(counts);
        counts.appendChild(el("h3", { style: "margin:0 0 8px", text: "Right now you have" }));
        const box = (v, l) => el("div.prog-box", {}, [
          el("div.prog-val", { text: String(v) }), el("div.prog-label", { text: l }),
        ]);
        counts.appendChild(el("div.prog-grid", {}, [
          box(papers.length, papers.length === 1 ? "thing to read" : "things to read"),
          box(papers.filter((p) => (p.status || "unread") === "read").length, "finished"),
          box(tasks.filter((t) => !t.done).length, "open tasks"),
        ]));
      });
    },
  };
})();

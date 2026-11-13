# Mainframe — what it is, and what it looks like

Paste this whole file into a new Claude conversation before asking for any UI work.
It is written to be handed to someone who has never seen the app and must produce
mockups that drop straight into it.

---

## 1. What Mainframe is

Mainframe is a **personal operating system** — one self-hosted web app where a single
person runs their research, their body, their money and their creative output, all
against one shared graph database. It is not a product for other people; it has one
user, and it is shaped around how they actually work rather than around what is
conventional.

Everything is **local-first**. It runs entirely on the user's machine: a Neo4j graph
on localhost, a local LLM (Ollama) for extraction and the voice assistant, a
FastAPI server on `localhost:8000` that serves both the JSON API and the frontend.
There are no cloud APIs, no keys, no telemetry, and it works with the network
unplugged. The only deliberate exception anywhere in the codebase is resolving
academic references against Crossref/OpenAlex.

The organising idea is that everything is **one graph**. A reading session, a
workout, a bank transaction and a task are all nodes in the same Neo4j database, so
the modules cross-link rather than sit in silos: a distraction logged while reading
a paper can be pushed into the Learning tab; a reading session can be pushed into
the work database; a task can belong to any module. Every mutation anywhere writes
a `:ChangeEvent` to one shared activity log.

**Scale, so you know what you are designing for:** ~29,000 lines of vanilla JS
across ~130 view files, 577 API routes, ~120 node labels in the graph.

---

## 2. How it is built — constraints any mockup must respect

These are hard constraints. A design that violates them cannot be used.

- **Vanilla HTML/CSS/JS. Zero libraries.** No React, no Vue, no Tailwind, no
  jQuery, no chart library, no spreadsheet library, no icon font. The knowledge-graph
  canvas, the spreadsheet grid and every chart are hand-rolled. A mockup may use
  plain `<canvas>`, inline `<svg>`, CSS gradients and CSS grid — nothing else.
- **No external fonts, no external anything.** The app must run offline, so no
  Google Fonts, no CDN, no remote images. Type uses system stacks that approximate
  JetBrains Mono and Inter (see tokens below).
- **Dark only.** There is no light theme and none is wanted.
- **One stylesheet**, `frontend/css/main.css` (~3,100 lines), plus one CSS custom
  property block that everything derives from. New colours should come from the
  existing tokens, not from a new palette.
- **Views are plain functions** that build DOM with one tiny helper and register
  themselves on a global registry. There is no build step, no bundler, no npm.

The DOM helper, used by every view, is worth knowing because mockup markup should
translate into it cleanly:

```js
el("div.card", { onclick: fn }, [ el("h3", { text: "Title" }), childNode ])
// "tag.class.class", then attributes ({text, html, on*, or any attribute}), then children
```

A view registers itself like this:

```js
window.Views.repo = {
  id: "repo", label: "Repository", scoped: false,
  render(view) { clear(view); view.appendChild(...); }
};
```

---

## 3. The shell — the frame every screen sits inside

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◆ MAINFRAME / SYNAPSE   [SYNAPSE][PULSE][VISION][VAULT]  tab tab tab …  │ 52px topbar
│                                              FAQ  ◉mic  ●neo4j ●llm     │
├──────────────────────────────────────────────────────────────────────────┤
│              module tabs, tinted the module's accent colour              │ module bar
├────────────────┬─────────────────────────────────────────────────────────┤
│ context panel  │                                                         │
│ (300px,        │   the view — everything is rendered here                │
│  optional,     │                                                         │
│  hidden by     │                                                         │
│  default)      │                                                         │
└────────────────┴─────────────────────────────────────────────────────────┘
                                                        [＋ quick capture]  ← fixed
```

- **Topbar** — 52px tall, sticky, `--surface` background, 1px `--border` bottom.
  Left: a `◆` brand mark in the accent colour and `MAINFRAME / SYNAPSE` in mono,
  where the second half is the active module and takes the accent colour. Then the
  module switcher (four small mono buttons). Then the shared tab strip, which
  scrolls horizontally. Pinned at the right, outside the scroll: the FAQ tab, a
  dictation mic button `◉`, and a status pill with two dots (neo4j, llm) that go
  teal when up and red when down.
- **Module bar** — a second sticky row directly beneath, holding the active
  module's own tabs. It is tinted: `linear-gradient(var(--accent-d), transparent 60%)`
  over `--surface`, with a **2px solid `--accent` top border**. It has 130px of left
  padding to clear a fixed "← mainframe" button. When a module isn't open it is empty
  and collapses.
- **Layout** — `display:flex; height: calc(100vh - 52px)`. An optional 300px context
  panel on the left (used by the paper Workspace), then the view, which scrolls
  independently with `padding: 22px 26px`.
- **Home screen** — behind everything sits a separate landing screen: four tall
  module cards with gradients derived from each module's own accent, a lifetime stat
  strip, a period snapshot, and a customisable background (gradient / wallpaper
  slideshow / video, with a dim slider and particles).
- **Boot screen** — the app opens on a CRT boot sequence in phosphor green with
  ice-blue accents: logo fade-in, scrolling system checks with `OK`/`WARN` status
  columns, a loading bar, then a pulsing `[ENTER]`. It covers the app from first
  paint so the dashboard never flashes underneath.
- **Floating, on every screen** — a cyan pill "quick capture" button fixed at the
  bottom-right, plus a reminders bell and an unlogged-work chip in the topbar.
- **Toasts** — bottom centre, mono, `--raised` with a teal border (red when an error).

---

## 4. The modules and their tabs

Four modules, each with its own accent colour that repaints the shell chrome
(`--accent` is swapped when you switch):

| Module | Accent | What it is |
|---|---|---|
| **SYNAPSE** | `#00D4AA` teal | Research. Papers, reading passes, highlights, knowledge graph, references, terms. |
| **PULSE** | `#DE7BA4` warm pink | Body. Habits, experiments, routines, fitness, nutrition, recovery, medical. |
| **VISION** | `#FF4757` red | Creative output. Video blueprints, scripts, storyboards, writing, portfolio. |
| **VAULT** | `#D4A017` gold | Money. Accounts, transactions, monthly plan, investments, inventory. |

**Synapse tabs:** Repository · Workspace · Planner · Dictionary · Scanner ·
Reference Map · Paper Timeline · Knowledge Graph · Deep Dive · Decomposition ·
Lattice · Sections

**Pulse tabs:** Benchmark · Habits · Active Tracking · Experiments · Routines ·
Fitness · Nutrition · Recovery · Medical · Medications · Pulse Dive

**Vision tabs:** Blueprint · YouTube · Writing · Portfolio · Network · Sandbox

**Vault tabs:** Overview · Accounts · Transactions · Monthly Plan · Investments ·
Analytics · Inventory · Diary

**Shared tabs — visible in every module**, because they are Mainframe-level rather
than owned by any one module, in nav order:

Snapshot · Tasks · Calendar · Diary · Goals · Progress · Database · Ideas · Docs ·
Sheets · Framework · Learning · Activity · Gantt · Mind Dump · Project · Log ·
Settings · FAQ

Snapshot leads and is the default view (the day as it is actually happening).
Tasks is the spine everything else hangs off.

---

## 5. The visual language

### 5.1 Tokens — paste this verbatim; do not invent colours

```css
:root {
  --bg:      #0B0F14;   /* page */
  --surface: #141A22;   /* cards, topbar, modals */
  --raised:  #1B2330;   /* buttons, inset wells */
  --border:  #232d3b;
  --text:    #dfe6ee;
  --muted:   #8194a8;   /* secondary copy */
  --dim:     #7B8BA3;   /* tertiary: labels, meta */

  --teal:   #00D4AA;    --amber:  #F0A030;
  --purple: #8B7EC8;    --red:    #E05A5A;
  --blue:   #5A9DE0;    --green:  #4ADE80;
  --pulse:  #DE7BA4;

  /* 12%-alpha fills of each, for tag and chip backgrounds */
  --teal-d: rgba(0,212,170,.12);    --amber-d: rgba(240,160,48,.12);
  --purple-d: rgba(139,126,200,.12); --red-d:  rgba(224,90,90,.12);
  --blue-d: rgba(90,157,224,.12);    --green-d: rgba(74,222,128,.12);

  /* the active module's colour — everything chrome-like reads this */
  --accent:   #00D4AA;
  --accent-d: rgba(0,212,170,.12);

  --mono: ui-monospace, "JetBrains Mono", "Cascadia Code", "SF Mono", Menlo, Consolas, monospace;
  --sans: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
body { background: var(--bg); color: var(--text); font-family: var(--sans); font-size: 14px; }
```

### 5.2 Type — the single most characteristic thing about this UI

**Mono is for the machine, sans is for your words.** Get this wrong and it stops
looking like Mainframe.

- **Mono** (`--mono`): every tab, every button, every tag/pill/chip, every field
  label, every number, every stat, every table header, every empty state, every
  toast, the brand. Small — 9px to 12.5px. Field labels are 9–10px, uppercase,
  `letter-spacing: 1px`, in `--dim`.
- **Sans** (`--sans`): headings, body copy, textarea and input contents — the
  things a human writes or reads as prose.
- Base size 14px. `h1` 20px/600. Big stat numbers are mono 24px/700.
- Sub-lines under a heading are `.sub`: 12.5px, `--muted`, one plain-English
  sentence explaining what the screen is for.

### 5.3 Voice of the copy

Headings are Title Case ("Repository", "Mind dump"). **Everything else is
lowercase and conversational**, written as a question or an instruction to
yourself — this is a personal tool talking to one person, not a product:

> `what did I understand` · `to look into later` · `when you read it, what you took
> away — fill in info…` · `+ add distraction` · `↗ push to learning` ·
> `stick an idea or "come look at this"` · `Nothing stuck here yet.` ·
> `hide optional / review-later` · `✦ suggest (local LLM)`

Buttons carry a leading glyph rather than an icon font: `↗ push`, `⤴ push to
database`, `+ add`, `✦ suggest`, `× delete`, `← mainframe`, `◉`, `◆`.

### 5.4 Components — real classes, use these names

```css
/* card — the workhorse container */
.card { background: var(--surface); border: 1px solid var(--border);
        border-radius: 10px; padding: 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px,1fr)); gap: 14px; }

/* a card that carries a status takes a 3px coloured left border */
.prog-card { border-left: 3px solid var(--green); border-radius: 10px; padding: 16px 18px; }

/* stat strip */
.prog-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 12px; }
.prog-box  { background: var(--surface); border: 1px solid var(--border);
             border-radius: 8px; padding: 16px; text-align: center; }
.prog-val   { font-family: var(--mono); font-size: 24px; font-weight: 700; }  /* coloured per metric */
.prog-label { font-family: var(--mono); font-size: 9px; color: var(--dim);
              letter-spacing: 1px; text-transform: uppercase; margin-top: 4px; }

/* buttons */
button, .btn { font-family: var(--mono); font-size: 12.5px; background: var(--raised);
               color: var(--text); border: 1px solid var(--border); border-radius: 6px;
               padding: 7px 12px; cursor: pointer; }
button:hover { border-color: var(--teal); color: var(--teal); }
.btn-primary { background: var(--accent); color: var(--bg); border-color: var(--accent); font-weight: 600; }
.btn-danger:hover { border-color: var(--red); color: var(--red); }
.btn-sm { padding: 4px 8px; font-size: 11px; }

/* inputs — darker than the card they sit on, teal focus ring */
input, select, textarea { font-family: var(--sans); font-size: 13px; background: var(--bg);
  color: var(--text); border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; }
input:focus, textarea:focus { outline: none; border-color: var(--teal); }
label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 4px; }

/* tags, pills, chips */
.tk-tag { font-family: var(--mono); font-size: 10px; padding: 3px 8px; border-radius: 3px; }
         /* filled: background var(--x-d), color var(--x) */
.pill   { font-family: var(--mono); font-size: 10.5px; padding: 2px 7px; border-radius: 10px;
          border: 1px solid var(--border); color: var(--muted); }
         /* outlined, recoloured by state: .reading amber, .read teal */

/* tables */
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); }
th { color: var(--muted); font-family: var(--mono); font-size: 11px;
     text-transform: uppercase; letter-spacing: .04em; }
tr:hover td { background: var(--surface); }

/* modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.6);
                 display: flex; align-items: center; justify-content: center; padding: 20px; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
         padding: 24px 28px; max-width: 560px; max-height: 82vh; overflow-y: auto; }
.mform-label { font-family: var(--mono); font-size: 10px; color: var(--dim);
               letter-spacing: 1px; text-transform: uppercase; margin-bottom: 4px; }
.mform-row   { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }

/* layout helpers used constantly */
.row    { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.spread { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.view-head { display: flex; align-items: center; justify-content: space-between;
             margin-bottom: 18px; gap: 12px; flex-wrap: wrap; }
.sub   { color: var(--muted); font-size: 12.5px; }
.empty { color: var(--muted); text-align: center; padding: 50px 20px;
         font-family: var(--mono); font-size: 13px; }
```

### 5.5 Colour semantics

Colour always means something; it is never decoration.

- `--teal` done / known / healthy / good · `--amber` in progress / needs review /
  warning · `--red` bad / overdue / delete · `--blue` reference / informational ·
  `--green` complete / positive delta · `--purple` idea / to implement ·
  `--dim` inactive, dropped, set aside.
- A 0–10 familiarity or confidence score is red 0–3, amber 4–6, teal 7–10.
- A card's status shows as a 3px coloured left border, not as a background wash.
- Backgrounds for tags are the 12%-alpha version of the same hue, never solid.

---

## 6. Interaction idioms that recur everywhere

Reuse these rather than inventing new mechanics — they are what makes the app feel
like one thing:

1. **S/M/L/XL text boxes.** Every long-form textarea carries a small mono size bar
   with S · M · L · XL buttons and a label to its left. The choice persists per
   field, so a form reopens at the shape you last gave it.
2. **"↗ push to X" buttons.** Cross-module handoffs are explicit and pre-filled,
   never silent: a distraction pushes into Learning, a reading session pushes into
   the work Database, all through a pre-filled modal you can edit before saving.
3. **Read-only provenance lines.** Where content is pulled in from elsewhere, the
   card says where it came from and that it must be edited there:
   `from v2 · deep read`.
4. **Start/stop stamping.** Time fields come with a single button that walks
   started → ended, so a session can be bracketed without typing a clock time.
5. **Counts that cannot lie.** A manual count field can be raised by hand but is
   never allowed to sit below the number of items actually listed.
6. **Empty states are sentences**, centred, mono, muted, telling you what would
   appear here and how to make it appear.
7. **Everything is live.** No mock data anywhere — every number on screen is
   fetched from the graph on render.

---

## 7. A paste-ready skeleton

Build mockups inside this so they sit in a real frame. It is the actual shell
markup and the actual tokens.

```html
<!doctype html><html lang="en"><head><meta charset="utf-8">
<style>
:root{--bg:#0B0F14;--surface:#141A22;--raised:#1B2330;--border:#232d3b;--text:#dfe6ee;
--muted:#8194a8;--dim:#7B8BA3;--teal:#00D4AA;--amber:#F0A030;--purple:#8B7EC8;--red:#E05A5A;
--blue:#5A9DE0;--green:#4ADE80;--teal-d:rgba(0,212,170,.12);--amber-d:rgba(240,160,48,.12);
--blue-d:rgba(90,157,224,.12);--red-d:rgba(224,90,90,.12);--purple-d:rgba(139,126,200,.12);
--green-d:rgba(74,222,128,.12);--accent:#00D4AA;--accent-d:rgba(0,212,170,.12);
--mono:ui-monospace,"JetBrains Mono","SF Mono",Menlo,Consolas,monospace;
--sans:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px}
.topbar{display:flex;align-items:center;gap:20px;height:52px;padding:0 18px;
  background:var(--surface);border-bottom:1px solid var(--border)}
.brand{display:flex;align-items:center;gap:8px;font-family:var(--mono);font-weight:600}
.brand-accent{color:var(--accent)}
.mod-btn{font-family:var(--mono);font-size:11px;padding:3px 10px;border:1px solid var(--border);
  border-radius:6px;background:transparent;color:var(--muted);cursor:pointer}
.mod-btn.active{color:var(--bg);background:var(--accent);border-color:var(--accent);font-weight:600}
.tabs{display:flex;gap:2px;flex:1;overflow-x:auto}
.tab{font-family:var(--mono);font-size:12.5px;padding:7px 12px;border-radius:6px;cursor:pointer;
  white-space:nowrap;color:var(--muted);border:1px solid transparent;background:none}
.tab.active{color:var(--bg);background:var(--accent);font-weight:600}
.module-bar{display:flex;gap:2px;align-items:center;padding:5px 18px;overflow-x:auto;
  background:linear-gradient(var(--accent-d),transparent 60%),var(--surface);
  border-top:2px solid var(--accent);border-bottom:1px solid var(--border)}
.view{padding:22px 26px}
h1{font-size:20px;margin:0 0 4px;font-weight:600}
.sub{color:var(--muted);font-size:12.5px}
.view-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;gap:12px;flex-wrap:wrap}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.spread{display:flex;justify-content:space-between;align-items:center;gap:10px}
button,.btn{font-family:var(--mono);font-size:12.5px;background:var(--raised);color:var(--text);
  border:1px solid var(--border);border-radius:6px;padding:7px 12px;cursor:pointer}
.btn-primary{background:var(--accent);color:var(--bg);border-color:var(--accent);font-weight:600}
.btn-sm{padding:4px 8px;font-size:11px}
input,select,textarea{font-family:var(--sans);font-size:13px;background:var(--bg);color:var(--text);
  border:1px solid var(--border);border-radius:6px;padding:7px 9px}
.tk-tag{font-family:var(--mono);font-size:10px;padding:3px 8px;border-radius:3px;display:inline-block}
.pill{font-family:var(--mono);font-size:10.5px;padding:2px 7px;border-radius:10px;
  border:1px solid var(--border);color:var(--muted)}
.prog-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin-bottom:24px}
.prog-box{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;text-align:center}
.prog-val{font-family:var(--mono);font-size:24px;font-weight:700}
.prog-label{font-family:var(--mono);font-size:9px;color:var(--dim);letter-spacing:1px;text-transform:uppercase;margin-top:4px}
.wl-label{font-family:var(--mono);font-size:10px;color:var(--dim);letter-spacing:1px;text-transform:uppercase}
.empty{color:var(--muted);text-align:center;padding:50px 20px;font-family:var(--mono);font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border)}
th{color:var(--muted);font-family:var(--mono);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
</style></head><body>
<header class="topbar">
  <div class="brand"><span style="color:var(--accent)">◆</span>
    <span>MAINFRAME<span class="brand-accent"> / SYNAPSE</span></span></div>
  <div class="row" style="gap:4px">
    <button class="mod-btn active">SYNAPSE</button><button class="mod-btn">PULSE</button>
    <button class="mod-btn">VISION</button><button class="mod-btn">VAULT</button>
  </div>
  <nav class="tabs">
    <button class="tab active">Snapshot</button><button class="tab">Tasks</button>
    <button class="tab">Calendar</button><button class="tab">Ideas</button>
  </nav>
</header>
<nav class="module-bar">
  <button class="tab">Repository</button><button class="tab">Workspace</button>
  <button class="tab">Planner</button><button class="tab">Knowledge Graph</button>
</nav>
<main class="view">
  <!-- ▼ design here ▼ -->
  <div class="view-head">
    <div><h1>Screen name</h1><div class="sub">One plain sentence saying what this screen is for.</div></div>
    <button class="btn-primary btn-sm">+ add thing</button>
  </div>
</main>
</body></html>
```

---

## 8. How to hand the design back

Return **one self-contained HTML file** using the skeleton above — no libraries, no
external assets, no build step. In it:

- Say which **tab** the screen belongs to and which **module** (so the accent is right).
- Reuse the existing class names (`.card`, `.prog-box`, `.tk-tag`, `.btn-sm`, `.row`,
  `.spread`, `.sub`, `.empty`) wherever the component already exists. Only invent a
  new class when the component genuinely does not exist yet, and prefix it with the
  view's name (`.repo-`, `.wl-`, `.prog-`, `.pulse-`), which is the convention.
- Use the tokens for every colour. If a design needs a colour that is not in the
  token list, say so explicitly and why.
- Note anything that needs new data from the backend, since that is a separate change.

That file can then be ported into the real view code directly: the markup maps
one-to-one onto the `el()` helper, and the CSS appends to `main.css`.

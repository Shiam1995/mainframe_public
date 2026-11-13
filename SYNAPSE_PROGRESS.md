# Synapse — Build Progress & Changelog

Living record of the upgrade defined in `~/Downloads/UPDATE_SPEC.md` ("Synapse Update Spec").
This upgrade is applied **in place** to the existing app at `~/mainframe-app` (the spec's assumed
`~/mainframe-synapse` was never a real path — most spec features already existed here).

Purpose of this file:
1. A human-readable changelog of what has actually changed.
2. Context you can paste into the **web version of Claude** (which can't see your local files) so it
   can ideate with accurate knowledge of the current state.

Last updated: 2026-07-24

---

## How to run

```
cd ~/mainframe-app && ./start.sh      # Neo4j (Docker) + Python venv + API on :8000
cd ~/mainframe-app && ./stop.sh       # stop everything
```
Open http://localhost:8000 · Neo4j browser http://localhost:7474 (neo4j / mainframe) · LLM = local Ollama `qwen2.5:7b-instruct`.
After any frontend change, **hard-refresh** the browser (`Ctrl+Shift+R`) — the JS is cached aggressively.

---

## Stack (unchanged by the upgrade)
- **Neo4j 5 Community** (Docker, bolt://localhost:7687) — all data.
- **FastAPI + uvicorn** (:8000) — serves API + frontend.
- **Vanilla HTML/CSS/JS** frontend, **zero JS libraries** (deliberate — kept vanilla per local-first preference).
- **Local LLM only** — Ollama, heuristic fallback. No cloud SDKs.

---

## Spec progress (9 items)

| # | Spec item | Status |
|---|-----------|--------|
| 1 | Rename Paper Metabolism → Synapse | ✅ **DONE** (this session) |
| 2 | Task system — complete redesign (journal/entries, horizons, nesting, time-tracking, List/Tree/Graph views, Progress tab) | ✅ **DONE** (built to TASKS_SPEC.md + synapse-tasks.html mockup) |
| 3 | Ideas sheet polish (kept vanilla — NOT using handsontable/jspreadsheet) | ⬜ mostly already built; polish pending |
| 4 | Terms familiarity 0–10 | ✅ already built (pre-session) |
| 5 | Triple KG (manual / auto / auto_edit) with edges & editing | ✅ already built; polish per spec pending |
| 6 | Deep dive — monthly focus | ✅ already built |
| 7 | Custom headers — extensible sections | ✅ already built |
| 8 | Activity log → richer `ChangeEvent` schema | ✅ **DONE** (this session) |
| 9 | CRT boot screen (phosphor green #33FF33 + Gojo blue #00BFFF/#2DE2FF) | ✅ **DONE** (this session) |

---

## Changelog

### 2026-07-23 — Increment #1: Rename → Synapse  ✅
**Backend**
- `config.py`: `app_name` → `"Synapse"`; data dir `~/.mainframe/papers/{originals,instances}` → `~/.mainframe/synapse/{originals,instances}` (exports stay Mainframe-level at `~/.mainframe/exports`).
- Loggers `papermetabolism.*` → `synapse.*` across `main/llm/pdf/db/activity.py`; docstrings retitled.
- Route prefixes: 9 paper-domain routers renamespaced to `/api/synapse/*` — `papers, instances, highlights, terms, kg, refs, deepdive, headers, ideas`.
- `tasks` and `log` **kept at `/api/*`** (Mainframe-level, not Synapse-specific).

**Frontend**
- `index.html`: title → "Synapse — Mainframe"; topbar → `MAINFRAME / SYNAPSE`.
- All JS fetch paths updated to `/api/synapse/*`.
- `css/main.css`: header comment renamed.

**Data migration (3 real papers)**
- PDFs moved on disk to `~/.mainframe/synapse/`.
- Absolute paths stored in Neo4j rewritten: `Paper.original_path` ×3 and `Instance.file_path` ×3 (verified 0 stale).

### 2026-07-23 — Increment #2: Task system redesign  ✅
Built from `~/Downloads/TASKS_SPEC.md` (authoritative) + `~/Downloads/synapse-tasks.html` (UI mockup).
**Backend**
- `models.py`: new `TaskCreate`/`TaskUpdate` (horizon, module, est_time, due_date, parent_id, priority, status, done) + `TaskEntryCreate` (journal entry: type, date, time_of_day, time_spent_mins, time_spent_label, notes, learned, next_step).
- `routes/tasks.py`: full rewrite. `GET /api/tasks` returns each task with its entry journal + `total_mins` + `subtask_count`. `POST` (optional initial_idea entry, `OWNED_BY` module, `CHILD_OF` parent). `PATCH` (done/hide/park/reparent). `DELETE ?cascade=` (reparent children or delete subtree). `POST /{id}/entries`, `DELETE /{id}/entries/{eid}`.
- `db.py`: `TaskEntry` id constraint + `task_status/horizon/module/parent` indexes.
- Neo4j model: `(:Task)-[:HAS_ENTRY]->(:TaskEntry)`, `(:Task)-[:CHILD_OF]->(:Task)`, `(:Task)-[:OWNED_BY]->(:Module)`.
**Frontend**
- `js/tasks.js`: full rewrite — List (indented nesting) / Tree / Graph (drag) views, filter chips, New-task/Add-entry/Add-subtask modals, expandable journal with total-time bar, entry type colors, hide/delete.
- `js/progress.js`: NEW — Progress tab (5 stat boxes + completed tasks with full entry history).
- `css/main.css`: `tk-` prefixed task-system styles + `--green`/`--dim`/`-d` palette vars.
- `js/ideas.js`: added ↑ promote-to-task button.
- `js/app.js`: added `progress` to nav ORDER; **default landing view → tasks** (was repo).
- `index.html`: load `progress.js`.
**Verified in-browser**: create task, initial-idea entry, subtask nesting, timed entry with accumulation (⏱ header + total-time bar), List/Tree/Graph render, Progress stats. Zero app console errors.

### 2026-07-23 — Nav: Tasks leads  ✅
- `frontend/js/app.js`: nav `ORDER` now starts with `tasks`; default `active` → `"tasks"`.
- Rationale: spec #2 makes Tasks a **Mainframe-level spine**, so it leads the UI rather than sitting among the paper module tabs.

### 2026-07-24 — Increment #8: Activity log → ChangeEvent  ✅
Upgraded the log from the flat `:LogEntry` schema to the spec's richer `:ChangeEvent`.
**Backend**
- `activity.py`: `record()` gains `module` (defaults from a `CATEGORY_MODULE` map), `trigger` (`manual`|`llm`|`system`, validated), and `entity_id`. Nodes now created with **both** labels `(:ChangeEvent:LogEntry)` so legacy reads keep working; store `timestamp` alongside `ts`. When `paper_id`/`entity_id` is present, draws `(:Entity)-[:HAS_CHANGE]->(:ChangeEvent)` via an unlabelled id match (DB is tiny). Still never raises.
- `db.py`: added `ce_module`/`ce_trigger` indexes + a new idempotent `_MIGRATIONS` pass (run after schema DDL) that backfills existing `:LogEntry` rows with the `:ChangeEvent` label + `module`/`trigger`/`timestamp`. **Migrated all 49 existing entries** on startup.
- `routes/log.py`: `GET /api/log` + `/by-day` now filter by `module` and `trigger` too; queries match on `:ChangeEvent`. New `GET /api/log/facets` returns value+count for each of category/module/trigger (drives the UI dropdowns).
- `routes/tasks.py`: create/update/entry calls now thread the task's real `module` + `entity_id` into `record()` (tasks are the one genuinely multi-module entity).
**Frontend**
- `js/log.js`: full rewrite of the view — three filter dropdowns (category/module/trigger) fed by `/facets`, per-row **module tag** (module-colored) and **trigger glyph** (✋ manual / ✦ llm / ⚙ system), combined query-string filtering.
- `css/main.css`: `.logentry` grid 3→5 cols; added `.lmod`/`.ltrig` styles.
**Verified**: migration backfilled 49/49 entries (all dual-labelled, module+trigger set); live `vitality`-module task create produced a `:ChangeEvent {module:'vitality', trigger:'manual'}` with a `HAS_CHANGE` edge from the Task; `?module=vitality` filter returns it; Log tab renders new dropdowns + module/trigger columns in-browser; zero app console errors.
**Deferred (spec #8 optional):** `(:ChangeEvent)-[:PART_OF]->(:Session)` grouping — not built; day-grouping already covers the UI need.

### 2026-07-24 — Increment #9: CRT boot screen  ✅
Phosphor-green + Gojo-ice-blue boot sequence that covers the app from first paint.
**Backend**
- `config.py`: added `boot_wallpapers` / `boot_sounds` paths (`~/.mainframe/synapse/{wallpapers,sounds}`).
- `routes/boot.py`: NEW — `GET /api/synapse/boot/config` returns live `stats` (papers / active tasks / terms / ChangeEvents / KG nodes), `checks` (neo4j + llm + module, each with label/path/ok), the first `wallpaper`/`sound` asset found (served URLs, else null), and `prefs` (skip/mute) read from a `boot:` section in settings.yaml. All lookups fail soft to zeros/null.
- `main.py`: registered `boot_router`; mkdir the two asset dirs at import time; mounted `/boot-assets/wallpapers` + `/boot-assets/sounds` StaticFiles **before** the catch-all `/` mount so they win.
**Frontend**
- `index.html`: `<div id="boot">` added right after `<body>` (covers app from first paint, no dashboard flash); loads `js/boot.js` last.
- `js/boot.js`: NEW — builds the scaffold and runs the sequence (logo fade-in → checks scroll in one-by-one with `[OK]`/`[--]` → green→blue loading bar → 5-tile stats reveal → `[ ENTER ]` pulse). Click-anywhere / Enter / Esc / Space dismisses (fade + remove). Optional wallpaper (as darkened bg layer) + looping sound with volume ramp + fade-out (autoplay-blocked → starts on first gesture); honours `prefs.skip` (instant dismiss) and `prefs.mute`. Falls back to a static config if the API is down.
- `css/main.css`: `--phosphor`/`--gojo`/`--gojo-bright` vars + full CRT block — scanline+vignette+flicker overlay, glowing logo with flicker, boot-log grid, gradient loading bar, stat tiles, pulsing ENTER, `prefers-reduced-motion` fallback, responsive stats grid.
**Verified in-browser**: full sequence renders (logo, all 3 checks `[OK]` with real paths, filled gradient bar, 5 stat tiles with live counts — 3/2/0/52/11, pulsing ENTER); DOM inspection confirmed the stat tiles + values; click/focus transitions cleanly to the dashboard and removes `#boot`; empty asset dirs return 404 (not 500); zero app console errors. **Note:** the browser screenshot tool's focus-click dismisses the armed boot — a real feature (click-to-enter), not a bug.

### 2026-07-24 — Progress tab made editable (user request)  ✅
The Progress tab was read-only (stats + completed history). Now you can edit priority and add notes on in-flight work.
**Frontend only** (backend already supported both — `priority` was a stored-but-unsurfaced `TaskUpdate` field; notes = `POST /api/tasks/{id}/entries`).
- `js/progress.js`: full rewrite. Added an **ACTIVE TASKS — editable** section (amber accent) above the **COMPLETED** history. Every card is an expandable row (▸/▾, expand state kept across re-draws via a module-level `open` Set) showing horizon/module tags, entry count, time, overdue flag. Each card has an inline **priority `<select>`** (low/med/high, saves instantly via `PATCH`, recolors) and a **"+ note"** popover (type = note/reflection/progress/blocker + textarea → `POST` entry, re-draws in place). Both sections sorted high→medium→low.
- `css/main.css`: `.prog-card.active` (amber border) + `.prog-row`/`.prog-row-edit`/`.prio-sel`(prio-low/medium/high colors)/`.prog-note-form` styles.
**Verified in-browser**: priority change on "Sample task" persisted server-side (`priority:'high'`, selector went red) and re-sorted to top; "+ note" added a reflection entry (2→3 entries, correct type/text) and the card auto-expanded to show it; test data then reverted/deleted. Also hardened `boot.js` with `isConnected` guards so the boot sequence bails cleanly if the element is removed mid-animation (surfaced during testing).

### 2026-07-24 — Workspace upgrades (user request, 4-part). Part 1: Dictionary-in-Workspace + optional terms  ✅
While reading a paper the user wants to check/add dictionary words and flag terms as "review later".
**Backend**
- `models.py`: `TermCreate`/`TermUpdate` gained `optional: bool` (review-later flag on `:Concept`).
- `routes/terms.py`: create stores `c.optional`; PATCH already updates it (via `optional` in TermUpdate).
- `routes/dictionary.py`: NEW `GET /api/synapse/dictionary/lookup?name=` — exact case-insensitive existence check → `{exists, term}`.
- `api.js`: added `dictionary.lookup(name)`.
**Frontend (`workspace.js`)**
- NEW **dictWidget** card ("Dictionary — check / add a word"): type any word → `check` → shows its definition if in the Dictionary, else offers "+ add to Dictionary" with an **optional** definition field. Covers both "check if it exists" and "any word → entry".
- Terms section: add-form now has a **definition (optional)** input + an **opt** checkbox; a "hide optional / review-later" filter; each term row shows its definition, an **☆/★ opt** toggle (PATCHes `optional`, amber when on) + an "optional" tag.
- `css`: `.btn-sm.opt-on` amber active state.
**Verified in-browser**: dict check on an unknown word offered add; optional toggle flipped ☆→★, showed the tag, persisted server-side; add-term-with-definition+optional, PATCH toggle, and delete all confirmed via API; test data reverted; zero console errors.
### 2026-07-24 — Workspace upgrades Part 2: reading-session logging  ✅
- `models.py`: `InstanceCreate`/`InstanceUpdate` gained `read_date`, `time_spent` (freeform), `notes`.
- `routes/instances.py`: create stores them; PATCH updates them.
- `workspace.js`: the Reading-instances card now shows a **Session log** panel for the active instance — editable purpose / read-date / time-spent + a notes textarea → PATCH. Verified: PATCH persisted, panel prefilled from server, test data removed.

### 2026-07-24 — Workspace upgrades Part 3: references scan → name + link  ✅
"Scan a paper, store each reference's name + link, citation-map ready."
- `llm.py`: `_REFS_SYS` prompt now asks for a `link`; added `_URL_RE` + `_extract_link` (URL, else DOI→doi.org) wired into the heuristic parser.
- `models.py`: `ReferenceCreate {title, link, year}`. `db.py`: `reference_id` constraint.
- `routes/refs.py`: NEW stored-references API — `POST /scan` (extract section → parse → store `(:Paper)-[:REFERENCES]->(:Reference {title,link,year,matched_paper_id})`, MERGE-dedup on (paper,title), draws `CITES` edge when a ref matches a repo paper), `GET /stored`, `POST /stored` (manual add), `DELETE /stored/{id}`. `_normalize_link` makes DOIs/bare domains clickable.
- `workspace.js`: NEW full-width **References** card — ✦ scan button, manual add (title+link), list sorted by year with clickable links / "no link" + delete.
- Verified: real PDF scan stored **35 references** (names + links), sorted by year, 22 clickable; manual add + delete confirmed; fabricated test ref removed (35 real ones kept).

### 2026-07-24 — Workspace upgrades Part 4: global Mind-Dump inbox  ✅
- `models.py`: `MindDumpCreate`/`Update` (text, kind idea|look-at|note, status, link, paper_id). `db.py`: `minddump_id` constraint. `activity.py`: added `mind` category.
- NEW `routes/mind.py` — **Mainframe-level `/api/mind`** (list w/ status+kind filters, create resolving paper_title + `(:MindDump)-[:ABOUT]->(:Paper)`, PATCH status/text, delete). Registered in `main.py`.
- NEW `js/mind.js` — **Mind Dump** view (nav tab, inserted after Progress in app.js ORDER; loaded in index.html): quick-capture (text·kind·link·paper), open/done + kind filters, checkable items with kind tag, clickable paper link (→ selectPaper) + external link.
- `workspace.js`: NEW **🧠 Mind dump** widget in the left column — stick a thought linked to the current paper. (Fixed a bug where its textarea wasn't appended.)
- Verified in-browser: tab renders, captures via both the Mind view and the Workspace widget (paper link resolved), done-toggle + delete work, all test items cleaned up; zero console errors across all four parts.

### 2026-07-24 — Reference Map: scalable citation graph (user request)  ✅
A new global graph view of papers ↔ their references, built to scale to thousands. Design decisions (with user): edges = ref↔paper only (no dedup/bridging — papers are hubs, references leaves); add refs = structured fields (already built); renderer = **vanilla canvas, zero deps**.
**Backend**
- `models.py`: `RefNodeCreate {label,type}`, `RefEdgeCreate {source_id,target_id,label}`. `db.py`: `refnode_id` constraint.
- NEW `routes/refgraph.py` (`/api/synapse/refgraph`): `GET ""` assembles one payload — nodes (papers/references/manual `:RefNode`) + edges (`[:REFERENCES]`, `[:CITES]`, manual `[:REF_LINK]` matched generically by node `id`). `POST/DELETE /nodes` (manual `:RefNode`), `POST/DELETE /edges` (manual `[:REF_LINK]` between any two nodes). Registered in `main.py`. Reuses existing scan + structured-add from `routes/refs.py`.
**Frontend**
- NEW **Reference Map** nav tab (`js/refgraph.js`, added to app.js ORDER after `refs`, loaded in index.html). Hand-rolled canvas force-graph: zoom (wheel), pan, drag-node, click→detail panel (title/link/source-paper/＋link), hover-highlight neighbors, LOD labels (papers always; refs when zoomed/hovered), type/source/search filters, fit + re-run + ＋node.
- **Layout engine**: started as Barnes-Hut but rewrote to **grid (spatial-hash) repulsion** — O(n), no recursion, per-node interaction cap (48), hard iteration cap (180), and **per-frame time-slicing (9ms budget)** so the main thread never blocks. NaN guards; window-listener teardown on view switch; deterministic seeded RNG.
- `css`: `.rg-*` (toolbar, stage, canvas, detail panel).
- `index.html`: cache-busted the script (`refgraph.js?v=2`) — the browser was executing a stale cached copy.
**Verified**: backend payload + manual node/edge CRUD via curl; graph renders as clean per-paper star clusters at real scale (39 nodes) AND at a **1,039-node scale test** (injected 1000 dummy refs, then deleted); click→detail panel confirmed via simulated click; zero console errors. **Perf**: synchronous benchmark = **0.96ms/tick, full 180-tick layout in 173ms at 1,039 nodes** — fully interactive. (Note: in-browser rAF is throttled in the backgrounded automation tab, so timing had to be measured synchronously; a real foreground tab runs at 60fps.)

### 2026-07-24 — Activity timeline + Gantt view (user request)  ✅
"Timeline should show when I complete tasks + let me edit; and a Gantt of how long things took, overlapping."
**Backend** (make timing editable)
- `models.py`: `TaskUpdate.done_at` (editable completion timestamp); new `TaskEntryUpdate` (edit an entry's date/notes/mins/…).
- `routes/tasks.py`: `update_task` now honours an explicit `done_at`; NEW `PATCH /api/tasks/{id}/entries/{eid}` to edit a journal entry. (Verified: complete → edit done_at, add entry → edit its date/mins.)
**Frontend** (two new tabs, added to app.js ORDER after `progress`, loaded in index.html)
- `js/activity.js` — **Activity** tab: merges task completions (`done_at`) + journal entries (`date`) + all non-task log events into one chronological, day-grouped feed. Completions show a **date editor** (→ PATCH `done_at`) + **reopen**; entries show a date editor (→ PATCH entry date); log events read-only (dashed). User chose "completions + all activity".
- `js/gantt.js` — **Gantt** tab: one bar per task on a calendar axis, **calendar span** = earliest(entry dates, created_at) → `done_at` (or now if ongoing). Bars on separate rows overlap in time = parallel work; color by status (done=teal/active=amber/parked=dim); label = logged time + done; 7-tick date axis; hover tooltip with dates/span/effort. Uses `Date.now()`/`new Date()` (browser-side; fine).
- `css`: `.act-*` (timeline rows) + `.gantt-*` (axis, track with day gridlines, positioned bars).
**Verified in-browser** with 3 backdated test tasks (2 done + 1 ongoing, overlapping spans): Activity renders day-grouped with editable completions (rescheduled ZZ Gamma Jul 21→23, persisted); Gantt draws overlapping bars (Alpha 16–20, Beta 17–ongoing, Gamma 19–23) with correct spans/labels. Test data deleted; zero console errors.

### 2026-07-24 — Removed the Reference Matrix tab (user request)  ✅
Redundant now that the Reference Map exists. Frontend-only removal: dropped `"refs"` from `app.js` ORDER and the `js/refs.js` script tag in `index.html`. **Backend `routes/refs.py` kept intact** — its `/refs/stored` + `/refs/scan` power the Workspace References panel + Reference Map, and `GET /api/synapse/refs` (matrix payload) is still read by `timeline.js` for the Publication Timeline's cites/cited-by counts. `js/refs.js` left on disk, just unloaded. Verified: References tab gone, Reference Map + Publication Timeline still render, zero console errors.

### 2026-07-24 — Projects + contribution grid, Deep Dive redesign, remove Lit Review (user request)  ✅
**Removed Literature Review** — it was a user-created `:CustomHeader` (global), deleted via the API. Not code.
**Project area** (Mainframe-level `/api/projects`)
- `models.py`: `ProjectCreate/Update`, `ProjectLinkCreate`, `HeatCellUpdate`. `config.py`: `projects_dir = ~/.mainframe/projects`. `db.py`: `project_id`/`projectfile_id`/`heatcell_date`/`ddsource_id` constraints. `activity.py`: `project` category (its events feed the grid).
- NEW `routes/projects.py`: projects CRUD + `POST /{id}/files` (multipart upload → copy to disk, record size, reuse papers.py pattern), `POST /{id}/links` (register url/path + note; stat size if local), `DELETE /{id}/files/{fid}`, `GET …/download` (FileResponse). Every mutation records a `project` ChangeEvent.
- NEW `js/projects.js` **Project** tab (app.js ORDER after `mind`): a project = editable note + file list (⬆ uploads w/ size+download, 🔗 links w/ url/path+note), upload input + add-link form.
**Contribution grid** (GitHub-style, light-blue)
- NEW `routes/heatmap.py` `/api/activity/heatmap`: per-day counts from `:ChangeEvent` + `:HeatCell` colour overrides; `POST /cell` upsert/clear.
- Component at top of the Project view: 53×7 squares, 5-step light-blue ramp by count (bright `#2de2ff` = most), month labels + legend. **All activity lights a day**; click a square → native colour picker → save override; right-click → reset. Verified: today's cell bright, manual override renders (pink test) + persists.
**Deep Dive redesign** (topic-first) — dropped monthly/paper scheduling.
- `routes/deepdive.py` rewritten: `:DeepDive {topic, info, sources_text}` + `(:DeepDive)-[:HAS_SOURCE]->(:DeepDiveSource {title,link})`. `db.py` migration carries old `theme/month`→`topic`, `notes`→`info` (existing "Sample topic" dive survived). Endpoints: create(topic)/patch(topic,info,sources_text)/delete + add/del source.
- `js/deepdive.js` rewritten: editable topic + info textarea + **sources table** (title|link rows, +row/×) + **free-text** sources box.
- `css`: `.heat-*` (grid), `.proj-file`, `.dd-sources` (table).
**Verified in-browser**: Project tab (grid + create project + link + recolour), Deep Dive (topic/info/sources table+text), Lit Review gone; backend curl (upload size, link, heatmap override, deepdive migration+sources). Test data cleaned; zero console errors.

### 2026-07-24 — Mainframe module framework + Pulse module (new, in progress)
Growing the app from "Synapse" into a multi-module Mainframe (~6 self-contained modules that share one graph + activity log and can cross-link). First new module: **Pulse** (habits/routines/medical/meds, warm pink #F4709C) per `~/Downloads/PULSE_SPEC.md`.
**Phase 0 — module seam  ✅ (browser-verified)**
- NEW `frontend/js/modules.js` = the **master manifest**: `window.MODULES` (synapse/pulse: key, label, accent, topbar, tabs) + `window.SHARED_TABS` (tasks/progress/activity/gantt/mind/project/log — visible in every module). Add a module = one entry + its tab files.
- `app.js`: nav = SHARED_TABS + active module's tabs; a topbar **Synapse⇄Pulse switcher** (`setModule`, persisted in localStorage) swaps `data-module`, theme, brand text; custom headers are Synapse-only.
- `css`: `--accent`/`--accent-d` var drives the chrome (brand/active-tab/dot/btn-primary), overridden to pink under `:root[data-module="pulse"]`; `.module-switch`/`.mod-btn`. `index.html`: `#module-switch` + brand JS-driven + loads modules.js first + the 6 Pulse scripts (`?v=1`).
- Verified: switcher flips teal⇄pink, brand + nav swap, shared tabs persist in both, Synapse untouched, zero console errors. Pulse tabs render "under construction" stubs for now.
**Phase 1 — Pulse backend  ✅ (curl-verified)**
- `config.py`: `pulse_dir`, `pulse_medical_dir`. `activity.py`: categories habit/experiment/routine/medical/medication → module="pulse". `db.py`: 11 Pulse constraints + 3 indexes. `models.py`: all Pulse models (Habit/Sub/Note/Log, Experiment, Routine/Step/StepLog/Note, MedicalEntry, MedEntry).
- NEW `routes/pulse.py` (`/api/pulse/*`): full CRUD per spec — habits (+subs/notes/logs, one HabitLog per day upsert), experiments (days_done list), routines (+steps/step-logs/notes), medical (11 config sections + PDF/JPG/PNG upload + file serve), meds (9 config sections). All nodes `-[:OWNED_BY]->(:Module{name:"pulse"})`; every mutation `activity.record(...)` → shared log.
- Verified: create/nest/log across all 5 areas; **11 pulse events landed in the shared `/api/log?module=pulse`** (cross-module integration proven). Test data cleaned.
**Phase 2 — Habits + Active Tracking  ✅ (browser-verified)**
- `js/pulse-common.js` (shared: category/level config, `streak()`, `modal()`, date utils, section+colour config). `js/habits.js`: expandable pink habit cards, sub-habits, notes timeline, tags, 🔥 streak. `js/tracking.js`: 120-day pink heatmap (16px cells, 4 levels), Day-Log modal (cumulative level buttons 1-4, time, what-happened, **feel**, **connections**), legend + streak header. `css`: `.pulse-*`/`.pheat-*`/`.plevel-btn`.
- Verified: 5-day streak calc, graded heatmap, Day-Log modal all fields + cumulative fill.
**Phase 3 — Experiments + Routines  ✅ (browser-verified)**
- `js/experiments.js`: amber (active)/green (done) cards, amber→pink progress bar, hypothesis, clickable day-dots (toggle), Complete→conclusion. `js/routines.js`: pink expandable cards, steps w/ inline last-5 logs + fast **3-field quick-log** (date/time/note), add-step/note.
- Verified: 4/14 dots + 29% bar; routine step + inline log + quick-log modal.
**Phase 4 — Medical + Medications  ✅ (browser-verified)**
- `js/medical.js`: 11 config-driven accordion sections; entries w/ severity colour tags, purple NOTES, links, tag chips, **PDF/JPG/PNG upload** (images inline / PDFs as links). `js/medications.js`: 9 sections; name + dose·frequency (pink) + status colour tag. `css`: `.acc-*`/`.med-entry`.
- Verified: 11 + 9 sections, severity/status tags, dose·freq line. All Pulse test data cleaned; zero console errors.
**PULSE MODULE COMPLETE** — all 6 tabs live per spec, sharing the Mainframe graph + activity log.

### 2026-07-24 — Pulse Fitness sub-module  ✅ (browser-verified, `~/Downloads/FITNESS_SPEC.md`)
Fitness added as a **sub-module inside Pulse**: one Pulse tab "Fitness" that renders its own
**secondary sub-tab bar** (7 sub-views registering into a `window.FIT_TABS` registry — the module
pattern one level deeper). All owned by `(:Module{pulse})`, writes to the shared log.
- **Backend** `routes/fitness.py` (`/api/pulse/fitness/*`): dashboard (aggregate), cycles
  (+week toggles, `current_week=ceil` calc), workouts (+`:Exercise`, search by type/exercise/notes),
  goals, body (per-region `:BodyState` upsert + `:BodyStateLog` history + notes), activity (dynamic
  metric fields + `:FitnessConfig` tracked-list), stretching. `models.py`/`db.py` (8 constraints +
  2 indexes)/`config.py` (`pulse_fitness_dir`, videos dir reserved)/`activity.py` (`fitness` cat).
- **Frontend**: `js/fitness.js` (sub-tab shell) + `fitness-{dashboard,program,workouts,body,activity,
  stretch,history}.js`. Dashboard cockpit (cycle banner pink→teal bar, 5 stats, goals, recent);
  Program week-grid (current bold-pink / done pink-dim / click toggles); Workouts (ONE exercises
  textarea parsed on `/`, colour-coded intensity green/amber/red, ⚠ interrupted, expandable, shared
  `window.FIT.workoutCard`); Body Map (hand-rolled stick-figure SVG, 19 clickable regions cycling
  clear→pain→imbalance→tight, legend, notes); Activity (metric toggles + dynamic log form); Stretching
  (purple cards, one-per-line); History (debounced search reusing workoutCard). `modules.js`: `fitness`
  added to Pulse tabs. `css`: `.fit-*`, `.week-sq`, `.intensity-*`, `.bodymap`. 8 scripts loaded `?v=`.
- Verified per phase (dashboard aggregate, week toggle, exercise parse + intensity colour + interrupted,
  history search, body-region cycling, activity toggles, stretch); a fitness action lands in the shared
  log (8 events). Test data cleaned; zero console errors. **FITNESS COMPLETE — all 7 sub-tabs.**

### 2026-07-24 — Two-tier navigation (user request)  ✅
Split the single mixed top bar into two tiers so module tabs are clearly separated from the shared Mainframe tabs. `app.js`: `renderTabs()` now paints `sharedViews()` (SHARED_TABS) into the top `#tabs` and `moduleViews()` (active module's tabs + Synapse custom headers) into a NEW `#module-tabs` bar. `index.html`: added `<nav id="module-tabs" class="module-bar">` under the topbar. `css`: `.module-bar` is sticky (`top:52px`), accent-tinted (`--accent-d` gradient + 2px `--accent` top stripe → teal for Synapse, pink for Pulse). **Fitness sub-tabs stay inside the page** (not a 3rd chrome bar), so max two toolbars. Verified: top bar = 7 shared tabs (both modules), module bar swaps 9 Synapse ↔ 7 Pulse tabs with the accent colour; zero console errors.

### 2026-07-24 — Pulse Benchmark tab (user request + `~/Downloads/BENCHMARKS_SPEC.md`)  ✅
Added as the **FIRST Pulse tab** (user override of the spec's "inside Fitness"): a **baseline** front + expandable periodic-assessment system.
- **Backend** `routes/benchmarks.py` (`/api/pulse/benchmarks`): `:Baseline` singleton (age/height/weight/body_fat/resting_hr/goals); `:BenchmarkMetric` catalogue (28 seeded: 10 fitness + 18 blood, each icon/unit/`higher_is_better`/category/tracked; +custom); `:Assessment`-`[:HAS_VALUE]`->`:MetricValue`; `/compare` (all assessments+metrics, client computes deltas); `/trend/{key}`; `/schedule/info` (next_due = last + frequency via `_add_months`, status overdue/due-soon/ok); `/{id}/import-blood` (links latest Medical blood entry). models/db (3 constraints+index). Events → shared log (`fitness` cat).
- **Frontend** `js/benchmarks.js` (`Views.benchmark`, **first** in Pulse `modules.js` tabs): baseline card (editable, auto-save) + goals; **"▾ show full snapshot"** reveals schedule banner (colour by status + freq dropdown + ＋Log Assessment), **comparison table** (columns=assessments, rows=tracked metrics, cell=value + **direction-aware coloured delta** — green=improvement incl. lower-is-better ↓, red=decline), metric-config toggles (fitness pink/blood red/custom grey +add). Log modal shows only tracked metrics grouped, **pre-filled from latest**. `css`: `.bl-grid`/`.bm-table`/`.bm-delta`.
- Verified: first-tab placement; baseline save; schedule "next due 2026-10-15 in 83 days" (matches spec example); comparison deltas incl. cholesterol ↓=green; log modal 6 tracked inputs, 5 pre-filled. Test data cleaned (28-metric catalogue kept); zero console errors.

### 2026-07-24 — Fitness "Day Review" sub-tab (user request)  ✅
Per-day view: muscle-group focus + log body-map key points for a specific day.
- **Backend** `routes/fitness.py`: `MUSCLE_MAP` (workout type → muscle groups); `GET /day-review?date=` (that day's workouts + derived muscle groups + per-day body points + note); `PUT /day-body/{region}` (MERGE `:BodyDayState {region,date}`); `PUT /day-note` (`:BodyDayNote {date}`). `models.py`: `BodyDayUpdate`, `BodyDayNoteUpdate`.
- **Frontend**: refactored `fitness-body.js` to expose a shared `window.FIT.buildBodySvg(points, onRegionClick, highlight)` + `bodyLegend()`. NEW `js/fitness-dayreview.js` (`Day Review` sub-tab, loaded after Workouts → sits 4th): date navigator (prev/next/today + picker), muscle-focus chips, the shared stick-figure with **worked muscles highlighted pink** (`MUSCLE_REGIONS` map) AND clickable to log per-day pain/imbalance/tight, workout summary, day note. `css`: `.bodymap circle.worked`.
- Verified: Push+Legs → 7 muscle chips + 11 highlighted regions; per-day body point (lower_back tight + head pain) persists by date; day note saves; empty days blank. Test data cleaned; zero console errors. (Existing "Body Map" tab kept as the current/overall snapshot.)

### 2026-07-24 — Pulse Nutrition (new top-level Pulse tab, user request)  ✅
Full nutrition area: macros/micros, food diary with a local food DB, targets, weekly gaps, intolerances, supplements.
- **Backend** `routes/nutrition.py` (`/api/pulse/nutrition`): **`:Food` catalogue seeded with 76 common foods** (per-100g macros + micros for a dozen; `custom` add/edit/del; `GET /foods?q=` search). `:FoodLog` diary (`POST /diary` scales macros+micros by grams and **snapshots** them so history is stable; `[:OF_FOOD]` link; `GET /diary?date=` → entries + daily totals + targets; delete). `:NutritionTarget` singleton (`GET/PUT /targets`). `GET /weekly?start=` → 7 days each with totals + `logged` flag (**gap**). `:Intolerance` + `:Supplement` lists. models/db (4 constraints + index), `activity` cat `nutrition`. All `_own()` pulse, shared log.
- **Frontend**: `js/nutrition.js` (sub-shell + `NUT_TABS`) added FIRST-after-fitness in Pulse `modules.js` tabs; sub-views `nutrition-{diary,weekly,foods,intolerances,supplements}.js`. Diary: date nav + **food search→autofill→log** (grams/meal/quality) + **daily totals with target progress bars** (Cal/Protein/Carbs/Fat/Sugar/Fibre/Salt) + **"▾ micronutrients"** hidden (Vit A/C/D/B12, Folate, Iron, Calcium, Magnesium, Zinc, Potassium) + set-targets modal + meal-grouped diary. Weekly: 7-day strip, **gap flags** for un-logged days + count. Food DB: search + add custom. Intolerances (severity colours) + Supplements (dose·timing) lists. `css`: `.nut-*`.
- Verified: 76 foods seeded, search "chicken", **150g → 247.5 kcal / 46.5 P (exact scaling)**, micros aggregate (spinach → vit C 28, iron 2.7), target bars, weekly 6-gap flagging, all 5 sub-tabs render, `nutrition` events in shared log. Test data cleaned (76-food catalogue kept); zero console errors.

### 2026-07-24 — Biomarkers → Benchmark blood work (user request)  ✅
User's biomarker list already mapped to the Benchmark's blood-work metrics; made them first-class.
- `routes/benchmarks.py` `DEFAULT_METRICS`: split **Ferritin** out from Iron ("Iron (serum)"), added **Kidney — eGFR** and **Liver — AST**, renamed Creatinine→"Kidney — Creatinine", ALT→"Liver — ALT", Glucose→"Blood Glucose (fasting)"; set **tracked=true** for the 13 biomarkers (glucose, hba1c, crp, ferritin, iron, vitamin_d, vitamin_b12, cholesterol, triglycerides, creatinine, egfr, alt, ast) — correct `higher_is_better` per marker.
- Catalogue is seed-once, so cleared the old 28-metric `:BenchmarkMetric` set (no assessments existed) → re-seeded 31 metrics. Verified in-browser: all requested biomarkers show as green tracked toggles in Benchmark → Metrics tracked, and as fields in the Log-Assessment blood group; zero console errors. Once an assessment is logged they populate the comparison table with direction-aware deltas.

### 2026-07-24 — Recovery (new top-level Pulse tab)  ✅
Log recovery/mindfulness practices — meditation, breathing, forest bathing, +.
- **Placement:** top-level Pulse tab (user chose this over a Fitness sub-tab), slotted after `nutrition`. `modules.js` Pulse tabs updated.
- **Backend** `routes/recovery.py` (`/api/pulse/recovery`, owned by `:Module{pulse}`, shared log category `recovery`):
  - `(:RecoveryType {id,name,icon,ord,custom})` — **config list** seeded once with 8 (meditation/breathing/forest/sauna/cold/nap/yoga-nidra/nature-walk); add custom / remove (past sessions keep their snapshotted type name).
  - `(:RecoverySession {id,date,type_id,type_name,type_icon,duration,feel,notes,created_at})-[:OF_TYPE]->(:RecoveryType)`.
  - `GET/POST/DELETE /types`, `GET/POST/DELETE /sessions`, `GET /stats` (this-week sessions+minutes, day streak, per-type breakdown, all-time totals).
  - `models.py` (RecoveryTypeCreate, RecoverySessionCreate), `db.py` (rectype_id, recsession_id + recsession_date index), `activity.py` (`recovery`→pulse), `main.py` (router), `api.js` (`api.pulse.recovery.*`).
- **Frontend** `js/recovery.js` — single view: stats strip + per-type chips, "＋ log session" modal (type/date/minutes/feel/note), "⚙ types" manager, recent-sessions cards (expandable note, delete). Header points loose thoughts at the shared **Mind Dump** (the universal brain-dump); the per-session note is local context.
- **Notes decision:** universal Mainframe Mind Dump stays the one shared brain-dump; areas keep their own contextual notes (Recovery = per-session note). Not per-area brain-dumps.
- Verified: types seed (8), session log via UI api → stats (week=1, streak=1, by_type breakdown) → list → delete round-trip; `recovery` event in shared `/api/log?module=pulse`; modal shows all 8 typed options; zero app console errors. Test data cleaned.

### 2026-07-24 — Benchmark: Snapshots + Trends + baseline history (user request)  ✅
User: "no history … a way to have snapshots of all the data and trends … save current baseline … date snapped + date of next snap." The assessment engine existed but was buried under a "show full snapshot" expander and never froze the baseline. Restructured Benchmark into a **sub-tabbed area** (like Fitness/Nutrition): **Baseline · Snapshots · Trends**.
- **`benchmarks.js` → shell** rendering `window.BENCH_TABS` (mirror of FIT_TABS/NUT_TABS); three sub-views:
  - `benchmark-baseline.js` — editable baseline card (autosave) + next-snapshot-due banner (cadence selector) + one-click **📸 Save snapshot** (freezes current baseline at today's date). Defines shared `window.BENCH` helpers (scheduleBanner, BASELINE_FIELDS).
  - `benchmark-snapshots.js` — schedule banner + **＋ Log snapshot** modal (baseline fields pre-filled+editable + metric/blood values) + comparison table with a **Baseline section** (age/height/weight/body-fat/resting-HR) above the metric sections, coloured deltas; saved-snapshot history cards (date · label · **next-due tag**, expandable to all frozen data, delete); metrics-tracked config.
  - `benchmark-trends.js` — **vanilla inline-SVG sparklines** (no libs) per baseline numeric + tracked metric, latest value + change-since-first coloured by improvement direction; single-point series show a dot.
- **Backend `routes/benchmarks.py`:** every snapshot now **freezes the baseline** (`bl_age/height/weight/body_fat/resting_hr/goals`) + stores a per-snapshot **`next_due`** (from schedule freq + snap date). New `POST /snapshot` (quick, captures current baseline), `GET /trends` (series across snapshots; baseline strings like "75kg" parsed via `_parse_num`). `AssessmentCreate.baseline` optional override + `SnapshotQuick` model; `api.js` `quickSnapshot`/`trends`; `.bm-section` CSS.
- Verified (curl + in-browser api/DOM): quick snapshot freezes baseline + computes next_due; full snapshot overrides baseline + captures vo2max/glucose; comparison table shows Baseline+Fitness+Blood sections across 2 snapshot columns with deltas; next-due tags; 3 sparkline polylines (2+pt series) + single-point dots; all round-trips + deletes clean. **Restored the user's real baseline** after curl testing overwrote it (age 34/height 180/weight 76.5/body-fat 19.4, resting-HR+goals empty). Zero app console errors; 0 stray snapshots.

### 2026-07-24 — Baseline biomarkers/notes + Habit Trends (user request)  ✅
Two asks: (1) add blood-work/biomarker results + notes to the baseline; (2) a separate Trends view over all habits.
- **Baseline biomarkers + notes** (`benchmark-baseline.js`, `routes/benchmarks.py`, `models.py`):
  - `BaselineUpdate` now `extra="allow"` + a `notes` field — the baseline carries current metric readings as **`mv_<metric_key>`** props (e.g. `mv_glucose`) alongside anthropometrics.
  - Baseline tab gained a **Notes** textarea and a **"Current readings"** card: number inputs for every tracked blood + fitness metric (pre-filled from `mv_*`, autosave), plus **＋ add biomarker** (creates a tracked blood metric — `add_custom_metric` now honours `category`, keys `bio_*`, 🩸 icon).
  - `_do_snapshot` freezes **`bl_notes`** and, when no explicit values are given (quick snapshot), **derives snapshot MetricValues from the baseline's `mv_*`** — so current biomarker readings flow into the timeline + trends. Snapshot history card shows frozen notes.
- **Habit Trends** — Habits is now a **sub-shell** (`habits.js` renders `window.HABIT_TABS`): **My Habits** (existing cards → `habits-list.js`) + **Trends** (`habits-trends.js`). New backend `GET /api/pulse/habits/trends` (per-habit: weekly done-count series over 12 weeks, current + longest streak, 30/90-day rates; `api.js` `habitTrends`). Trends view = summary strip + per-habit **vanilla-SVG weekly bars** + streak/rate stats.
- Verified (curl + in-browser): baseline stores notes + mv_ readings; custom biomarker → blood/🩸/tracked; quick snapshot freezes bl_notes + glucose/hba1c/vitamin_d values; Habits shows My Habits · Trends with 24 weekly bars (2 habits × 12wk) + streak stats; Baseline shows Notes + 13 blood + 4 fitness inputs + add-biomarker. Fixed a Cypher aggregation/ORDER BY error in habit_trends (WITH before RETURN). **Cleaned all test data** (deleted test snapshot + `bio_*` metric, scrubbed leftover `mv_*`/`notes` off the real baseline — age 34/weight 76.5 intact). Zero app console errors.

### 2026-07-27 — Expandable + reorderable cards: Mind Dump & Ideas (user request)  ✅
Ask: "something in mind dump and idea where i can expand it, and the ability to move the cards up and down."
- **Manual ordering (shared mechanism):** both `:MindDump` and `:Idea` carry a `position` float; list endpoints order by `coalesce(position, 1e15) ASC, created_at DESC`. Two new `db.py` migrations backfill `position` on existing nodes from their old newest-first order, so nothing jumps on first use. New rows/captures land at the **top** (`min(position) - 1`).
- **`POST /api/mind/reorder` + `POST /api/synapse/ideas/reorder`** (`{ids: [...]}`, `ReorderRequest`): the listed ids take the positions *those same nodes* already occupy, reassigned in the order given. Two ids = a swap; the whole list = a full reorder. Untouched nodes keep their slots, so **reordering inside a filtered view is safe**. Shared helper `reorder_nodes(label, ids)` lives in `routes/mind.py`; ideas imports it. 400 on <2/duplicate ids, 404 if any id is missing.
- **Mind Dump (`mind.js`)** — cards now expand (caret ▸/▾ or click the card) into a full editor: `text` textarea, a new **`detail`** field (longer body, `MindDumpCreate/Update`), and kind/link/paper selects. Each field autosaves on blur via PATCH and patches the local object — **no reload, so focus and expansion survive editing**. Collapsed cards clamp the capture to 2 lines (`.md-clamp`) and show a `❐ detail` badge when there's a body. ▲▼ per card; expansion state (`open` Set) is keyed by id so it follows a card as it moves. `update_dump` now uses `exclude_unset` (fields can be cleared) and **re-points the `:ABOUT` edge + `paper_title`** when the paper changes.
- **Ideas (`ideas.js`)** — new leading `≡` column with caret + ▲▼. Expanding a row inserts a full-width `<tr>` detail panel: wide title, **textareas** for description/notes, then a responsive grid of every remaining column (incl. custom ones). Cell and panel editors for the same field are registered together and **sync live** (`register`/`syncEditors`), so edits in the panel update the collapsed row instantly. Column headers now cycle **asc → desc → manual order**, plus a `≡ manual order` toolbar button; ▲▼ are disabled while a column sort is active (a sorted view has no manual "next row"). `position` added to `_RESERVED` + frontend `HIDDEN` so a custom column can't clobber it.
- CSS: `.ord-col`/`.ord-btn`, `.md-clamp`, `.md-body`/`.idea-detail`, `.md-field`, `.md-grid`. `mind.js`, `ideas.js`, `main.css` bumped to `?v=2` in index.html.
- Verified (API + in-browser): backfill gave existing rows positions 0..n; create lands at top; swap persists and is filter-safe; error cases 400/400/404; expand → type detail → blur → persisted; `❐ detail` badge; ▼ moves a card and its open panel with it; sort disables ▲▼ and the 3rd header click restores manual order; panel→cell live sync. **All test data deleted; user's items left in their original relative order.** Note: the Ideas × button uses `window.confirm`, which freezes the tab under Chrome automation — delete via API when testing.

### 2026-07-27 — Pulse · Active Tracking: labelled month/week views + reports (user request)  ✅
Ask: "month by month with a clear gap between months vertically, a week by week view with a clear gap horizontally, the ability to toggle through, and the ability to create reports from the info — so I need it labelled."
- **One labelled data source** — new `GET /api/pulse/tracking/report?period=month|week&periods=N&end=&habit_id=&active_only=`. Buckets every habit's logs into **labelled periods**: months (`2026-07` / "July 2026") or **ISO weeks** (`2026-W30` / "Wk 30 · 20–26 Jul", cross-month spans render "27 Jul – 2 Aug"). Per bucket per habit: `logged_days`, `days`/`elapsed_days` (partial current period counted correctly), `rate`, `avg_level`, `levels{1..4}`, `minutes`, `untimed_entries`, `best_streak`, and the raw `entries`. Plus a whole-range `summary` per habit with `current_streak` (computed from ALL logs via a separate read, so a streak that predates the window isn't truncated). `_parse_minutes` reads free-text `time_spent` ("30 min", "1h 20m", "1:30", bare number); unparseable non-empty values are counted, not silently dropped.
- **`GET /tracking/report/export?format=md|csv|json`** — Markdown report (summary table + a section per labelled period with per-habit stats, level distribution, and a Date/Level/Time/What happened/Felt/Connections table), CSV (one row per log entry, every row carrying its period + habit labels), or the raw JSON. Writes a copy to the exports dir like the other exporters. `activity.py` gained the `tracking` → pulse category.
- **`tracking.js` rewritten** around that endpoint. Toolbar: **Month | Week** toggle, **◀ ▶** to step through time in the active unit, a "today" reset, a period-count select (2/3/6/12 months or 4/8/12/26 weeks), a live range label, and a **📄 Report ⇄ ▤ Grid** switch.
  - **Month view** — real calendar per month (Mon-start, day numbers in the cells), months stacked vertically with a **30px gap + a rule** between them; each labelled with its name and its own stat line.
  - **Week view** — one column per ISO week laid out left-to-right with a **14px gap + a divider**, each labelled `Wk N` above and its date range + `n/7` count below, with an M T W T F S S gutter down the left.
  - **Report view** — the same buckets rendered on screen (summary table + per-period sections + entry tables) with Markdown/CSV/JSON download buttons.
- CSS: `.ptrack-{day,cal,dow,dowv,month,plabel,stat,weeks,week,wcol,wnum,wsub,wcount,wgutter}`, `.btn-sm.ptrack-on`. Cache-bust bumps: `tracking.js?v=4`, `main.css?v=5`, and **`api.js` gained `?v=2` — it had none, so the browser served a stale copy without `trackingReport` and the view died on first load.** Bump it from now on when editing api.js.
- Verified (API + in-browser): month/week bucket labels + boundaries incl. a cross-month week; aggregates against a seeded 95-day dataset; Markdown + CSV exports fully labelled; both views render with the gaps/labels asked for; ◀ paging re-labels the range and reveals "today"; report view + day-log modal (correct pre-filled date from a clicked cell) both work; zero app console errors. **All test data removed** — temp habit `ZZ TEST TRACKING` + its 40 logs deleted (cascades), the 44 ChangeEvents it generated purged, and the test export files deleted. The user's 2 real habits still have 0 logs.

### 2026-07-27 — Tracking follow-up: horizontal months + a Year view (user request)  ✅
Ask: "I want the months next to each other the same way weeks are, and I'd like a year view."
- **All three modes now share one layout primitive** — `.ptrack-strip` (flex row, 18px gap, `overflow-x:auto`, `> * + *` gets a left rule). Month blocks moved out of the vertical stack into that strip, oldest→newest left→right like weeks, each block = label / weekday header / calendar / stat line (stats sit under the calendar now and wrap at 206px instead of being spread to the far right). The week mode's weekday gutter is exempted from the rule via `.ptrack-strip > .ptrack-wgutter + *`.
- **Year view** — `period=year` added to the report endpoint (`_year_periods`, cap 10; the `{month,week,year}` dispatch replaced the two-way branch; `_report_markdown` says "Yearly"). `yearBlock()` renders a full calendar year GitHub-style: a **7-row × ~53-column grid** (`grid-auto-flow: column`, 11px cells) with **month names labelled across the top**, each label spanning the columns its days occupy (`grid-column: c / span n`, computed from the Monday on/before Jan 1), an M/W/F/S gutter, and days outside the year blanked. Toolbar toggle is now **Week · Month · Year** with per-mode counts (4/8/12/26 weeks, 3/6/12/24 months, 1/2/3/5 years) and year-aware ◀ ▶ paging.
- Fixed: the report header hardcoded "Monthly"/"Weekly" and read "Weekly" in year mode.
- Verified (API + in-browser, against a seeded 500-day/2-year dataset): year buckets + boundaries; months side by side with rules; year grid alignment (month labels sit over their columns, future days blank after today); report + Markdown export in year mode; no console errors. **All test data removed again** — habit + 237 logs, 240 ChangeEvents, export files. Confirmed the user's own logs (`stretch 10 mins` ×2, `lights out 23:00` ×1, added during the session) survived the cleanup.

### 2026-07-27 — Image system: Mainframe-level service + first 5 surfaces (VISION_SPEC increment 1)  ✅
Spec: `~/Downloads/VISION_SPEC.md` (with mockup `~/Downloads/vision-v2.html`, 5 of 6 tabs, no Sandbox). Vision is to be the 3rd module (red `#FF4757`, tabs Blueprint/YouTube/Writing/Portfolio/Network/Sandbox). Images are the spec's foundation and are explicitly **Mainframe-level, not Vision-specific**, so they're built first. User's steer: *"I want every tool and element to have the functionality and I can hide or delete if needed"* — so images go everywhere, unobtrusively, with a hide switch.
- **`routes/images.py`** — `/api/images` (list w/ module+context_id filters, multipart upload, metadata, `/file` serve, PUT rename, DELETE incl. the file on disk). **Deliberately generic:** an image knows only its `module` + `context_id`, and the `HAS_IMAGE` edge is drawn by matching *any* node carrying that id (the unlabelled id-match trick `activity.record()` already uses). **No route, model or label anywhere needs to know about images** — a `:Task`, `:Paper`, `:Habit`, `:Idea` or `:MindDump` all attach for free. Verified: uploading against a task id produced `(:Task)-[:HAS_IMAGE]->(:Image)` with zero task-side code.
- **Images only**, per decision: PNG/JPG/JPEG/GIF/WEBP/SVG. PDFs are rejected with a helpful message; the four existing uploaders (dictionary term images, medical files, project files, paper PDFs) are untouched and keep working alongside.
- **Name is mandatory** (spec says so three times): blank/whitespace names 400. Files land at `~/.mainframe/images/<module>/<slugged-name>_<timestamp>.<ext>`; the original name is kept on the node for display. `config.images_dir`, 3 constraints/indexes in `db.py` (76 total), `image` → CATEGORY_MODULE fallback.
- **`frontend/js/images.js`** — the shared widget, loaded right after `ui.js` so every view can use it. `Images.mount(host, {module, contextId, surface, title})` is the whole integration cost. Name modal → upload → thumbnail strip → click for a lightbox (Esc/backdrop closes) → ✎ rename / × delete. **Empty state is one small `📷 add image` button, no gallery chrome** — that's what makes putting it on surfaces you never use free. `Images.setHidden(surface)` drops the widget entirely per surface (localStorage `mf.images.hidden`). The file `<input>` lives in the DOM for the widget's lifetime rather than being created per click — no DOM churn, and it's drivable by anything (that's also what made the upload path browser-testable).
- **Wired into 5 representative surfaces** for UX review before the full sweep: paper workspace (`synapse`), task detail (`tasks`), habit card (`pulse`), idea detail panel (`synapse`), mind-dump expanded card (`mind`).
- Verified (API + in-browser): upload/list/serve/rename/delete round trip; PDF rejected 400; blank name rejected 400; generic edge confirmed in Cypher; full UI flow driven end-to-end (file → name modal pre-filled from filename → Save → thumbnail → lightbox); widget present and empty-state-collapsed on all 5 surfaces; no console errors. **All test data removed** — 2 images + files, 5 `image` ChangeEvents, scratch PNGs. 0 Image nodes, 0 HAS_IMAGE edges left.
- **Next increments:** sweep the remaining ~25 entity types → Vision module skeleton + Blueprint → YouTube → Writing/Portfolio/Network → Sandbox.

### 2026-07-27 — Image sweep: every entity surface in the app  ✅
Follow-up to the above — the widget now sits on **25 mount sites across 23 files**, one per entity type. Nothing else changed: no backend edits, no new endpoints. The whole sweep was `Images.mount(host, {module, contextId, surface})` per card, which is the point of the generic design.
- **Synapse:** paper (workspace), reading instance (session log), highlight, term, idea, deep dive, custom section. **Dictionary:** term — the generic gallery sits *alongside* the existing single "hero picture" uploader rather than replacing it, titled "More images".
- **Mainframe:** task, **task entry** (spec calls these out — screenshots/diagrams/whiteboard photos), mind-dump capture, project.
- **Pulse:** habit, day log, experiment, routine, recovery session, medical entry (gallery alongside its own single-file upload, per the spec's "extend it"), medication, workout, training cycle, stretch session, activity log, intolerance, supplement, benchmark snapshot.
- Small refactor where a widget had to be a *child node* rather than appended to a host: a local `imgHost(id, surface)` helper in `workspace.js`, `tracking.js`, `fitness-activity.js`, `nutrition-intolerances.js`, `nutrition-supplements.js`, and `entryImages(e)` in `tasks.js`.
- Verified: all 23 files pass `node --check`; **every target label confirmed to carry an `id` property in Neo4j** (the generic `HAS_IMAGE` match depends on it) — checked `Experiment, Routine, RecoverySession, MedicalEntry, MedEntry, Workout, Cycle, StretchSession, ActivityLog, Intolerance, Supplement, Assessment, HabitLog, DeepDive, Project, CustomHeader, TaskEntry, Highlight, Instance, Term, Concept`; visually confirmed the widget on task, task entry, paper, habit, idea, mind dump, experiment, deep dive; zero console errors across a full tab sweep of both modules. All `?v=` bumped.
- **Known gaps (documented, not bugs):** see "Image system — what it can't do" below.

### 2026-07-27 — Images: multi-upload + lightbox paging (user request)  ✅
Ask: *"I just need to be able to have more than 1 image and move through the image."* Many-per-entity already worked; adding them one at a time and having no way to browse them didn't.
- **Multi-select upload** — the file input gained `multiple` and the handler loops instead of taking `files[0]`. The spec's every-image-needs-a-name rule can't become ten dialogs, so `namesModal()` is **one dialog with a row per file**: a thumbnail (from `URL.createObjectURL`, revoked on close — `IMG_4471` tells you nothing about which shot it is), a name input pre-filled from the filename, and the filename + KB underneath. Uploads run sequentially with a `n/total` toast so order stays stable and progress is honest.
- **Lightbox pages through the whole set** — `lightbox(list, index)` opens on the clicked thumbnail and keeps the rest to hand: on-screen ‹ › , **← / → keys**, Esc to close, an `n / total` counter, and wrap-around at both ends. Arrows and counter hide themselves when there's only one image. Still back-compatible with single-image callers (`lightbox(img)` wraps to a one-item list).
- CSS: `.img-namemodal/.img-namelist/.img-namerow/.img-namethumb`, `.img-stage/.img-nav/.img-count`. `images.js?v=3`, `main.css?v=9`.
- Verified in-browser: 4 files picked at once → one dialog with 4 named rows → renamed one to "Attention diagram" → all 4 saved in a single pass with the custom name applied; lightbox opened at `2 / 4`, arrows and ← / → both paged and wrapped 4→1 and 1→4, captions tracked the image, Esc closed; with one image left the arrows and counter were correctly hidden. **All test data removed** (4 images + files + log events; 0 Image nodes, 0 HAS_IMAGE edges).
- Still not wired: **paste** (Ctrl+V of a screenshot) and drag-drop — see gap 3 below. Given the user screenshots often, paste is the obvious next quality-of-life add.

### 2026-07-27 — VISION module + Blueprint (VISION_SPEC increment 2)  ✅
Vision is live as the **third Mainframe module** (red `#FF4757`), with **Blueprint** built.
- **Module registration was one entry in `modules.js`**, exactly as that file promised: key/label/accent/topbar + the full 6-tab list. `app.js` already does `.map(id => Views[id]).filter(Boolean)`, so **unbuilt tabs simply don't render** — no placeholder views needed, and each future increment just adds its file. CSS `:root[data-module="vision"]` supplies the red accent to the shared chrome.
- **`routes/vision.py` — Blueprint.** `GET/POST /pipelines`, `PUT/DELETE /pipelines/:id`, `POST /pipelines/:id/stages`, `PUT/DELETE /pipelines/:id/stages/:sid`, `PUT /pipelines/:id/reorder`, plus `GET /tools`. Nodes `-[:OWNED_BY]->(:Module{name:"vision"})`, every mutation logged with the new `pipeline/video/writing/portfolio/contact/sandbox → vision` categories. 3 constraints (79 total).
- **Deliberate deviation from the spec's graph sketch:** it shows `(:StageIO)` nodes for inputs/outputs *and* declares them as ordered `[String]` in the Stage schema. Ordering is what the user sees ("one per line") and a pattern comprehension can't be ordered, so **inputs/outputs are array properties**. **Tools still get real `(:Tool)` nodes** via MERGE, because a shared tool node is what makes "which pipelines use Claude?" answerable — the reason this app is on a graph DB at all. `GET /tools` returns each tool with its stage count and pipeline names.
- **Bug found and fixed during testing:** MERGEd tools are shared, so deleting a pipeline left a graveyard of 0-use `(:Tool)` nodes. Added `_prune_tools()` (`MATCH (t:Tool) WHERE NOT (t)<-[:USES_TOOL]-() DETACH DELETE t`) wired into pipeline delete, stage delete, and the tool re-point path. Verified: a tool used only by a deleted pipeline disappears; it also swept the orphans the earlier tests had already created.
- **`vision-blueprint.js`** — pipeline cards (red left border, inline-editable name + description, blur-saves), stages as **connected boxes with → between them** flowing left→right: numbered badge, name, IN (teal), OUT (amber), 🤖 tool tags (purple), process notes clamped to 3 lines and click-to-expand. Per-stage **◀ ▶ reorder / ✎ edit / × delete**; one modal serves both add and edit. Each stage also carries an image widget (`surface: "vision-stage"`).
- Verified (API + in-browser): create pipeline → 3 stages with multi-line inputs/outputs/tools → reorder → re-point tools → delete stage (orders compact to 0..n) → delete pipeline; in the UI, VISION appears in the switcher with red chrome and only Blueprint in the module bar, stage modal round-trips (add + edit pre-fill), ◀▶ renumbers live, `+ stage`/`delete` work. Zero app console errors. **All test data removed** (2 pipelines, stages, 6 tools, 13 vision log events; only the `(:Module {name:"vision"})` marker node remains, which is correct).
- **Next:** YouTube (video cards → full detail view with script/concept/journal/images/stage advancement), then Writing/Portfolio/Network, then Sandbox.

### 2026-07-27 — YouTube increment A: video core + pipeline linking (VISION_UPDATE_SPEC)  ✅
New spec `~/Downloads/VISION_UPDATE_SPEC.md` (13 KB) **replaces VISION_SPEC's YouTube section**: a video becomes a full production workspace. Also downloaded: `~/Downloads/vision-full.html` — an updated 6-panel mockup, but its YouTube panel **predates this update** (no storyboard/prompt log/markers), so the update spec wins.
- **Plan for YouTube, 4 increments:** **A. video core + pipeline linking** ← this one · B. Research + Prompt log · C. Script + markers · D. Storyboard + Thumbnail board. Then Writing/Portfolio/Network, then Sandbox.
- **`vision-youtube.js` is a shell with a section registry.** `window.VID_SECTIONS` (same idea as FIT_TABS/NUT_TABS): each later increment pushes `{key, label, render(host, video, reload)}` and the detail view renders them in order between Concept and the Journal. So B/C/D are new files, not edits to this one.
- **Video core:** `(:Video)` with title/type/stage/pipeline_id/target_date/thumbnail/description/script/framework/llms_used/tags/notes. `GET/POST /videos` (filterable by type/stage), `GET/PUT/DELETE /videos/:id`, `POST /videos/:id/entries` + delete, and **`POST /videos/:id/advance`**. 6 type badges with their own icon+colour (📚 educational, ⚡ short, 🏗️ big-project, 🛠️ tutorial, 📹 vlog, 📺 series). Card grid: thumbnail as background with a gradient-free tag strip, type badge, stage badge, 📐 pipeline tag, framework, 🤖 LLM tag. Clicking a card opens the **full detail view** (spec: a detail page, not an expand).
- **Pipeline linking (spec: do NOT skip).** `(:Video)-[:FOLLOWS_PIPELINE]->(:Pipeline)`; the stage dropdown is populated **from that pipeline's stage list — never hardcoded**. Creating a video with a pipeline starts it at that pipeline's first stage; re-pointing the pipeline resets the stage; `advance` walks the list in order and 400s at the end. The detail view shows the whole pipeline as a compact reference bar with the current stage highlighted.
- **Delete cascades** every child node type the later increments will add (ResearchNote/ScriptMarker/PromptEntry/StoryPanel/ThumbnailOption), so increments B–D can't leave orphans. Video FILES are never stored, per spec.
- **Schema left open for the spec's FUTURE fields** (`input_tokens`/`output_tokens`/`cost`/`energy` on prompt entries) — not built, not blocked.
- Fixed while testing: disabled buttons had **no disabled styling anywhere in the app** — "→ move to next stage" at the final stage looked fully clickable. Added a global `button:disabled { opacity:.38; cursor:not-allowed }`.
- 4 new constraints/indexes (83 total). Verified (API + in-browser): create with pipeline → starts at "Idea"; 2× advance → "Record"; journal entry; advance to "Publish" then 400 "already at the final stage"; grid shows badges + pipeline tag; detail view renders every field, the pipeline bar highlights Publish, all sections present; disabled button now visibly dimmed; zero console errors. **All test data removed** (1 video, 1 pipeline + 5 stages, journal entry, vision log events — 0 of every label left).

### 2026-07-27 — YouTube increment B: Research + Prompt log  ✅
- **Section registry now sorts by `order`, not file load order** — `research 10 · script 20 · prompts 30 · storyboard 40 · thumbnails 50`. That's what lets increment C's Script slot *between* two sections already shipped, without touching either file.
- **🔬 Research** (`vision-research.js`) — `(:ResearchNote {id,title,url,summary,date})` via `HAS_RESEARCH`. Add with title + optional url; every field edits inline and blur-saves; `open ↗` when a url is set. Spec only listed POST/DELETE — **added PUT** because a source with a typo'd summary being uneditable is silly.
- **🤖 Prompt log** (`vision-prompts.js`) — `(:PromptEntry {llm,prompt,response,variation,status,notes,date})` via `HAS_PROMPT`. Accordion: 🤖 LLM badge, truncated prompt, colour-coded status (draft grey / approved green / rejected red / edited amber), date. Expand for full prompt + response in scrollable blocks, variation, notes, an inline status switch, and **`→ use as script`**, which is the spec's "the approved entry feeds into the script field" made explicit (confirm dialog, 400s if the entry has no response) rather than something that silently overwrites work. **Entirely manual — no model API is called anywhere**, per spec.
- **Future-proofed, as instructed:** `PromptEntryCreate/Update` are `extra="allow"`, so the spec's later `input_tokens`/`output_tokens`/`cost`/`energy` store today without a migration. Verified by posting them and reading them back — not built, not blocked.
- **Bug found and fixed:** Neo4j drops null properties, so a research note saved without a url came back with **no `url` key at all** — a different response shape for the same endpoint. Optional strings now store `""`. Same fix applied to the video's `pipeline_id`/`target_date`.
- **UX fix:** every expand/collapse re-renders the (long) detail view, which threw you back to the top each time. `reload()` now preserves scroll when it's re-rendering the same video. Note for future work: **the app scrolls `.view`, not the window** — `window.scrollY` is always 0 here.
- 2 new constraints (85 total). Verified (API + in-browser): research with and without a url; 3 prompts across 3 LLMs with different statuses; `use-as-script` copied the approved response into `video.script`; a response-less entry correctly refused; sections render in spec order (Concept → Research → Prompt log → Journal → Notes → Images); expand holds scroll. **All test data removed — and deleting the video cascaded its research notes and prompt entries to 0, confirming increment A's cascade works.**
- **Next:** increment C — Script + markers (the spec's flagged key feature).

### 2026-07-27 — YouTube increment C: Script + markers  ✅
The spec's flagged key feature: annotate LINE RANGES of the script so you can see its structure at a glance.
- **`(:ScriptMarker {line_start, line_end, label, note})`** via `HAS_MARKER`; POST/PUT/DELETE under `/videos/:id/markers`. The 8 labels are a `Literal` of keys (`hook, key-point, abstraction, data, transition, climax, cta, broll`) — **the icon/colour live only in the frontend**, so the presentation can't drift out of sync with what's stored. Reversed ranges are normalised server-side (`sorted()`), so "line 6 to line 3" saves as 3–6.
- **`vision-script.js`** — two modes. **Edit** is a plain mono textarea. **Read** is a numbered block with a **left gutter of coloured bars**, rounded at the range's first and last line, one bar per marker.
  - **Overlapping markers get their own lane.** `laneOf()` sweeps markers by start line and drops each into the first lane whose last-used line is already passed — so Abstraction L7–9 and Key Point L8–8 render side by side instead of on top of each other. Verified with a deliberately overlapping pair.
  - **Creating a marker is two clicks**: click a line number (it highlights red), click a second (either direction) → modal pre-filled with the range, a label picker that shows each label's meaning as you change it, and a note.
  - Marker tags sit inline in the right margin on the line the marker starts, and clicking either the tag or the gutter bar opens the same editor.
  - A legend of the labels actually in use sits above the script.
- **Stale markers are surfaced, never dropped.** Markers store line numbers but the script is free text, so shortening it can strand them. Rather than silently discarding annotations, out-of-range markers are listed under a ⚠ banner as clickable tags (`Transition L4–5`, `CTA L13–13`…) that open straight into the editor to move or delete them. Verified by cutting a 13-line script to 3.
- 1 new constraint (86 total). Verified (API + in-browser): 7 markers incl. an overlap and a reversed range; lanes render correctly; two-click creation pre-fills; tag/bar click opens the editor pre-filled; stale banner lists exactly the 5 out-of-range markers; zero app console errors. **All test data removed** (video + 7 markers + children → 0 of every label).
- **Next:** increment D — Storyboard panel grid + Thumbnail comparison board. Both are image-heavy, so they'll use the image service (spec allows "URL **or** uploaded image path").

### 2026-07-27 — YouTube increment D: Storyboard + Thumbnail board — **YOUTUBE COMPLETE**  ✅
- **🎬 Storyboard** (`vision-storyboard.js`, order 40) — `(:StoryPanel)` via `HAS_PANEL {order}`. Comic-panel grid (auto-fill, ~4 per row): frame with the image or a big grey panel number, duration badge bottom-right, caption, dialog in quotes, notes. Click the frame → editor with caption/dialog/duration/notes/image. Delete compacts the remaining orders to 0..n. **Panels are the PLAN, never video files** — spec is explicit.
- **🖼️ Thumbnails** (`vision-thumbs.js`, order 50) — `(:ThumbnailOption)` via `HAS_THUMB_OPTION`. Horizontal board of options, each with style + notes; click one to choose it → **green border + ✓ badge, all others unset, and the video's `thumbnail` is set to its image** so it shows on the card. Deleting the chosen option **clears the video's thumbnail** rather than leaving the card pointing at an option that no longer exists.
- **Both accept a pasted URL or an upload through the Mainframe image service** (spec: "URL or uploaded image path"). Uploading routes through `Images.nameModal` → `/api/images` → stores `/api/images/<id>/file`, so `panel.image` is always just a URL string and nothing downstream cares which it was. Verified end to end: a PNG uploaded inside the panel editor rendered as that panel's frame.
- **Reordering:** ◀ ▶ buttons (the tested, accessible path) **plus native HTML5 drag-and-drop**, no libraries. ⚠ **The drag path is unverified** — synthetic mouse events don't reliably trigger HTML5 DnD, so browser automation can't exercise it. The arrows are fully verified; drag needs a human to confirm.
- **Route-order gotcha:** `PUT /storyboard/reorder` is declared **before** `PUT /storyboard/{sid}` — FastAPI matches in declaration order, so the literal path must come first or "reorder" is swallowed as a panel id.
- 2 new constraints (88 total). Verified (API + in-browser): 5 panels → reorder → delete compacts orders; 3 thumbnail options, choosing switches exclusively and feeds `video.thumbnail`, deleting the chosen one clears it; upload-into-panel works; ◀▶ renumbers live; zero console errors. **All test data removed** (video, panels, thumbs, image + file → 0 of every label).
- **YouTube is now complete** — concept, research, script + markers, prompt log, storyboard, thumbnails, journal, notes, images, pipeline-driven stages. **Next: Writing, Portfolio, Network** (three simpler CRUD tabs, likely one increment), then **Sandbox**.

### 2026-07-27 — Writing + Portfolio + Network — **VISION COMPLETE (Sandbox skipped)**  ✅
User decision: **skip Sandbox entirely.** It's cleanly separable — it was tab 6 and nothing else depends on it. Left declared in `modules.js` so it simply doesn't render (`app.js` filters unbuilt views); if it's ever wanted it's one file, and the PNG-export approach is documented above.
- **Writing** (`vision-writing.js`, `(:WritingPiece)`) — expandable cards with type (Blog/Article/Thread/Newsletter/Essay) and platform (Blog/Medium/Substack/LinkedIn/Twitter/Other) tags. **Reuses the video stage machinery**: `IN_PIPELINE` to a Blueprint pipeline, stage dropdown fed from that pipeline, `POST /writing/:id/advance`, and the same compact pipeline reference bar with the current stage highlighted. Plus link, notes, images.
- **Portfolio** (`vision-portfolio.js`, `(:PortfolioProject)`) — card grid, image as the cover or the type icon (💻🔬🎬🎨🔧✍️📦) when there's none, type badge overlaid, description, tags, link. Click a card to expand into inline editing. **Deliberately a different label from the Mainframe-level `(:Project)`** behind the shared Project tab — that one is a working file store, this is things you show people.
- **Network** (`vision-network.js`, `(:Contact)`) — contact cards with an avatar circle that **falls back to the initial letter** when no image is set, name, role, platform, notes, link.
- All three take images through the shared service (upload → `Images.nameModal` → `/api/images` → store the file URL), consistent with storyboard panels and thumbnails.
- 3 new constraints (91 total). Verified (API + in-browser): writing created against a pipeline starts at its first stage and advances through it; portfolio stores tags as a real list; contact renders the initial-letter avatar; all five tabs present in the module bar; zero console errors. **All test data removed** (0 of every Vision label).

## VISION — status
**Built:** Blueprint · YouTube (concept, research, script + markers, prompt log, storyboard, thumbnails, journal, notes, images, pipeline stages) · Writing · Portfolio · Network. Plus the Mainframe-level image system underneath it all.
**Skipped by choice:** Sandbox.
**Outstanding across the app:** storyboard drag-and-drop is unverified (needs a human — automation can't drive HTML5 DnD); orphaned images on entity delete (see gap 8 below) — worth fixing before real data accumulates; paste-to-attach screenshots (gap 3), deferred by the user.

### 2026-07-27 — VAULT module + Accounts + Transactions (VAULT_SPEC increment A)  ✅
New spec `~/Downloads/VAULT_SPEC.md` (17.7 KB) + a partial mockup `~/Downloads/vault-analytics.html` (covers trend/comparison/verdict/insight only — the spec is richer and wins). **Vault = 4th Mainframe module**, gold `#D4A017`, 8 tabs: Overview · Accounts · Transactions · Monthly Plan · Investments · Analytics · Inventory · Diary.
- **Plan, 4 increments:** **A. Accounts + Transactions** ← this one · B. Budget + Investments · C. Inventory + Diary + Overview · D. Analytics. A comes first because budget-vs-actual, the dashboard and every chart in Analytics are all *computed from transactions* — nothing else can exist first.
- **Module registration** was again one `modules.js` entry + a CSS accent block. `vault-common.js` holds the shared money/category/verdict/date helpers (same role as `pulse-common.js`).
- **Accounts** — 6 types with icons, inline-editable name/balance/type/provider, a total-across-all-accounts card. **Deleting an account keeps its transactions** (it just clears their link) — losing spending history because a bank account closed would be wrong.
- **Transactions** — the log everything computes from. Table with date/description/category (inline dropdown)/amount/account/verdict/delete, a running in/out/net summary, and five filters (text search debounced, month, category, account, verdict incl. "unset").
- **Sign is normalised server-side from `type`** — send +18.40 or −18.40 for an expense and it always stores −18.40, so downstream sums never have to guess. Verified.
- **Verdict system** (spec: do NOT skip) — one button per row cycling unset → needed → wanted → wasteful, colour-coded grey/green/amber/red.
- **Bulk paste** (spec: do NOT skip) — `POST /transactions/bulk` with `dry_run` for the required preview step. Auto-detects tab/comma/CSV, drops a header row, accepts **7 date formats** (`2026-07-14`, `14/07/2026`, `14 Jul 2026`…), reads **accounting negatives `(54.10)`** and strips `£ $ € ,`. ~60 keyword→category rules (Tesco→Food & Drink, Netflix→Subscriptions, Trainline→Transport…). Unparseable lines are **reported per-line, never silently dropped**; everything imports with verdict unset.
- 5 new constraints/indexes (96 total). Verified (API + in-browser): sign normalisation both directions; verdict cycles through all four states and back; bulk preview flagged a garbage line, normalised `22/07/2026`→`2026-07-22`, read `(38.20)` as −38.20 and guessed all three categories; filters (month+category, verdict=unset, search) all correct; gold theme applied. **All test data removed** (0 accounts, 0 transactions, log purged).

### 2026-07-27 — Vault increment B: Monthly Plan + Investments  ✅
- **Monthly Plan** (`vault-budget.js`) — **budget categories are entirely user-defined** (spec: do NOT hardcode), each with its own icon and monthly target, editable inline. Income is set per-month, so the plan can change month to month; if none is set it falls back to actual income received. Shows allocated / unallocated / spent, and a bar per category following the spec's colour rule: **teal under, gold at 100%, red + ⚠ over** (verified all three).
- **Actual is never stored.** `budget_actual(month)` sums transactions by category for the month and compares to targets — one shared function so Monthly Plan, the Overview dashboard and Analytics can't disagree with each other. It's already exported for increments C and D.
- **Spending outside the plan gets its own section.** Categories with transactions but no budget line would otherwise vanish from the comparison; they're listed with a **"+ budget it"** button that creates the line. Caught by test data spending in "Fun & Social" with no budget for it.
- **Investments** (`vault-investments.js`) — teal-bordered cards with type/platform/strategy tags, large current value, and **P&L in £ and % with ↑/↓, green/red**. Three summary cards: Total Invested / Current Value / Total P&L. Values are snapshots updated by hand — **nothing calls a broker API**, per spec. `updated_at` moves only when the valuation changes, so "valued on" means what it says.
- **Future-proofed as instructed:** `InvestmentCreate/Update` are `extra="allow"`, so the spec's later `api_source` / `ticker` / `last_api_sync` store today without a migration. Verified by posting `ticker` + `api_source` and reading them back.
- 3 new constraints (99 total). Verified (API + in-browser): budget-vs-actual computed from 7 seeded transactions across 5 categories; income set vs fallback; over-budget flip to red + ⚠ at 121%; unbudgeted category surfaced with its "+ budget it" action; investment P&L both positive (+14.0%) and negative (−21.6%); summary totals correct. **All test data removed** (0 of every Vault label).
- **Next:** increment C — Inventory + Diary + Overview dashboard.

### 2026-07-27 — Vault increment C: Inventory + Diary + Overview  ✅
- **Inventory** (`vault-inventory.js`) — **three separate sections, deliberately not merged** (spec: do NOT combine need/want): *What you have* (active/in-use/owned/stored, **grouped by category** with a total), *Need to buy* (red border, estimated price), *Want to buy* (purple border, the wishlist), plus a Broken/Sold section so retired kit doesn't clutter the main list. Status dropdown is colour-coded per the spec's palette; everything edits inline.
- **Diary** (`vault-diary.js`) — its own tab, not transaction notes (spec). Gold-bordered cards, date, gold title, body, tags; newest first.
- **Overview** (`vault-overview.js`) — the dashboard, and **every number on it is derived**: six summary cards (total balance, income, spent, free cash flow, invested, savings), budget-vs-actual bars, last 10 transactions. `GET /vault/overview` computes them from accounts + this month's transactions and **calls the same `budget_actual()` the Monthly Plan uses**, so the two pages can't disagree. Savings reads only from `type = 'savings'` accounts, not everything.
- Month selector on both Overview and Monthly Plan, so past months are reviewable.
- 3 new constraints (102 total). Verified (API + in-browser): overview arithmetic against seeded data (balance £8,050.40 across two accounts, savings £6,200 from the savings account only, free cash flow £1,386.61 = 2,400 − 1,013.39); Transport correctly flagged over budget on both Overview and Monthly Plan; inventory sections split need/want and grouped "have" by category with per-section totals; diary entry with tags. **All test data removed** (0 of every Vault label).
- **Next:** increment D — Analytics. The big one: %/£/Both toggle, allocation sliders, donut, stacked monthly bars, trend line, month-to-month table, category breakdown, purchase review, auto-insights.

### 2026-07-27 — Vault increment D: Analytics — **VAULT COMPLETE**  ✅
The biggest single page in any spec so far. `routes/vault_analytics.py` (6 endpoints: monthly, categories, trend, verdicts, allocation, insights) + `vault-analytics.js`. All hand-rolled SVG/CSS, zero libraries.
- **%/£/Both toggle** — every number on the page respects it, including the stacked-bar totals and the difference column (see the bug below).
- **Allocation sliders** (0–50% of income) — dragging updates the page live *without touching the server*; releasing saves the target (`percent × income`) to the budget. A planning tool you can play with, and a commit when you let go. Verified: moving Transport 5%→21% instantly rebuilt the target stack and moved the allocation counter to 87%.
- **Target vs actual stacked bars**, **detailed comparison** (faded target behind solid actual), **donut** (target split in % mode, actual in £ mode — spec), **monthly stacked bars** (6 months, current gold-outlined, click to switch month), **category breakdown**, **month-to-month table** (red up / green down, highest month flagged, total row), **spending-vs-income trend** (red solid / green dashed), **purchase review** with working verdict buttons, and **auto-insights**.
- **Insights are plain arithmetic, no LLM** — month-over-month movement, per-category swings ≥25%, over-budget warnings, over-allocation, wasteful share, unreviewed share, investing consistency. Against seeded data they read: *"Spending is down 15% on last month"*, *"Transport rose 608% this month"*, *"Transport is over budget by 27"*, *"64% of this month's spending hasn't been reviewed yet"*, *"Invested or saved in each of the last 3 months"*.
- **Two real bugs found and fixed in testing:**
  1. **The monthly stacked bars rendered empty.** Percentage heights inside nested flex boxes resolved against an auto-height parent and collapsed. Now computed in pixels.
  2. **The comparison subtracted percentages with different denominators.** `target_pct` is a share of *income*; `actual_pct` was a share of *spending*. Rent exactly on target showed **+18.9pp in green** — meaningless and misleading in a finance tool. The API now returns **both** `actual_pct` (share of spending, for the donut and breakdown, where it reads naturally) and `actual_pct_income` (share of income, for the target comparison). Rent now correctly shows `0.0pp`.
- Verified (API + in-browser): all 6 endpoints against 6 months of seeded data across 8 categories; every section renders; toggle switches every value; sliders drive the charts live; verdict buttons work inside the review. Zero console errors. **All test data removed — 0 nodes across all 7 Vault labels.**

## VAULT — status
**All 8 tabs built:** Overview · Accounts · Transactions · Monthly Plan · Investments · Analytics · Inventory · Diary. Every spec "do NOT" respected: verdict system, bulk paste with preview, the three-way toggle, allocation sliders, snapshot-only investments (with room for future API import), need/want kept separate, month-to-month table, purchase review, the diary as its own tab, user-defined budget categories, and budget-vs-actual derived from transactions.

### 2026-07-30 — The assistant gets a face and a voice button (user request)  ✅
The assistant is **Leo** now, and looks like it.

- **`backend/avatar.py`** — drop any image into **`~/mAInframe/AI_assistant/`** and it becomes the
  assistant's face. Same shape as the wallpaper and module-card caches: **the source is only ever
  read**, sized copies live under `~/.mainframe/assistant/`, and the cache filename carries a
  fingerprint of the source so replacing the picture busts the browser cache for free and an
  unchanged file is skipped. **252 KB 1264×1264 → 42 KB and 14 KB** at the two sizes actually drawn —
  serving the original to paint a 26px chip is exactly the waste this app criticises elsewhere.
  Square-cropped from the centre server-side, because the avatar is drawn in a circle and a
  non-square source would otherwise be squashed. If several images are present the newest wins, so
  dropping a new one replaces it without deleting anything.
- **Leo is the launcher.** Pressing his face is what brings him up; the old ◉ glyph remains only as
  the fallback when no picture has been dropped in yet, so the assistant is never invisible.
- **His face sits beside everything he says**, so a reply is never anonymous, and in the panel header
  next to his name. The name is `assistant_name` in config — nothing about "Leo" is hardcoded in the
  frontend, it all arrives from `/api/agent/status`.
- **A 🔊 on every reply speaks it.** Works whether or not the auto-speak toggle is on — that's the
  point of it being a button rather than a setting. Only one voice at a time: pressing a second
  speaker cuts the first off rather than talking over itself, and a blocked autoplay now says so
  instead of failing silently.

**Bug found by testing, and it was a latent one from the original build:** `ui.el()` splits its spec
string on `"."` only — **it has no `#id` syntax**. `el("button#ag-launch.ag-launch")` therefore
created an element whose tag name was literally `BUTTON#AG-LAUNCH` — not a real `<button>`, and with
no id at all. It *looked* fine because the class and click handler still applied, which is why it
survived the original session; but `document.getElementById("ag-launch")` returned null, so the
launcher could never be repainted with Leo's face. The id goes in the attributes. **Swept the
codebase — no other instance.**

- Verified in-browser: launcher shows Leo, header shows "Leo", his face is beside the reply, and the
  speaker button served `POST /api/agent/speak → 200`. **Test log rows purged.**
  `agent.js?v=3`, `main.css?v=59`.

### 2026-07-30 — Voice assistant: one agent with a safe grip on the whole app  ✅
Reachable from **every view** — mounted on `<body>`, not inside a view — via **Ctrl+K** or the ◉
button. Type, or **hold space to talk**. Entirely local: whisper on the GPU, Ollama for reasoning,
piper for the spoken reply.

**The design problem was never the microphone — it was 421 routes.** Handing a 7B model 421 tools
produces a confused assistant, not a capable one. So `backend/agent/capabilities.py` is a hand-written
layer *over* the routes: **23 broad, verb-shaped capabilities** ("log time on a task", not six task
endpoints) spanning calendar, tasks, work log, nutrition, habits, Vault, Synapse and the activity log.

**The safety model is enforced in code, not in the prompt** (user's choice: *reads run, writes need a
yes*). Every capability declares `kind`. A `read` executes immediately and its result is fed back so
the model answers from real numbers. A `write` is **never executed by `/ask`** — it is captured,
described in plain English, and returned as a pending action. Only `/confirm`, from a human pressing
the button, runs it. A misheard command cannot change anything on its own.

**The model must never compute dates.** Asked what was on tomorrow, qwen2.5 confidently answered
`2023-10-05` — it has no idea what day it is. Every date parameter now takes the user's own words
("tomorrow", "friday", "+3d") and `resolve_date()` resolves them against the server clock. Today's
date is injected into the system prompt as well, but resolution is what guarantees correctness.

**Local voice, verified round-trip:** piper spoke *"What have I got on tomorrow, and log thirty
minutes on the README task"*, whisper `large-v3` transcribed it back **exactly**. **1.5 s warm** for
a 4-second clip on the 5090 (25 s on the first call — that's the model loading). Deliberately NOT the
browser's `webkitSpeechRecognition`, which uploads microphone audio to Google and would quietly break
the local-first rule the rest of the app follows.

**Four bugs found by testing, each a real class of failure:**
1. **`bool(Path)` is always true**, so `/status` reported speech-out as working while `/speak`
   correctly 503'd on a voice model that wasn't downloaded. Check `.is_file()`.
2. **A whole-phrase `CONTAINS` match fails constantly.** The model says "the readme task"; the row
   is called "Update the Readme". Lookups now reduce the phrase to keywords (dropping noise words like
   "task"/"the") and rank rows by how many match.
3. **`TaskEntryCreate.type` is a closed Literal** and `"work"` isn't one of its values — the confirm
   path failed, *and reported the failure honestly* ("0 of 1 done") rather than claiming success. Now
   `"progress"`.
4. **The model gets times wrong in two different ways.** Asked for "tomorrow at 6pm" it first filled
   `end` and left `start` empty — creating an **all-day event while the confirmation still read "at
   18:00"** — then, on a retry, sent `start == end` for a zero-length block. `_normalise_times()` now
   repairs both, parses "6pm"/"0900"/"6.30pm", and gives a lone start a one-hour default. The
   confirmation text describes the times that will *actually* be stored, because a confirmation that
   doesn't match the outcome is worse than none.

- `POST /api/agent/ask` · `/confirm` · `/listen` (audio → text) · `/speak` (text → WAV) · `/status`.
- **New dependency: `faster-whisper`** (MIT, CTranslate2). Model caches to `~/.cache/huggingface` and
  runs offline after. Voice-out uses the already-installed `piper` binary with an `en_GB-alba-medium`
  voice in `~/.mainframe/voices/`. Configurable: `whisper_model`, `whisper_device`, `piper_voice`.
- `window.refreshActive()` added to `app.js` — after a confirmed action the open view may be showing
  data the agent just changed, and a stale screen after "done ✓" reads as a bug.
- Verified in-browser: panel opens over any view and **survives switching views**; "put a gym session
  in the calendar tomorrow at 6pm" → proposed → confirmed → appeared in the Calendar at 18:00–19:00;
  "log 45 minutes on the readme task" resolved to "Update the Readme" and logged. **All test data
  purged — 0 events, task back to 0m, 17 log rows removed.** `agent.js?v=1`, `app.js?v=7`,
  `main.css?v=58`.

**Not built yet:** wake-word / always-listening (hold-to-talk only), multi-turn memory across a
conversation (each turn is independent), and capabilities for Vision, Fitness detail, Benchmarks,
Recipes and the dictionary — the registry is designed to grow, each addition is one decorated function.

### 2026-07-30 — Calendar: a top-level service that plans against your own data  ✅
New Mainframe-level tab, **second in the top bar, straight after Tasks** — tasks are the spine, and
the calendar is where they meet actual time. No spec existed for this; it was designed from the
request.

**Why it isn't just another calendar.** Google knows your commitments. The Mainframe already knows
your tasks, the work you logged, your workouts and habits. A day here has three layers, deliberately
distinct: **events** (`:CalEvent`, yours or imported) · **due** (tasks read *live* from `:Task`) ·
**done** (work sessions, workouts, habit logs, read-only). Due dates and logged work are **never
copied** into calendar nodes — copying makes two places for one fact, and they drift within a week.

- **Three views, hand-rolled, zero libraries.** Month grid; Week and Day on a real hour axis where
  events are positioned by the minute. **Overlapping events share the column width** rather than
  hiding each other — a clash you can't see is a clash you don't fix. All-day events get their own
  strip, because they can't sit on a clock. Logged work is drawn *behind* as a hatched bar, so
  plan-vs-actual reads at a glance.
- **Google Calendar gets in via .ics import** (user's choice: fully offline, no OAuth, no Google
  Cloud project, nothing leaves the machine). Drop exports in `~/.mainframe/calendar/import/`.
  `backend/icsimport.py` is a **dependency-free RFC 5545 reader**.
- **Suggestions are computed, never guessed** (user's choice). Every one carries a `why` naming the
  numbers behind it, and actionable ones carry a one-click `action`. Deliberately not an LLM —
  nothing here can hallucinate a meeting. Five generators: clashes · due-soon with no time booked ·
  free gaps matched against what's actually due · overdue · neglect (recovery vs workouts). This is
  also the tool surface the **voice agent will drive later**, which is exactly why it returns facts
  and not prose.
- **Planning closes the loop**: "book time for it" opens a pre-filled block already linked to the
  task (`(:CalEvent)-[:PLANS]->(:Task)`), and once booked, the suggestion **stops appearing** and the
  day's free gap recalculates. Verified live: 7 suggestions → 6, gap 08:00–14:00 → 16:00–22:00.

**The .ics cases that break naïve parsers — all handled and tested:**
- **Line unfolding.** Long titles are split across lines with a leading space. Parse line-by-line and
  every long event title arrives silently truncated.
- **Params vs values.** `DTSTART;TZID=Europe/London:2026…` splits on the FIRST colon — a URL in
  DESCRIPTION has its own colons, so splitting on the last (or every) colon corrupts data.
- **Escaping.** `\,` `\;` `\n` `\\` are escapes; a location reading "Hall B, Main Building"
  arrives with a stray backslash otherwise.
- **UTC.** `…T090000Z` must convert to local or every imported event sits an hour out for half the
  year. Verified: 09:00Z → 10:00 BST.
- **All-day DTEND is EXCLUSIVE.** A one-day event ends on the *following* day; stored as-is it spans
  two days, every time.
- **RRULE** expanded into concrete days inside a bounded window (unbounded expansion of "every
  weekday forever" is an infinite loop), with `EXDATE` cancellations and `COUNT`/`UNTIL`/`INTERVAL`/
  `BYDAY`. Anything more exotic falls back to the single start date — **a wrong repeating event is far
  worse than a missing one**, because it fills the calendar with fiction. Verified: `WEEKLY;BYDAY=MO,WE;
  COUNT=6` minus one EXDATE → exactly 5 occurrences. `STATUS:CANCELLED` dropped.
- **Month arithmetic that survives the 31st** — the 31st + 1 month has no correct answer; clamped.
- **Imported events are read-only in the UI**, with an amber banner saying why: editing one here
  would be silently overwritten by the next import.

**Three bugs found by testing, all mine:**
1. `coalesce(e.end_date, e.date)` **silently hid every event** — `end_date` is stored as `""`, not
   null, and `"" >= "2026-07-25"` is false. Neo4j has no `""`→null coercion; a `CASE` is required.
2. **`$from` never bound.** Python can't have a parameter named `from`, so the kwargs sent `from_`
   while the Cypher asked for `$from`. Renamed to `$start`/`$end`.
3. My own fix-up `sed` then turned `$today` into `$endday`, because **`$to` is a prefix of `$today`**.
- Also fixed: the modal called `api.tasks.list`, which doesn't exist — tasks are fetched with the
  generic `api.get("/api/tasks")`. It now falls back rather than blocking event creation.

**Not built (deliberate):** the voice agent (user said later — the suggestion engine and event CRUD
are its tool surface), recurring events *created* in-app (only imported ones recur), reminders/
notifications, drag-to-move, and two-way Google sync. The .ics parser is the same work either way, so
adding secret-URL polling later is small.

- Verified in-browser across month/week/day: real clash detected, task due shown, import panel,
  read-only guard, book-time flow end to end. **All test data purged — 0 events, 0 .ics files;
  the 5 real tasks untouched.** `calendar.js?v=3`, `api.js?v=25`, `modules.js?v=11`, `main.css?v=57`.

### 2026-07-30 — "Add everything you can": the catalogue goes to 4,037,170 foods  ✅
Three more sources on top of the morning's 13,602. Every one openly licensed, every one now
permanent and offline.

| Source | Foods | Why it's here |
|---|---:|---|
| Open Food Facts (ODbL) | 2,158,620 | Packaged products **with barcodes** — the UK supermarket shelf |
| USDA Branded (public domain) | 1,862,096 | US packaged products, also with barcodes |
| USDA SR Legacy | 7,793 | Classic whole-food tables |
| USDA FNDDS | 5,431 | Foods as eaten, best portion data |
| **UK CoFID** (OGL) | 2,852 | **McCance & Widdowson — the UK's own tables** |
| USDA Foundation | 378 | Newest lab analyses |

- **`search "wholemeal bread"` now returns Hovis, Kingsmill, Warburtons, Sainsbury's, Tesco and M&S**,
  each with its barcode, and picking one offers "1 slice (29 g)" as the default serving. That is the
  thing MyFitnessPal did that this app couldn't.
- **Type a barcode and it goes straight to the product** (`5010003000247` → Hovis Wholemeal, 6 ms).
  Any all-digit query of 8+ characters is treated as a barcode before it's treated as a name.
- **Whole foods outrank packaged ones.** With ~4M packaged rows against ~16k reference foods, a plain
  search for "banana" would otherwise return several hundred cereal bars. Results are grouped
  (reference sources first), then scored within the group — so "banana" gives *Bananas, raw* but
  "hobnobs" still works, because no reference table has ever heard of a hobnob.
- **Open Food Facts is crowd-sourced, and the app says so.** Adopting an OFF food sets
  `verified: false` (every other source sets true) — the flag's whole value is that distinction. The
  source tooltip says it outright. Expect a wrong entry occasionally: the same Hobnobs pack appears at
  491, 472 and 100 kcal depending on who typed it in.

**Performance work this needed — the naïve version would have taken hours:**
- **`run_write` opens a session per call.** Right for a request, badly wrong for a bulk import: it
  held the writer to ~200 rows/s. One session per source took it to **~5,400 rows/s** (~20×).
- **Dropped `OWNED_BY` on `:CatalogFood`.** Every other node in the app is owned by a module, but this
  is Mainframe-level reference data and the edge would have cost 4 million relationships to answer a
  question nobody asks.
- **Per-source counts are cached on a `:CatalogMeta` singleton.** `count(c)` grouped by `c.source` is a
  full scan of 4M nodes, and the Food Database tab asked for it on every render. (A *bare* label count
  is free — it uses Neo4j's count store — so the boot check still counts live.)
- **The full-text query is capped at 400 candidates before re-ranking.** Uncapped, a common word like
  "chicken" makes the procedure stream all ~100k matches before the sort can begin.
- Result: **searches run in 7–20 ms across 4,037,170 rows**; the store is 3.2 GB.

**Data quirks that would have silently corrupted things:**
- **Open Food Facts states minerals and vitamins in GRAMS**, USDA in mg/µg. Import `sodium_100g`
  as-is and a bag of crisps reports 0.5 mg of sodium. Verified after the fact by comparing medians
  across sources — OFF 304 mg vs USDA Branded 338 mg, so the ×1000 is right.
- **Its export is unquoted TSV containing stray quote characters.** Letting `csv` interpret them
  merges rows into nonsense; `QUOTE_NONE` is mandatory.
- **Anyone can edit OFF**, so every row passes a sanity check (≤900 kcal/100 g — pure fat is 900 — and
  no macro over 100 g per 100 g) and must carry a name and all four macros. That's what takes 4.5M raw
  rows down to 2.16M usable ones.
- **CoFID's 'Tr' means trace (≈0, known) and 'N' means not measured (unknown).** Treating 'N' as zero
  would state that 90 foods contain no vitamin C, which is a different claim entirely.
- **CoFID's "Group" column is a two-letter internal code** (`DR`, `FA`, `JA`) — deliberately not
  carried through as a category; the food's name is a far better signal.
- **USDA Branded turned out to be 1.86M rows, not the ~450k advertised** — it's the full historical set.

**New dependency: `openpyxl==3.1.5`** — CoFID ships as an .xlsx and there's no other way in. Pure
Python, MIT, local-only.

- Boot screen now reads `food catalogue · usda · open food facts · cofid — 4,037,170 foods [ OK ]`.
- Sources live in `~/.mainframe/foodcatalog/source/` (~460 MB). `POST /catalog/import?source=` limits a
  re-import to one source; a full rebuild should be run as `python foodcatalog.py`, since ~15 minutes
  is far too long to hold an HTTP request open.
- **Two bugs found by testing and fixed:** the adopt modal captioned every food "USDA …" including the
  Open Food Facts ones, and an adopted food recorded `source: "usda"` regardless of where it came
  from. Both were fine when USDA was the only source and wrong the moment it wasn't.
- Verified in-browser: 4,037,170 shown across six sources · "wholemeal bread" → UK supermarket brands ·
  barcode → one product · adopt Hovis at 1 slice (29 g) → **64 cal · P2.9 C11 F0.5**, brand and barcode
  carried into My Foods. **All test data purged — 0 foods, 0 entries.**
  `nutrition-catalog.js?v=3`, `boot.js?v=5`.

### 2026-07-30 — A permanent food database: 13,602 USDA foods in the graph (user request)  ✅
The gap the user named: Nutrition had every MyFitnessPal *feature* but none of its *catalogue*, so
every food had to be typed in by hand. MyFitnessPal itself is not an option — its public API has been
closed to new developers for years, and scraping it would breach their terms and the local-first rule
both. **USDA FoodData Central is public domain**, so it can simply live in the graph forever.

- **`backend/foodcatalog.py`** — parses three FDC archives straight from their zips (no extraction) and
  MERGEs them into Neo4j. **SR Legacy 7,793 · FNDDS 5,431 · Foundation 378 = 13,602 foods**, each with
  per-100g macros, up to 19 nutrients and real portions ("1 cup = 244 g"). ~70 s cold, ~5 s to re-run.
- **Two `:Food` tables, deliberately.** `:CatalogFood` is read-only reference data; `:Food` is still
  your personal library, still starts empty, still sorts most-used-first. Adopting **copies a
  snapshot** — so the spec's "never pre-populate" rule survives intact, 13k rows never drown My Foods,
  and a future re-import can't rewrite a food you've been logging for months.
- **Per-100g → per-serving happens exactly once, at adoption**, where you pick a portion and *see the
  converted numbers before committing*. USDA states food per 100 g; NUTRITION_SPEC states it per
  serving; that modal is the only place the two meet.
- **`GET /catalog`** (full-text, CONTAINS fallback) · `/catalog/status` · `/catalog/{id}` ·
  `POST /catalog/{id}/adopt` · `POST /catalog/import`. New tab **Food Database** (order 35) plus a
  picker modal reachable from My Foods — one code path, `window.NUT.catalogPicker`.
- **Boot screen now reports it**: `food catalogue · usda fooddata central · 13,602 foods [ OK ]`. An
  empty catalogue should be visible at boot, not discovered mid-meal.
- **Three things that cost real time, worth remembering:**
  1. **FNDDS states nutrients by `nutrient_nbr`, not `nutrient_id`** — its `food_nutrient.nutrient_id`
     column holds 208/203/301 where the other two archives hold 1008/1003/1087. Map one way only and
     5,431 foods import with every nutrient silently blank. The lookup is keyed on both.
  2. **The Foundation archive is ~88,000 rows of laboratory bookkeeping** (`sample_food`,
     `sub_sample_food`, `market_acquisition`) around 378 real foods. Filter on `data_type`.
  3. **My first Lucene escape missed `,` and `%`**, so a search for `milk, 2%` became
     `milk,* AND 2%*` and matched nothing — while `chicken breast` worked fine, which is exactly the
     kind of bug that ships. Queries now reduce to plain alphanumeric words, and the CONTAINS fallback
     requires all words rather than the raw string.
- Also: FNDDS foods point at a **WWEIA** category, not a `food_category` — without loading
  `wweia_food_category.csv` every survey food imports uncategorised. And USDA's own category names
  ("Bananas") don't map to the app's buckets by keyword alone, so `_app_category()` reads the name too.
- Verified in-browser end to end: search → 40 results with source badges → adopt "Chicken, breast,
  boneless, skinless, raw" at 175 g (live preview 186 kcal / P39.4 / F3.4, exactly 1.75× the per-100g
  figures) → appears in My Foods → logged to Lunch → **dashboard reads 186/2200 with the protein bar at
  25%**. Re-import is idempotent (13,602 → 13,602, no duplicates). **All test data purged — 0 foods,
  0 entries, 16 test log rows removed; the catalogue and the genuine import log row kept.**
- Archives live in `~/.mainframe/foodcatalog/source/` (12.7 MB), so re-import works offline forever.
  `nutrition-catalog.js?v=1`, `nutrition-foods.js?v=3`, `api.js?v=24`, `main.css?v=56`, `boot.js?v=4`.

### 2026-07-29 — Reference Map: a source is drawn as what it is (user request)  ✅
- **`kind` now reaches the graph payload** (`refgraph.py` returns `coalesce(p.kind,'paper')`). `type` stays `"paper"` — the renderer keys layout, edges and filters on it — while `kind` decides how the node is *drawn*.
- **Kind-specific colour AND shape**: paper = teal circle · **book = gold square** · video = red triangle · course = purple diamond · article = cyan circle · note = grey diamond. Shape as well as colour, so the distinction survives for anyone who can't separate the hues. Canvas has no polygon primitive, so `nodePath` spells the four shapes out.
- Legend counts each kind actually present with its own glyph, and the detail panel reports the kind rather than the generic type.
- Verified in-browser: all three books render as gold squares among nine teal paper circles; legend reads `■ books 3 · ● papers 9`. `refgraph.js?v=5`.

### 2026-07-29 — Repository: hide finished papers, move the cards (user request)  ✅
- **Cards are movable.** `:Paper` gained a `position` float and `POST /papers/reorder`, reusing the same `reorder_nodes` helper as mind-dumps, ideas and reading passes. ◀ ▶ on each card. A `db.py` migration seeds `position` **from the order they're already displayed in** (year desc, added_at desc), so nothing jumps the first time an arrow is used. Manual order wins in the list query; anything never moved keeps the old newest-first arrangement.
- **Finished papers hide.** `read` is the finished state (`revisit` deliberately isn't). Hidden by default, remembered across reloads, with a `finished hidden ⇄ ✓ finished shown` toggle and a count of what's hidden. Selecting the `read` status filter overrides the toggle — that filter is explicitly *about* finished papers. `revisit` added to the status dropdown, which had been missing it.
- **Bug found by testing, and it was mine from earlier today: `◀` did nothing.** `reorder()` gives the listed ids the slots those nodes already hold *in the order listed*, so passing `[b, a]` to move `a` **earlier** merely restates the existing order — a silent no-op. `▶` worked, which is why it looked fine. The pair is now ordered by direction. **The same bug was in the workspace's reading-pass arrows** (written earlier today) and is fixed there too.
- Verified in-browser: 12 cards → toggle → 11 with "1 finished paper hidden"; ◀ moved Sample Paper B above Sample Paper C, ▶ put it back. Test log rows purged, original order restored. `repo.js?v=9`, `workspace.js?v=15`, `api.js?v=23`, `main.css?v=53`.

### 2026-07-29 — Workspace: flag work that never got time logged (user request)  ✅
The user expected "each time I do something I'd log it" and asked whether anything checks. **Nothing did** — the two records existed and were never compared.
- **`GET /api/work/gap?ref_id=`** compares the `:ChangeEvent` trail (what you *did*) against `:WorkSession` rows (what you *logged*). Anything done after the last session you logged is, by definition, time not in the database. Read-only and derived — nothing is written or guessed.
  - Filters out rows that aren't *doing* something — `status` changes and the work log's own `work logged` / `completed` entries — otherwise every paper would look permanently unlogged.
- **A banner at the top of the Workspace**: `⏱ 31 things done here since you last logged time — nothing logged yet`, with **show what** (a dated list of the actual events) and **+ log it now** (the work-log form, pre-filled and locked to this paper).
- **When there's nothing outstanding it says so** — `✓ All work here is logged — 2h 10m across 3 sessions` — rather than showing nothing, so "no banner" can never be mistaken for "we didn't check".
- Verified on real data: Sample Paper A showed **31 unlogged actions, 0 sessions**; Sample Paper B 18. Expanding listed them with timestamps, category and detail. `workspace.js?v=14`, `api.js?v=22`, `main.css?v=52`.

### 2026-07-29 — NUTRITION_SPEC increment B: all eight tabs  ✅ — **NUTRITION COMPLETE**
- **`nutrition-common.js`** holds the vocabulary the spec fixes — meal slots, food categories, serving units, **macro colours (protein blue · carbs amber · fat pink)** and the shared `calorieRing`/`macroBar` — so eight tabs can't drift apart on naming or colour.
- **Dashboard** — the calorie ring is the hero visual the spec forbids skipping. **The arc is clamped at one full turn**: 3,000 calories over target must not wrap twice and read as "nearly done". Macro bars, meal-summary cards for every slot (logged or not), water, weight, streak, weekly average. The weight arrow states the *direction* and its colour states whether that's the direction you wanted — down is only "good" when the goal is to lose.
- **Food Log** — collapsible meal slots with per-slot totals, and all four ways in the spec demands: library search (most-used first), **quick add inline under every slot** (four fields, Enter saves), **copy a day or one meal**, and **bulk paste with a preview** where unreadable lines are listed with a reason rather than dropped.
- **My Foods** — starts empty, sorted most-used first, star for favourites. Only name, serving and four macros are asked for; the ten optional nutrients hide behind a toggle. Deleting a food warns that logged entries keep their numbers.
- **Recipes** — totals and per-serving are always derived, never typed. Ingredients come from the library *or* are typed freehand; a library food scales by amount, a typed one is taken as entered. One click logs a serving.
- **Water** — an SVG bottle that fills (clipped rect, not a percentage-height div — those collapse in flex), quick-add buttons, custom amount, per-entry times.
- **Weight & Body** — graph with daily dots **and** the smoothed weekly-average line, target line, BMI; measurement table showing latest vs previous with delta arrows, and the log form only offers fields you've used before. Progress photos via the shared image service.
- **Fasting** — a live circular timer ticking each second, protocol presets, and history. The ring fills to the target and stops there, since 17 of 16 hours is a success not an overflow.
- **Goals** — grams ⇄ percentage kept in step via 4/4/9 kcal per gram, three presets, and a running check that **warns when the macro split doesn't add up to the calorie target** — the classic way targets end up quietly wrong.
- **Bug caught before it shipped:** `PULSE.modal` calls `a.onClick(close)` unconditionally, so the `{label:"Cancel"}` actions I first wrote would have thrown on click. Every Cancel now carries `onClick: (close) => close()`, matching the convention the other Pulse views already use.
- Tabs register with an **`order`**, so the bar's sequence no longer depends on script load order in index.html. Superseded `nutrition-diary.js` and `nutrition-weekly.js` removed (their job is now Food Log + Dashboard).
- Verified in-browser: 10 tabs in order; seeded a food → logged it → quick-added → water → weight, and the **dashboard read 568/2400 kcal with 1832 left, P51/170 C44/260 F19/80, 750/3000ml, 76.8kg, 1-day streak, 2 entries**, with Lunch 248 and Snacks 320 against four "not logged" slots. **All test data purged — dashboard back to 0 cal, 0 entries.** `main.css?v=51`, `api.js?v=21`.

### 2026-07-29 — NUTRITION_SPEC increment A: the whole backend  ✅
New authoritative spec `~/Downloads/NUTRITION_SPEC.md` (19 KB, 19:59) — Nutrition rebuilt as an 8-tab MyFitnessPal replacement. This increment is the complete backend; the frontend follows tab by tab.
- **Audited the data first: nothing of the user's was at risk.** 76 seeded foods, but **0 food logs, 0 targets, 0 intolerances, 0 supplements** and 0 custom foods. So the spec's "**Do NOT pre-populate the food database — it starts EMPTY**" could be honoured cleanly: the seeder and its 76 generic foods are gone.
- **Per-serving, not per-100g.** The old schema stated everything per 100g; the spec states it per serving ("a slice", "a scoop", "150g"), so logging is *"one of those"* rather than arithmetic. Only name, serving and the four macros are required — every micronutrient is optional, per the spec's explicit DO-NOT.
- **Entries snapshot their macros.** Correcting a food later must not silently rewrite what you ate last month — the same rule Vault follows for transactions and Synapse for paper titles. Deleting a food leaves logged entries intact.
- **All eight areas implemented** in `routes/nutrition.py` (~30 endpoints): goals · my foods (search, category filter, **most-used-first**) · food log grouped by meal slot with per-slot totals · **quick add** · **bulk paste with a mandatory dry-run preview** · **copy meals** (whole day or one slot) · recipes with auto-calculated totals and per-serving · water · weight with a **smoothed weekly average** · body measurements with **BMI-style ratios only where the inputs exist** · fasting · dashboard.
- **Recipes take ad-hoc ingredients.** The spec's `(:Recipe)-[:CONTAINS]->(:Food)` edge is drawn for library foods, but ingredients typed freehand live in the recipe's JSON — a recipe must not demand that everything in it already exists as a Food. Neo4j can't hold a list of maps, hence the JSON property alongside the edges.
- 12 constraints/indexes added to `db.py` exactly as the spec lists them.
- **Verified end to end by API**: empty food DB → create food → log it → `use_count` bumps → quick add → bulk paste preview (**3 parsed, 1 bad line reported per-line, not dropped**) → real import → day grouped by slot → recipe totals 482 cal / 241 per serving → log a serving → water 1250/3000 → weight trend −2.3 kg with weekly averages → waist-to-height 0.491 → fasting start, **double-start refused (400)**, end at 17h of 16h = completed → copy dinner to another date → dashboard showing calories/protein/water/weight-trend/streak/slots. **All test data purged.**
- Kept intolerances and supplements: they pre-date this spec, which neither lists nor forbids them, and there was no reason to delete working features.
- **Still to build:** the 8 frontend tabs (`nutrition-dashboard/log/foods/recipes/water/weight/fasting/goals.js`), including the calorie ring, fasting timer, weight graph and progress-photo comparison.

### 2026-07-29 — Paper Timeline reverted to a scroll (user request)  ✅
The lineage graph built an hour earlier was **removed at the user's request** — "it doesn't need connections, it can be a scroll". The picture-of-lineage job already belongs to the Reference Map, which has the room for it.
- Now a straight scroll of the whole library, oldest year first, undated last, with a per-year entry count. Each row: kind icon, title, authors, venue, read status, and **`cites` / `cited by` only when non-zero** — a column of zeroes is noise.
- The citation counts still come from the KG endpoint (`type` field, not `kind`), so a resolved reference counts the same as a manual `:CITES`.
- **Video series already work in the Reference Map** — verified by creating one: it drew as a **red triangle**, a `videos` toggle appeared in the toolbar automatically, and the legend read `▲ video 1`. Nothing was missing; there simply weren't any video-kind sources. Test source removed afterwards.
- `timeline.js?v=6`.

### 2026-07-29 — Paper Timeline: lineage drawn along time (user request)  ✅
- **Tab renamed Timeline → "Paper Timeline"** (the label lives on `Views.timeline`, so one word does it).
- **New lineage graph above the year list.** Papers sit at their publication year on a horizontal axis; every paper→paper citation is drawn as a curve with an **arrow from the older work to the paper citing it** — influence's actual direction, so a foundational paper is the one several arrows leave. Hand-rolled inline SVG, no libraries.
- Node size grows with how many links a paper has; colour is its read status. **Click a paper to isolate its lineage** (everything unrelated dims); click again to clear. Undated papers get their own lane rather than being dropped.
- **Citations that run backwards in time are drawn amber and counted**, not hidden — either the years or the citation is wrong, and that's worth seeing. One in the current library.
- **Two bugs found on screen:**
  1. **0 links at first.** The KG endpoint names the relationship **`type`** (`"cites"`, `"cites (reference)"`) while the reference-map payload uses `kind` — I filtered on the wrong field. Fixed; 9 links appear.
  2. **Labels overlapped into mush.** Per-year stacking isn't enough — papers a year apart still collide, because a *label* is ~190px wide. Replaced with **greedy lane packing**: sweep left to right, take the first lane whose previous label has ended (the same trick the script markers use for overlapping ranges). Right margin widened to 210 so the last titles aren't clipped.
- Verified: `12 papers · 9 citation links · 1 run backwards in time (amber)`; Sample Paper A (2012) → Sample Paper D (2017) → Sample Paper E (2021) → Sample Paper F (2024) reads as a chain, and clicking Sample Paper A dims everything not in its lineage. `timeline.js?v=5`, `main.css?v=50`.

### 2026-07-29 — Reference Map: per-kind and shared-only toggles (user request)  ✅
- **One toggle per source kind actually present** — `books`, `papers`, and any future kind — **built from the data**, so a new kind appears without a code change. Books can be shown without papers, or on their own. `filters.kinds` defaults to shown for anything unlisted, so a new kind can't vanish by omission.
- **`shared only`** hides every reference cited by just one paper. What's left is the skeleton: the papers, the books, and the 11 works that actually connect them — 268 leaves drop away and the structure becomes readable in one glance.
- Edges needed no change: the draw loop already skips an edge whose endpoint is hidden, so hiding a kind removes its links too.
- Verified in-browser: toggles read `books · papers · references · manuals · shared only`; papers-off leaves books, books-off leaves papers, refs-off leaves the hubs, and shared-only produces the connection skeleton. `refgraph.js?v=7`.

### 2026-07-29 — Reference Map: shared works merged at render time (user request)  ✅
The overlap measured below is now visible. **Storage is untouched** — still one `:Reference` per paper, which is what lets each paper keep its own read-state for the same cited work. The merging happens only while building the payload.
- **`refgraph.py`** groups references by normalised title (case and punctuation vary between bibliographies for the same work, and neither may split it in two). One node per distinct work, an edge to **every** citing paper, `paper_ids` + `ref_ids` carried on it, `shared` set when more than one paper cites it. Node id is `"ref:<key>"` — synthetic but **stable**, so dragged positions survive a reload.
- **A reference that resolves to a paper you hold gets no leaf at all** — the edge goes straight to the real paper (`matched_paper_id`, or a title match), with a self-edge guard. Duplicate edges from a resolved reference and a real `:CITES` are de-duped.
- **`refgraph.js`**: shared nodes are pink, larger in proportion to how many papers cite them, outlined, and **labelled unprompted** — they're what you're looking for. The source filter treats a shared node as belonging to every paper citing it, and the detail panel lists every citing paper rather than one.
- **Result on the real data: 284 reference rows → 268 nodes, 11 shared, 3 resolved to papers, 0 dangling edges.** The map went from nine isolated stars to one connected structure, with *A survey of graph databases* (3 papers), *Efficient index structures*, *Scalable query planning* and eight others sitting as bridges between clusters. Legend reads `■ books 3 · ● papers 9 · ● refs 268 · ● shared 11 · ↳ resolved 3`.
- **Fixed while writing it:** `Element.append()` is not `el()`'s children list — a `null` there renders the literal text "null". Nulls are filtered before appending.
- ⚠ **Not verified by click:** the detail panel listing all citing papers is implemented but I could not land a canvas hit-test under browser automation (the node radius is a few pixels and synthetic mouse sequences missed). Everything else here was confirmed on screen. `refgraph.js?v=6`.

### 2026-07-29 — Answered: is there overlap between papers? (measured, not changed)
**Yes — the data has overlap; the map can't show it.** Measured across 284 reference rows → 271 distinct works: **12 works are cited by more than one paper** (*A survey of graph databases* by three), and **2 references are papers held in the repo**.
It doesn't appear because each `(:Paper)-[:REFERENCES]->(:Reference)` creates its **own `:Reference` node per paper** — the deliberate no-dedup design ("papers are hubs, refs leaves"), which is also what lets each paper carry its own read-state per reference. So a shared work exists twice and the hubs never touch. **Left as-is and raised with the user** rather than reversing an earlier decision unasked; the fix would be to merge on normalised title at graph-build time only, leaving storage alone.

### 2026-07-29 — Repo card layout + the reference scan losing whole citations (user request)  ✅
- **Year/venue moved off the top of the repo card** to a footnote just above the buttons, so the title leads. It's now **absent** when there's nothing to say rather than showing an em-dash.
- **The real bug behind "it's scanning but not getting the whole title."** Traced from the actual data: one stored reference read **`'Planni'`**. The scan merges the local model's parse with the literal parser's and dedupes on title — and a truncation normalises to a *different* key than the full title, so the fragment survives as its own reference.
  - Root cause, found by re-running the parser on the source PDF: **`split_entries` found only 8 entries in a 24,117-character bibliography.** That paper's references are author-first with no `[n]` markers and wrap without blank lines, so blank-line splitting returned a few enormous blocks holding dozens of citations each. The literal parser therefore never saw that citation at all, and the model's truncated guess was the only thing left to store.
  - **New `_split_author_first`**: a line starts a new entry only when it *looks like an author list* **and** the text so far *looks finished* (ends on a year, page range, DOI tail or bracket). Requiring both is what stops a wrapped title line beginning with a capitalised word from cutting an entry in half. **8 → 45 entries**, and the lost citation now parses in full: *"Planning with learned models under sparse rewards"*.
  - **`_drop_truncations` in llm.py** as a second line of defence: a title is dropped when another starts with it **and the cut fell mid-word**. That distinction is the whole point — `"Graph models"` prefixes `"Graph models are strong baselines"` but breaks at a word boundary, so it's a real, distinct reference and stays; `"Planni"` / `"Sparse indexing at sca"` do not.
- Checked for regressions across every stored PDF: 26 / 62 / 40 / 7 / 66 / 45 entries, all with usable titles. One paper still yields 3 weak ones (`"In ICCV"`, `"21"`) from its own layout — pre-existing, not introduced here.
- **Repaired the live data**: the `'Planni'` reference now carries its full title. No reference in the database has a title under 8 characters. `repo.js?v=7`.

### 2026-07-29 — Learning: diary entries, growable lists, habits, and a database on top (user request)  ✅
- **Overview vs. the long version.** `what_happened` stays the one-line overview you scan the table by; new **`detail`** is the diary entry behind it — what led to it, what you were doing. On the card and in the log-one form.
- **Two growable lists, `ideas` and `consulted`.** Each entry is its own box with `+ add` and ×, numbered, so you keep adding — idea one, idea two — rather than reorganising one blob. `consulted` is for "asked X this, and this came back" (person or AI). Both save as a whole list, so removing one is a save like any other edit.
  - **`update_opportunity` switched to `exclude_unset`** (then drops explicit nulls): under `exclude_none` an empty list read as "no change", so **clearing every idea was impossible**. Verified `{"ideas": []}` now clears while leaving `consulted` alone.
- **Types of mistake are a managed catalogue with high-level habits.** `:LearningKind {name, group}` — the kind is what you file under ("missed a deadline"), the **group** is the habit it rolls into ("scheduling"). A kind is **auto-registered the moment it's used**, so the catalogue describes reality instead of needing curation, and a `db.py` migration registered every kind already in use. `/summary` gained a **habits** rollup: count, active, resolved, the kinds inside it, and **days since it last happened**. Removing a kind leaves entries filed under it untouched — deleting a label shouldn't rewrite what you wrote.
- **A database above the log.** Sortable on every column (When · What happened · Kind · Habit · Module · Status · ideas/asked/notes counts), **group by habit**, and **resolved hidden by default** with a toggle. Clicking a row opens that card below and scrolls to it. Summary sits above it, exactly as asked.
- **Direct push to Learning from three more places.** The push modal moved to `window.LearningPush` so one modal and one wording serves all of them: **each distraction row** in a reading pass now has its own `↗` (the whole-set button remains — one entry for the session, or one per recurring interruption, which is what repeat detection actually needs), plus `↗ learning` on **project cards** and on **deep dives** (pre-filled with the topic and its notes).
- **Bug caught on screen:** the pluraliser rendered "2 entrys". Now handles consonant-y → -ies.
- Verified end-to-end: seeded two entries under one habit → summary showed `×2 zztest scheduling · 2 active · last 2 days ago` with both kinds; diary and consultation round-tripped; two ideas added through the UI and read back from the API; group-by-habit, column sorting and the resolved toggle all worked. **All test entries, kinds and log rows purged.**
- ⚠ **Finding worth recording: the Learning tab had no entries before this work.** Eight `learning logged` rows sit in the activity log, all stamped `2026-07-28T18:00:08` — one batch, one instant — with **no matching `:LearningOpportunity` nodes and no `learning deleted` rows**. That signature (seeded, then removed with a direct Cypher delete, which writes no log row) matches this project's own test-data cleanup pattern. Today's only learning deletion was scoped to `ZZTEST` and removed exactly the one row it reported.

### 2026-07-29 — Database: custom kinds, period views, "completed", distraction gone (user request)  ✅
Five asks on the Database tab.
- **Distraction columns removed.** `distraction_mins` and `distraction` are out of `COLUMNS` (which drives the table *and* the CSV header) and out of the log-time form — the reading workspace now records distractions properly, one entry per interruption. **The properties are still accepted and still on old rows**; they're simply no longer collected or shown, so nothing already logged was destroyed. The "distracted" stat tile went with them.
- **Deleting a row was already possible — but unreachable.** The × sat in the *last* column of a table that scrolls sideways past a dozen columns. It's now the **first** column, and the confirm names the row (date · duration · what) instead of asking "Delete this row?" about something you can't see.
- **`pushed` → `completed`.** Same flag, a name that says what it means, migrated in `db.py` (`completed = coalesce(pushed, false)`) with the old property left in place so nothing reading it breaks. It's a checkbox in the table, so it's set by hand per row; the day rollup `coalesce`s both, so the contribution grid keeps starring the same days.
- **Day · Week · Month · Year views, with Rows as the default.** A toggle above the toolbar; the choice persists. Each period row totals time, sessions, days, active, passive, completed and which modules were touched. **Day/month/year bucket by slicing the ISO date string** — never constructing a `Date` — so a timezone can't shift a row into the wrong day; weeks need real date maths and use UTC with the ISO-8601 Thursday rule.
  - **Bug caught on screen:** week rows read `Wk 30 · 07-26 → 08-01` and `Wk 31 · 07-27 → 08-02`, which look like overlapping ranges. They were different *years*. The label now leads with the year.
- **Kinds are user-defined.** `RefKind` stopped being a closed `Literal` (which would have rejected a kind you'd just made) and kinds live as `:WorkKind` nodes: `GET/POST/DELETE /api/work/kinds`, seeded with the original six on first read. `+ kind` adds one; it appears in the column dropdown, the filter and the log-time form, and sorts like any other column. **Removing one is offered only while that kind is the active filter** so it's unmistakable which goes — and **rows already filed under it keep their value**, because deleting a label shouldn't silently rewrite history. Built-ins are refused by the server, not just hidden.
- Verified end-to-end: kinds seeded and a custom `book` added, used on a row, filtered by, and counted in the day rollup's star; `DELETE /kinds/task` refused with 400; CSV header now `…,notes,completed`; all four period groupings bucket correctly and the choice persists; delete × is column one; remove-kind appears for `book` and not for built-ins. **Test row and its log entry purged — 5 real rows untouched.** The custom kind **`book` was left in place** — it's the example you named; remove it with `× kind` if you don't want it. `work.js?v=5`, `worklog.js?v=7`, `api.js?v=20`.

### 2026-07-29 — Workspace: distractions after the write-up, delete from the pass chip (user request)  ✅
- **Distractions moved below the "what you took away" box.** What you took away is the point of the session; what interrupted it is the postscript, so the order now reads look-into → notes → distractions.
- **Every pass chip has its own ×.** `delete pass` already existed *inside* the session form — but the form can now be folded away, and you shouldn't have to open a pass to get rid of it. Both call one shared `deletePass()` so the warning can't drift between them; it names the purpose, says the highlights and notes go while **the original PDF and the frozen auto-KG stay**, and warns when it's the paper's last pass. Deleting the pass you're viewing clears `activeInstance` so the next render picks another rather than drawing an empty form.
- Verified: both chips carry a correctly-labelled ×, field order confirmed in the DOM (look-into → notes → distraction list), and the endpoint the × calls returns 204. **The × itself was not clicked in testing — `confirmDo` uses `window.confirm`, which hard-freezes the tab under Chrome automation.**
- **Noted, not fixed:** two *overlapping* `activate()` calls can double-render a view (I reproduced it by calling `selectPaper` and `openModule` back to back in the console — "Reading instances" appeared twice). A single navigation and in-view re-renders both render once. It's the same race `app.js` already guards the log-time button against, and fixing it properly means giving every view a render token. `workspace.js?v=12`, `main.css?v=48`.

### 2026-07-29 — Workspace: a distraction list, foldable session boxes, mind dump by the highlights (user request)  ✅
- **Distractions are a list now, one row per interruption.** `distraction_types` (a single comma-joined string) became **`distraction_items: list[str]`** — a string can't say what each separate interruption was. Numbered rows with their own × , a `+ add distraction` button, and a `db.py` migration that **splits the old string on commas** so anything already written is carried over rather than dropped. The Master Instance renders them one per line under a `4×` tag.
  - **The count stays yours to set** — you might be pulled away five times and only describe three — but it can never sit *below* what you've listed, so adding a row bumps it if needed.
  - The Learning push uses **the first entry as `kind`** (the field Learning groups repeats by) and the rest as detail; one kind per entry would fragment the grouping and defeat the repeat detection.
- **Click the pass you're on to fold its boxes away.** The active chip toggles `▾ / ▸`; the pass stays selected (the highlights below still belong to it) and only the logging form hides. Remembered in `localStorage`, so a paper you're *reading* rather than logging stays uncluttered between visits.
- **Mind dump moved into the right column, directly above Highlights** — a thought that arrives mid-read gets caught next to where you're writing the highlights, not across the page.
- **Two pre-existing bugs found by the toggle** (a re-render is what exposed them):
  1. **`+ log time` vanished from the header after any workspace re-render.** The button is mounted by the shell in `activate()`, but the workspace redraws itself after every save, rebuilding the head without it. `window.remountWorkLog()` added and called from `rerender`.
  2. **…and then mounted twice.** `mountHeader`'s duplicate guard was `viewEl.querySelector(":scope > .wl-header")`, but when a `.view-head` exists the bar is appended *into* the action group — never a direct child — so the guard never fired. Now matches at any depth.
- Verified in-browser: 4 distraction rows round-tripped through save and reload; toggle hides/shows with `stored` flipping `1`/`0` and the chip arrow following; exactly **one** `+ log time` before, during and after repeated toggles; mind dump renders above highlights. **Test pass and its log rows purged — the Sample Paper A entry is back to its single "first read".** `workspace.js?v=11`, `worklog.js?v=6`, `app.js?v=5`, `main.css?v=47`.

### 2026-07-29 — Workspace: movable passes, a Master Instance that sees everything (user request)  ✅
Six asks, all on the reading workspace.
- **Reading passes can be moved.** `:Instance` gained a `position` float and `POST /instances/reorder`, reusing **the same `reorder_nodes` helper** the mind-dumps and ideas already share (so reordering inside a filtered view stays safe). ◀ ▶ buttons on each pass chip swap it with its neighbour. **`version` never changes** — which read came first is a fact; `position` is only how they're arranged, so a pass can be moved without rewriting history. A `db.py` migration seeds `position` from `version`.
- **Master Instance moved to the top** of the workspace — it's the whole paper in one place, so it reads as the summary the passes below feed into rather than an afterthought.
- **Ideas written in the workspace now reach it.** The real gap was in `quickidea.js`: the floating capture **never sent `paper_id`**, so an idea had while reading was never linked and could never appear. It now offers a pre-ticked *"link to <paper>"* — but **only when the view on screen is paper-scoped**, because a paper stays "selected" while you're off in Vault and silently filing a budget thought under a paper is worse than not linking at all.
- **The log is in the Master Instance** — `GET /instances/master` now returns the paper's `:ChangeEvent` history (200 most recent) as its own `log` array, rendered as a collapsed *"Everything that has happened to this paper"* section. **Deliberately not merged into `blocks`**: blocks are what you *wrote*, the log is what *happened*, and merging them would bury a highlight under twenty "updated" rows.
- **"To look into later" when a pass is created.** `+ new instance` now opens a modal (purpose + what you already know you want to come back to) instead of silently making a "revisit" pass. Stored as `look_into`, editable afterwards in the session log, flagged with ⌛ on the pass chip, and surfaced in the Master Instance as its own block.
- **Distraction kinds, pushable to Learning.** A count says a session went badly; the kinds say what to change. New `distraction_types` beside the count, plus **↗ push to learning** which pre-fills a Learning entry with the **first type as the `kind`** — that field is what Learning groups repeats by, so the wording has to match what you'd log anywhere else or the repeat detection can't see it. Pre-filled and editable rather than posted silently.
- Verified end-to-end: created two passes with look-into notes → reorder swapped them **with versions unchanged** (v1, v3, v2); master returned `look into`, `distractions (3×)`, `session note`, `idea` and `concept` blocks plus 28 log rows; the pushed distraction landed in Learning as a real entry. **All ZZTEST instances, ideas, learning entries and log rows purged — the Sample Paper A entry is back to its single "first read" pass, and your Sample Paper C (8 passes) and Sample Book (2) are untouched.** `workspace.js?v=9`, `quickidea.js?v=2`, `main.css?v=46`.

### 2026-07-31 — The snapshot: one panel in the top bar for "where am I right now" (user request)  ✅
The ◈ chip already held the phase and the goals. It now opens the whole picture — what you're doing, what's on today, what's due — with **you choosing which sections appear**.

- **`backend/routes/snapshot.py`** — `GET /api/snapshot?sections=a,b,c`, plus `GET /api/snapshot/sections` listing what can be served. **Fourteen sections**: Now · Today's calendar · Due · Goals & phase · Suggestions · Reminders & bills · Money · Habits today · Pulse scores · Nutrition today · Moving lately · Learning · Mind Dump · Recent activity. Defaults to the first five.
- **Not one node, table or migration belongs to this file.** Every section re-uses a function the rest of the app already runs — `calendar.range_feed`/`freebusy`/`suggestions`, `focus.overview`, `vault.budget_actual`, `pulsescore.scores`, `nutrition.dashboard`, `recurring.due_now` — so the snapshot can never disagree with the page it summarises. Same rule `/api/focus` was built on: an overview with its own bookkeeping is stale in a fortnight.
- **Only what's asked for is computed**, and the sections run concurrently via `asyncio.gather`, so you pay for the slowest rather than the sum. All fourteen together: **122 ms**.
- **A section that fails returns `{error}`, not a 500.** The panel is the first thing seen on opening the app; one module with nothing set up must never be able to blank the whole overview.
- **The choice lives on the `:Focus` node** as a JSON array (`FocusUpdate.sections`), not localStorage — the panel looks the same in any browser, and the shape is the frontend's, so a future way of arranging it needs no migration. Keys the backend no longer serves are filtered out on load, so a renamed section shrinks the panel instead of emptying it. Toggling a section no longer writes a **"phase set"** row to the activity log — a preference isn't a change of direction, and it would bury the real ones.
- **`frontend/js/focus.js` rewritten** as the panel: a renderer per section, a ⚙ editor (tick on/off, ▲▼ to order), and the phase editor kept at the top. **Live timers tick in place** — only the digits repaint each second (`data-sn-timer`, its own attribute rather than the dock's `data-timer`, since one name for two owners is a trap for whoever queries globally next), so nothing you're typing loses focus and the scroll position survives.
- **The agent brief is both halves.** Suggestions render inline with the `why` naming their numbers — computed, so nothing there can invent a meeting — and **`▷ brief me`** hands the same day to Leo for a prose read-out. `window.Agent` now exposes `name()` so the tooltip reads the assistant's configured name rather than hardcoding one.
- **Bug found and fixed in `calendar.py`:** `range_feed` projected `w.minutes`/`w.title`/`w.kind` on `:WorkSession`, but the properties are **`w.mins`/`w.what`/`w.ref_kind`** — so every logged work block came back unlabelled and with a null duration, which also fed the free/busy maths behind the suggestions. Aliased rather than renamed, so the published shape is unchanged.
- **Race closed:** `open()` is async, so two fast clicks could draw into a panel the first call no longer owned and start a second clock nobody clears. A generation counter makes the later call win.
- Verified in-browser: all five defaults render against real data; four more switched on and **persisted across a full reload** (server-side, in the chosen order); a running timer ticked live in the panel matching the dock; `▷ brief me` closed the panel, opened Leo and sent the prompt. **Pulse's "Fuel" shows a grey `–`, not a red 0** — the not-tracked-isn't-failure rule carries through. Test timers discarded rather than stopped, so **no `:WorkSession` rows were written**. `main.css?v=72`, `api.js?v=34`, `timers.js?v=2`, `focus.js?v=4`, `agent.js?v=4`.
- ⚠ **`▷ brief me` reaches Leo, but Leo can't currently answer.** `POST /api/agent/ask` 502s on the 120 s `llm_timeout_s`. Not this feature: ollama is serving **qwen2.5:7b-instruct at ~0.6 tok/s** (16 tokens in 26 s) despite reporting `100% GPU` on the RTX 5090 Laptop — a trivial "Say OK" takes 28 s, and the agent prompt carries 23 tool schemas. Every Leo call is affected, including Ctrl+K. Likely a Blackwell/CUDA build mismatch in the installed ollama. The deterministic half of the panel is unaffected.

### 2026-07-29 — Tasks: how long it took, and hiding what's finished (user request)  ✅
A task now records both ends of its life, so "is this a short task or a long one" is answered by what actually happened rather than by the horizon it was filed under.
- **`opened_at` — a new, editable start.** `created_at` records when the row was made and never moves (it's the audit trail); `opened_at` is when the work *began* and is yours to set, because a task written down today may have started last week. New-task modal gained a **Started on** field defaulting to today, and a `db.py` migration seeds every existing task's `opened_at` from its `created_at` so nothing starts un-measurable.
- **`done_at` is now genuinely editable.** The old `if "done_at" in data and data["done_at"]` meant a *wrong completion time could never be cleared* — a null was silently ignored. Both fields now test `in data`, so null clears. A `done_at` sent with `done: true` also wins over the automatic stamp.
- **Lifespan editor** in the task's detail panel: `started [date] [time] → finished [date] [time]`, with a **`■ finish now`** button that stamps both at once (a finish time without its date is meaningless) and a live readout that flips **"open 24d" → "took 24d"** as you type. Saving a finish **completes the task**, and clearing it reopens — otherwise a task could claim it ended while still sitting in the active list.
- **The card is tinted by how long it has been alive** — same-day teal · days blue · weeks amber · months orange · a year+ red, as a left-to-right wash so the horizon stripe still reads. **Open tasks tint stronger than closed ones** at the same age: a "short" task still running after a month is the one worth noticing. A badge shows `open 9m` / `took 24d`, and its tooltip spells out the two dates.
- **Completed tasks are hidden by default**, remembered in `localStorage`, with a `completed hidden ⇄ ✓ completed shown` toggle and a new **Done** filter chip for looking at just the finished ones. It's a toggle rather than another chip because it cuts across the others — "Short" should mean short *and unfinished* unless you say otherwise.
- **Bug caught in testing:** the preference was read into a variable once at script load, so changing it elsewhere left the list disagreeing with its own toggle. Now read through to storage on every check.
- Verified end-to-end: backdated create → `opened_at` set with `created_at` untouched; explicit `done_at` honoured; correcting the start kept the finish; **clearing the finish worked** (previously impossible); tint and badge correct for a 24-day open task; `■ finish now` → "took 24d" → save → the task vanished from the list; toggle brought it back struck-through; the setting survived a full page reload. **Test task and its log rows removed — your one real task ("Update the Readme") untouched.** `tasks.js?v=6`, `main.css?v=45`.

### 2026-08-10 — Inventory: three views of the same stuff, and how old it is (user request)  ✅
The inventory was one long scroll — everything you own, then the two buy lists, stacked. It now answers three different questions from a sub-tab bar (**What I have · What I need · By location**), and every item can say how old it is.
- **The tabs are a lens, not a re-model.** `need` and `want` stay two separate lists inside the "What I need" tab — merging them is a spec DO-NOT, and the reason holds: an essential you're missing and a thing you fancy are different decisions. The tab only puts them together because they answer the same question. Choice persists in `localStorage` (`vault.inv.sub`), matching the Transactions tabs, and **the tab you're on sets the add-row's default status**, so adding on "What I need" doesn't silently create an owned item.
- **By location** groups the same owned things by *where* rather than *what* — the question category-grouping can't answer ("what's in the loft?"). Grouped **case-insensitively** so `Loft` and `loft` are one shelf, labelled with the spelling used first, alphabetical with **"no location recorded" last**. Wishlist items are excluded (a thing you haven't bought isn't in the loft) and so are sold ones; **broken things stay**, because they're still taking up the space, which is usually why you're asking. Editing an item's "where?" box in this view regroups immediately.
- **Age is recorded at the precision you actually have.** New `acquired` field, stored verbatim as `YYYY`, `YYYY-MM` or `YYYY-MM-DD` — rounding "some time in 2019" up to a specific day would invent a fact. The chip reads `~7y` for a bare year and `2y 4m` for a real date, and **a year-precision value never shows a months component**, so typing `3y` reads back as `~3y` and not `~3y 1m`. Chips are colour-coded by age (teal <1y · dim 1–4y · amber 4–8y · red 8y+) so a list skims as a heat map, and each group header calls out its oldest item.
- **The age box takes shorthand**: `3y`, `6m`, `2w`, `10d`, `new`/`today`, or a date. Shorthand resolves to the **coarsest** date that means it — `3y` in 2026 becomes `2023`, never a fabricated exact day. Unparseable input is rejected with a toast rather than stored as junk.
- **Bug caught in testing:** age was derived by dividing days by 30.44, which made a thing bought *exactly* a year ago read `11m`. Months are now counted off the calendar, and the part-month borrow only applies to a real date — on an invented midpoint it would be arithmetic on a fact we don't have.
- Server-side `_acquired()` validates the shape, rejects impossible dates (`2019-02-30`) and future ones, with **a day of slack** so someone east of UTC can still stamp their own "today".
- Verified end-to-end: all three tabs in-browser; `Loft`/`loft` merged into one group of 2; per-location and per-section totals; typing `5y` into a row saved `2021` and redrew as `~5y`; API rejects `junk` / `2019-13` / `2019-02-30` / `2030` / `19` with 400 and clears back to `""`. **All five test items deleted — your two real entries (desk lamp, bookshelf) untouched.** Vault's sub-tab bars also went gold (`.vlt-subtabs`); they were inheriting Pulse pink. `vault-inventory.js?v=3`, `vault-transactions.js?v=3`, `main.css?v=83`.

### 2026-07-29 — "now" stamping on every date and time field (user request)  ✅
Logging *when* something happened is the most repeated action in the app and typing `14:35` into a picker is the most tedious part of it. Rather than add a button to twenty forms, this went into the shared toolkit and reaches every field at once.
- **`ui.js` gained `nowHM` / `todayISO` / `stampNow` / `nowBtn` / `stampPair`.** All **local time** — `new Date().toISOString()` is UTC and would write *yesterday's* date for anyone west of Greenwich after 00:00 UTC.
- **`stampPair(start, end)` is a one-button stopwatch**: `▶ start` → `■ end` → `↺ again`, driven by what the inputs already hold, so reopening a saved session or typing a time by hand keeps the button honest. Wired explicitly into the **reading-session log** (`workspace.js` — the "read on / started / ended" row) and the **work-log form** (`worklog.js`), the two real session surfaces. Verified: start 12:40 → press end → `14:08`, **MINS auto-filled 88**.
- **Everything else is decorated automatically.** A `MutationObserver` on `<body>` gives every `input[type=date|time|datetime-local]` a `today`/`now` button — including inputs in modals mounted later, which is most of them. Opt out with `data-no-now`.
  - **Key detail: setting `.value` from script fires no events.** The stamp dispatches `input` *and* `change`, or the duration that syncs on `change` would silently never update.
  - **`work.js`'s table is opted out** — it's a dense grid of fixed-width cells and a button in every date/time cell would wreck the columns. Its row editor and the log-time form both have one anyway. Confirmed: 11 date/time inputs there, 2 buttons (the filter range only).
- Verified in-browser across surfaces: work-log form (`today` under Date, `now` under From/To, `▶ start` beside them), Workspace reading session, Vault transactions, and the Recovery log-session modal — the last proving the observer catches inputs created after render. **No data was created while testing** — work sessions 0, recovery sessions 0, Sample Paper A still on 1 instance. `ui.js?v=2`, `workspace.js?v=8`, `worklog.js?v=5`, `work.js?v=2`, `main.css?v=44`.

### 2026-07-29 — Increment A: the Repository holds sources, not just papers  ✅
A book you only own on paper, or a video series, is now a first-class entry — with the same master view, instances and knowledge graph a PDF gets. **`:Paper` is deliberately still the label**: every paper-scoped view is already built on it, so reusing the node gives a video series the whole workspace for free instead of a parallel implementation to keep in sync.
- **`kind` on the entry** — `paper · book · video · course · article · note` (`SourceKind` in models.py), with a `db.py` migration backfilling every existing row to `paper`. Card badge, `?kind=` filter on the list endpoint, and a picker in the filter bar. The filter `coalesce`s so a stale database can't hide rows.
- **`POST /papers/manual`** (`SourceCreate`) — an entry with no file at all: title, kind, authors/creator, year, publisher/channel, **`url`**, blurb. Declared before the `/{paper_id}/…` routes, though no collision exists today.
- **The scan is now a choice.** `POST /papers` takes `kind`, an optional `title`, and **`scan`**. `scan=false` never calls the LLM — verified at **0.083s** on a PDF that does have text. A typed title always wins over anything extracted, and `_extraction_source` records which happened (`not scanned + typed title`). Not scanning opens the edit modal too, since a filename is not a title.
- **`repo.js` restructured** around a shared `modal()` shell so the add and edit forms can't drift; `kindField`, `authorList` and `badYear` are shared. Cards show a kind badge and a `↗ link` when there's a URL; the empty state distinguishes "nothing here" from "nothing matches those filters".
- **Fileless entries verified through the real machinery, not by inspection:** created a video-series source with no PDF → **instances** created on it (v1, v2), **manual KG nodes + an edge** created and read back, and `kg/generate` **400s with a message that tells you to add nodes by hand** rather than the old bare "original PDF missing".
- **Bug found and fixed: instances promised a file that was never written.** `create_instance` set `file_path` to an instances/ path unconditionally, but only *copies* the PDF when one exists — so every fileless pass carried a path to nothing. Now `""` when nothing was copied (`""` not null, since Neo4j drops null properties and the key would vanish from the response).
- **Second bug, pre-existing: `delete_paper` leaked instance copies.** It unlinked the original but not the per-instance annotation PDFs, so deleting a paper stranded them. Now swept, matching what `delete_instance` already did for a single pass. **Two orphans from 23 Jul (20 MB) are still on disk** — left for the user to confirm before deleting.
- **Live data corrected:** the Sample Book entry still carried ResNet's venue (CVPR), year (2016) and DOI from the hallucination — cleared, and both books re-kinded from `paper` to `book`.
- **Testing mishap worth recording:** to prove the new sweep, a throwaway entry was pointed at a *real* original's path — deleting it then deleted the Sample Paper A PDF, correctly but destructively. Restored byte-identical (sha1-verified) from its own instance copy, and the title restored from the ligature form `Classiﬁcation` that `/reextract` writes. **Never point a test node at a real file's path.** All ZZTEST nodes, log events and orphaned instances purged; back to 5 entries. `repo.js?v=6`, `api.js?v=19`, `main.css?v=43`.

### 2026-07-29 — Increment D: stop the scanner inventing titles, and stop it reading whole books  ✅
A book upload came back titled **"Deep Residual Learning for Image Recognition"**. Investigating it turned up the actual cause and a second, unrelated cost.
- **Root cause: the book has no text layer.** `sample-textbook-scan.pdf` is 288 pages of page *images* — a scan. Every page returns `""` from PyMuPDF, so `extract_head` handed the model an empty prompt and it supplied a title from memory. Two earlier uploads produced "T E X T B O O K S E R I E S" the same way. **A model asked to find a title in an empty string will always answer something**; the fix is not to ask.
  - `llm.py` — below **`META_MIN_CHARS = 120`** the model is never called. The title falls back to the filename (`_title_from_filename`, deliberately dumb: strip extension, `-_`→spaces) with **`_source: "filename"`** and `_no_text: True`. A guess that can't be wrong about something it never read beats a plausible hallucination.
  - `papers.py` upload returns a `_warning`; `repo.js` opens the edit modal immediately **with that reason printed in red inside it** — a toast would fade while you were still reading, leaving a filename guess looking like a reading.
  - **`POST /reextract` now refuses on a text-less PDF (400)** instead of running. It overwrites every field, so on a scan it would have replaced a hand-typed title with a guess derived from a UUID filename.
- **Books open with a cover, a half-title and a blank verso**, so the fixed 2-page read was often nearly empty even on real text PDFs — the 1,665-page reference textbook gave only **209 chars**. New **`pdf.extract_head_adaptive`** reads on until `HEAD_MIN_CHARS = 400` (cap 12 pages): that book now yields 553 chars from 3 pages, while a normal paper stops at **page 1** and is *faster* than before (3,463 chars, 7.7ms).
- **`extract_references_section` was reading the entire document.** On the 1,665-page textbook that meant parsing **2,156,955 characters (1.40s)** to find a section that is always at the end. It now reads the last `REFS_TAIL_PAGES = 40` via the new `extract_tail` — **46ms, a 30× cut** — and still finds 26,686 chars of references. (`extract_head` 2pp, terms 3pp and KG 12pp were already capped; this was the only uncapped reader.)
- **`pdf.has_text_layer`** samples up to 30 pages spread across the document (a scan can still have a text cover), so "this needs OCR" is answerable rather than inferred.
- Verified: re-uploading the real 288-page scan now gives `title: "sample textbook scan"`, `_source: "filename"`, `_pages_read: 12` **in 0.26s** with the warning shown; `/reextract` on it 400s with an explanation; `/reextract` on a real paper still returns `ollama`; timings above measured on the actual files. **Test uploads and their `:ChangeEvent` rows removed — back to 5 papers.**
- **Two live data fixes:** the mislabelled entry is now *Sample Book* (A. Author), and testing `/reextract` on Sample Paper A had rewritten its title with a ligature (`Classiﬁcation`) — restored to the plain form. `repo.js?v=5`.

### 2026-07-29 — Home screen: your own artwork on the module cards (user request)  ✅
Four images in `~/mAInframe/Imageformainframescreen` (synapse · pulse · vision · vault) now fill the four cards you click to enter each module, each framed in that module's accent.
- **`backend/modulecards.py`** — mirrors the folder into `~/.mainframe/module-cards` at ≤900px JPEG q88 (**590 KB → 239 KB** across the four; cards render 380px tall, so 900 covers a 2× display). **The filename is the wiring** — `synapse.jpg` → the Synapse card — so this module holds no list of modules and a fifth one later means a fifth file, not a code change. A second file claiming the same module is ignored with a warning rather than silently winning.
- **`backend/wallpapers.py`** — its resizer became the shared **`build_web_copy(src, dest, max_px, quality)`**, plus `fingerprint`/`is_animated` made public. Same guarantees as the wallpaper cache and now literally the same code: **originals are only ever opened for read**, the cache name carries a `sha1(path|mtime|size)` fingerprint (unchanged file skipped, re-cropped file gets a new name and so busts the browser cache for free, deleted file swept), animated GIFs are copied rather than flattened, and alpha is composited onto the app background instead of going black.
- **`backend/routes/modulecards.py`** — `GET /api/module-cards` (the listing **is** the sync, so swapping a file and returning home is enough — no restart) + `POST /rescan?force=1`, served from the `/module-card-files` static mount.
- **`frontend/js/home.js`** — fetches the listing on mount and on every return to home, re-rendering **only when a URL actually changed** (the fingerprint is in the URL), so the usual case costs nothing on screen. A URL typed into the 🎨 customiser still **overrides** the folder for that module; blank falls back to it, and the placeholder now says which is in use. No artwork → the old accent gradient, unchanged.
- **The accent border** is a `--card-accent` custom property set per card from `window.MODULES`, read by `.hm-card`'s `border-color` — **not an inline `box-shadow`**, which would have out-specified the `:hover` rule and stopped the cards lifting. The card's name is tinted to match.
- **Sizing checked, not guessed.** The card renders ~207×376 CSS px, so a 2× display wants 752px of source height — `module_card_max_px: 900` covers it, and `Image.thumbnail` only ever shrinks, so nothing is upscaled server-side. Measured crop per image at card ratio: synapse 2.2%, vault 2.3%, vision 5.5%, **pulse 26.7% of its width** (it's the widest source at 0.75 vs the card's 0.55). **`vault.jpg` is only 236×419** — the one image stretched (1.8×) on a 2× screen and so the softest; a bigger source is the only fix.
- **The four now read as one set.** Vault's artwork is near-white while the other three are dark, so at rest it blew out against the dark screen. `.hm-card-ov` gained a light veil over the whole card on top of its existing bottom scrim, and the veil **lifts on hover** — the card you point at wakes up, which also gives the hover a second cue beyond the lift.
- Verified in-browser: all four cards show their image with the right border (`#00D4AA` · `#F4709C` · `#FF4757` · `#D4A017`); hover still lifts and brightens; card → module → Esc → home still works; second call cached 4/built 0; `rescan?force=1` rebuilt 4; a fifth file added → 5 cards, removed → swept back to 4; **the four originals are byte-for-byte untouched**. Zero app console errors. `home.js?v=4`, `api.js?v=18`, `main.css?v=42`.

### 2026-07-29 — Repository: edit the scanned metadata by hand (user request)  ✅
The local LLM reads the first two pages, which suits papers but misreads **books** — a cover, a series name or an imprint gets taken for the title. There was no way to correct it: the `PATCH` endpoint existed but nothing in the UI called it.
- **`frontend/js/repo.js`** — an **`✎ edit`** button on every paper card opens an *Edit details* modal: title, authors (comma-separated), year, venue/publisher, DOI, arXiv id, abstract. Title is pre-selected on open so the common case is type-and-Enter. Enter saves (except inside the textarea), Escape and click-outside cancel. A blank field **clears** the property rather than being ignored, and the card's meta line updates in place. If the edited paper is the one selected for the Workspace, `PM.paper` is refreshed too — *not* via `selectPaper`, which would navigate away from the repo.
- **`backend/routes/papers.py`** — three fixes the edit form exposed:
  1. `update_paper` now patches on **`exclude_unset`, not `exclude_none`**. An explicit `null` is how the client clears a field (Neo4j drops null properties); under `exclude_none` a cleared field was silently ignored. Both existing callers send single non-null fields, so nothing else changes.
  2. **Empty/whitespace titles are rejected** with a 400 — every paper-scoped view uses the title as its heading.
  3. **Author and venue edges are re-pointed, not just added.** `_link_authors_and_venue` only ever `MERGE`s, so correcting a mis-scanned author left the wrong `:Author` attached forever. New `_relink_authors_and_venue` drops the old `AUTHORED_BY`/`PUBLISHED_AT` edges first, then `_prune_authors_and_venues` sweeps any `:Author`/`:Venue` no paper points at — same reasoning as Vision's `_prune_tools`. The prune also runs on **paper delete**, which had the same leak.
- A rename now also updates the `paper_title` that `:MindDump` snapshots, so the mind inbox can't keep showing the old title. `:ChangeEvent` rows keep theirs — they're a historical record of what the paper was called at the time.
- **Bug found and fixed in testing:** the modal's Escape handler closed the overlay, then the event bubbled to `app.js`, whose own Escape handler checks `document.querySelector(".modal-overlay")` — by then gone — and sent the app **home**. Escape now calls `stopPropagation()`. (Other modals don't bind Escape at all, which is why this never surfaced before.)
- Verified (API + in-browser, `repo.js?v=3`): rename saves and re-renders; authors corrected → old `:Author` node gone, 16 real authors untouched; year and venue cleared with null; blank title and a non-numeric year rejected with the modal left open and its other fields intact; Escape closes without navigating. **Test paper, its 7 `:ChangeEvent` rows, its PDF and its orphaned author all removed — back to 6 papers.**

### 2026-07-27 — MAINFRAME_MASTER_SPEC audit + Dictionary Scanner  ✅
`~/Downloads/MAINFRAME_MASTER_SPEC.md` (121 KB / 3,287 lines) arrived. **It is a consolidation of the eight specs already implemented** — Tasks, Dictionary, Pulse, Fitness, Benchmarks, Vision, Vision-Update, Vault — under a new 10-line header. Rather than re-implement it, I diffed it against the running app.
- **Audit method:** extracted all 169 route declarations from the spec and all 295 from `backend/routes/*.py`, normalised path params, and diffed. **153/169 matched.** The 16 unmatched broke down as: 6 = Sandbox (deliberately skipped), 3 = false positives from param-name normalisation (`related/:targetId`, `trend/:metricKey`), 1 = satisfied differently (`POST /videos/:id/images` — the generic image service covers it), 2 = **the Dictionary Scanner, genuinely never built**, and the rest naming variants (`benchmarks/schedule` vs the app's `/schedule/info`).
- **Built the missing piece — Dictionary Scanner** (`routes/dictionary.py` + `frontend/js/scanner.js`, new Synapse tab):
  - `POST /dictionary/scan` implements the spec's algorithm **exactly**: lowercase → strip to letters/digits/spaces/hyphens → drop words ≤2 chars → drop the spec's 60-word stopword list → frequency-count singles **and bigrams where neither half is a stopword** → top 80. **Deliberately not LLM-powered** — the spec says the prototype uses frequency extraction, with LLM as a future enhancement.
  - `POST /dictionary/bulk-add` creates stubs (name + familiarity 0, `source: "scanner"`, everything else blank to fill in later).
  - **Word cloud** sized 11–36px by frequency, and a **ranked list** with proportional bars. Both cycle unselected → selected (teal) → dismissed (faded + struck) → unselected. Terms already in the dictionary render green ✓ and can't be selected.
  - **Bug found and fixed in testing:** `bulk-add` deduped against the database but not *within* the request, so the same term twice in one payload hit the unique-name constraint and 500'd the whole batch. Now deduped case-insensitively both ways.
- Verified (API + in-browser): stopwords and short words excluded, bigrams found, frequency ranking correct; all three click states; both views; adding flips terms to green ✓ in place; duplicates skipped not errored. **Test stubs removed — the 9 real dictionary terms untouched.**
- **Spec inconsistency worth noting:** the new header says *"Synapse (cyan #00F5D4)"* but every Synapse section in its own body uses **#00D4AA**, which is what's built. Left as-is; flagged to the user.
- **Not in the spec at all:** `~/Downloads/mainframe-home2.html` and `mainframe-home3.html` describe a **home page** (module cards with imagery, a background customiser with image/video/particle layers, and a snapshot panel) that the spec text never mentions. Raised with the user rather than guessed at.

### Home screen (from `~/Downloads/mainframe-home3.html`)
The Mainframe front door — what you land on after the boot screen, with the four modules as cards.
- **`backend/routes/home.py`** — three endpoints, every figure computed live so home can't drift from the modules it summarises:
  - `GET /api/home/stats` — lifetime strip: hours (summed `TaskEntry.time_spent_mins ÷ 60`), workouts, habit instances, pieces of content, projects. **A papers tile was built and then removed at the user's request** — they don't want papers on the front page. The snapshot dropdown's "Papers added" row is deliberately kept (different surface).
  - `GET /api/home/snapshot?period=daily|weekly|monthly` — per-module activity for the period. Entities with their own date are counted on it; the rest fall back to the shared `:ChangeEvent` log.
  - `GET|PUT /api/home/prefs` — a `:HomePrefs` singleton holding a JSON blob. In Neo4j rather than localStorage so the home screen looks the same in any browser, and the shape is owned by the frontend — a new setting never needs a backend change.
- **`frontend/js/home.js`** — background stack (gradient / image / video / dim / particles), snapshot dropdown with a D/W/M toggle, and module cards whose gradients are *derived from `window.MODULES`*, not hardcoded. `window.openModule(key, tab)` / `window.goHome()` in `app.js` swap between home and the module shell; `← mainframe` in the tab bar and Esc both go back.
- **Colours deliberately unchanged.** The mockup wanted `#00F5D4` for Synapse; the built accents stay **Synapse `#00D4AA` · Pulse `#F4709C` · Vision `#FF4757` · Vault `#D4A017`** at the user's request.
- **Boot screen rebranded** to MAINFRAME / "PERSONAL // KNOWLEDGE OPERATING SYSTEM", `app_name` → `Mainframe`, `<title>` → `Mainframe`, and the old single "synapse module" check split into `modules` (lists all four) + `store`.
- **Bug found and fixed in testing:** a week straddling a month rendered as "27–2 Aug". The label now names both months when they differ.
- Verified in-browser: stats and snapshot show real figures, dropdown sections colour-coded per module, card → module → back, Esc-to-home, gradient choice persisted server-side and restored after reload. **Test `:HomePrefs` node deleted afterwards.**

### Wallpaper slideshow (2026-07-27)
The home screen cycles the user's own wallpaper folder.
- **`backend/wallpapers.py`** — mirrors `~/mAInframe/Wallpapers` (recursive, `Video/` skipped) into `~/.mainframe/wallpapers` at ≤1920px JPEG q82. **16 MB → 5.9 MB** across 35 images, ~2.3s cold, **0.25s when nothing changed**. Two rules make it safe to run on every request: originals are only ever opened for read, and the cache filename carries a `sha1(path|mtime|size)` fingerprint — so an unchanged file is skipped, an edited one gets a new name (free cache-busting), and a deleted source is swept on the next pass. Animated GIFs are copied through rather than resized, since flattening one to a still frame would silently break it. EXIF rotation is applied; transparency is flattened onto the app background so PNGs don't become black boxes.
- **`backend/routes/wallpapers.py`** — `GET /api/wallpapers` (listing *is* the sync, so newly-dropped images appear without a restart) and `POST /rescan?force=1` to re-encode everything after a size/quality change. Served from the `/wallpaper-files` static mount. **New dependency: Pillow 12.3.0** — first non-stdlib image lib in the project; it also unblocks the thumbnailing gap listed below.
- **`home.js`** — background kind `"slideshow"`. Random **order** is a fresh Fisher–Yates shuffle per pass (so every wallpaper shows once before any repeat — plain `random()` wouldn't), with a seam check so a reshuffle can't butt the same image against itself. Random **timing** is re-rolled per slide in `[5s, 30s)`. **W** (or →) skips immediately; ignored while typing or when home isn't on screen. Two cross-fading layers mean an image is never replaced by a blank frame, plus a slow scale drift.
- **Timer stops when home is hidden** — opening a module clears it rather than leaving it cross-fading images nobody can see; verified via the DOM (`homeOpen:false, active:0`).
- **Bug found and fixed in testing:** `ui.guard()` *runs* its argument — it isn't a wrapper. `addEventListener("click", guard(fn))` therefore fired the handler while the panel was building itself, and since the handler calls `refreshPanel()` the result was infinite recursion that wedged the tab (`Maximum call stack size exceeded`, 4377 console messages). Handlers must be `() => guard(fn)`. Swept the codebase — no other instance.
- Verified: 35 images cached, W advances, auto-advance observed, add-a-file → 36 (1 built), delete-it → 35 (1 swept), animated GIF kept all 31 frames.

### Image system — what it can't do
1. **Attach before an entity exists.** `context_id` needs a saved node, so create-modals can't take an image — you save first, then attach. The Pulse day-log modal only shows the widget for a day that's already logged.
2. **Canvas-drawn things have no per-item DOM.** Knowledge Graph nodes, the Reference Map, the fitness body map, sparklines and the contribution grid are drawn to `<canvas>`/generated SVG, so there's nothing to hang a widget off. Attaching images to an individual KG node needs a side panel first.
3. **Paste and drag-drop aren't wired.** Upload is file-picker only (multi-select works). `paste`/`drop` handlers are a small addition to `images.js` when wanted.
4. **No reordering, captions, or cover-image selection.** Images list newest-first; there's no `position` like Ideas/Mind Dump got, no caption field beyond the name, and no way to mark one as the card's hero. (The lightbox pages through them in that same newest-first order.)
5. **No resizing/thumbnailing.** The original file is stored and served at full size, scaled by CSS. A 12 MB photo downloads at 12 MB for a 116px thumbnail. Needs Pillow (a new dependency) to fix properly.
6. **No dimensions captured.** The spec's `width`/`height` fields are absent for the same reason — reading them means decoding the image server-side.
7. **Images only.** PDFs/docs are rejected by design; the four pre-existing file uploaders still handle those separately, so "attachments" remain split across two systems.
8. **No global gallery.** `/api/images` can list everything, but there's no browse-all-images view, no search by name, and no orphan cleanup if an entity is deleted (the `:Image` node and its file survive — `DETACH DELETE` on the owner drops the edge, not the image).
9. **Hide is per-browser.** `Images.setHidden` writes to localStorage, so it doesn't sync across devices and there's no settings UI for it yet — it's a console call today. Note for Sandbox: the spec's `POST /sandbox/:id/export-png` can't render server-side (DOM boxes, zero-lib rule); plan is to build an SVG from the geometry client-side, paint it into a `<canvas>`, `toBlob()`, and POST to `/api/images`.

---

## API map (old → new)
| Old | New |
|-----|-----|
| `/api/papers`, `/api/instances`, `/api/highlights`, `/api/terms`, `/api/kg`, `/api/refs`, `/api/deepdive`, `/api/headers`, `/api/ideas` | `/api/synapse/<same>` |
| `/api/tasks`, `/api/log`, `/api/health` | unchanged (Mainframe-level) |

---

## Not yet touched
- `start.sh` / `stop.sh` / `README.md` still say "Paper Metabolism" (cosmetic only).
- No feature *logic* changed yet — increment #1 was rename + path move only.

## Starred references → yellow edges on the Reference Map (2026-08-28)

Each stored reference now carries `starred` + `note`, set from the ★ toggle on
its row in the Workspace. The star lives on the **(citing paper, cited work)**
pair — the same thing an edge is — so "read this after" stays attached to the
paper that made you want to read it, and the same work can be starred from one
paper and not another.

- `PATCH /api/synapse/refs/stored/{id}/flag` `{starred?, note?}` — the two
  fields are independent; sending one leaves the other alone, a blank note
  clears it, and unstarring keeps the note. Neither is touched by
  `_store_reference`, so a PDF re-scan can't wipe what you marked by hand.
- `GET /api/synapse/refgraph` ships `starred`/`note`/`ref_id` on every
  reference edge, `starred` + `notes[]` on the node, and `counts.starred`.
  A reference that resolved to a paper you own has no leaf of its own, so its
  mark lands on the real paper node instead.
- Map: starred edges draw in `#FFD426` at 2px and last (on top of the mesh);
  starred nodes get a yellow ring and an always-on label; the note shows in the
  inspector above everything else. New `★ starred only` toggle = the read-after
  list as a map — the marked works plus the papers you marked them from.

## Phases tab — fourteen-week sprints (2026-09-07)

Built from `~/Downloads/mainframe_phases_modals.html` (the two modals; the
full-tab mockup it refers to, `mainframe_phases_mockup.html`, was never
downloaded, so the tab body is built from the stat grid that file shows plus
the existing card idiom). This **supersedes** the older
`~/Downloads/2026-08-30-mainframe-phases-tab.md`, which specced phases as four
fixed slots inside a standalone single-file HTML widget — a different design,
not an earlier increment of this one.

New topbar tab between Goals and Progress (`SHARED_TABS`, so Mainframe-level).
The `:Phase` node is the *same* node the Goals view scopes phase-goals to; it
grew a lifecycle rather than being duplicated.

- `:Phase` gains `status` (active|closed), `seq`, `weeks`, `goal`,
  `reflection`, `closed_at`. Two migrations backfill: existing phases close if
  their end date has passed, and are numbered by start order.
- Membership is `(:Project)-[:IN_PHASE]->(:Phase)`; the relationship carries
  `outcome` (done|carried|dropped) + `outcome_note` once answered.
- `/api/phases` — `GET` (all, with rollups), `GET /active`, `GET /candidates`
  (open projects, carried ones pre-ticked), `GET /{id}`, `POST` (409 while a
  phase is running), `POST /{id}/close` (400 until every project has an
  outcome). Deleting a phase is still `DELETE /api/goals/phases/{id}`.
- **Counts cannot lie**: hours/sessions are summed from `:WorkSession` rows on
  the phase's projects *inside its window* — never posted, never stored. A
  project carried across two phases shows each phase's own hours.
- **Working on something joins it**: `_absorb()` reconciles membership on read
  of an active phase, so a session logged (or backdated) into the window pulls
  its project in without a hook in every write path. Closed phases are frozen.
- Closing with `done` also sets the project's own `status = 'done'`, which is
  what keeps it out of the next phase's candidate list.

Known seam: the Goals tab can still create a bare phase inline via
`POST /api/goals/phases`, which bypasses the one-active-at-a-time guard.

## Phase 00 Alpha seeded (2026-09-13)

Seeded from `~/Downloads/PHASE_SEED.md` (the YAML block plus the prompt at its
foot). Every number is the file's own: `Σ(weeks)` is what the phase claims a
project for, `low_h`/`high_h`/`done_when` are written verbatim, and nothing was
recomputed or rescaled. Backup of the Project/Task/Phase subgraph taken first at
`backups/alpha-preseed-20260913-090000.json`.

Writes went through the HTTP API wherever an endpoint owns the field, so
`phasehook` filed what was created under the running phase and the Inbox log
recorded the moves. Cypher was used only for fields no endpoint owns yet.

- **The phase**: the empty `Phase 0 Alpha` created 2026-09-10 was already
  active with exactly the file's window (2026-09-14 → 2026-12-20), so it was
  filled rather than replaced — `POST /api/phases` would have 409'd anyway.
  `goal` set via `PATCH /api/phases/{id}`.
- **New `:Phase` properties, written directly**: `number`, `naming`,
  `capacity_h_per_week` (25) with `capacity_floor_h` 18 / `capacity_ceiling_h`
  35, `breaks_after_weeks` (2), `score_w_habits|hours|content|mistakes` (25
  each), `next_number|next_name|next_start` (1, Beta, 2027-01-04), and
  `body_cardio_per_week` / `body_sleep_target_h` / `body_steps_per_day`.
  **Nothing reads any of these yet** — no model field, no endpoint, no UI. They
  are data waiting for the Weeks view and the score.
- **12 projects claimed**, `(:Project)-[:CLAIMED_BY]->(:Phase)` via
  `POST /api/phases/{id}/pull`, which also draws the `:IN_PHASE` membership the
  dashboard counts against. 750h claimed in total.
- **`:Project` gains `tier`** (must | progress | external | cadence | out) and
  **`ref`** (the file's 6a, 3b, K, Q… labels). `Project Group A` and `Project Group B`
  were created as parent projects; they are deliberately *not* claimed, because
  the file lists them only as `parent:` values and never as rows with hours.
- **`PLANNED` lives on the claim**: `r.planned` is the 14-number weeks array on
  the `CLAIMED_BY` edge, not a row per week. A project claimed by two phases
  then keeps two independent plans, which is the same reason hours are summed
  per-window — a phase's plan is a fact about that phase. Respread rewrites the
  tail of one list; provenance goes in the `:Change` rows that already exist.
- **28 tasks, all dated.** `due_week` N becomes `start + 7N - 1` days, i.e. the
  last day of that phase week (week 1 → 2026-09-20). The nine Sample Book chapter tasks,
  plus one task per cadence occurrence carrying that cadence's `hours_each` as
  `low_h`/`high_h`.
- **Three existing empty shells reused, not duplicated**: `Sampel
  Book` → `Sample Book`, `Project C` → `Project C
  (engine)`, `Project D` → `Project D (engine)`. All three had
  zero estimates, zero children, zero tasks and zero sessions, so reusing them
  cost nothing and kept the project picker from carrying two rows for one
  project. (The Sample Book shell did carry one undated task, `Chapter 1`, left in place —
  nothing is deleted in the Inbox model.)

### TODOs this seed left open

- **The Video cadence is NOT seeded.** The file marks it `CADENCE NOT FINAL` and
  says to wait for the user to confirm kinds and frequency. 14 weekly
  occurrences at 3–6h each are waiting on that answer.
- **There is no Phases → Weeks view**, so the seed's own verification step
  ("confirm the Weeks view shows these rows and totals, and that editing a cell
  writes PLANNED") cannot pass yet. The file cites
  `notes/ui/mainframe_phase_weeks.html` as if it existed; it was never
  downloaded, and neither was `notes/research/phase_reading_lists.md`. Still to
  build: the planned-vs-actual grid, cell edit, Respread, and the weekly
  re-forecast at the measured rate.
- **Drift on project rows** is mechanism 2 of the file. `drift.py` already has
  BURN and THURSDAY and `renegotiate` already has the three levers writing a
  `:Change` and a dated why `:Note` — but all of it runs on `:PoolGoal`, not on
  projects. Extending it needs the planned hours above to compare against.
- **The plan is 1.6–2.7× its own stated capacity.** Every project is internally
  consistent (`Σweeks` sits inside `low_h..high_h` for all 10), but the weekly
  totals run 40–68h against a 25h/week capacity with a 35h ceiling — and that is
  before 150–300h of cadences, which no weeks array accounts for. Weeks 13–14
  are worst (68h, 66h) because Project E lands 24h and 23h on top of
  everything else. Left exactly as written, per the file's "the CLI must not
  change them"; this is the honest log the phase goal asks for.
- **`split: half inside the 25h, half in external time`** on the Paper deep
  dive cadence has nowhere to go — no field on the claim divides phase hours
  from external hours.
- `habits_main` and `habits_experimental` are empty in the file, left for the
  Habits tab to fill.

## Phases → Pace: the plan against the hours (2026-09-13)

Built the same day as the Alpha seed, for the question the seed could not
answer: the fourteen weeks of hours a phase is seeded with are a guess, and two
or three real weeks are enough to tell you which of those guesses were fantasy —
while there is still phase left to spend.

This is **not** the Weeks view `PHASE_SEED.md` asks for. That one is a plan
*editor* (edit a cell → write PLANNED, "Respread" refills future cells). This is
a read-only *instrument*. The seed's own spec file, `notes/ui/
mainframe_phase_weeks.html`, was never downloaded, so the editor is still open —
see the TODOs under the seed entry above.

- **`GET /api/phases/active/pace`** — one payload against one `today`, the same
  idiom as `/active/dashboard`. Planned comes off `r.planned` on the
  `CLAIMED_BY` edge; logged is summed from `:WorkSession` rows on the phase's
  projects inside its window and is never stored, per the counts-cannot-lie rule
  the rest of the router runs on.
- **A week is the unit the plan is written in; a day is the unit you live in.**
  The day therefore gets three numbers rather than one target: `share_h` (the
  week's plan ÷ 7), `logged_h`, and `catchup_h` (the week's plan still
  outstanding ÷ days left in it, today included). Catch-up is the one that
  moves — skip a day and it climbs, which is the earliest honest warning that a
  week is going.
- **Verdicts refuse to guess.** `_PACE_MIN_WEEKS = 2` complete weeks *with work
  in them*; under that every verdict reads "not enough weeks yet" and the view
  says how many weeks are still needed. An empty finished week is a fact about
  the week, not about the plan, so it is not allowed to drag a verdict down
  (`counts` on each week row). Ratios are logged ÷ planned, banded by
  `_PACE_HEAVY` 0.60 / `_PACE_LIGHT` 1.15 into "plan too heavy" / "about right" /
  "plan too light". The verdict is about the PLAN, never about the person.
- Projects are measured **over the complete weeks only**, never against a plan
  that includes weeks which have not happened — that would call everything too
  heavy on day one.
- Three honesty fields that need no data at all: `plan_total_h` vs
  `capacity_total_h` (Alpha: 640h against 350h, 1.83×), `unplanned_claim_h`
  (110h of cadences claimed with no weekly plan, which the week totals cannot
  see), and `off_plan_h` (hours logged in the window on nothing the phase
  claimed — real work the plan never accounted for).
- **`frontend/js/phase-pace.js`** + a `phase | pace` toggle in the Phases head
  (`.ph-hz`, remembered in `localStorage`). `load()` was split so the toggle
  repaints without refetching. Pace reads its own endpoint — the dashboard
  payload carries neither the plan nor the per-day hours.
- **A log-hours row sits in the view**, posting `/api/work`. The work database
  had zero rows: every number here is summed from sessions, so a view that asks
  you to log hours and then sends you elsewhere to do it would not be used on a
  Tuesday. Verified end to end (2.5h logged → week 1 and the project both moved;
  test row deleted).

Verified by temporarily shifting the phase start back three weeks, writing
sessions through the real `POST /api/work`, reading the endpoint, then restoring
— Sample Book at 3h/wk against 6h planned gave ×0.5 "plan too heavy", Project F at 11h
against 9h gave ×1.22 "plan too light".

**One thing that verification broke and how it was fixed**, because it will
happen again to anyone who moves a phase window by hand: while the window was
shifted, `phasehook.sweep()` filed everything created that day under the phase —
178 Notes/Tasks plus four projects. `phasehook.refile()` cleans the first kind
but *deliberately never evicts a `:Project`* ("membership is the lineup you
ticked plus what you worked on, not the date it was created"), so the four
unclaimed projects — `Project Group A`, `Project Group B`, `Online lecture series`,
`Electronics kit` — had to be dropped explicitly on the rule that they were neither
claimed nor worked on. Restoring a phase's dates with raw Cypher skips
`refile()`; `PATCH /api/phases/{id}` is the path that reconciles.

### Pace tile on Snapshot (2026-09-13)

`@section("pace", …)` in `routes/snapshot.py`, added to `DEFAULT_KEYS` and to
`TILE_SECTIONS` in `snapshot.js`, drawn **second — directly after Now**, since
the two are the same subject: hours today. Amber top border.

It calls `routes.phases.active_pace` and cuts the payload down rather than
re-deriving planned-vs-logged, per this file's own rule that a snapshot with its
own bookkeeping goes stale within a fortnight. Running, it reads:

    0.0h today · 6.1h even share
    catch-up 11.8h a day to finish week 3     ← red past 10h
    week 3 of 14: 31.5h of 43.0h planned
    plan too heavy
    real 25.2h vs 38.0h a week

Before the phase starts it falls back to the arithmetic that needs no data
("starts in 1 day" / "the plan is 1.83× capacity"), so the tile is never blank.
`.snap-line` is one nowrap line with an ellipsis, so the verdict and the numbers
that justify it take a line each instead of clipping mid-number.

**`_PACE_HEAVY` moved 0.60 → 0.85** on the evidence of this tile. With the old
floor, a fortnight delivering 25.2h against a 38h plan came out "about right" —
a third of the plan missing, called fine. That is the one thing this screen must
never do. The band is now ±15%, which is tolerance; beyond it is the finding.

Verified by putting the phase into a running state (start shifted back two weeks,
40 sessions across weekdays), reading the tile, then restoring — this time
through `PATCH /api/phases/{id}` so `refile()` ran. The four unclaimed projects
still had to be dropped by hand afterwards, exactly as recorded above: `refile()`
never evicts a `:Project`. Graph is back to 0 `:WorkSession` rows, the
2026-09-14 → 2026-12-20 window, and 12 filed projects.

## 2026-09-29 — Database: paste many rows at once
- **⇪ paste rows** button in the Database tab (`work.js` `pasteModal`). Paste a spreadsheet range / CSV → preview grid → **add N rows**. Nothing is written until you press add.
- `backend/workimport.py` (pure parser): tab/comma/semicolon/pipe detection, optional header (aliases: Date, Project/On, Time/Minutes/Hours, From, To, What I did, Notes, Focus, Completed…), headerless = the ⬇ CSV column order so an export pastes straight back. Dates: ISO, UK day-first 28/09, 28 Sep, today/yesterday. Durations: 90, 1h30, 1.5h, 1:30, 45m; an "Hours" column multiplies by 60.
- `POST /api/work/import/preview` matches "On" names to projects (exact, then unique containment: "Atlas" → "Mapping (Atlas)"); ambiguous names get a picker, unknown names warn that the hours won't reach any project/phase; rows already in the table are flagged and start unticked. `POST /api/work/import` writes through `create_session`, so :ON links, work-type inheritance and activity logging are identical to + new row.
- Verified in browser: 3 rows added, phase totals rose by exactly the pasted minutes, repeat paste flagged; test rows removed.

## 2026-09-29 — Inbox: star hover, red × delete, cyan ?
- ★/☆ lights **bright yellow** (#FFE500 + glow) when the star itself is hovered, starred or not.
- New **red ×** beside the star: `DELETE /api/synapse/inbox/{id}` — deletes the row and its :TaskEntry journal for real (confirm dialog first). The one exception to "nothing is deleted": drop is still the move for "decided against". Logged :WorkSessions keep their ref_title; a :Question the row came from stays in the Questions tab; one `DELETED` :Move line keeps "What changed" honest.
- ❓ emoji → plain **?** glyph in cyan #2DE2FF (emoji ignore `color`). Gotcha: the global `button:hover { color: var(--teal) }` (main.css:231) repaints any button whose own :hover rule doesn't set `color` — every hover rule here now sets it.

## 2026-09-29 — Inbox: paste a whole column
- A single-line `<input>` squashes a multi-line paste into one row. The Inbox add box now catches any paste with line breaks and opens **"Add N rows to the Inbox"**: one row per non-blank line (first filled cell of a multi-column copy), repeats in the paste folded into one (×N shown), rows already in the Inbox unticked, titles editable, kind + optional category for the batch.
- `POST /api/synapse/inbox/bulk {titles, kind, category}` → loops `create_row`, so the :Idea label rule holds exactly as for the add box.
- Folding compares letters+digits only (case/punctuation-insensitive); spelling variants (normalisation/normalization, ltsm/LSTM) are NOT folded — untick by hand.

## 2026-09-29 — Phase week/month goals with progress · Inbox notes · do on / takes
- **Phase goals**: "+ week goal" / "+ month goal" in the Time viewer. Each goal picks how it's measured (`measure`): **count** (scope_done of scope_total, −1/+1 on the row), **hours** (sessions on its project inside its window vs `target_h`, never typed; needs a project), **tasks** (tasks that SERVE it). Progress bar + "n of N · pct%" + "done" button. `poolgoals.progress()` builds it.
  - The window is the week / calendar month holding the goal's **due date** (default: Sunday / last of month), so a September goal doesn't reset on 1 Oct.
  - Fixed seam: `POST /api/phases/goals` now also writes `CLAIMED_BY` — the panels list claimed goals, so goals set through it never showed.
  - Fixed: the tasks measure counted `t.done`, but Inbox tasks finish as `status='done'`; both count now.
- **Inbox "note" kind**: a quick to-do. Status is a tick box (open ⇄ done); new `POST /inbox/{id}/reopen`. "notes" filter chip; note in every kind picker.
- **do on / takes** columns on every row: `do_on` (date), `do_at` (HH:MM), `takes_min` (typed 45, 45m, 1h30, 1.5h, 1:30). Separate from `due` (the deadline). `/api/calendar/range` returns `planned`; the Calendar draws timed ones as dashed teal blocks (untimed in the all-day strip); clicking opens the Inbox.
- Seam noticed, NOT fixed: Calendar's due list reads `t.due_date`, Inbox rows store `due` — Inbox due dates never reach the Calendar.

## 2026-09-29 — Calendar: what you did, colour-coded by module; weekly reviews + planning
- **Module colours** on every calendar item (border + tint): Synapse `#00D4AA`, Pulse/fitness `#DE7BA4`, Vision `#FF4757`, Vault/money `#D4A017`, none/Mainframe `#7FA8C8`. Line style says what it is: solid = event / logged work, dashed = planned (Planner blocks, Inbox "do on"), heavy left edge = review / planning.
- **Logged work** (`:WorkSession` with a start time) is now a labelled block in the lanes (was a faint unlabelled strip behind). Untimed work stays a dot. Click → Database.
- **Workouts** come through `workouts` in `/api/calendar/range`; no start time yet, so they sit in the all-day strip (pink). Once fitness commit 3 stores block times, `x.start` makes them timed with no calendar change. Click → Pulse > Fitness > Workouts.
- **Planner blocks** via `_plan_blocks()` → the Planner's own `_calendar_payload` per week (auto blocks are computed, and Planner :CalEvents store ISO `start`, not date + HH:MM). "planner blocks" toggle in the header (localStorage `cal.showPlan`). Click → Planner.
- **Review / Planning** event kinds + **repeat weekly (until)**: one :CalEvent per series, expanded on read by `_repeats()`; occurrences carry `series_id` + `series_first`, and editing one edits the series. Choosing review/planning on a new event ticks repeat by default. Module picker in the event modal sets the colour.
- Seam noted: :CalEvent has two shapes (Calendar: date + HH:MM; Planner: ISO start/end), so Planner's hand-placed blocks never showed in the Calendar's own list — they arrive through `plan_blocks` now.

## 2026-09-29 — Synapse bar trimmed
- Removed from the Synapse module bar by request: **Scanner** (`scanner`), **Knowledge Graph** (`kg`), **Project** (`deepdive`, Synapse's name for Deep Dive) and **Framework** (`framework`). Only the `tabs` list in `modules.js` changed: views, routes and data are untouched, nothing linked into them, and the top-bar Project tab and Pulse's Deep Dive are unaffected. Add a key back to restore a tab.

## 2026-09-30 — Log workout parts 2 and 3: program days, /today, maxes, stored blocks

The timed Log workout form (3b9af29, "1/3, form") now has its backend.

- **Program = a cycle.** Each cycle gets training days that repeat every week:
  `(:ProgramDay {day,label})-[:DAY_OF]->(:Cycle)`, prescriptions as
  `(:Prescription {idx,exercise,key,sets,reps,pct_max})-[:PRESCRIBED_ON]->(:ProgramDay)`.
  Routes: `GET/POST /fitness/cycles/{cid}/days`, `PUT/DELETE /fitness/days/{did}`.
  Deleting a cycle takes its days; deleting a day leaves its workouts on the cycle.
- **Maxes.** One `(:LiftMax {exercise,key,kg,reps,from_kg,from_reps,date,source})` per record;
  current = latest per `key`, older ones come back as `previous`. `GET/POST /fitness/maxes`,
  `DELETE /fitness/maxes/{id}` (the previous record becomes current).
  `key` = `ex_key()` in fitness.py, the same rule as `exKey` in fitness-logworkout.js — keep them in step.
- **`GET /fitness/today[?cycle_id=]`** — program (the asked cycle, else the active one whose span holds
  today, else the newest active), week = the cycle's current week, day = the one after the last day
  logged this week (wrapping; day 1 if none), its prescriptions, all current maxes, and every cycle for the picker.
- **`POST /workouts`** now stores what the form sends: `(w)-[:HAS_BLOCK]->(:WorkoutBlock)` per timed row,
  `fatigue_before`, `warmup_min`, `(w)-[:ON_DAY]->(:ProgramDay)` + `program_week` (from the workout's date),
  `(w)-[:IN_CYCLE]->(:Cycle)` (from the day, else `cycle_id`), and ticked maxes as `(w)-[:SET_MAX]->(:LiftMax)`.
  Deleting the workout deletes its blocks and the maxes it set. Legacy `:Exercise` rows still written.
- **UI.** Program tab: a Maxes card (add / delete) and a "Days, every week" block per cycle with a day editor
  (label with workout-type suggestions, exercise/sets/reps/% of max rows). Log form header: program picker
  (re-reads /today for the chosen cycle) · week · day · prescriptions · change day. Workout card: cycle · week · day,
  and the timed blocks + new maxes when expanded.
- Verified: API round trip and in-browser (day editor save, log form prescriptions / vs max / PR? / program switch,
  log with max confirm, card). All test data and its activity events were removed afterwards.

## 2026-09-30 — Cardio block in the Log workout form

- Third section after Exercises: from · to · type (run/walk/cycle/swim/row/hike/other) · km · avg hr · effort (1–10) · min.
  "+ row" starts where the last cardio row (else the last exercise/warm-up row) ended. Totals gain "cardio N min · X km";
  total and the workout's duration include it; effort counts toward the legacy `intensity`.
- `WorkoutCreate.cardio: list[CardioBlockIn]`. Each row becomes a real `:CardioSession` (same node the Cardio tab uses,
  so distance/pace/summary include it) with `from`/`to`/`workout_id` and `(w)-[:HAS_CARDIO]->(c)`. Duration = to − from.
  `create_cardio` now goes through `_insert_cardio()`. Deleting the workout deletes its cardio sessions.
- Workout reads return `cardio` (shaped with pace); card header shows "cardio X km", expanded shows each row.
  Cardio tab tags such sessions "in a workout · HH:MM".
- Verified via API and in-browser; test data and its activity events removed.

## 2026-09-30 — Edit a workout

- "✎ edit" on every workout card (Workouts and History) reopens the Log workout form filled in: program and
  day, date, type, fatigue, interrupted, warm up, exercise rows, cardio rows, notes. Add rows, change anything, Save.
- `PUT /fitness/workouts/{id}/replace` (body = `WorkoutCreate`): overwrites the fields, clears and rewrites
  exercises, blocks and cardio sessions, redraws `IN_CYCLE`/`ON_DAY`/`program_week`. Same id, so images stay;
  maxes the workout set are kept, newly ticked ones added. Create and replace share `_fill_workout()`.
- Workouts from before the timed form have no blocks: their `:Exercise` rows come back as exercise rows
  ("20 reps @ 60kg rpe 6" → reps/kg/rpe; unreadable detail stays in the name). With no times entered, the
  saved duration and intensity keep their old values instead of dropping to 0 and 5.
- Verified via API (incl. 404 on a missing id) and in-browser on an old-style and a timed workout; test data removed.

## 2026-09-30 — Cardio style: LISS or HIIT, with HIIT sets

- `:CardioSession` gains `style` ("liss" | "hiit", optional) and `sets` (HIIT only). `CardioCreate`,
  `CardioUpdate` and `CardioBlockIn` take both; the server drops `sets` unless the style is HIIT,
  and switching a session to LISS clears them.
- Log workout cardio rows: style select + a sets box that only shows for HIIT; totals add "N HIIT sets";
  editing a workout refills both. Cardio tab form: style + HIIT sets (sets alone is enough to log);
  its list shows a LISS / "HIIT × N sets" pill. Workout cards show e.g. "cardio: cycle HIIT × 8 sets".

## 2026-09-30 — Body Map v3: a snapshot a day

- The Body Map is now ONE DAY: date bar (‹ date ›, today by default), the figure coloured by that day's entries.
  Click a muscle → log/edit it for that day: kind (soreness/pain/tight/imbalance), severity 1–5, note, "fine today"
  to remove; the editor lists that muscle's other days. Nothing carries forward on its own: "carry over from <last
  logged day>" copies it (regions already logged that day are kept). Day note per day; History lists every logged
  day (click to open). Old general body notes are still shown underneath.
- Storage = the existing `(:BodyDayState {date, region})`, now with `kind`, `severity`, `note`, `updated_at`
  (legacy `state` kept filled). Routes: `GET /fitness/body/days`, `GET /fitness/body/days/{date}` (+ `prev`),
  `PUT|DELETE /fitness/body/days/{date}/{region}`, `POST /fitness/body/days/{date}/carry {from_date}`.
- Day Review shows the same snapshot (sev colours) and opens the same editor (`window.FIT.openDayEntry`).
  Dashboard pain/imbalance counts come from the latest logged day ≤ today, not the old always-on `:BodyState`.
- v2 issues: no longer shown as a panel. While any are open, a banner offers "add to <day> and close them"
  (`POST /fitness/body/issues/to-day {date, close}`) or "just close them". Issue data is untouched otherwise.
- Pre-rewrite region keys (`l_arm`, `r_shoulder`) are named after the muscle they map to (`regionName()`).

## 2026-09-30 — Body Map: all clear

- Under the date bar: "✓ All clear — body feeling fine". Records a day checked and fine (≠ a day not logged):
  `all_clear` on that day's `(:BodyDayNote {date})`, via `PUT /fitness/body/days/{date}/all-clear {all_clear}`
  (declared before `/{region}` so "all-clear" isn't read as a muscle). Setting it removes the day's entries (asks first
  if there are any); logging a muscle, carrying over, or moving old issues into the day unsets it. Shows as a green
  "All good — body looking fine" strip with undo; History marks the day "✓ all clear".

## 2026-09-30 — Synapse bar: Decomposition and Lattice removed

- By request, `decomposition` and `lattice` came off the Synapse module bar (`modules.js` tabs) and out of
  `REVIEW_TABS` in app.js. Views, routes and data are untouched; add the keys back to restore them.
  Repository's "Decomposition" entry kind (🌳, links to a decomposition node) is unchanged.

## 2026-10-05 — Vision · YouTube: master view, thumbnail feedback, notes @-mentions

- Blueprint marked amber (added to `REVIEW_TABS` in app.js) — under review, may be cut.
- **Master view** (YouTube list, `vision-youtube.js`): homepage-style 16:9 grid — search + chips (types and stages
  actually in use, filtered client-side), stage badge where YouTube puts the duration, type avatar, title clamp.
  Cover = chosen thumbnail else first option with an image; hovering a video with several options cycles them.
- **Thumbnail feedback** (`vision-thumbs.js`): `(:ThumbnailOption)-[:HAS_FEEDBACK]->(:ThumbFeedback {text, verdict
  ""|like|dislike, date})` — a dated thread, not the old one-line `notes` (field kept in the model, no longer shown).
  `POST|DELETE /api/vision/videos/{vid}/thumbnails/{tid}/feedback[/{fid}]`; video/option deletes cascade it.
  Clicking an option opens `window.ThumbViewer`: full-size, ‹ › and ←/→ cycle, filmstrip, an in-feed-size preview
  with the video title, choose button, feedback thread (ctrl+↵ to add). Choosing moved from "click the image" to a
  "✓ choose" button, since the click now opens the viewer.
- **Production notes @-mentions**: type `@` → `GET /api/vision/mentionables?q=` (videos, Synapse `:Concept`s, ideas,
  docs) → inserts `@[Label](kind:id)`. On notes save the backend mirrors tokens into
  `(:Video)-[:MENTIONS {kind}]->(target)` (unknown ids dropped), so chips render the *current* title and the video
  payload carries `mentions` + `mentioned_by` backlinks. Notes show read-mode with clickable chips; click to edit.

## 2026-10-05 — Vision · Network: table + person pages + contact log

- `vision-network.js` rewritten from expandable cards to a sortable, searchable **table** (Name · Known from ·
  First contacted · Last contacted (+ "4d ago") · Platform · Role · Touches). Add row = name + known from + first-contacted date.
- Clicking a row opens the person's **page**: every field editable (new `known_from`, `first_contact`, `email` on
  `:Contact`, "" defaults so old contacts read fine), click the avatar to upload, notes, images widget, delete.
- **Contact log**: `(:Contact)-[:HAS_INTERACTION]->(:ContactInteraction {date, channel, note})`;
  `POST|DELETE /api/vision/network/{id}/interactions[/{iid}]`, `GET /api/vision/network/{id}`. List/get return
  `interactions` (newest first) + `last_contact`; the table falls back to `first_contact` when nothing's logged.
  Deleting a contact cascades its log.
- Urgency "!" on contacts: `urgency` ""|red|blue|green on `:Contact` (Literal-validated). A round "!" button in the
  table's first column and next to the name on the person page; click cycles none→red→blue→green→none without
  opening the row. Sorting by "!" ranks red, blue, green, then none.

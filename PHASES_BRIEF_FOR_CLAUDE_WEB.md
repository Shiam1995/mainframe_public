# Phases — brief for a Claude web design session

Paste or upload this into claude.ai. It describes what the Phases tab in my
personal OS ("Mainframe") does today and what I want the next version to do.
Please give back **a design and an HTML mockup**, not backend code. The code
changes happen locally afterwards.

## The app, in one paragraph
Mainframe is a local-first personal OS: FastAPI + Neo4j backend, vanilla
HTML/CSS/JS frontend with no JS libraries, and only local LLMs (Ollama). Work
is recorded as `:WorkSession` rows (date, minutes, what, project). A **Phase**
is a 14-week sprint over my `:Project` nodes. Only one phase can be active at a time.

## Rules the design must keep
1. **Counts cannot lie.** Hours and sessions are always *summed from
   WorkSessions inside the phase window*. They are never typed in or stored.
2. **A phase closes only when every project has an outcome**:
   done / carried / dropped.
3. Anything I work on during an active phase joins it automatically (`IN_PHASE`).
4. No external services, and no auto-saving an LLM's guess. The LLM proposes,
   I confirm.

## What exists today (example data)
**Phase 0 "Alpha"**, active, 14 Sep → 20 Dec 2026 (week 3 of 14). Next is
"Beta", starting 4 Jan 2027.
Goal: *"Visible progress on the main projects, the must-land items done, and an
honest log of estimate vs actual so Beta's plan can be trusted."*
Capacity: 25 h/week (floor 18, ceiling 35). Breaks come after every 2 weeks.

**The problem: the plan is about twice my capacity.**
- Planned: **700 h**. Capacity: **350 h** (14 × 25).
- Planned hours per week run from 40 to 70, against 25 available.
- Logged so far: wk1 0 h, wk2 2.5 h, wk3 1.5 h.
- Another 115 h of "cadence" claims have no weekly plan at all.

Planned projects (tier · ref · claimed hours):
| tier | project | h |
|---|---|---|
| must | Sample Course A · 1 | 50 |
| must | Hardware Kit Build · 2a (all in wks 13–14!) | 45 |
| must | Textbook One · 3a | 40 |
| must | Textbook Two · 3b | 35 |
| must | Intro Course B · 3c | 30 |
| must | Video Series C · V | 30 |
| progress | Textbook Three · 3d | 110 |
| progress | Side Project X · 4a | 65 |
| progress | Side Project Y · 4b | 55 |
| progress | Side Project Z · 4c | 55 |
| progress | Maths Refresher · 3e | 50 |
| progress | Textbook Four · 3f | 40 |
| progress | Textbook Five · 3g | 30 |
| work | Mainframe · 5 | 65 |
| cadence | Monthly topic · 6 / Paper deep dive · 7 / One question a week · Q | 50 / 45 / 20 (no weekly plan) |

Another 10 projects are in the phase with no plan (Books, General Learning,
Habits, Misc, a few more textbooks, a reading group…).
They joined automatically.

Each plan is stored on the `(:Project)-[:CLAIMED_BY {planned:[14 weekly hours]}]->(:Phase)` edge.
Book projects also track chapters (done / estimate / logged).

What the tab shows now: the phase header (name, goal, banner, edit), a stat
grid, project cards with sessions/hours/outcome, a **Pace** view (per-day
share, catch-up hours, planned vs logged per week, and a calibration verdict
after 2 full weeks), phase goals (empty so far), and a close modal that asks
for an outcome for each project.

## What I want next — please design these
### A. Cut & change (re-planning)
- A **planning board** covering 14 weeks × projects. Each cell holds planned
  hours, with a capacity line per week. Over-capacity weeks turn red.
- **Cut** actions:
  - drop a project from the phase (outcome = dropped, with a reason),
  - defer it to the next phase (carried),
  - shrink its claimed hours,
  - slide its hours to other weeks.
- A **"fit to capacity"** helper that *proposes* a cut (for example: keep
  musts, scale progress tiers) as a diff that I accept line by line.
- Every re-plan is **versioned**. I want to see plan v1 → v2 → v3 with the
  reason for each change. The phase's goal is an honest estimate-vs-actual
  record, so the original plan must never be overwritten.

### B. Writing attached to the phase — blog, feelings, thoughts
- One place to write inside the phase. Each entry has a kind (**blog draft /
  reflection / feeling / thought**), a date, and optional links to a project
  and/or a week.
- Entries show in the phase's **timeline**, next to the hours for that week.
- Weekly check-in prompt at each 2-week break: "how did it feel, what would
  you cut?" The answer can turn directly into a re-plan (links to A).
- Blog drafts can be promoted to a real document (Mainframe already has a
  Docs tab that writes markdown files) and marked published.
- The phase-close reflection is built from those entries.

## Existing pieces to reuse (don't reinvent)
- **Diary** (`:DiaryEntry {date, text, title, module, section, tags}`), which
  has *no link to phases or projects yet*.
- **Notes**: these can already be `IN_PHASE`.
- **Journal / Mind dump** (`:MindDump`, voice → main points → proposal → commit).
- **Docs** (markdown files on disk, history, export).

The open question for you: should phase writing be a new node type, or
Diary/Notes entries with a phase + project edge? I lean towards reusing Diary
and adding `-[:IN_PHASE]->` and `-[:ABOUT]->(:Project)` edges, so there is one
store and nothing gets copied.

## Deliverables I want back
1. Short IA: where A and B sit inside the Phases tab (sub-tabs? panels?).
2. One self-contained HTML mockup (no libraries) of the planning board and
   the phase timeline with writing entries.
3. The data changes as a list of nodes/edges/endpoints, so I can hand them
   to Claude Code.

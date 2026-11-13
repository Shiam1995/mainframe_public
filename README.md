# Paper Metabolism

A self-hosted tracker for how deeply you engage with academic papers — from first
read through implementation. A module of **Mainframe**, your personal knowledge OS.

**Local-first by design.** Every moving part runs on your machine. The only
network traffic is to `localhost` (Neo4j on 7687, Ollama on 11434). No cloud
APIs, no keys, no telemetry. It works fully offline; if the local LLM is off,
extraction falls back to a pure-Python heuristic so nothing ever breaks.

---

## Everything that runs — the full stack

| Layer | Program | Version | What it does | Where it runs |
|---|---|---|---|---|
| Database | **Neo4j Community** | 5.x | Graph store — *all* data (papers, KG, citations, log) lives here | Docker, `localhost:7687` (+ browser UI `:7474`) |
| LLM engine | **Ollama** (MIT, open source) | your install | Runs the local model for metadata/KG/concept/reference extraction | `localhost:11434` |
| LLM model | **qwen2.5:7b-instruct** (Apache-2.0) | 7B, Q4_K_M | The actual weights doing extraction — fully open source, **~4.7 GB** | pulled into Ollama |
| API + web server | **Uvicorn / FastAPI** | 0.115 / 0.34 | Serves the JSON API *and* the frontend | `localhost:8000` |
| PDF parsing | **PyMuPDF** (`fitz`) | 1.25 | Extracts text from PDFs — local, no OCR service | in-process |
| Frontend | **Vanilla HTML/CSS/JS** | — | UI; KG canvas + ideas grid are hand-rolled, **zero JS libraries** | your browser |

### Python dependencies (`backend/requirements.txt`) and why each is here
- `fastapi`, `uvicorn` — the API server, which also serves this frontend.
- `neo4j` — official driver; the **only** data layer (Cypher). No SQLite, no JSON store.
- `pydantic`, `pydantic-settings` — request/response models + config.
- `PyMuPDF` — local PDF → text.
- `httpx` — talks to the **local** Ollama HTTP endpoint only.
- `python-multipart` — PDF file uploads.
- `PyYAML` — reads `~/.mainframe/config/settings.yaml`.

There is deliberately **no** `anthropic` or any cloud SDK in the list.

### Why no frontend framework or spreadsheet library
The spec suggested Handsontable/jSpreadsheet for the ideas table. Those are heavy
and license-encumbered, and a framework would hide what the app is doing. To keep
everything auditable and offline, the ideas grid and the knowledge-graph canvas
are **written by hand in plain JS** (see `frontend/js/ideas.js`, `frontend/js/kg.js`).
If you ever want a richer grid, `ideas.js` is the single file to swap.

---

## Running it

```bash
./start.sh          # brings up Neo4j (Docker) + the API, waits for readiness
# open http://localhost:8000
./stop.sh           # stops both; your graph persists in the Docker volume
```

`start.sh` is idempotent — rerun it any time. First Neo4j boot takes ~20s.

### The local LLM — model to download

Extraction runs on a local Ollama model. The default is fully open source:

```bash
ollama pull qwen2.5:7b-instruct     # ~4.7 GB download (7B params, Q4_K_M)
```

| Model | License | Download size |
|---|---|---|
| **qwen2.5:7b-instruct** (default) | Apache-2.0 — fully open source, no usage caveats | **~4.7 GB** |

Both the engine (Ollama, MIT) and these weights (Apache-2.0) are open source, so
the whole LLM stack is cleanly permissive. To use a different model, `ollama pull`
it and set `ollama_model:` in `~/.mainframe/config/settings.yaml`.

**No model, no problem:** with Ollama stopped — or the model not yet pulled — the
app still ingests papers using the built-in pure-Python heuristic parser (regex +
layout heuristics), just with rougher metadata. Nothing ever hard-fails.

---

## Where things live

```
~/.mainframe/                     # all your data (outside the code repo)
├── papers/originals/             # pristine uploaded PDFs
├── papers/instances/             # per-reading annotated copies
├── config/settings.yaml          # Neo4j + LLM config, idea categories
└── exports/                      # log + ideas CSV/JSON exports

~/mainframe-app/                   # this application
├── start.sh / stop.sh
├── docker-compose.yml            # reference (start.sh uses plain docker run)
├── backend/                      # FastAPI + Neo4j + LLM + PDF
│   ├── main.py  config.py  db.py  activity.py  llm.py  pdf.py  models.py
│   └── routes/  (papers, instances, highlights, terms, tasks, refs,
│                 kg, deepdive, ideas, headers, log)
└── frontend/                     # vanilla JS, one file per view
    ├── index.html  css/main.css
    └── js/  (api, ui, app + one module per tab)
```

---

## How a paper flows through the system

1. **Upload** a PDF → stored in `papers/originals/`.
2. **PyMuPDF** extracts the first pages' text (local).
3. **Ollama** returns structured metadata (title/authors/year/venue/abstract/ids);
   if unavailable, the **heuristic** fills in. A `:Paper` node is written to Neo4j,
   with `:Author`/`:Venue` linked.
4. In the **Workspace** you create reading **instances** (v1, v2…), add
   **highlights** (knew/new/rethink/implement), and score **terms** 0–10 by
   familiarity (red 0–3 / amber 4–6 / teal 7–10).
5. The **Knowledge Graph** has three layers: `manual` (yours), `auto`
   (LLM-generated, **frozen** — editing returns HTTP 409), and `auto_edit`
   (a clone of an auto node you *can* edit; every edit is logged with before/after).
6. **Tasks**, **citation matrix**, **timeline**, **deep dives**, the
   **ideas spreadsheet**, and **custom sections** all read/write the same graph.
7. **Every mutation** writes a timestamped `:LogEntry` — see the **Log** tab
   (filter by category, export JSON).

---

## API surface (all under `/api`)

`papers · instances · highlights · terms · tasks · refs · kg/nodes · kg/edges ·
kg/generate · kg/query · deepdive · ideas · headers · log`
plus `GET /api/health` (reports Neo4j + which LLM backend is effective).
Interactive docs: **http://localhost:8000/docs**.

---

## Data model (Neo4j)

Nodes: `Paper, Instance, Highlight, Concept, Question, Task, Author, Venue,
DeepDive, Idea, CustomHeader, KGNode, LogEntry`.
Key relationships: `HAS_INSTANCE, CONTAINS, INTRODUCES, CITES{highlighted},
AUTHORED_BY, PUBLISHED_AT, BELONGS_TO, FOCUSES_ON, SCOPED_TO, RELATES{label,layer}`.
Constraints/indexes are created idempotently on every startup (`backend/db.py`).
Inspect the raw graph any time at the Neo4j browser: **http://localhost:7474**
(user `neo4j`, password `mainframe`).

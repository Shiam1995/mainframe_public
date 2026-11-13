"""Synapse (Mainframe module) — FastAPI entrypoint.

Serves the JSON API under /api/* and the vanilla-JS frontend at /. All data is
in Neo4j; the LLM is local (Ollama) with a heuristic fallback. Nothing here
reaches a cloud service.

Run:  uvicorn main:app --reload   (from the backend/ directory)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import llm
from config import settings
from db import close_driver, init_schema, verify_connectivity

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
log = logging.getLogger("synapse")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from routes.planner import start_scheduler  # noqa: PLC0415 — avoids an import cycle at module load

    settings.papers_originals.mkdir(parents=True, exist_ok=True)
    settings.papers_instances.mkdir(parents=True, exist_ok=True)
    settings.exports_dir.mkdir(parents=True, exist_ok=True)
    settings.dictionary_images.mkdir(parents=True, exist_ok=True)
    settings.boot_wallpapers.mkdir(parents=True, exist_ok=True)
    settings.boot_sounds.mkdir(parents=True, exist_ok=True)
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    settings.pulse_medical_dir.mkdir(parents=True, exist_ok=True)
    (settings.pulse_fitness_dir / "videos").mkdir(parents=True, exist_ok=True)
    if await verify_connectivity():
        await init_schema()
    else:
        log.warning("Starting WITHOUT Neo4j — start it, then restart the API.")
    # Planner: Friday 16:00 weekly-report generation (idempotent per week).
    report_task = start_scheduler()
    yield
    report_task.cancel()
    await close_driver()


app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Self-hosted paper-engagement tracker (Mainframe module). Local-first.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "neo4j": await verify_connectivity(),
        "llm": await llm.status(),
    }


# --- Routers ---
from routes.papers import router as papers_router  # noqa: E402
from routes.instances import router as instances_router  # noqa: E402
from routes.highlights import router as highlights_router  # noqa: E402
from routes.terms import router as terms_router  # noqa: E402
from routes.tasks import router as tasks_router  # noqa: E402
from routes.refs import router as refs_router  # noqa: E402
from routes.kg import router as kg_router  # noqa: E402
from routes.deepdive import router as deepdive_router  # noqa: E402
from routes.ideas import router as ideas_router  # noqa: E402
from routes.headers import router as headers_router  # noqa: E402
from routes.dictionary import router as dictionary_router  # noqa: E402
from routes.log import router as log_router  # noqa: E402
from routes.boot import router as boot_router  # noqa: E402
from routes.mind import router as mind_router  # noqa: E402
from routes.refgraph import router as refgraph_router  # noqa: E402
from routes.projects import router as projects_router  # noqa: E402
from routes.projectpasses import router as projectpasses_router  # noqa: E402
from routes.heatmap import router as heatmap_router  # noqa: E402
from routes.work import router as work_router  # noqa: E402
from routes.decomposition import router as decomposition_router  # noqa: E402
from routes.learning import router as learning_router  # noqa: E402
from routes.pulse import router as pulse_router  # noqa: E402
from routes.fitness import router as fitness_router  # noqa: E402
from routes.benchmarks import router as benchmarks_router  # noqa: E402
from routes.nutrition import router as nutrition_router  # noqa: E402
from routes.recovery import router as recovery_router  # noqa: E402
from routes.habit_areas import router as habit_areas_router  # noqa: E402
from routes.attach import router as attach_router  # noqa: E402
from routes.images import router as images_router  # noqa: E402
from routes.vision import router as vision_router  # noqa: E402
from routes.vault import router as vault_router  # noqa: E402
from routes.vault_analytics import router as vault_analytics_router  # noqa: E402
from routes.home import router as home_router  # noqa: E402
from routes.wallpapers import router as wallpapers_router  # noqa: E402
from routes.modulecards import router as modulecards_router  # noqa: E402
from routes.calendar import router as calendar_router  # noqa: E402
from routes.agent import router as agent_router  # noqa: E402
from routes.docs import router as docs_router  # noqa: E402
from routes.sheets import router as sheets_router  # noqa: E402
from routes.recurring import router as recurring_router  # noqa: E402
from routes.focus import router as focus_router  # noqa: E402
from routes.framework import router as framework_router  # noqa: E402
from routes.pulsescore import router as pulsescore_router  # noqa: E402
from routes.snapshot import router as snapshot_router  # noqa: E402
from routes.lattice import router as lattice_router  # noqa: E402
from routes.planner import router as planner_router  # noqa: E402
from routes.settings import router as settings_router  # noqa: E402
from routes.diary import router as diary_router  # noqa: E402
from routes.phases import router as phases_router  # noqa: E402
from routes.notes import router as notes_router  # noqa: E402
from routes.inbox import router as inbox_router  # noqa: E402
from routes.lessons import router as lessons_router  # noqa: E402
from routes.questions import router as questions_router  # noqa: E402
from routes.rows import router as rows_router  # noqa: E402
from routes.assumptions import router as assumptions_router  # noqa: E402
from routes.books import router as books_router  # noqa: E402
from routes.timeline import router as timeline_router  # noqa: E402
from routes.gratitude import router as gratitude_router  # noqa: E402
from synapse.api.references import router as references_router  # noqa: E402

for r in (
    papers_router, instances_router, highlights_router, terms_router, tasks_router,
    refs_router, kg_router, deepdive_router, ideas_router, headers_router,
    dictionary_router, log_router, boot_router, mind_router, refgraph_router,
    projects_router, projectpasses_router, heatmap_router, work_router, decomposition_router, learning_router, pulse_router, fitness_router, benchmarks_router,
    nutrition_router, recovery_router, images_router, vision_router, vault_router, vault_analytics_router, home_router, wallpapers_router,
    modulecards_router, calendar_router, agent_router, docs_router, sheets_router, recurring_router, focus_router, framework_router, pulsescore_router,
    snapshot_router, lattice_router, planner_router, settings_router, references_router,
    diary_router, phases_router, notes_router, lessons_router, questions_router, rows_router, assumptions_router,
    inbox_router, books_router, habit_areas_router, attach_router, timeline_router, gratitude_router,
):
    app.include_router(r)

# --- Boot-screen assets (mounted before the catch-all so they take priority) ---
# StaticFiles validates the dir at construction, before lifespan mkdir runs.
settings.boot_wallpapers.mkdir(parents=True, exist_ok=True)
settings.boot_sounds.mkdir(parents=True, exist_ok=True)
app.mount(
    "/boot-assets/wallpapers",
    StaticFiles(directory=str(settings.boot_wallpapers)),
    name="boot-wallpapers",
)
app.mount(
    "/boot-assets/sounds",
    StaticFiles(directory=str(settings.boot_sounds)),
    name="boot-sounds",
)

# --- Home-screen wallpapers (web-sized copies; originals stay where you put them) ---
settings.wallpapers_cache.mkdir(parents=True, exist_ok=True)
app.mount(
    "/wallpaper-files",
    StaticFiles(directory=str(settings.wallpapers_cache)),
    name="wallpaper-files",
)

# --- Module-card artwork (same deal: web-sized copies of your own images) ---
settings.module_cards_cache.mkdir(parents=True, exist_ok=True)
settings.assistant_avatar_cache.mkdir(parents=True, exist_ok=True)
app.mount(
    "/assistant-files",
    StaticFiles(directory=str(settings.assistant_avatar_cache)),
    name="assistant-files",
)

app.mount(
    "/module-card-files",
    StaticFiles(directory=str(settings.module_cards_cache)),
    name="module-card-files",
)

# --- Frontend (served last so /api/* wins) ---
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

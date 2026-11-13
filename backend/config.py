"""Configuration for Synapse (Mainframe module).

Values come from (in order of precedence):
  1. environment variables / a .env file next to this backend
  2. ~/.mainframe/config/settings.yaml   (persistent, human-editable)
  3. the defaults below

Nothing here points at a cloud service. NEO4J and OLLAMA are both localhost.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import os

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

def _load_dotenv() -> None:
    """Export .env into the process environment, before anything reads it.

    pydantic-settings parses .env for the Settings model only — it does NOT put
    those values in `os.environ`. MAINFRAME_HOME is read below at import time
    (every storage path derives from it), so without this a fork's `.env` is
    silently ignored and the fork writes into the original's data directory.

    `setdefault`, so a real environment variable still beats the file.
    """
    p = Path(__file__).resolve().parent / ".env"
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# ~/.mainframe holds all user data + config (per the spec).
#
# Overridable via the MAINFRAME_HOME environment variable so a second copy of
# this app — a fork, a hackathon branch, a test instance — can run side by side
# with its own data instead of silently writing into yours. Every storage path
# below is derived from this, so one variable moves all of them together; setting
# them individually would be fifteen chances to miss one and have a "separate"
# instance quietly share your uploads.
MAINFRAME_HOME = Path(os.environ.get("MAINFRAME_HOME") or Path.home() / ".mainframe").expanduser()
CONFIG_FILE = MAINFRAME_HOME / "config" / "settings.yaml"


def _yaml_defaults() -> dict:
    """Load settings.yaml if present; return {} otherwise (never crash)."""
    if CONFIG_FILE.exists():
        try:
            data = yaml.safe_load(CONFIG_FILE.read_text()) or {}
            # flatten a couple of nested sections we care about
            flat: dict = {}
            for key in ("neo4j", "llm", "storage"):
                section = data.get(key) or {}
                if isinstance(section, dict):
                    flat.update(section)
            flat.update({k: v for k, v in data.items() if not isinstance(v, dict)})
            return flat
        except Exception:  # malformed yaml → fall back to env/defaults
            return {}
    return {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "Mainframe"
    environment: str = "development"
    debug: bool = True
    cors_origins: str = "http://localhost:8000,http://localhost:5173"

    # --- Neo4j (local graph DB — the only primary store) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "mainframe"
    neo4j_database: str = "neo4j"

    # --- LLM (local-first) ---
    # provider: "ollama" | "heuristic". No cloud provider by design.
    llm_provider: str = "ollama"
    ollama_host: str = "http://localhost:11434"
    # Apache-2.0, fully open source. See README for the pull command + size.
    ollama_model: str = "qwen2.5:7b-instruct"
    llm_timeout_s: float = 120.0

    # --- Reference resolution (Synapse references pipeline) ---
    # The ONE deliberate exception to "no network egress": Crossref/OpenAlex
    # lookups to resolve citations. The mailto joins Crossref's polite pool.
    # Empty by default; set CROSSREF_MAILTO in backend/.env to your own address.
    crossref_mailto: str = ""
    ref_resolve_timeout_s: float = 20.0
    # Below this, a parsed reference goes to the review queue, not the graph.
    ref_confidence_threshold: float = 0.80

    # --- File storage ---
    # Synapse module data lives under ~/.mainframe/synapse/ (per UPDATE_SPEC #1).
    # Exports stay at the Mainframe level (~/.mainframe/exports).
    papers_originals: Path = MAINFRAME_HOME / "synapse" / "originals"
    papers_instances: Path = MAINFRAME_HOME / "synapse" / "instances"
    exports_dir: Path = MAINFRAME_HOME / "exports"
    # Dictionary is a global Mainframe service, so its images sit at the
    # Mainframe level (not under synapse/).
    dictionary_images: Path = MAINFRAME_HOME / "dictionary" / "images"
    # Boot-screen assets (UPDATE_SPEC #9). Drop any image/audio file in here and
    # the CRT boot screen picks it up automatically.
    boot_wallpapers: Path = MAINFRAME_HOME / "synapse" / "wallpapers"
    boot_sounds: Path = MAINFRAME_HOME / "synapse" / "sounds"
    # Project files (Mainframe-level). Uploaded project files are copied here.
    projects_dir: Path = MAINFRAME_HOME / "projects"
    # Documents (Mainframe-level). Deliberately REAL FILES on disk, one per
    # document, not text blobs in Neo4j: a document you can't grep, diff, open
    # in another editor or drop into a backup isn't self-owned. Neo4j holds the
    # metadata (title/folder/format/timestamps) and points at the file.
    documents_dir: Path = MAINFRAME_HOME / "documents"
    # Pulse module (habits/routines/medical/meds). Medical uploads go under
    # pulse/medical/<section>/.
    pulse_dir: Path = MAINFRAME_HOME / "pulse"
    pulse_medical_dir: Path = MAINFRAME_HOME / "pulse" / "medical"
    # Fitness sub-module; videos dir reserved for the FUTURE form-checker.
    pulse_fitness_dir: Path = MAINFRAME_HOME / "pulse" / "fitness"
    # Images are a MAINFRAME-LEVEL service shared by every module (VISION_SPEC).
    # Files land in images/<module>/, so a module's pictures stay together.
    images_dir: Path = MAINFRAME_HOME / "images"
    # Home-screen wallpapers. `wallpapers_source` is where YOU drop full-size
    # images (scanned recursively, originals never touched); `wallpapers_cache`
    # holds the web-sized copies the home screen actually serves. Both are
    # overridable in settings.yaml so the source folder can live anywhere.
    wallpapers_source: Path = Path.home() / "mAInframe" / "Wallpapers"
    wallpapers_cache: Path = MAINFRAME_HOME / "wallpapers"
    # USDA FoodData Central archives — the permanent food catalogue's source.
    # Public domain, downloaded once, imported into Neo4j. Kept on disk so the
    # import can be re-run offline forever (see foodcatalog.py).
    foodcatalog_source: Path = MAINFRAME_HOME / "foodcatalog" / "source"
    # Which Open Food Facts countries to import, as comma-separated OFF country
    # tags (e.g. "en:united-kingdom,en:ireland"). Empty = the whole world, which
    # is a few million products. Changing this needs a re-import to take effect.
    off_countries: str = ""
    # Calendar. Export an .ics from Google Calendar (or any calendar app) and
    # drop it in here — the importer reads every .ics it finds. Deliberately a
    # folder, not one file: several calendars can be imported side by side, and
    # each keeps its own name.
    calendar_import_dir: Path = MAINFRAME_HOME / "calendar" / "import"
    # --- Voice assistant (all local) ---
    # Speech in: faster-whisper on the GPU. "large-v3" is the most accurate;
    # "small"/"medium" are lighter if you'd rather. Changing this re-downloads
    # once, then it's cached under ~/.cache/huggingface.
    whisper_model: str = "large-v3"
    whisper_device: str = "cuda"          # "cpu" works, just slower
    whisper_compute: str = "float16"      # use "int8" on CPU
    whisper_language: str = "en"          # "" to auto-detect
    # Speech out: piper. Point this at a downloaded .onnx voice.
    piper_voice: Path = MAINFRAME_HOME / "voices" / "en_GB-alba-medium.onnx"
    # The assistant's face. Drop an image in the source folder and it becomes
    # the launcher button and the icon beside everything it says. Originals are
    # never modified; sized copies are cached (see avatar.py).
    assistant_avatar_source: Path = Path.home() / "mAInframe" / "AI_assistant"
    assistant_avatar_cache: Path = MAINFRAME_HOME / "assistant"
    # What it's called, in its own header and when it introduces itself.
    assistant_name: str = "Leo"
    # Long edge of the cached copy, and JPEG quality. 1920 covers any normal
    # screen; anything larger is bytes the browser throws away on scale-down.
    wallpaper_max_px: int = 1920
    wallpaper_quality: int = 82
    # Home-screen module-card artwork. Drop one image per module into
    # `module_cards_source`, named after the module key (synapse.jpg, pulse.png,
    # …) — the filename IS the wiring. Same mirror-into-a-cache approach as the
    # wallpapers; originals are never modified. Cards render ~380px tall, so 900
    # covers a 2× display with room to spare.
    module_cards_source: Path = Path.home() / "mAInframe" / "Imageformainframescreen"
    module_cards_cache: Path = MAINFRAME_HOME / "module-cards"
    module_card_max_px: int = 900
    module_card_quality: int = 88

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Precedence, as promised at the top of this file: env / .env, then
    settings.yaml, then the defaults above.

    The previous version passed the whole yaml in as constructor kwargs with the
    comment "env vars still win because BaseSettings reads them last" — that is
    **backwards**. In pydantic-settings, init kwargs are the HIGHEST priority
    source, above environment variables and .env. So settings.yaml quietly beat
    everything, and a fork that set NEO4J_URI in its own .env still connected to
    the original's database. Yaml keys already present in the environment are
    dropped here so yaml is a genuine default layer.
    """
    yaml_defaults = {k: v for k, v in _yaml_defaults().items()
                     if k.upper() not in os.environ}
    return Settings(**yaml_defaults)


settings = get_settings()

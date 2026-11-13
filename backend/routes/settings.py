"""/api/settings — the one screen where the Mainframe's own moving parts are chosen.

Every choice here is a *local* one: which whisper model hears you, which Ollama
model thinks, which piper voice answers. Nothing in this file can point the app
at a cloud service; the lists it offers are the models already on this machine
(Ollama's own tag list, the .onnx voices on disk) plus the whisper sizes
faster-whisper knows how to fetch.

Writes land in ~/.mainframe/config/settings.yaml — the same human-editable file
config.py already reads, so a change made here is a change you can also see, and
undo, in a text editor. They are then applied to the *running* process, because a
settings screen that needs a restart to take effect is a config file with extra
steps.

One honest caveat the UI surfaces: an environment variable outranks settings.yaml
(see config.get_settings), so a key set in .env is reported as locked rather than
silently accepted and lost on the next boot.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import CONFIG_FILE, settings

log = logging.getLogger("synapse.settings")
router = APIRouter(prefix="/api/settings", tags=["settings"])

# The whisper sizes worth offering, biggest-first, with the trade the user is
# actually making. Notes are deliberately in plain English: the point of the
# screen is choosing without having to know what a compute type is.
WHISPER_MODELS = [
    {"id": "large-v3", "label": "large-v3", "size": "~3.1 GB",
     "note": "the most accurate. Best on a GPU."},
    {"id": "large-v3-turbo", "label": "large-v3-turbo", "size": "~1.6 GB",
     "note": "almost large-v3's accuracy, several times faster. A good default."},
    {"id": "distil-large-v3.5", "label": "distil-large-v3.5", "size": "~1.5 GB",
     "note": "distilled large — fast, English-focused."},
    {"id": "medium", "label": "medium", "size": "~1.5 GB",
     "note": "solid all-rounder if the GPU is busy."},
    {"id": "small", "label": "small", "size": "~480 MB",
     "note": "light. Fine for short commands, weaker on long dictation."},
    {"id": "base", "label": "base", "size": "~140 MB",
     "note": "runs on anything; expect to correct it."},
    {"id": "tiny", "label": "tiny", "size": "~75 MB",
     "note": "smallest and roughest. Last resort on a CPU."},
]
# .en variants are English-only and a touch sharper on English; offered for the
# smaller sizes where the accuracy gap actually matters.
WHISPER_MODELS += [
    {"id": f"{m}.en", "label": f"{m}.en", "size": "same, English-only",
     "note": f"{m}, trained on English alone — a little better if you only speak English."}
    for m in ("medium", "small", "base", "tiny")
]

DEVICES = [
    {"id": "cuda", "label": "cuda (GPU)", "note": "fastest, if you have an NVIDIA card"},
    {"id": "cpu", "label": "cpu", "note": "always works, several times slower"},
    {"id": "auto", "label": "auto", "note": "GPU if present, otherwise CPU"},
]
COMPUTES = [
    {"id": "float16", "label": "float16", "note": "GPU default — full quality"},
    {"id": "int8_float16", "label": "int8_float16", "note": "GPU, about half the VRAM"},
    {"id": "int8", "label": "int8", "note": "CPU default — the only sensible CPU choice"},
    {"id": "float32", "label": "float32", "note": "slowest, rarely needed"},
]
LANGUAGES = [
    {"id": "en", "label": "English"},
    {"id": "", "label": "auto-detect (slower, handles any language)"},
    {"id": "fr", "label": "French"}, {"id": "de", "label": "German"},
    {"id": "es", "label": "Spanish"}, {"id": "it", "label": "Italian"},
    {"id": "pt", "label": "Portuguese"}, {"id": "nl", "label": "Dutch"},
    {"id": "hi", "label": "Hindi"}, {"id": "zh", "label": "Chinese"},
    {"id": "ja", "label": "Japanese"}, {"id": "ar", "label": "Arabic"},
]
# CPU cannot run the float16 kernels; picking that pair fails deep inside
# ctranslate2 with a message no one should have to read.
_CPU_SAFE = {"int8": "int8", "float32": "float32",
             "float16": "int8", "int8_float16": "int8"}


# --------------------------------------------------------------- persistence
def _read_yaml() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return yaml.safe_load(CONFIG_FILE.read_text()) or {}
    except Exception as exc:                      # malformed file — don't clobber it
        raise HTTPException(500, f"{CONFIG_FILE} is not valid YAML ({exc}); "
                                 "fix or delete it and try again") from exc


_MANAGED_HEADER = "# --- chosen in the Settings screen ---"


def _flat(data: dict) -> dict:
    """The same flattening config.py does, so we can check a write landed where
    the loader will actually look for it."""
    flat: dict = {}
    for section in ("neo4j", "llm", "storage"):
        sec = data.get(section)
        if isinstance(sec, dict):
            flat.update(sec)
    flat.update({k: v for k, v in data.items() if not isinstance(v, dict)})
    return flat


def _save(updates: dict) -> None:
    """Change these keys in settings.yaml, and change *only* these keys.

    Line surgery rather than parse-and-redump: this file is documented, and the
    comments explaining what qwen2.5 is or where to get a piper voice are the
    reason it's worth hand-editing. A round-trip through yaml.safe_dump silently
    throws every one of them away.

    A key already in the file — including one nested inside neo4j/llm/storage —
    is rewritten where it stands, so it keeps its section and its comment. Only a
    genuinely new key is appended, under a header saying who put it there.
    """
    text = CONFIG_FILE.read_text() if CONFIG_FILE.exists() else ""
    lines = text.splitlines()
    appended: list[str] = []

    for key, value in updates.items():
        # Let yaml do the quoting — a Windows-style path or a value with a colon
        # would otherwise produce a file that no longer parses.
        rendered = yaml.safe_dump({key: value}, default_flow_style=False).strip()
        pattern = re.compile(rf"^(\s*){re.escape(key)}\s*:.*$")
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if m:
                lines[i] = m.group(1) + rendered
                break
        else:
            appended.append(rendered)

    if appended:
        if lines and lines[-1].strip():
            lines.append("")
        if _MANAGED_HEADER not in text:
            lines.append(_MANAGED_HEADER)
        lines.extend(appended)

    out = "\n".join(lines).rstrip() + "\n"

    # Never leave the user with a config that won't load. If the edit produced
    # something unparseable, or that doesn't say what we meant, don't write it.
    try:
        parsed = yaml.safe_load(out) or {}
        flat = _flat(parsed)
    except Exception as exc:
        raise HTTPException(500, f"the edit would have broken {CONFIG_FILE} ({exc}); "
                                 "nothing was written") from exc
    for key, value in updates.items():
        if flat.get(key) != value:
            raise HTTPException(500, f"couldn't set {key} cleanly in {CONFIG_FILE}; "
                                     "nothing was written — set it by hand instead")

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(out)
    tmp.replace(CONFIG_FILE)                      # atomic: never a half-written config


def _env_locked(keys: list[str]) -> list[str]:
    """Keys an environment variable will override at the next start. get_settings
    drops yaml keys that are already in the environment, so saving one of these
    works now and silently reverts on restart — worth saying out loud."""
    return [k for k in keys if k.upper() in os.environ]


# ------------------------------------------------------------------ what's here
async def _ollama_models() -> list[str]:
    """The models actually pulled on this machine. Empty list = Ollama is down,
    which the caller must treat as "unknown", not "none installed"."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            if r.status_code != 200:
                return []
            return sorted(m["name"] for m in r.json().get("models", []))
    except Exception:
        return []


def _piper_voices() -> list[dict]:
    """Every .onnx voice sitting in the voices folder. Piper needs the matching
    .json beside it, so a voice without one is listed as unusable rather than
    offered and then failing at the first sentence."""
    out = []
    folder = Path(settings.piper_voice).expanduser().parent
    try:
        for p in sorted(folder.glob("*.onnx")):
            out.append({"path": str(p), "label": p.stem,
                        "ok": p.with_suffix(".onnx.json").is_file()})
    except Exception as exc:
        log.warning("voice scan failed for %s: %s", folder, exc)
    return out


@router.get("")
async def read_settings() -> dict:
    """Everything the settings screen draws, in one call."""
    from routes import agent as agent_routes
    ear = agent_routes.whisper_state()
    voice = Path(settings.piper_voice).expanduser()
    return {
        "speech_in": {
            "model": settings.whisper_model,
            "device": settings.whisper_device,
            "compute": settings.whisper_compute,
            "language": settings.whisper_language,
            "loaded": ear["loaded"],
            "error": ear["error"],
        },
        "brain": {"model": settings.ollama_model, "host": settings.ollama_host},
        "speech_out": {"voice": str(voice), "ok": voice.is_file(),
                       "folder": str(voice.parent)},
        "assistant": {"name": settings.assistant_name},
        "options": {
            "whisper_models": WHISPER_MODELS,
            "devices": DEVICES,
            "computes": COMPUTES,
            "languages": LANGUAGES,
            "ollama_models": await _ollama_models(),
            "piper_voices": _piper_voices(),
        },
        "env_locked": _env_locked([
            "whisper_model", "whisper_device", "whisper_compute",
            "whisper_language", "ollama_model", "piper_voice", "assistant_name",
        ]),
        "config_file": str(CONFIG_FILE),
    }


class SettingsBody(BaseModel):
    """Only the fields sent are changed — the screen can save one section at a
    time without having to echo back the rest."""
    whisper_model: str | None = None
    whisper_device: str | None = None
    whisper_compute: str | None = None
    whisper_language: str | None = None
    ollama_model: str | None = None
    piper_voice: str | None = None
    assistant_name: str | None = None


@router.put("")
async def write_settings(body: SettingsBody) -> dict:
    updates: dict = {}
    notes: list[str] = []

    if body.whisper_model is not None:
        model = body.whisper_model.strip()
        known = {m["id"] for m in WHISPER_MODELS}
        # A local directory or a HuggingFace repo id is valid too — faster-whisper
        # takes either — so only an obvious typo is rejected.
        if not model or (model not in known and "/" not in model
                         and not Path(model).expanduser().exists()):
            raise HTTPException(400, f"unknown speech model {model!r}. "
                                     f"Pick one of: {', '.join(sorted(known))}")
        updates["whisper_model"] = model

    if body.whisper_device is not None:
        device = body.whisper_device.strip()
        if device not in {d["id"] for d in DEVICES}:
            raise HTTPException(400, f"device must be one of cuda, cpu, auto (got {device!r})")
        updates["whisper_device"] = device

    if body.whisper_compute is not None:
        compute = body.whisper_compute.strip()
        if compute not in {c["id"] for c in COMPUTES}:
            raise HTTPException(400, f"unknown compute type {compute!r}")
        updates["whisper_compute"] = compute

    # Whichever of the two was just changed, the *pair* has to be runnable.
    device = updates.get("whisper_device", settings.whisper_device)
    compute = updates.get("whisper_compute", settings.whisper_compute)
    if device == "cpu" and _CPU_SAFE[compute] != compute:
        notes.append(f"{compute} needs a GPU — using {_CPU_SAFE[compute]} on the CPU")
        updates["whisper_compute"] = _CPU_SAFE[compute]

    if body.whisper_language is not None:
        lang = body.whisper_language.strip()
        if lang and not (2 <= len(lang) <= 5):
            raise HTTPException(400, "language must be a code like 'en', or empty to auto-detect")
        updates["whisper_language"] = lang

    if body.ollama_model is not None:
        model = body.ollama_model.strip()
        installed = await _ollama_models()
        if not model:
            raise HTTPException(400, "pick a model for the assistant to think with")
        # Only enforced when Ollama answered: if it's down we can't tell the
        # difference between "not pulled" and "can't ask", and refusing to save
        # a valid model because the daemon is asleep would be wrong.
        if installed and model not in installed:
            raise HTTPException(400, f"{model} isn't pulled on this machine. "
                                     f"Available: {', '.join(installed)} "
                                     f"(or run: ollama pull {model})")
        if not installed:
            notes.append("Ollama didn't answer, so the model name wasn't checked")
        updates["ollama_model"] = model

    if body.piper_voice is not None:
        voice = Path(body.piper_voice).expanduser()
        if not voice.is_file():
            raise HTTPException(400, f"no voice file at {voice}")
        if not voice.with_suffix(".onnx.json").is_file():
            raise HTTPException(400, f"{voice.name} has no matching .onnx.json beside it")
        updates["piper_voice"] = str(voice)

    if body.assistant_name is not None:
        name = body.assistant_name.strip()[:40]
        if not name:
            raise HTTPException(400, "the assistant needs a name")
        updates["assistant_name"] = name

    if not updates:
        raise HTTPException(400, "nothing to change")

    _save(updates)

    # Apply to the process that's running now. `settings` is one shared object
    # (config.get_settings is lru_cached), so every module that imported it sees
    # these immediately.
    for key, value in updates.items():
        setattr(settings, key, Path(value) if key == "piper_voice" else value)
    if any(k.startswith("whisper_") for k in updates):
        from routes import agent as agent_routes
        agent_routes.reset_whisper()
        notes.append("the speech model will load on your next dictation")

    locked = _env_locked(list(updates))
    if locked:
        notes.append("set in the environment, so this reverts on restart: "
                     + ", ".join(locked))
    log.info("settings updated: %s", ", ".join(updates))
    return {"saved": updates, "notes": notes, "config_file": str(CONFIG_FILE)}


@router.post("/speech-in/warm")
async def warm_speech_in() -> dict:
    """Load the speech model now, and report how long it took.

    large-v3 costs several seconds to load, and paying that mid-sentence feels
    like the microphone is broken. This is the "get ready" button.
    """
    from routes import agent as agent_routes
    started = time.perf_counter()
    model = agent_routes._get_whisper()
    took = round(time.perf_counter() - started, 2)
    if model is None:
        state = agent_routes.whisper_state()
        raise HTTPException(503, f"couldn't load {settings.whisper_model}: {state['error']}")
    return {"ok": True, "model": settings.whisper_model,
            "device": settings.whisper_device, "seconds": took}

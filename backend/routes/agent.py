"""/api/agent — the voice assistant.

Fully local by design: **faster-whisper** on the GPU for speech, **Ollama** for
reasoning, **piper** for the spoken reply. Nothing here calls a cloud service,
and the browser's own speech API is deliberately unused — Chrome streams
microphone audio to Google, which would quietly break the rule the rest of this
app follows.

The safety contract, chosen by the user: **reads run, writes need a yes.**
`/ask` executes read tools and returns proposed writes; only `/confirm` runs
them. See agent/runner.py.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel

from activity import record
from agent import capabilities as C
from agent import runner
import avatar
from config import settings

log = logging.getLogger("synapse.agent")
router = APIRouter(prefix="/api/agent", tags=["agent"])

# The model is loaded once and kept — it costs seconds to load and milliseconds
# to run, so reloading per request would dominate the response time.
_whisper = None
_whisper_error: str | None = None


def _get_whisper():
    global _whisper, _whisper_error
    if _whisper is not None or _whisper_error:
        return _whisper
    try:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(
            settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute,
        )
        log.info("whisper loaded: %s on %s", settings.whisper_model, settings.whisper_device)
    except Exception as exc:                       # missing package, no CUDA, no model
        _whisper_error = f"{type(exc).__name__}: {exc}"
        log.warning("whisper unavailable: %s", _whisper_error)
    return _whisper


def whisper_state() -> dict:
    """What the ear is doing *right now*, without forcing a load.

    /status deliberately loads the model to answer "does speech work"; the
    settings screen is opened far more often and must not pay ten seconds for
    large-v3 just to draw a dropdown. So it asks this instead.
    """
    return {"loaded": _whisper is not None, "error": _whisper_error}


def reset_whisper() -> None:
    """Drop the cached model so the next transcription loads the newly chosen
    one. Called when the model/device/compute settings change — without this a
    change of model would only take effect at the next restart."""
    global _whisper, _whisper_error
    _whisper, _whisper_error = None, None
    log.info("whisper cache cleared; next request will load %s", settings.whisper_model)


class AskBody(BaseModel):
    text: str
    history: list[dict] = []


class ConfirmBody(BaseModel):
    actions: list[dict]


@router.get("/status")
async def status() -> dict:
    """What the assistant can currently do. The UI uses this to explain itself
    rather than silently failing when a piece isn't installed."""
    import httpx
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.ollama_host}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False
    return {
        "brain": {"ok": ollama_ok, "model": settings.ollama_model},
        "speech_in": {"ok": _get_whisper() is not None,
                      "model": settings.whisper_model,
                      "device": settings.whisper_device,
                      "error": _whisper_error},
        # `bool(Path)` is always true — checking truthiness reported speech-out
        # as working while /speak correctly 503'd on the missing model. Check
        # the file is actually there.
        "speech_out": {"ok": bool(shutil.which("piper"))
                             and Path(settings.piper_voice).expanduser().is_file(),
                       "voice": str(settings.piper_voice),
                       "error": None if Path(settings.piper_voice).expanduser().is_file()
                                else "voice model not downloaded"},
        "capabilities": [{"name": c["name"], "kind": c["kind"],
                          "description": c["description"]} for c in C.CAPS],
        "policy": "reads run immediately; writes are proposed and need confirming",
        "name": settings.assistant_name,
        "avatar": await asyncio.to_thread(avatar.ensure_cache, False),
    }


@router.post("/ask")
async def ask(body: AskBody) -> dict:
    if not body.text.strip():
        raise HTTPException(400, "nothing to do")
    try:
        out = await runner.ask(body.text.strip(), body.history)
    except Exception as exc:
        log.exception("agent ask failed")
        raise HTTPException(502, f"the local model failed: {exc}") from exc
    await record("agent", "asked", detail=body.text[:80], trigger="llm")
    return out


@router.post("/confirm")
async def confirm(body: ConfirmBody) -> dict:
    """Run actions the user has explicitly approved. The ONLY path by which the
    assistant changes data."""
    if not body.actions:
        raise HTTPException(400, "nothing to confirm")
    results = await runner.execute(body.actions)
    done = [r for r in results if r.get("ok")]
    await record("agent", "actions confirmed",
                 detail="; ".join(r.get("describe", "") for r in done)[:120], trigger="llm")
    return {"results": results,
            "summary": f"{len(done)} of {len(results)} done"}


# Whisper writes what it expects to hear next, so a sample of the expected style
# is the whole of the tuning. Commands are short and unpunctuated; dictation is
# prose and wants full stops and capitals, which are tedious to add by hand.
_DICTATION_PROMPT = (
    "The following is dictated prose, written out with correct capitalisation, "
    "commas, full stops and question marks."
)


@router.post("/listen")
async def listen(audio: UploadFile = File(...),
                 mode: str = Form("command")) -> dict:
    """Speech to text, on this machine. Returns the transcript only — the caller
    decides whether to send it on to /ask, so a mis-hear can be seen and edited
    before anything acts on it.

    `mode="dictate"` is voice typing: the text goes straight into whatever field
    you were typing in, so it is nudged towards punctuated prose rather than the
    bare phrases a command is.
    """
    model = _get_whisper()
    if model is None:
        raise HTTPException(503, f"speech recognition unavailable: {_whisper_error}")

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await audio.read())
        path = tmp.name
    try:
        dictating = mode == "dictate"
        segments, info = model.transcribe(
            path, language=settings.whisper_language or None,
            # A short command is easy to mis-hear; beam search costs
            # milliseconds on this GPU and measurably improves accuracy.
            beam_size=5, vad_filter=True,
            initial_prompt=_DICTATION_PROMPT if dictating else None,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        return {"text": text, "language": getattr(info, "language", ""),
                "duration": round(getattr(info, "duration", 0.0), 2)}
    except Exception as exc:
        log.exception("transcription failed")
        raise HTTPException(500, f"transcription failed: {exc}") from exc
    finally:
        Path(path).unlink(missing_ok=True)


class SpeakBody(BaseModel):
    text: str


@router.post("/speak")
async def speak(body: SpeakBody) -> Response:
    """Text to speech via piper, locally. Returns WAV bytes."""
    if not shutil.which("piper"):
        raise HTTPException(503, "piper is not installed")
    if not settings.piper_voice or not Path(settings.piper_voice).expanduser().is_file():
        raise HTTPException(503, f"no piper voice model at {settings.piper_voice}")
    text = (body.text or "").strip()[:1000]
    if not text:
        raise HTTPException(400, "nothing to say")
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out = tmp.name
    try:
        proc = subprocess.run(
            ["piper", "--model", str(Path(settings.piper_voice).expanduser()),
             "--output_file", out],
            input=text.encode("utf-8"), capture_output=True, timeout=60,
        )
        if proc.returncode != 0:
            raise HTTPException(500, f"piper failed: {proc.stderr.decode()[:200]}")
        data = Path(out).read_bytes()
        return Response(content=data, media_type="audio/wav")
    finally:
        Path(out).unlink(missing_ok=True)

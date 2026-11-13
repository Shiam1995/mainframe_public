"""The assistant's reasoning loop: text in, answers and proposed actions out.

The safety model, which is the whole design
-------------------------------------------
The user chose: **reads run, writes need a yes.** That is enforced here, not in
the prompt — a model cannot be trusted to police itself, and a misheard command
must never be able to change data.

  * A `read` tool call is executed immediately and its result fed back, so the
    model can answer from real numbers.
  * A `write` or `delete` tool call is **never executed**. It is captured,
    described in plain English, and returned as a *pending action*. Only an
    explicit call to `execute()` — from a human pressing confirm — runs it.

Everything is local: Ollama for reasoning, the capability registry for doing.
No cloud call is made anywhere in this file.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime

import httpx

from agent import capabilities as C
from config import settings

log = logging.getLogger("synapse.agent")

MAX_STEPS = 5          # tool → result → tool → … before we force an answer

SYSTEM = """You are the assistant inside Mainframe, a personal knowledge and life \
operating system belonging to one user. You have tools that read and change their \
real data.

Today is {today} ({weekday}). The current time is {time}.

Rules:
- NEVER guess or calculate a date yourself. Pass the user's own words \
("tomorrow", "friday", "next week") straight into date parameters — the system \
resolves them correctly.
- NEVER invent an id. To act on something, pass the words the user said and let \
the tool find it.
- Prefer ONE well-chosen tool over several. If the question is broad \
("what should I do today?"), use whats_next.
- Tools marked as changing data are shown to the user for confirmation before \
they run. Say what you are about to do; do not claim it is already done.
- When you have the information, answer in one or two short sentences. This is \
often read aloud, so write it to be spoken: no markdown, no bullet points, no \
lists of ids.
- If a tool reports an error, say plainly what went wrong. Do not invent a result.
"""


def _describe(name: str, args: dict) -> str:
    """Plain English for a pending action. This is what the human actually reads
    before saying yes, so it must describe the effect, not the call."""
    a = {k: v for k, v in (args or {}).items() if v not in (None, "", [])}
    date_ = C.resolve_date(a.get("date") or a.get("due") or "", default_today=False)
    when = f" on {date_}" if date_ else ""
    if name == "calendar_create_event":
        # Describe the times the capability will ACTUALLY use, not the raw
        # arguments: the model often fills `end` and leaves `start` empty, and a
        # confirmation that doesn't match what happens is worse than none.
        s, e = C._normalise_times(a.get("start", ""), a.get("end", ""))
        return (f'Add “{a.get("title","")}” to the calendar{when}'
                + (f" at {s}–{e}" if s else " as an all-day event")
                + (f', for the task “{a.get("task_query")}”' if a.get("task_query") else ""))
    if name == "task_create":
        return f'Create the task “{a.get("title","")}”' + (f" due {date_}" if date_ else "")
    if name == "task_log_time":
        return (f'Log {C._mins_from(a.get("minutes", 0))} minutes'
                f' against the task matching “{a.get("task_query","")}”{when or " today"}')
    if name == "task_complete":
        return f'Mark the task matching “{a.get("task_query","")}” as done'
    if name == "work_log":
        return f'Log {C._mins_from(a.get("minutes", 0))} minutes of work: “{a.get("what","")}”{when or " today"}'
    if name == "food_log":
        return f'Log {a.get("servings", 1)} × “{a.get("food_query","")}” to {a.get("meal","snacks")}{when or " today"}'
    if name == "water_add":
        return f'Record {a.get("ml")} ml of water{when or " today"}'
    if name == "weight_log":
        return f'Record your weight as {a.get("kg")} kg{when or " today"}'
    if name == "habit_log":
        return f'Tick off the habit matching “{a.get("habit_query","")}”{when or " today"}'
    if name == "vault_add_transaction":
        return (f'Record {a.get("type","expense")} of {a.get("amount")} '
                f'— “{a.get("description","")}”{when or " today"}')
    if name == "mind_dump":
        return f'Capture “{str(a.get("text",""))[:70]}” into the Mind Dump'
    return f"{name} with " + ", ".join(f"{k}={v}" for k, v in a.items())


async def _ollama(messages: list[dict], tools: list[dict] | None) -> dict:
    payload: dict = {"model": settings.ollama_model, "messages": messages, "stream": False,
                     # Low temperature: this drives real actions, not prose.
                     "options": {"temperature": 0.1}}
    if tools:
        payload["tools"] = tools
    async with httpx.AsyncClient(timeout=settings.llm_timeout_s) as client:
        r = await client.post(f"{settings.ollama_host}/api/chat", json=payload)
        r.raise_for_status()
        return r.json().get("message", {}) or {}


async def ask(text: str, history: list[dict] | None = None) -> dict:
    """Interpret one instruction. Runs reads; proposes writes."""
    now = datetime.now()
    messages: list[dict] = [{"role": "system", "content": SYSTEM.format(
        today=date.today().isoformat(), weekday=now.strftime("%A"), time=now.strftime("%H:%M"))}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": text})

    tools = C.tool_schemas()
    pending: list[dict] = []
    did: list[dict] = []
    reply = ""

    for _step in range(MAX_STEPS):
        msg = await _ollama(messages, tools)
        calls = msg.get("tool_calls") or []
        reply = (msg.get("content") or "").strip()

        if not calls:
            break

        messages.append({"role": "assistant", "content": msg.get("content", ""),
                         "tool_calls": calls})

        for tc in calls:
            fn = tc.get("function", {}) or {}
            name = fn.get("name", "")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}

            spec = C.find(name)
            if not spec:
                messages.append({"role": "tool", "content": f"No such tool: {name}"})
                continue

            if spec["kind"] == "read":
                try:
                    result = await spec["fn"](**args)
                except Exception as exc:                      # a broken tool must not
                    log.exception("agent read tool failed: %s", name)   # kill the turn
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                did.append({"tool": name, "args": args})
                messages.append({"role": "tool",
                                 "content": json.dumps(result, default=str)[:4000]})
            else:
                # Never executed here. Captured, described, and handed to a human.
                action = {"id": str(uuid.uuid4()), "tool": name, "args": args,
                          "kind": spec["kind"], "describe": _describe(name, args)}
                pending.append(action)
                messages.append({"role": "tool", "content": json.dumps(
                    {"status": "awaiting the user's confirmation — do NOT claim this is done",
                     "action": action["describe"]})})

    if not reply:
        reply = ("Here's what I'll do." if pending else "I couldn't work that one out.")
    return {"reply": reply, "pending": pending, "read": did}


async def execute(actions: list[dict]) -> list[dict]:
    """Run actions a human has confirmed. The only path by which the assistant
    changes anything."""
    out = []
    for a in actions:
        spec = C.find(a.get("tool", ""))
        if not spec:
            out.append({"ok": False, "error": f'unknown tool {a.get("tool")}'})
            continue
        if spec["kind"] == "read":
            out.append({"ok": False, "error": "reads don't need confirming"})
            continue
        try:
            result = await spec["fn"](**(a.get("args") or {}))
            ok = not (isinstance(result, dict) and result.get("error"))
            out.append({"ok": ok, "tool": a["tool"], "result": result,
                        "describe": a.get("describe", "")})
        except Exception as exc:
            log.exception("agent write failed: %s", a.get("tool"))
            out.append({"ok": False, "tool": a.get("tool"),
                        "error": f"{type(exc).__name__}: {exc}"})
    return out

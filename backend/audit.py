"""Append-only audit trail: output/audit_trail.json (a JSON array of events).

Every agent-loop step is recorded as it happens:
  run_start      agent, delegation chain, the task it was given
  model_request  what went INTO the model: tool results, retry prompts, user prompt
  model_response what came OUT: tool calls with full args, text, model name, tokens
  run_end        the agent's structured output and cumulative team usage
  run_error      any exception, before it propagates
Plus delegation refusals (agents/base.py) and human payment decisions (approvals.py).

The file is never wiped or rewritten: each event is appended in place (the closing
`]` is replaced by `,<event>]`). There is no temp-file swap, which Windows refuses while
another process (e.g. the board's /events poll) has the file open. If the file doesn't end
in a JSON array, writing stops with an error instead of starting over.
"""

import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    RetryPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RunUsage, UsageLimits

from config import MODEL_SETTINGS, OUTPUT_DIR, USAGE_LIMITS
from models import TeamDeps

AUDIT_PATH = OUTPUT_DIR / "audit_trail.json"
MAX_RESULT_CHARS = 4000  # long tool results are cut, with the original length kept

_lock = threading.Lock()


def new_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:6]


def append(event: dict[str, Any]) -> None:
    record = {"ts_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), **event}
    body = json.dumps(record, indent=2, default=str).encode("utf-8")
    with _lock:
        for attempt in range(20):  # a reader or antivirus may hold the file for a moment
            try:
                _append_in_place(body)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.05)


def _append_in_place(body: bytes) -> None:
    if not AUDIT_PATH.exists() or AUDIT_PATH.stat().st_size == 0:
        AUDIT_PATH.write_bytes(b"[\n" + body + b"\n]\n")
        return
    with open(AUDIT_PATH, "r+b") as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        # Walk back over trailing whitespace to the closing bracket.
        while pos > 0:
            f.seek(pos - 1)
            ch = f.read(1)
            if not ch.isspace():
                break
            pos -= 1
        if ch != b"]":
            raise RuntimeError(f"{AUDIT_PATH} doesn't end with ']'; refusing to modify it.")
        close = pos - 1
        # Is the array empty ("[ ]")? Look at the previous non-space byte.
        prev = close
        while prev > 0:
            f.seek(prev - 1)
            c = f.read(1)
            if not c.isspace():
                break
            prev -= 1
        sep = b"\n" if c == b"[" else b",\n"
        f.seek(close)
        f.truncate()
        f.write(sep + body + b"\n]\n")


def _clip(value: Any) -> Any:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= MAX_RESULT_CHARS:
        return value
    return {"truncated": text[:MAX_RESULT_CHARS], "original_chars": len(text)}


def _usage(u: RunUsage) -> dict:
    return {"requests": u.requests, "tool_calls": u.tool_calls,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


async def run_logged(
    agent: Agent, prompt: str, deps: TeamDeps, usage: RunUsage | None = None,
    limits: UsageLimits = USAGE_LIMITS,
):
    """Run an agent step by step, appending an audit event per loop step."""
    base = {"run_id": deps.run_id, "ticket_id": deps.ticket_id, "agent": deps.agent,
            "chain": deps.chain, "depth": deps.depth}
    append({**base, "event": "run_start", "task": prompt,
            "limits": {"request_limit": limits.request_limit,
                       "total_tokens_limit": limits.total_tokens_limit,
                       "max_tokens_per_response": MODEL_SETTINGS.get("max_tokens")}})
    step = 0
    try:
        async with agent.iter(prompt, deps=deps, usage=usage, usage_limits=limits) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    step += 1
                    parts = []
                    for p in node.request.parts:
                        if isinstance(p, ToolReturnPart):
                            parts.append({"type": "tool_result", "tool": p.tool_name,
                                          "tool_call_id": p.tool_call_id, "content": _clip(p.content)})
                        elif isinstance(p, RetryPromptPart):
                            parts.append({"type": "retry", "tool": p.tool_name, "error": _clip(p.content)})
                        elif isinstance(p, UserPromptPart):
                            parts.append({"type": "user_prompt", "content": _clip(p.content)})
                    append({**base, "step": step, "event": "model_request", "parts": parts})
                elif Agent.is_call_tools_node(node):
                    step += 1
                    r = node.model_response
                    parts = []
                    for p in r.parts:
                        if isinstance(p, ToolCallPart):
                            parts.append({"type": "tool_call", "tool": p.tool_name,
                                          "tool_call_id": p.tool_call_id, "args": p.args_as_dict()})
                        elif isinstance(p, TextPart) and p.content.strip():
                            parts.append({"type": "text", "content": _clip(p.content)})
                    append({**base, "step": step, "event": "model_response", "model": r.model_name,
                            "tokens": {"input": r.usage.input_tokens, "output": r.usage.output_tokens},
                            "parts": parts})
        result = run.result
    except Exception as e:
        append({**base, "step": step, "event": "run_error", "error": f"{type(e).__name__}: {e}"})
        raise
    append({**base, "step": step + 1, "event": "run_end",
            "output": result.output.model_dump(), "team_usage_so_far": _usage(result.usage)})
    return result

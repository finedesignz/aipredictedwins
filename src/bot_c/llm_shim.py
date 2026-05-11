"""OpenAI-compatible HTTP shim backed by ClaudeLLM (Claude Code CLI).

Why this exists
---------------
TradingAgents (TauricResearch) is built on LangChain. Its analyst nodes call
``ChatOpenAI.bind_tools()`` and ``with_structured_output()`` which require the
upstream LLM endpoint to return OpenAI-shaped ``tool_calls`` and JSON objects
matching a schema. The Claude CLI returns plain text, and the existing
gateway/ service does not emulate function calling.

This shim sits between TradingAgents and ClaudeLLM:

- Accepts OpenAI ``/v1/chat/completions`` requests.
- When ``tools`` are present, injects the tool JSON schemas into the prompt
  and asks Claude to emit a strict JSON object naming the tool + arguments.
- When ``response_format`` requests JSON (json_object or json_schema), asks
  Claude to emit a strict JSON object matching the schema.
- Parses Claude's reply and shapes it as a proper OpenAI response — either
  ``message.tool_calls`` for tool requests, or ``message.content`` (JSON
  string) for structured output.

Run inside the dashboard container alongside the FastAPI app and Next.js
web server, on localhost:8765. TradingAgents points at it via
``TRADINGAGENTS_LLM_BACKEND_URL=http://localhost:8765/v1``.

This is a one-process, single-tenant shim — no auth, no rate limit. Only
exposed inside the container.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.claude_llm import ClaudeLLM

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("BOT_C_SHIM_MODEL", "claude-sonnet-4-6")
SHIM_CACHE_DB = os.environ.get("BOT_C_SHIM_CACHE", "/app/data/bot_c_llm_cache.db")

app = FastAPI(title="Bot C LLM Shim", version="1.0.0")

# One ClaudeLLM per model (created lazily). The CLI itself is stateless per
# call, so we just multiplex the model parameter.
_llm_cache: dict[str, ClaudeLLM] = {}


def _get_llm(model: str) -> ClaudeLLM:
    if model not in _llm_cache:
        _llm_cache[model] = ClaudeLLM(model=model, cache_db=SHIM_CACHE_DB)
    return _llm_cache[model]


# ─── Health / models ────────────────────────────────────────────────────────


@app.get("/health")
@app.get("/v1/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-opus-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-haiku-4-5", "object": "model", "owned_by": "anthropic"},
            # Pass-through aliases TradingAgents may request:
            {"id": "gpt-5.4", "object": "model", "owned_by": "anthropic"},
            {"id": "gpt-5.4-mini", "object": "model", "owned_by": "anthropic"},
            {"id": "gpt-4o", "object": "model", "owned_by": "anthropic"},
            {"id": "gpt-4o-mini", "object": "model", "owned_by": "anthropic"},
        ],
    }


def _resolve_model(requested: str) -> str:
    """Map non-Claude model aliases to a real Claude model.

    TradingAgents defaults are 'gpt-5.4' / 'gpt-5.4-mini'. We map both to
    Sonnet so the upstream config can stay untouched. Explicit Claude model
    names pass through.
    """
    if not requested:
        return DEFAULT_MODEL
    if requested.startswith("claude-"):
        return requested
    # gpt-5.4-mini, gpt-4o-mini → sonnet (we don't currently expose haiku
    # for cost; flip later if calls are too expensive).
    return DEFAULT_MODEL


# ─── Prompt assembly ────────────────────────────────────────────────────────


def _flatten_content(content: Any) -> str:
    """LangChain sends content as either a string or a list of content blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                parts.append(str(block))
                continue
            t = block.get("type")
            if t == "text":
                parts.append(block.get("text", ""))
            elif t == "image_url":
                parts.append("[image omitted — Claude CLI text-only]")
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts)
    return str(content)


def _messages_to_prompt(messages: list[dict]) -> tuple[str, str]:
    """Return (system_prompt, user_prompt). System parts are concatenated and
    surfaced separately so we can prepend our own structured-output instructions
    cleanly.
    """
    system_parts: list[str] = []
    convo_parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = _flatten_content(msg.get("content", ""))
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            # Include any tool_calls from a prior assistant turn as plain text
            # so Claude has the same context, even though we can't replay tools.
            tcs = msg.get("tool_calls") or []
            if tcs:
                tc_text = "\n".join(
                    f"[Called tool {tc.get('function', {}).get('name', '?')}"
                    f" with arguments {tc.get('function', {}).get('arguments', '{}')}]"
                    for tc in tcs
                )
                content = (content + "\n" + tc_text).strip()
            convo_parts.append(f"Assistant: {content}")
        elif role == "tool":
            convo_parts.append(
                f"Tool result ({msg.get('name', 'tool')}): {content}"
            )
        else:
            convo_parts.append(f"User: {content}")
    return "\n\n".join(system_parts), "\n\n".join(convo_parts)


# ─── Tool / structured-output prompt injection ──────────────────────────────


_TOOL_INSTRUCTION_TEMPLATE = """You have access to the following tools. To call one,
respond with a single JSON object — no prose, no markdown fences — of the form:

  {{"tool": "<tool name>", "arguments": {{...}}}}

If no tool call is needed, respond with:

  {{"tool": null, "content": "<your textual response>"}}

Available tools:
{tools}
"""


_JSON_SCHEMA_INSTRUCTION_TEMPLATE = """You MUST respond with a single JSON object
matching this schema. Output JSON only — no prose, no markdown fences.

Schema:
{schema}
"""

_JSON_OBJECT_INSTRUCTION = (
    "You MUST respond with a single valid JSON object. "
    "No prose, no markdown fences — JSON only."
)


def _format_tools_block(tools: list[dict]) -> str:
    """Render OpenAI tools array as readable JSON spec for the prompt."""
    formatted = []
    for tool in tools:
        fn = tool.get("function") or {}
        name = fn.get("name", "unnamed")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        formatted.append(
            f"- name: {name}\n"
            f"  description: {desc}\n"
            f"  parameters: {json.dumps(params, indent=2)}"
        )
    return "\n".join(formatted)


def _extract_json(text: str) -> dict | None:
    """Greedy JSON extraction from a Claude response.

    Strips ```json``` fences if present, otherwise pulls the first balanced
    {...} block. Returns None if nothing parses.
    """
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        candidate = fence.group(1)
    else:
        # First balanced brace block
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        end = -1
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end == -1:
            return None
        candidate = text[start:end]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


# ─── Chat completions ───────────────────────────────────────────────────────


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages: list[dict] = body.get("messages", [])
    tools: list[dict] = body.get("tools") or []
    tool_choice = body.get("tool_choice")
    response_format = body.get("response_format")
    requested_model = body.get("model", DEFAULT_MODEL)
    max_tokens = int(body.get("max_tokens") or 2048)
    model = _resolve_model(requested_model)

    system_prompt, user_prompt = _messages_to_prompt(messages)

    structured_mode: str | None = None  # None | "tool" | "json_schema" | "json_object"

    if tools:
        tools_block = _format_tools_block(tools)
        injection = _TOOL_INSTRUCTION_TEMPLATE.format(tools=tools_block)
        system_prompt = (system_prompt + "\n\n" + injection).strip()
        structured_mode = "tool"
    elif isinstance(response_format, dict):
        rf_type = response_format.get("type")
        if rf_type == "json_schema":
            schema = response_format.get("json_schema", {}).get("schema") or response_format.get("json_schema", {})
            injection = _JSON_SCHEMA_INSTRUCTION_TEMPLATE.format(
                schema=json.dumps(schema, indent=2)
            )
            system_prompt = (system_prompt + "\n\n" + injection).strip()
            structured_mode = "json_schema"
        elif rf_type == "json_object":
            system_prompt = (system_prompt + "\n\n" + _JSON_OBJECT_INSTRUCTION).strip()
            structured_mode = "json_object"

    full_prompt = (system_prompt + "\n\n" + user_prompt).strip() if system_prompt else user_prompt

    log.info(
        "[shim] model=%s mode=%s prompt=%d chars tools=%d",
        model, structured_mode or "text", len(full_prompt), len(tools),
    )

    llm = _get_llm(model)
    response_text = llm.call(full_prompt, max_tokens=max_tokens)

    if response_text is None:
        return JSONResponse(
            status_code=502,
            content={"error": {"message": "ClaudeLLM returned no response", "type": "upstream_error"}},
        )

    # ─── Shape response based on structured mode ────────────────────────────
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if structured_mode == "tool":
        parsed = _extract_json(response_text) or {}
        tool_name = parsed.get("tool")
        if tool_name and tool_name in {t.get("function", {}).get("name") for t in tools}:
            tool_args = parsed.get("arguments", {})
            if not isinstance(tool_args, str):
                tool_args = json.dumps(tool_args)
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": tool_name, "arguments": tool_args},
                }],
            }
            finish_reason = "tool_calls"
        else:
            # Fallback: surface the textual content
            content = parsed.get("content") if isinstance(parsed, dict) else None
            if not content:
                content = response_text
            message = {"role": "assistant", "content": content}
            finish_reason = "stop"
    elif structured_mode in ("json_schema", "json_object"):
        parsed = _extract_json(response_text)
        content = json.dumps(parsed) if parsed is not None else response_text
        message = {"role": "assistant", "content": content}
        finish_reason = "stop"
    else:
        message = {"role": "assistant", "content": response_text}
        finish_reason = "stop"

    approx_prompt_tokens = max(1, len(full_prompt) // 4)
    approx_completion_tokens = max(1, len(response_text) // 4)

    return JSONResponse({
        "id": request_id,
        "object": "chat.completion",
        "created": created,
        "model": requested_model,
        "choices": [{
            "index": 0,
            "message": message,
            "finish_reason": finish_reason,
        }],
        "usage": {
            "prompt_tokens": approx_prompt_tokens,
            "completion_tokens": approx_completion_tokens,
            "total_tokens": approx_prompt_tokens + approx_completion_tokens,
        },
    })


# ─── Embeddings stub ────────────────────────────────────────────────────────


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> JSONResponse:
    """Stub: TradingAgents' memory layer may try to embed reflections.

    Returns a deterministic zero vector so the call doesn't crash. Memory
    reflection quality is degraded, but the framework keeps running. Replace
    with a real embedding model later if reflection accuracy matters.
    """
    body = await request.json()
    inputs = body.get("input", [])
    if isinstance(inputs, str):
        inputs = [inputs]
    return JSONResponse({
        "object": "list",
        "data": [
            {"object": "embedding", "index": i, "embedding": [0.0] * 1536}
            for i in range(len(inputs))
        ],
        "model": body.get("model", "text-embedding-3-small"),
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    })

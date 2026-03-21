"""
Claude Code Bridge — OpenAI-compatible API backed by the Anthropic SDK.

Exposes /v1/chat/completions in OpenAI format, translates to Anthropic API
calls under the hood. Supports streaming (SSE) and project folder routing
via X-Project header for CLAUDE.md context injection.
"""

import json
import logging
import os
import time
import uuid
from pathlib import Path

import anthropic
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "./projects"))
DEFAULT_PROJECT = os.getenv("DEFAULT_PROJECT", "mirofish")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Model mapping: OpenAI-style names → Anthropic model IDs
MODEL_MAP = {
    "claude-sonnet-4-6": "claude-sonnet-4-20250514",
    "claude-opus-4-6": "claude-opus-4-20250514",
    "claude-haiku-4-5": "claude-haiku-4-5-20241022",
    # Pass through if already an Anthropic model ID
}

app = FastAPI(title="Claude Code Bridge", version="2.0.0")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Health & Models ──────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-opus-4-6", "object": "model", "owned_by": "anthropic"},
            {"id": "claude-haiku-4-5", "object": "model", "owned_by": "anthropic"},
        ],
    }


# ── Chat Completions ────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    x_project: str | None = Header(None, alias="X-Project"),
):
    body = await request.json()

    messages = body.get("messages", [])
    stream = body.get("stream", False)
    model = body.get("model", "claude-sonnet-4-6")
    max_tokens = body.get("max_tokens", 4096)
    temperature = body.get("temperature", 1.0)

    # Resolve model ID
    anthropic_model = MODEL_MAP.get(model, model)

    # Extract system message and convert to Anthropic format
    system_text, anthropic_messages = _convert_messages(messages, x_project)

    if stream:
        return StreamingResponse(
            _stream_response(anthropic_model, system_text, anthropic_messages, max_tokens, temperature, model),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        result = _call_anthropic(anthropic_model, system_text, anthropic_messages, max_tokens, temperature)
        return _format_response(result, model)


def _load_project_context(x_project: str | None) -> str:
    """Load CLAUDE.md and kb/ files from the project folder."""
    project_name = x_project or DEFAULT_PROJECT
    if not project_name:
        return ""

    project_path = PROJECTS_DIR / project_name
    if not project_path.is_dir():
        return ""

    parts = []

    # Load CLAUDE.md
    claude_md = project_path / "CLAUDE.md"
    if claude_md.exists():
        parts.append(claude_md.read_text(encoding="utf-8"))

    # Load kb/ files
    kb_dir = project_path / "kb"
    if kb_dir.is_dir():
        for f in sorted(kb_dir.glob("*.md")):
            parts.append(f"## {f.stem}\n\n{f.read_text(encoding='utf-8')}")

    if parts:
        log.info("Loaded project context from %s (%d files)", project_path, len(parts))

    return "\n\n---\n\n".join(parts)


def _convert_messages(messages: list[dict], x_project: str | None) -> tuple[str, list[dict]]:
    """Convert OpenAI-format messages to Anthropic format.

    Returns (system_text, anthropic_messages).
    """
    system_parts = []
    anthropic_msgs = []

    # Inject project context as system prompt
    project_context = _load_project_context(x_project)
    if project_context:
        system_parts.append(project_context)

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Handle multi-part content
        if isinstance(content, list):
            text_parts = [p["text"] for p in content if p.get("type") == "text"]
            content = "\n".join(text_parts)

        if role == "system":
            system_parts.append(content)
        elif role in ("user", "assistant"):
            anthropic_msgs.append({"role": role, "content": content})

    # Ensure messages alternate user/assistant (Anthropic requirement)
    if not anthropic_msgs or anthropic_msgs[0]["role"] != "user":
        anthropic_msgs.insert(0, {"role": "user", "content": "Hello"})

    return "\n\n".join(system_parts), anthropic_msgs


def _call_anthropic(model: str, system: str, messages: list[dict],
                    max_tokens: int, temperature: float) -> dict:
    """Make a synchronous Anthropic API call."""
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if system:
        kwargs["system"] = system
    if temperature != 1.0:
        kwargs["temperature"] = temperature

    log.info("Calling Anthropic API (model=%s, msgs=%d, max_tokens=%d)",
             model, len(messages), max_tokens)

    response = client.messages.create(**kwargs)

    content = ""
    for block in response.content:
        if block.type == "text":
            content += block.text

    return {
        "content": content,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


async def _stream_response(model: str, system: str, messages: list[dict],
                           max_tokens: int, temperature: float, display_model: str):
    """Stream Anthropic API response as OpenAI-compatible SSE events."""
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if system:
        kwargs["system"] = system
    if temperature != 1.0:
        kwargs["temperature"] = temperature

    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": display_model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": text},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    # Final chunk
    final = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": display_model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


def _format_response(result: dict, model: str) -> JSONResponse:
    """Format Anthropic response as OpenAI-compatible response."""
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": result["content"],
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": result.get("input_tokens", 0),
            "completion_tokens": result.get("output_tokens", 0),
            "total_tokens": result.get("input_tokens", 0) + result.get("output_tokens", 0),
        },
    })


# ── Error Handlers ───────────────────────────────────────────────────

@app.exception_handler(anthropic.APIError)
async def anthropic_error_handler(request: Request, exc: anthropic.APIError):
    return JSONResponse(
        status_code=exc.status_code or 500,
        content={"error": {"message": str(exc), "type": "api_error"}},
    )


@app.exception_handler(Exception)
async def general_error_handler(request: Request, exc: Exception):
    log.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": {"message": str(exc), "type": "server_error"}},
    )

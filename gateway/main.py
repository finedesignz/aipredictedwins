"""
Claude Code Bridge — OpenAI-compatible API backed by the Claude CLI.

Spawns `claude -p --output-format json` as a subprocess for each request.
Uses the Claude Max subscription via OAuth token for zero incremental cost.
Supports project folder routing via X-Project header for CLAUDE.md context.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "./projects"))
CLI_TIMEOUT = int(os.getenv("CLI_TIMEOUT", "300"))
DEFAULT_PROJECT = os.getenv("DEFAULT_PROJECT", "mirofish")

app = FastAPI(title="Claude Code Bridge", version="2.0.0")


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

    prompt = _messages_to_prompt(messages)
    project_dir = _resolve_project(x_project)

    if stream:
        return StreamingResponse(
            _stream_claude(prompt, model, project_dir),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        result = await _call_claude(prompt, model, project_dir, max_tokens)
        return _format_response(result, model)


def _messages_to_prompt(messages: list[dict]) -> str:
    """Convert OpenAI-style messages to a single prompt string for the CLI."""
    parts = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            text_parts = [p["text"] for p in content if p.get("type") == "text"]
            content = "\n".join(text_parts)
        if role == "system":
            parts.append(f"[System instruction]: {content}")
        elif role == "assistant":
            parts.append(f"[Previous assistant response]: {content}")
        else:
            parts.append(content)
    return "\n\n".join(parts)


def _resolve_project(x_project: str | None) -> Path | None:
    """Resolve X-Project header to a project directory."""
    project_name = x_project or DEFAULT_PROJECT
    if not project_name:
        return None
    project_path = PROJECTS_DIR / project_name
    if project_path.is_dir():
        log.info("Using project folder: %s", project_path)
        return project_path
    return None


async def _call_claude(prompt: str, model: str, project_dir: Path | None,
                       max_tokens: int = 4096) -> str:
    """Spawn claude CLI subprocess and return the result."""
    cmd = ["claude", "-p", "--output-format", "json", "--max-turns", "1"]

    if model:
        cmd.extend(["--model", model])

    env = os.environ.copy()
    cwd = str(project_dir) if project_dir else None

    log.info("Calling claude CLI (model=%s, cwd=%s, prompt=%d chars)",
             model, cwd, len(prompt))

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        cwd=cwd,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=CLI_TIMEOUT,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Claude CLI timed out after {CLI_TIMEOUT}s")

    stdout_str = stdout.decode("utf-8", errors="replace").strip()
    stderr_str = stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        log.error("Claude CLI failed (rc=%d): stdout=%s stderr=%s",
                  proc.returncode, stdout_str[:500], stderr_str[:500])
        raise RuntimeError(
            f"Claude CLI error (rc={proc.returncode}): {stderr_str[:500] or stdout_str[:500]}"
        )

    # Parse JSON output from claude CLI
    try:
        data = json.loads(stdout_str)
        return data.get("result", data.get("content", stdout_str))
    except json.JSONDecodeError:
        return stdout_str


async def _stream_claude(prompt: str, model: str, project_dir: Path | None):
    """Stream claude CLI output as SSE events."""
    cmd = ["claude", "-p", "--output-format", "stream-json", "--max-turns", "1"]

    if model:
        cmd.extend(["--model", model])

    cwd = str(project_dir) if project_dir else None
    request_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )

    proc.stdin.write(prompt.encode("utf-8"))
    proc.stdin.close()

    async for line in proc.stdout:
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue

        try:
            chunk_data = json.loads(text)
            content = chunk_data.get("content", chunk_data.get("result", text))
        except json.JSONDecodeError:
            content = text

        if content:
            chunk = {
                "id": request_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": None,
                }],
            }
            yield f"data: {json.dumps(chunk)}\n\n"

    final = {
        "id": request_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop",
        }],
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"
    await proc.wait()


def _format_response(content: str, model: str) -> JSONResponse:
    """Format claude output as OpenAI-compatible response."""
    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": content,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": len(content) // 4,
            "total_tokens": len(content) // 4,
        },
    })


# ── Error Handlers ───────────────────────────────────────────────────

@app.exception_handler(TimeoutError)
async def timeout_handler(request: Request, exc: TimeoutError):
    return JSONResponse(status_code=504, content={"error": {"message": str(exc), "type": "timeout_error"}})

@app.exception_handler(RuntimeError)
async def runtime_handler(request: Request, exc: RuntimeError):
    return JSONResponse(status_code=500, content={"error": {"message": str(exc), "type": "server_error"}})

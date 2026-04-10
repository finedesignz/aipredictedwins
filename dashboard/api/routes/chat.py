"""POST /api/chat/message — streams Claude CLI output as SSE."""

import asyncio
import json
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")


class ChatMessage(BaseModel):
    message: str


def _bot_context(request: Request) -> str:
    """Build a live context string: running bots and open positions."""
    try:
        mgr = getattr(request.app.state, "bot_manager", None)
        mgr_status: dict = mgr.status() if mgr else {}
        with get_db() as conn:
            bots = conn.execute(
                "SELECT bot_id, label, status, status_detail FROM bots ORDER BY bot_id"
            ).fetchall()
            positions = conn.execute(
                "SELECT bot_id, symbol, entry_price, qty FROM alpaca_trades "
                "WHERE status = 'open' ORDER BY bot_id, timestamp DESC"
            ).fetchall()
        bot_lines = [
            f"  Bot {b['bot_id']} ({b['label']}): status={b['status']}"
            + (f", thread_alive={mgr_status.get(b['bot_id'], {}).get('thread_alive', False)}")
            + (f", note={b['status_detail']}" if b.get("status_detail") else "")
            for b in bots
        ]
        pos_lines = [
            f"  [{p['bot_id']}] {p['symbol']}: {p['qty']} @ ${p['entry_price']:.2f}"
            for p in positions
        ]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        return (
            f"Time: {now}\nBots:\n" + "\n".join(bot_lines or ["  none"]) +
            "\nOpen positions:\n" + "\n".join(pos_lines or ["  none"])
        )
    except Exception as exc:
        return f"(context unavailable: {exc})"


async def _stream(message: str, context: str):
    """Spawn Claude CLI with stream-json output and yield text deltas as SSE tokens.

    Uses `claude -p --verbose --output-format stream-json --system-prompt` which
    emits one JSON event per line.  In -p (print) mode the CLI emits:
      {"type":"assistant","message":{"content":[{"type":"text","text":"..."}],...}}
    We forward each assistant text content block to the browser as a token.
    NOTE: --verbose is REQUIRED when using --output-format stream-json with -p.
    NOTE: the system prompt flag is --system-prompt (not --system).
    """
    system = (
        "You are a trading assistant for an Alpaca crypto swing trading system.\n\n"
        f"LIVE CONTEXT:\n{context}\n\n"
        "When suggesting config changes, append a JSON action block:\n"
        '```action\n{"type":"update_bot","bot_id":"X","field":"hard_stop_pct","value":-0.06}\n```'
    )
    try:
        proc = await asyncio.create_subprocess_exec(
            CLAUDE_BIN,
            "-p",
            "--verbose",
            "--output-format", "stream-json",
            "--system-prompt", system,
            message,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield f"data: {json.dumps({'error': f'claude CLI not found at {CLAUDE_BIN}'})}\n\n"
        yield "data: [DONE]\n\n"
        return

    try:
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                event = json.loads(line.decode().strip())
            except json.JSONDecodeError:
                continue

            # In -p mode, claude emits type="assistant" with message.content blocks.
            # Each assistant event may contain partial or full text as it streams.
            if event.get("type") == "assistant":
                content = event.get("message", {}).get("content", [])
                for block in content:
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            yield f"data: {json.dumps({'token': text})}\n\n"

            # Also handle authentication errors surfaced as result events
            elif event.get("type") == "result" and event.get("is_error"):
                yield f"data: {json.dumps({'error': event.get('result', 'claude error')})}\n\n"

        await asyncio.wait_for(proc.wait(), timeout=60)
    except asyncio.TimeoutError:
        proc.kill()
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()

    yield "data: [DONE]\n\n"


@router.post("/message")
async def chat_message(body: ChatMessage, request: Request):
    """Stream a Claude CLI response for the given message as SSE."""
    ctx = _bot_context(request)
    return StreamingResponse(
        _stream(body.message, ctx),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

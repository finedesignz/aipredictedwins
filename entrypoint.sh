#!/bin/bash
# Entrypoint for the Alpaca paper trading bot container.
#
# Handles Claude CLI credential injection from the CLAUDE_CREDENTIALS
# environment variable. Set this in the Coolify UI to authenticate
# Claude Code CLI without SSH.
#
# The CLI then handles its own token refresh automatically.

set -e

# Create Claude config directory
mkdir -p /root/.claude

# If CLAUDE_CREDENTIALS env var is set, write it to the credentials file.
# The persistent volume at /root/.claude preserves this across restarts.
# The CLI's auto-refresh will update this file when the token rotates.
if [ -n "$CLAUDE_CREDENTIALS" ]; then
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials written from env var"
else
    if [ -f /root/.claude/.credentials.json ]; then
        echo "[entrypoint] Using existing Claude credentials from persistent volume"
    else
        echo "[entrypoint] WARNING: No Claude credentials found. Risk gate and exit advisor will use fallback mode."
        echo "[entrypoint] Set CLAUDE_CREDENTIALS env var in Coolify UI or run 'claude login' in the container terminal."
    fi
fi

# Verify Claude CLI is available (don't fail if it errors — set -e is active)
if command -v claude &> /dev/null; then
    claude_ver=$(claude --version 2>/dev/null || true)
    echo "[entrypoint] Claude CLI version: ${claude_ver:-unknown}"
else
    echo "[entrypoint] WARNING: Claude CLI not found"
fi

# Launch the bot
exec python -m src.alpaca_orchestrator --mode paper

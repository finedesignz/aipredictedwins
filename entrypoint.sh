#!/bin/bash
# Entrypoint for the Alpaca paper trading bot container.
# v2 — fixed set -e crash on missing Claude credentials
#
# Handles Claude CLI credential injection from the CLAUDE_CREDENTIALS
# environment variable. Set this in the Coolify UI to authenticate
# Claude Code CLI without SSH.
#
# The CLI then handles its own token refresh automatically.

set -e

# Create Claude config directory
mkdir -p /root/.claude

# Credential priority:
# 1. Existing file on persistent volume (may have been refreshed by CLI)
# 2. CLAUDE_CREDENTIALS env var (initial bootstrap only)
# 3. No credentials (warning)
if [ -f /root/.claude/.credentials.json ]; then
    echo "[entrypoint] Using existing Claude credentials from persistent volume"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials bootstrapped from env var"
else
    echo "[entrypoint] WARNING: No Claude credentials found. Risk gate and exit advisor will use fallback mode."
    echo "[entrypoint] Run 'claude login' in the container terminal to authenticate."
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

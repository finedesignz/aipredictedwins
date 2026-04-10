#!/bin/bash
# Entrypoint for the Alpaca paper trading bot container.
# v3 — refresh-aware credential bootstrap
#
# Handles Claude CLI credential injection from the CLAUDE_CREDENTIALS
# environment variable. Set this in the Coolify UI to authenticate
# Claude Code CLI without SSH.
#
# Credential priority:
#   1. Existing file on volume with non-expired token (keep it)
#   2. CLAUDE_CREDENTIALS env var (bootstrap or overwrite expired)
#   3. No credentials (warn + skip risk gate)

set -e

# Create Claude config directory
mkdir -p /root/.claude

# Check if existing credentials file has a non-expired access token
_creds_valid() {
    local file="/root/.claude/.credentials.json"
    [ -f "$file" ] || return 1
    # Extract expiresAt using python3 (always available in our image)
    local expires_ms
    expires_ms=$(python3 -c "
import json, sys
try:
    d = json.load(open('$file'))
    oa = d.get('claudeAiOauth', {})
    print(int(oa.get('expiresAt', 0)))
except Exception:
    print(0)
" 2>/dev/null)
    local now_ms
    now_ms=$(python3 -c "import time; print(int(time.time() * 1000))" 2>/dev/null)
    # Token is valid if it expires more than 5 minutes from now
    [ -n "$expires_ms" ] && [ -n "$now_ms" ] && [ "$expires_ms" -gt "$((now_ms + 300000))" ]
}

if _creds_valid; then
    echo "[entrypoint] Using existing Claude credentials from persistent volume (token valid)"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials bootstrapped from env var"
    if _creds_valid; then
        echo "[entrypoint] Bootstrapped credentials are valid (token not expired)"
    else
        echo "[entrypoint] WARNING: Bootstrapped credentials have an expired access token."
        echo "[entrypoint] The CLI will attempt token refresh on first inference call."
        echo "[entrypoint] If auth fails, update CLAUDE_CREDENTIALS env var with fresh credentials."
    fi
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

#!/bin/bash
# entrypoint.sh — runs startup tasks then hands off to supervisord.
# v2 — volume-first credential bootstrap (same logic as root entrypoint.sh)
set -e

# 1. Write Claude credentials — prefer persistent volume, fall back to env var.
# This prevents every restart from blowing away a successfully-refreshed token.
mkdir -p /root/.claude

_creds_valid() {
    local file="/root/.claude/.credentials.json"
    [ -f "$file" ] || return 1
    local expires_ms now_ms
    expires_ms=$(python3 -c "
import json
try:
    d = json.load(open('$file'))
    print(int(d.get('claudeAiOauth', {}).get('expiresAt', 0)))
except Exception:
    print(0)
" 2>/dev/null)
    now_ms=$(python3 -c "import time; print(int(time.time() * 1000))" 2>/dev/null)
    [ -n "$expires_ms" ] && [ -n "$now_ms" ] && [ "$expires_ms" -gt "$((now_ms + 300000))" ]
}

if _creds_valid; then
    echo "[entrypoint] Using existing Claude credentials from persistent volume (token valid)"
elif [ -n "$CLAUDE_CREDENTIALS" ]; then
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials bootstrapped from env var"
    if _creds_valid; then
        echo "[entrypoint] Bootstrapped credentials are valid"
    else
        echo "[entrypoint] WARNING: Bootstrapped credentials have an expired access token — CLI will attempt refresh on first call"
    fi
else
    echo "[entrypoint] WARNING: No Claude credentials. Run 'claude login' in the container terminal."
fi

# 2. Run DB migrations + seed bots (only if DATABASE_URL is set)
if [ -n "$DATABASE_URL" ]; then
    echo "[entrypoint] Running migrations..."
    python /app/api/migrations/run_migrations.py
    echo "[entrypoint] Seeding bots..."
    python /app/api/seed_bots.py
else
    echo "[entrypoint] DATABASE_URL not set — skipping migrations and seed"
fi

exec supervisord -c /etc/supervisor/conf.d/supervisord.conf

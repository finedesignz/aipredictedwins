#!/bin/bash
# entrypoint.sh — runs startup tasks then hands off to supervisord.
set -e

# 1. Write Claude credentials
if [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p /root/.claude
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials written"
else
    echo "[entrypoint] CLAUDE_CREDENTIALS not set — claude chat disabled until 'claude login' is run"
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

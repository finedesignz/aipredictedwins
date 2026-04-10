#!/bin/bash
# entrypoint.sh — writes Claude credentials from env var, then starts supervisord.
set -e

if [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p /root/.claude
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "[entrypoint] Claude credentials written"
else
    echo "[entrypoint] CLAUDE_CREDENTIALS not set — claude chat disabled until 'claude login' is run"
fi

exec supervisord -c /etc/supervisor/conf.d/supervisord.conf

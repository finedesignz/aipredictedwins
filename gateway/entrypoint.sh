#!/bin/bash
set -e

# Write Claude CLI OAuth credentials if provided via env var
if [ -n "$CLAUDE_CREDENTIALS" ]; then
    mkdir -p /root/.claude
    echo "$CLAUDE_CREDENTIALS" > /root/.claude/.credentials.json
    echo "Claude CLI credentials configured."
fi

# Accept TOS
export CLAUDE_CODE_ACCEPT_TOS=true

exec "$@"

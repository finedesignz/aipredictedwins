# ============================================================
# AI Predicted Wins — Trading Dashboard
# Single container: Next.js (frontend) + FastAPI (backend)
# Managed by supervisord
# ============================================================

# ------ Stage 1: Build Next.js ------
FROM node:22-slim AS web-builder

WORKDIR /build

# Install dependencies first (layer cache)
COPY web/package.json web/package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy source and build
COPY web/ ./
RUN npm run build

# ------ Stage 2: Production image ------
FROM python:3.13-slim

# Install Node.js 22 runtime (required to run Next.js standalone server)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# ------ Python dependencies ------
WORKDIR /app/api
COPY api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ------ Copy FastAPI source ------
COPY api/ ./

# Copy trading bot source for BotThread/BotManager
WORKDIR /app
COPY src/ ./src/

# ------ Copy built Next.js from builder ------
WORKDIR /app/web
COPY --from=web-builder /build/.next/standalone/ ./
COPY --from=web-builder /build/.next/static/ ./.next/static/
COPY --from=web-builder /build/public/ ./public/

# ------ Data directory (volume mount point) ------
RUN mkdir -p /app/data
RUN mkdir -p /root/.claude

# ------ Supervisord config ------
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ------ Health check ------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

# Next.js is the public-facing port; Traefik/Coolify routes to 3000
EXPOSE 3000

# Supervisord runs both processes in the foreground
CMD ["/entrypoint.sh"]

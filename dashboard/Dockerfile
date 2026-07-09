# ============================================================
# AI Predicted Wins — Trading Dashboard
# Single container: Next.js (frontend) + FastAPI (backend)
# Managed by supervisord
# ============================================================

# ------ Stage 1: Build Next.js ------
FROM node:22-slim AS web-builder

WORKDIR /build

# Install dependencies first (layer cache)
COPY dashboard/web/package.json dashboard/web/package-lock.json* ./
RUN npm ci --ignore-scripts

# Copy source and build
COPY dashboard/web/ ./
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
COPY dashboard/api/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ------ Copy FastAPI source ------
COPY dashboard/api/ ./

# Copy trading bot source for BotThread/BotManager
WORKDIR /app
COPY src/ ./src/

# ------ Bot C: vendor TradingAgents framework ------
# Adds the TauricResearch TradingAgents repo as a sibling package on PYTHONPATH.
# Its deps (langchain, langgraph, yfinance, stockstats) are installed editable
# but without re-installing the project to keep the upstream tree pristine.
COPY vendor/TradingAgents/ ./vendor/TradingAgents/
RUN pip install --no-cache-dir \
        "langchain-core>=0.3.81" \
        "langchain-openai>=0.3.23" \
        "langchain-anthropic>=0.3.15" \
        "langchain-experimental>=0.3.4" \
        "langgraph>=0.4.8" \
        "langgraph-checkpoint-sqlite>=2.0.0" \
        "stockstats>=0.6.5" \
        "yfinance>=0.2.63" \
        "parsel>=1.10.0" \
        "tqdm>=4.67.1" \
        "finnhub-python>=2.4.20" \
        "backtrader>=1.9.78.123"
ENV PYTHONPATH="/app:/app/vendor/TradingAgents"

# Bot C LLM shim points TradingAgents at localhost:8765 (started by supervisord).
# NOTE: provider must be "ollama" here — "openai" makes TradingAgents' ChatOpenAI
# client validate/require a real OpenAI-shaped backend and breaks the Claude shim.
ENV TRADINGAGENTS_LLM_PROVIDER=ollama \
    TRADINGAGENTS_LLM_BACKEND_URL=http://localhost:8765/v1 \
    TRADINGAGENTS_DEEP_THINK_LLM=claude-sonnet-4-6 \
    TRADINGAGENTS_QUICK_THINK_LLM=claude-sonnet-4-6 \
    TRADINGAGENTS_MAX_DEBATE_ROUNDS=1 \
    TRADINGAGENTS_MAX_RISK_ROUNDS=1 \
    OPENAI_API_KEY=shim-not-needed

# ------ Copy built Next.js from builder ------
WORKDIR /app/web
COPY --from=web-builder /build/.next/standalone/ ./
COPY --from=web-builder /build/.next/static/ ./.next/static/
COPY --from=web-builder /build/public/ ./public/

# ------ Data directory (volume mount point) ------
RUN mkdir -p /app/data
RUN mkdir -p /root/.claude

# ------ Supervisord config ------
COPY dashboard/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY dashboard/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ------ Health check ------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3000/ || exit 1

# Next.js is the public-facing port; Traefik/Coolify routes to 3000
EXPOSE 3000

# Supervisord runs both processes in the foreground
CMD ["/entrypoint.sh"]

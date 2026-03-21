FROM python:3.13-slim

# Install curl (for Coolify healthcheck) and Node.js (for Claude CLI)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Claude CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Accept Claude CLI terms of service non-interactively
ENV CLAUDE_CODE_ACCEPT_TOS=true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/projects /root/.claude
RUN chmod +x entrypoint.sh

ENV PORT=8000
ENV PROJECTS_DIR=/app/projects
ENV DEFAULT_PROJECT=mirofish
ENV CLI_TIMEOUT=300
ENV CLAUDE_CODE_ACCEPT_TOS=true

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

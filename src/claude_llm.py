"""
Claude Code CLI wrapper for LLM calls.

Replaces the OpenAI-compatible gateway with direct Claude CLI invocation.
The CLI handles OAuth token refresh automatically — no more expired tokens.

Usage:
    llm = ClaudeLLM(model="claude-sonnet-4-6")
    response = llm.call("Analyze this trade...")
"""

import hashlib
import json
import logging
import sqlite3
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Default model for trading intelligence (fast + cheap)
DEFAULT_MODEL = "claude-sonnet-4-6"

# Timeout for CLI calls (seconds)
DEFAULT_TIMEOUT = 90


class LLMCache:
    """SQLite-backed cache for LLM responses, keyed by sha256(prompt + model).

    Used by the backtester to replay past LLM decisions deterministically.
    Also written by the production bot so decisions accumulate over time.

    Cache key: sha256(prompt + "\x00" + model) — any prompt edit invalidates.
    """

    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS llm_cache (
        cache_key  TEXT PRIMARY KEY,
        prompt     TEXT NOT NULL,
        model      TEXT NOT NULL,
        response   TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(self._SCHEMA)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _key(prompt: str, model: str) -> str:
        return hashlib.sha256(f"{prompt}\x00{model}".encode()).hexdigest()

    def get(self, prompt: str, model: str) -> str | None:
        conn = sqlite3.connect(self._db_path)
        try:
            row = conn.execute(
                "SELECT response FROM llm_cache WHERE cache_key = ?",
                (self._key(prompt, model),),
            ).fetchone()
            return row[0] if row else None
        finally:
            conn.close()

    def put(self, prompt: str, model: str, response: str) -> None:
        key = self._key(prompt, model)
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (cache_key, prompt, model, response) "
                "VALUES (?, ?, ?, ?)",
                (key, prompt, model, response),
            )
            conn.commit()
        finally:
            conn.close()


class ClaudeLLM:
    """Wrapper around the Claude Code CLI for programmatic LLM calls.

    Calls `claude -p <prompt> --model <model> --output-format json`
    and parses the JSON response. The CLI handles OAuth token refresh
    internally — no manual token management needed.
    """

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT,
                 cache_db: str | None = None):
        self.model = model
        self.timeout = timeout
        self._cache: LLMCache | None = LLMCache(cache_db) if cache_db else None

    def call(self, prompt: str, max_tokens: int = 1024) -> str | None:
        """Send a prompt to Claude and return the text response.

        Parameters
        ----------
        prompt : str
            The user prompt to send.
        max_tokens : int
            Maximum tokens in the response (passed via --max-tokens).

        Returns
        -------
        str or None
            The text response, or None if the call failed.
        """
        # Check cache first
        if self._cache is not None:
            cached = self._cache.get(prompt, self.model)
            if cached is not None:
                log.debug("Claude LLM cache HIT for model=%s (%d chars)", self.model, len(cached))
                return cached

        cmd = [
            "claude",
            "-p", prompt,
            "--model", self.model,
            "--output-format", "json",
            "--max-turns", "1",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=None,  # inherit environment
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()[:200] if result.stderr else "no stderr"
                log.error("Claude CLI failed (exit %d): %s", result.returncode, stderr)
                return None

            if not result.stdout.strip():
                log.error("Claude CLI returned empty output")
                return None

            data = json.loads(result.stdout)

            if data.get("is_error"):
                log.error("Claude CLI error: %s", data.get("result", "unknown error"))
                return None

            response_text = data.get("result", "")
            cost = data.get("total_cost_usd", 0)
            duration = data.get("duration_ms", 0)

            log.debug(
                "Claude CLI: model=%s, cost=$%.4f, duration=%dms, response=%d chars",
                self.model, cost, duration, len(response_text),
            )

            # Write to cache
            if self._cache is not None and response_text:
                self._cache.put(prompt, self.model, response_text)

            return response_text

        except subprocess.TimeoutExpired:
            log.error("Claude CLI timed out after %ds", self.timeout)
            return None
        except json.JSONDecodeError as exc:
            log.error("Claude CLI returned non-JSON: %s", exc)
            return None
        except FileNotFoundError:
            log.error("Claude CLI not found — is it installed? Run: npm install -g @anthropic-ai/claude-code")
            return None
        except Exception as exc:
            log.error("Claude CLI unexpected error: %s", exc)
            return None

    def is_available(self) -> bool:
        """Quick check if the Claude CLI is installed and authenticated."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

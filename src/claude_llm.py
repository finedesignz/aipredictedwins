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
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Default model for trading intelligence (fast + cheap)
DEFAULT_MODEL = "claude-sonnet-4-6"

# Timeout for CLI calls (seconds)
DEFAULT_TIMEOUT = 90

# Path to Claude credentials file
_CREDENTIALS_PATH = Path("/root/.claude/.credentials.json")

# Minimum milliseconds before expiry to trigger a proactive refresh
_REFRESH_THRESHOLD_MS = 5 * 60 * 1000  # 5 minutes

# Module-level cooldown: don't hammer the token endpoint more than once per 10 min
_last_refresh_attempt: float = 0.0
_REFRESH_COOLDOWN_SECONDS = 600  # 10 minutes between refresh attempts


def _refresh_oauth_token() -> bool:
    """Attempt to refresh the Claude OAuth access token using the refresh token.

    Returns True if the credentials file was updated with a fresh token.
    This calls the platform.claude.com token endpoint directly.

    Rate-limited: only attempts once per _REFRESH_COOLDOWN_SECONDS to avoid
    429 errors from hammering the token endpoint on every LLM call.
    """
    global _last_refresh_attempt
    now = time.time()
    if now - _last_refresh_attempt < _REFRESH_COOLDOWN_SECONDS:
        log.debug("Skipping token refresh — cooldown active (%.0fs remaining)",
                  _REFRESH_COOLDOWN_SECONDS - (now - _last_refresh_attempt))
        return False
    _last_refresh_attempt = now
    log.info("Attempting Claude OAuth token refresh...")
    try:
        creds_text = _CREDENTIALS_PATH.read_text()
        creds = json.loads(creds_text)
        oa = creds.get("claudeAiOauth", {})
        refresh_token = oa.get("refreshToken", "")
        if not refresh_token:
            log.warning("No refresh token found — cannot refresh")
            return False
    except Exception as exc:
        log.warning("Cannot read credentials for refresh: %s", exc)
        return False

    # Use Node.js (always available in our container) to call the token endpoint
    node_script = r"""
const https = require('https');
const fs = require('fs');
const credsPath = '/root/.claude/.credentials.json';
const creds = JSON.parse(fs.readFileSync(credsPath, 'utf8'));
const rt = creds.claudeAiOauth.refreshToken;
const clientId = '9d1c250a-e61b-44d9-88ed-5944d1962f5e';
const data = new URLSearchParams({grant_type:'refresh_token',refresh_token:rt,client_id:clientId}).toString();
const opts = {
  hostname: 'platform.claude.com',
  port: 443,
  path: '/v1/oauth/token',
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    'Content-Length': Buffer.byteLength(data),
    'User-Agent': 'claude-code/2.1.100',
  }
};
const req = https.request(opts, res => {
  let body = '';
  res.on('data', d => body += d);
  res.on('end', () => {
    if (res.statusCode === 200) {
      const tok = JSON.parse(body);
      creds.claudeAiOauth.accessToken = tok.access_token;
      if (tok.refresh_token) creds.claudeAiOauth.refreshToken = tok.refresh_token;
      creds.claudeAiOauth.expiresAt = Date.now() + (tok.expires_in || 3600) * 1000;
      fs.writeFileSync(credsPath, JSON.stringify(creds));
      process.stdout.write('REFRESHED:' + creds.claudeAiOauth.accessToken.slice(0, 20));
    } else {
      process.stdout.write('FAILED:' + res.statusCode + ':' + body.slice(0, 100));
    }
  });
});
req.on('error', e => process.stdout.write('ERROR:' + e.message));
req.write(data);
req.end();
"""
    try:
        result = subprocess.run(
            ["node", "-e", node_script],
            capture_output=True, text=True, timeout=15
        )
        out = result.stdout.strip()
        if out.startswith("REFRESHED:"):
            log.info("Claude OAuth token refreshed successfully")
            return True
        else:
            log.warning("Claude OAuth token refresh failed: %s", out[:200])
            # On 429, extend the cooldown to 30 min so we stop hammering the endpoint
            if "429" in out:
                global _last_refresh_attempt
                _last_refresh_attempt = time.time() + 1800 - _REFRESH_COOLDOWN_SECONDS
                log.warning("Token refresh rate-limited (429) — backing off 30 minutes")
            return False
    except Exception as exc:
        log.warning("Claude OAuth token refresh error: %s", exc)
        return False


def _token_is_expired() -> bool:
    """Check if the stored Claude access token is expired or expiring soon."""
    try:
        creds = json.loads(_CREDENTIALS_PATH.read_text())
        expires_at_ms = creds.get("claudeAiOauth", {}).get("expiresAt", 0)
        now_ms = int(time.time() * 1000)
        return now_ms >= (expires_at_ms - _REFRESH_THRESHOLD_MS)
    except Exception:
        return False


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

        # Proactively refresh the token if it's expired or expiring soon
        if _token_is_expired():
            log.info("Claude access token is expired/expiring — attempting refresh before call")
            _refresh_oauth_token()

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
                error_msg = data.get("result", "unknown error")
                # If 401 auth error, try token refresh and retry once
                if "401" in error_msg or "authentication" in error_msg.lower():
                    log.warning("Got 401 auth error — attempting token refresh and retry")
                    if _refresh_oauth_token():
                        # Retry the call with fresh token
                        result = subprocess.run(
                            cmd,
                            capture_output=True,
                            text=True,
                            timeout=self.timeout,
                            env=None,
                        )
                        if result.returncode == 0 and result.stdout.strip():
                            data = json.loads(result.stdout)
                            if not data.get("is_error"):
                                # Fall through to success path below
                                pass
                            else:
                                log.error("Claude CLI error after refresh: %s", data.get("result", "unknown"))
                                return None
                        else:
                            log.error("Claude CLI failed after refresh (exit %d)", result.returncode)
                            return None
                    else:
                        log.error("Token refresh failed — cannot recover from 401")
                        return None
                else:
                    log.error("Claude CLI error: %s", error_msg)
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

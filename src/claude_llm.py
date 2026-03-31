"""
Claude Code CLI wrapper for LLM calls.

Replaces the OpenAI-compatible gateway with direct Claude CLI invocation.
The CLI handles OAuth token refresh automatically — no more expired tokens.

Usage:
    llm = ClaudeLLM(model="claude-sonnet-4-6")
    response = llm.call("Analyze this trade...")
"""

import json
import logging
import subprocess

log = logging.getLogger(__name__)

# Default model for trading intelligence (fast + cheap)
DEFAULT_MODEL = "claude-sonnet-4-6"

# Timeout for CLI calls (seconds)
DEFAULT_TIMEOUT = 90


class ClaudeLLM:
    """Wrapper around the Claude Code CLI for programmatic LLM calls.

    Calls `claude -p <prompt> --model <model> --output-format json`
    and parses the JSON response. The CLI handles OAuth token refresh
    internally — no manual token management needed.
    """

    def __init__(self, model: str = DEFAULT_MODEL, timeout: int = DEFAULT_TIMEOUT):
        self.model = model
        self.timeout = timeout

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

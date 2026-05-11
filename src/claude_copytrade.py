"""Claude CLI runner for ai4trade copy-trade leader selection.

The ai4trade copytrade SKILL.md (hosted at https://ai4trade.ai/skill/ai4trade)
instructs an AI agent to: discover top performers, pick the most promising,
and follow them. We fetch that skill, hand it to Claude with the current
leaderboard, and parse out a list of leader_ids to follow.

Failure modes handled here:
  - skill fetch failure (network) -> caller may fall back to top-N-by-return
  - leaderboard 504 (it's heavy) -> caller passes through skill-text-only
  - Claude returns prose, not a list -> we regex-extract numeric ids
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests

from src.claude_llm import ClaudeLLM

log = logging.getLogger(__name__)

SKILL_URL = "https://ai4trade.ai/SKILL.md"

_PROMPT_TEMPLATE = """You are an AI agent integrating with the ai4trade.ai copy-trading
platform. The platform's official integration skill is shown below verbatim,
followed by the current top-performer leaderboard.

Your job: pick the {n} leader agent_ids most likely to produce high-quality
copy-trade signals over the next 7 days. Favor agents with a verifiable
track record (return %, win rate, trade count) over agents with high
follower counts but thin history.

Respond with **only** a JSON object of the form:

  {{"leader_ids": [123, 456, 789], "rationale": "one sentence"}}

If the leaderboard is empty or unusable, respond:

  {{"leader_ids": [], "rationale": "no usable leaderboard data"}}

--- BEGIN ai4trade SKILL.md ---
{skill}
--- END SKILL.md ---

--- LEADERBOARD JSON ---
{leaderboard}
--- END LEADERBOARD ---
"""


def _fetch_skill() -> str:
    try:
        resp = requests.get(SKILL_URL, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        log.warning("Could not fetch ai4trade SKILL.md (%s) — using empty stub", exc)
        return "(skill unavailable)"


def _parse_response(text: str) -> tuple[list[int], str]:
    if not text:
        return [], ""
    # Try strict JSON first; fall back to extracting the first {...} block.
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{[^{}]*\"leader_ids\"[^{}]*\}", text, re.DOTALL)
        if not match:
            return [], ""
        try:
            data = json.loads(match.group(0))
        except Exception:
            return [], ""
    ids_raw = data.get("leader_ids") or []
    ids: list[int] = []
    for v in ids_raw:
        try:
            ids.append(int(v))
        except (TypeError, ValueError):
            continue
    rationale = str(data.get("rationale") or "")[:500]
    return ids, rationale


def pick_leaders(
    leaderboard: list[dict[str, Any]],
    *,
    n: int = 3,
    model: str = "claude-sonnet-4-6",
) -> tuple[list[int], str]:
    """Ask Claude to pick `n` leader_ids from the leaderboard.

    Returns (leader_ids, rationale). On any failure, returns ([], reason).
    Caller can fall back to a deterministic ranking when this returns [].
    """
    if not leaderboard:
        log.info("pick_leaders: empty leaderboard — skipping Claude call")
        return [], "empty leaderboard"

    skill = _fetch_skill()
    prompt = _PROMPT_TEMPLATE.format(
        n=n,
        skill=skill[:6000],  # cap skill payload — it's mostly stable
        leaderboard=json.dumps(leaderboard[:25], default=str)[:6000],
    )
    llm = ClaudeLLM(model=model)
    raw = llm.call(prompt, max_tokens=400)
    if not raw:
        log.warning("pick_leaders: Claude returned no response")
        return [], "claude no-response"
    ids, rationale = _parse_response(raw)
    if not ids:
        log.warning("pick_leaders: could not parse leader_ids from response: %s", raw[:200])
    return ids, rationale

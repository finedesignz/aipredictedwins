"""
MiroFish Risk Gate — pre-trade risk scenario simulation.

For each technical signal candidate, runs a single LLM call that
simulates a panel of risk analysts brainstorming what could go wrong.
Returns PROCEED or VETO with reasoning.

Uses Claude Code CLI directly — handles OAuth token refresh automatically.
"""

import json
import logging
import re
from dataclasses import dataclass

from src.claude_llm import ClaudeLLM
from src.trade_logger import TradeLogger

log = logging.getLogger(__name__)

RISK_GATE_PROMPT = """You are a panel of 5 risk analysts evaluating a proposed crypto trade.
Your job is NOT to predict whether the price will go up. The technical system already says BUY.
Your job is to find reasons this trade could FAIL in the next 48 hours.

PROPOSED TRADE:
  Asset: {symbol}
  Direction: BUY (long)
  Current Price: ${price:.2f}
  24h Change: {change_pct:+.2f}%
  24h Volume: {volume:,.0f}
  Technical Confluence: {confluence}/5 indicators bullish

RECENT PRICE ACTION (last 10 bars, 1-hour each):
{price_history}

NOTE ON VOLUME DATA: Alpaca crypto volume figures can appear low or zero — this is
a data feed limitation, NOT an indication of illiquid markets. These are top-8 crypto
assets by market cap (BTC, ETH, SOL, etc.) and always have deep liquidity on major
exchanges. Do NOT veto solely based on low reported volume. Focus on price action,
macro risks, and event risks instead.

ANALYST ROLES:
1. Macro Risk Analyst — looks for macro events (Fed, regulation, geopolitical)
2. Momentum Analyst — checks if price action supports the entry (trend strength, recent reversals)
3. Correlation Analyst — checks if this trade duplicates risk from other crypto positions
4. Event Risk Analyst — looks for upcoming catalysts (token unlocks, earnings, forks, exchange issues)
5. Technical Skeptic — challenges the bullish thesis with bearish chart patterns

INSTRUCTIONS:
Each analyst must identify 0-2 specific risk scenarios. Rate each:
- likelihood: "low", "medium", or "high"
- impact: "low", "medium", or "high"

Then each analyst votes: PROCEED or VETO.
Final decision: VETO if ANY scenario is high-likelihood AND high-impact, OR if 3+ analysts vote VETO.

Respond with JSON only:
{{
    "scenarios": [
        {{"analyst": "...", "risk": "...", "likelihood": "...", "impact": "..."}},
        ...
    ],
    "votes": {{
        "macro": "PROCEED or VETO",
        "momentum": "PROCEED or VETO",
        "correlation": "PROCEED or VETO",
        "event_risk": "PROCEED or VETO",
        "technical_skeptic": "PROCEED or VETO"
    }},
    "decision": "PROCEED or VETO",
    "reasoning": "2-3 sentence summary of the panel's conclusion"
}}"""


@dataclass
class RiskVerdict:
    """Result of the risk gate evaluation."""
    decision: str           # "PROCEED" or "VETO"
    reasoning: str
    scenarios: list[dict]
    votes: dict
    raw_response: str


class RiskGate:
    """Pre-trade risk evaluation using LLM-simulated analyst panel."""

    def __init__(self, config=None, logger: TradeLogger | None = None, model: str = "claude-sonnet-4-6"):
        self.logger = logger
        self._llm = ClaudeLLM(model=model, timeout=90)

    def evaluate(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        volume: float,
        confluence: int,
        bars: list[dict],
    ) -> RiskVerdict:
        """Run the risk panel simulation for a trade candidate."""
        # Format price history from last 10 bars
        recent = bars[-min(10, len(bars)):]
        price_lines = []
        for b in recent:
            ts = str(b.get("timestamp", ""))[:16]
            price_lines.append(
                f"  {ts}: O=${b['open']:.2f} H=${b['high']:.2f} "
                f"L=${b['low']:.2f} C=${b['close']:.2f} V={b['volume']:,.0f}"
            )
        price_history = "\n".join(price_lines) or "  No recent data"

        prompt = RISK_GATE_PROMPT.format(
            symbol=symbol,
            price=price,
            change_pct=change_pct,
            volume=volume,
            confluence=confluence,
            price_history=price_history,
        )

        raw = self._llm.call(prompt)

        if raw is None:
            log.error("Risk gate LLM call failed for %s — VETO (fail-closed)", symbol)
            verdict = RiskVerdict(
                decision="VETO",
                reasoning="Risk gate LLM unavailable. VETO fail-closed regardless of confluence.",
                scenarios=[], votes={}, raw_response="",
            )
        else:
            verdict = self._parse_response(raw)

        # Log to validations table
        if self.logger:
            try:
                self.logger.log_validation({
                    "kalshi_ticker": symbol,
                    "event_title": f"Crypto trade: {symbol}",
                    "mirofish_prob": confluence / 5.0,
                    "kalshi_price": price,
                    "gap": change_pct / 100.0,
                    "proposed_side": "buy",
                    "decision": verdict.decision,
                    "confidence": confluence / 5.0,
                    "risk_assessment": verdict.reasoning,
                    "veto_reason": verdict.reasoning if verdict.decision == "VETO" else None,
                })
            except Exception as exc:
                log.warning("Failed to log risk gate result: %s", exc)

        log.info(
            "RISK GATE %s: %s (scenarios=%d, veto_votes=%d/5) — %s",
            symbol,
            verdict.decision,
            len(verdict.scenarios),
            sum(1 for v in verdict.votes.values() if v == "VETO"),
            verdict.reasoning[:100],
        )

        return verdict

    def _parse_response(self, raw: str) -> RiskVerdict:
        """Parse the LLM JSON response into a RiskVerdict."""
        cleaned = re.sub(r"```json\s*", "", raw)
        cleaned = re.sub(r"```\s*", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("Risk gate returned non-JSON: %s", raw[:200])
            return RiskVerdict(
                decision="PROCEED",
                reasoning="Could not parse risk assessment. Defaulting to PROCEED.",
                scenarios=[], votes={}, raw_response=raw,
            )

        scenarios = data.get("scenarios", [])
        votes = data.get("votes", {})
        stated_decision = data.get("decision", "PROCEED").upper().strip()
        reasoning = data.get("reasoning", "No reasoning provided.")

        # Enforce decision rules regardless of what LLM said
        has_critical = any(
            s.get("likelihood", "").lower() == "high" and s.get("impact", "").lower() == "high"
            for s in scenarios
        )
        veto_count = sum(1 for v in votes.values() if str(v).upper().strip() == "VETO")

        if has_critical or veto_count >= 3:
            decision = "VETO"
        else:
            decision = stated_decision if stated_decision in ("PROCEED", "VETO") else "PROCEED"

        return RiskVerdict(
            decision=decision,
            reasoning=reasoning,
            scenarios=scenarios,
            votes=votes,
            raw_response=raw,
        )

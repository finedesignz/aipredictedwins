"""
Rules-based pre-trade gate — deterministic replacement for the LLM risk gate.

Replaces MiroFish 5-analyst LLM veto with fast, rule-based checks.
No LLM calls. Pure math on price/indicator data.

Rules:
  1. Gap rule: if price jumped/dropped > GAP_THRESHOLD in last 2 bars → VETO (chasing)
  2. Flat market rule: if ADX < MIN_ADX → VETO (no trend to trade)
  3. All other signals: PROCEED
"""

import logging
import os

from src.risk_gate import RiskVerdict
from src.technical_signals import _adx

log = logging.getLogger(__name__)

# Configurable thresholds via environment variables
GAP_THRESHOLD: float = float(os.environ.get("RULES_GAP_THRESHOLD", "5.0"))  # percent
MIN_ADX: float = float(os.environ.get("RULES_MIN_ADX", "12.0"))


class RulesGate:
    """
    Deterministic, rules-based pre-trade gate.

    Drop-in replacement for RiskGate. Accepts the same constructor
    arguments but ignores them — there are no LLM calls here.
    """

    def __init__(self, config=None, logger=None, model=None):
        # Signature matches RiskGate for compatibility; arguments are intentionally unused.
        pass

    def evaluate(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        volume: float,
        confluence: int,
        bars: list[dict],
    ) -> RiskVerdict:
        """
        Evaluate pre-trade rules for the given symbol.

        Parameters
        ----------
        symbol      : ticker symbol (e.g. "BTC/USD")
        price       : current price
        change_pct  : 24-hour change percentage
        volume      : recent volume
        confluence  : signal confluence score (0-5)
        bars        : list of OHLCV bar dicts, each with keys
                      "open", "high", "low", "close", "volume"

        Returns
        -------
        RiskVerdict with decision "PROCEED" or "VETO"
        """
        # Rule 1 — Gap / chase prevention
        if len(bars) >= 2:
            prev_close = bars[-2]["close"]
            last_close = bars[-1]["close"]
            if prev_close and prev_close != 0:
                bar_move_pct = abs((last_close - prev_close) / prev_close * 100)
                if bar_move_pct > GAP_THRESHOLD:
                    reasoning = (
                        f"Gap rule: price moved {bar_move_pct:.1f}% in last bar"
                        " — chasing prevention"
                    )
                    verdict = RiskVerdict(
                        decision="VETO",
                        reasoning=reasoning,
                        scenarios=[{"rule": "gap_rule", "detail": reasoning}],
                        votes={},
                        raw_response="rules_gate",
                    )
                    log.info(
                        "RULES GATE %s: %s — %s",
                        symbol,
                        verdict.decision,
                        verdict.reasoning[:100],
                    )
                    return verdict

        # Rule 2 — No-trend / flat market filter
        # ADX requires at least (period * 2 + 1) = 29 bars by default.
        if len(bars) >= 3:
            highs = [b["high"] for b in bars]
            lows = [b["low"] for b in bars]
            closes = [b["close"] for b in bars]
            adx_result = _adx(highs, lows, closes)
            if adx_result is not None:
                adx, _plus_di, _minus_di = adx_result
                if adx < MIN_ADX:
                    reasoning = (
                        f"Flat market: ADX={adx:.1f} < {MIN_ADX}"
                        " — no trend to trade"
                    )
                    verdict = RiskVerdict(
                        decision="VETO",
                        reasoning=reasoning,
                        scenarios=[{"rule": "flat_market", "detail": reasoning}],
                        votes={},
                        raw_response="rules_gate",
                    )
                    log.info(
                        "RULES GATE %s: %s — %s",
                        symbol,
                        verdict.decision,
                        verdict.reasoning[:100],
                    )
                    return verdict

        # Default — all rules passed
        verdict = RiskVerdict(
            decision="PROCEED",
            reasoning="Rules gate passed: no veto conditions triggered",
            scenarios=[],
            votes={},
            raw_response="rules_gate",
        )
        log.info(
            "RULES GATE %s: %s — %s",
            symbol,
            verdict.decision,
            verdict.reasoning[:100],
        )
        return verdict

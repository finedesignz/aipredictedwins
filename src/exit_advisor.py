"""
MiroFish Exit Advisor — smart position management.

Replaces the fixed 3%/8% stop-loss/take-profit with intelligent
exit decisions. Called by the PositionMonitor when positions cross
soft threshold levels.

Soft thresholds (-2%, +5%) trigger an LLM consultation.
Hard thresholds (-4%, +10%) trigger immediate exit regardless.
"""

import json
import logging
import re
from dataclasses import dataclass

from src.claude_llm import ClaudeLLM

log = logging.getLogger(__name__)

# Thresholds
SOFT_STOP_PCT = -0.02       # -2% triggers LLM consultation
SOFT_TAKE_PROFIT_PCT = 0.05  # +5% triggers LLM consultation
HARD_STOP_PCT = -0.04        # -4% immediate exit
HARD_TAKE_PROFIT_PCT = 0.10  # +10% immediate exit

# Trailing stop — once position is up >= TRAIL_ACTIVATION, the stop follows
# the high-water mark minus TRAIL_DISTANCE. Locks in gains automatically.
TRAIL_ACTIVATION_PCT = 0.03  # activate trailing stop once up 3%
TRAIL_DISTANCE_PCT = 0.02    # trail 2% behind the peak

EXIT_EVALUATION_PROMPT = """You are an expert crypto swing trader evaluating an open position.
Your job is to decide: HOLD, TIGHTEN, or EXIT.

POSITION DETAILS:
  Asset: {symbol}
  Side: {side} (long)
  Entry Price: ${entry_price:.2f}
  Current Price: ${current_price:.2f}
  P&L: {pnl_pct:+.2f}% (${pnl_dollar:+,.2f})
  Time Held: {hours_held:.1f} hours

RECENT PRICE ACTION (last 10 bars, 1-hour each):
{price_history}

TRIGGER: Position crossed the {trigger_type} threshold ({trigger_pct:+.1f}%).

DECISION OPTIONS:
- HOLD: The dip/rally is noise. Thesis is intact. Keep the position as-is.
- TIGHTEN: Risk is elevated. Move the mental stop-loss to breakeven (entry price).
           This means: if price drops below entry again, exit immediately.
- EXIT: The thesis is broken (for losses) or the opportunity is fully captured (for gains).
        Close the position now.

Consider:
1. Is the recent price action showing momentum continuation or reversal?
2. Has volume increased or decreased (confirming or denying the move)?
3. For losses: is this a normal pullback in an uptrend, or a trend reversal?
4. For gains: is there more upside momentum, or is this a local top?

Respond with JSON only:
{{
    "decision": "HOLD" or "TIGHTEN" or "EXIT",
    "confidence": "low" or "medium" or "high",
    "reasoning": "2-3 sentence explanation of your decision"
}}"""


@dataclass
class ExitAdvice:
    """Result of the exit advisor evaluation."""
    decision: str         # "HOLD", "TIGHTEN", or "EXIT"
    confidence: str       # "low", "medium", "high"
    reasoning: str
    trigger_type: str     # "soft_stop" or "soft_take_profit"


class ExitAdvisor:
    """MiroFish-powered exit intelligence for open positions."""

    def __init__(self, config=None, model: str = "claude-sonnet-4-6"):
        self._llm = ClaudeLLM(model=model, timeout=30)

    def should_exit(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        side: str,
        hours_held: float,
        bars: list[dict],
    ) -> ExitAdvice | None:
        """Evaluate whether to exit, hold, or tighten a position.

        Called by PositionMonitor when a position crosses a soft threshold.

        Returns None if the position is within normal range (no action needed).
        Returns ExitAdvice for soft threshold crossings.
        For hard thresholds, the caller should exit immediately without consulting.
        """
        if entry_price <= 0 or current_price <= 0:
            return None

        pnl_pct = (current_price - entry_price) / entry_price
        pnl_dollar = (current_price - entry_price)  # per-unit, caller multiplies by qty

        # Hard thresholds — don't consult, caller handles these
        if pnl_pct <= HARD_STOP_PCT or pnl_pct >= HARD_TAKE_PROFIT_PCT:
            return None  # Caller should exit immediately

        # Soft thresholds — consult MiroFish
        if pnl_pct <= SOFT_STOP_PCT:
            trigger_type = "soft_stop"
            trigger_pct = pnl_pct * 100
        elif pnl_pct >= SOFT_TAKE_PROFIT_PCT:
            trigger_type = "soft_take_profit"
            trigger_pct = pnl_pct * 100
        else:
            return None  # Within normal range, no action

        # Format price history
        recent = bars[-min(10, len(bars)):] if bars else []
        price_lines = []
        for b in recent:
            ts = str(b.get("timestamp", ""))[:16]
            price_lines.append(
                f"  {ts}: O=${b['open']:.2f} H=${b['high']:.2f} "
                f"L=${b['low']:.2f} C=${b['close']:.2f} V={b['volume']:,.0f}"
            )
        price_history = "\n".join(price_lines) or "  No recent data"

        prompt = EXIT_EVALUATION_PROMPT.format(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            pnl_pct=pnl_pct * 100,
            pnl_dollar=pnl_dollar,
            hours_held=hours_held,
            price_history=price_history,
            trigger_type=trigger_type.replace("_", " "),
            trigger_pct=trigger_pct,
        )

        raw = self._llm.call(prompt)

        if raw is None:
            log.error("Exit advisor LLM call failed for %s", symbol)
            advice = ExitAdvice(
                decision="HOLD",
                confidence="low",
                reasoning="Exit advisor unavailable. Defaulting to HOLD.",
                trigger_type=trigger_type,
            )
        else:
            advice = self._parse_response(raw, trigger_type)

        log.info(
            "EXIT ADVISOR %s: %s (confidence=%s, trigger=%s) — %s",
            symbol, advice.decision, advice.confidence, trigger_type,
            advice.reasoning[:100],
        )

        return advice

    def _parse_response(self, raw: str, trigger_type: str) -> ExitAdvice:
        """Parse the LLM JSON response into an ExitAdvice."""
        cleaned = re.sub(r"```json\s*", "", raw)
        cleaned = re.sub(r"```\s*", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            log.warning("Exit advisor returned non-JSON: %s", raw[:200])
            return ExitAdvice(
                decision="HOLD",
                confidence="low",
                reasoning="Could not parse exit advice. Defaulting to HOLD.",
                trigger_type=trigger_type,
            )

        decision = data.get("decision", "HOLD").upper().strip()
        if decision not in ("HOLD", "TIGHTEN", "EXIT"):
            decision = "HOLD"

        confidence = data.get("confidence", "low").lower().strip()
        if confidence not in ("low", "medium", "high"):
            confidence = "low"

        reasoning = data.get("reasoning", "No reasoning provided.")

        return ExitAdvice(
            decision=decision,
            confidence=confidence,
            reasoning=reasoning,
            trigger_type=trigger_type,
        )


class TrailingStop:
    """Tracks high-water marks and trailing stops for open positions.

    Once a position gains >= TRAIL_ACTIVATION_PCT, the stop follows
    the peak price minus TRAIL_DISTANCE_PCT. If the price drops below
    the trailing stop, the position is closed — locking in gains.
    """

    def __init__(self):
        self._peaks: dict[int, float] = {}  # trade_id → highest price seen

    def update(self, trade_id: int, entry_price: float, current_price: float) -> str | None:
        """Update the trailing stop and return action if triggered.

        Returns:
            "trailing_stop" if price fell below the trail
            None otherwise
        """
        if entry_price <= 0:
            return None

        pnl_pct = (current_price - entry_price) / entry_price

        # Track peak — always store the highest price seen
        prev_peak = self._peaks.get(trade_id)
        if prev_peak is None or current_price > prev_peak:
            self._peaks[trade_id] = current_price
            prev_peak = current_price

        # Only activate once position has gained enough
        peak_gain = (prev_peak - entry_price) / entry_price
        if peak_gain < TRAIL_ACTIVATION_PCT:
            return None

        # Trailing stop = peak minus trail distance
        trail_stop = prev_peak * (1 - TRAIL_DISTANCE_PCT)

        if current_price <= trail_stop:
            self.remove(trade_id)
            return "trailing_stop"

        return None

    def remove(self, trade_id: int):
        """Remove tracking for a closed position."""
        self._peaks.pop(trade_id, None)


def check_position_thresholds(entry_price: float, current_price: float) -> str | None:
    """Quick check for threshold crossings without LLM calls.

    Returns:
        "hard_stop" — immediate exit, position at -4% or worse
        "hard_take_profit" — immediate exit, position at +10% or better
        "soft_stop" — position at -2%, needs LLM consultation
        "soft_take_profit" — position at +5%, needs LLM consultation
        None — position within normal range
    """
    if entry_price <= 0:
        return None

    pnl_pct = (current_price - entry_price) / entry_price

    if pnl_pct <= HARD_STOP_PCT:
        return "hard_stop"
    if pnl_pct >= HARD_TAKE_PROFIT_PCT:
        return "hard_take_profit"
    if pnl_pct <= SOFT_STOP_PCT:
        return "soft_stop"
    if pnl_pct >= SOFT_TAKE_PROFIT_PCT:
        return "soft_take_profit"
    return None

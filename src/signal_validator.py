"""
Signal Validator — single-call Claude sanity check before trade entry.

Optional A/B layer. When tradingagents_enabled=True on a bot, every candidate
signal passes through this check. Uses ClaudeLLM (Claude Code CLI + OAuth) —
no API key needed. Fails open on any error so trades are never blocked by
infrastructure issues.
"""

import logging

from src.claude_llm import ClaudeLLM

log = logging.getLogger(__name__)

_PROMPT = """\
You are a fast trading sanity check. Given these technical signals, decide APPROVE or VETO.

Symbol: {symbol}
Side: {side}
Price change 24h: {change_pct:+.1f}%
EMA: {ema}
ADX: {adx:.1f} (trend strength, >25=strong)
RSI: {rsi:.1f} (>70=overbought, <30=oversold)
Volume spike: {volume_spike}
VWAP: {vwap}
4H trend: {trend_4h}
Market regime: {regime}
Confluence score: {confluence}/4

VETO only if there is a clear macro red flag: extreme RSI, weak ADX in a ranging market, \
or price chasing after an outsized move.
Respond with exactly one line: APPROVE or VETO: <one sentence reason>"""


class SignalValidator:
    """Single-call Claude signal sanity check. Fail-open on any error."""

    def __init__(self):
        self._llm = ClaudeLLM(model="claude-haiku-4-5-20251001", timeout=30)

    def validate(self, symbol: str, side: str, signal, price: float, change_pct: float) -> tuple[str, str]:
        """Return (decision, reason) where decision is 'APPROVE' or 'VETO'."""
        prompt = _PROMPT.format(
            symbol=symbol,
            side=side,
            change_pct=change_pct,
            ema="bullish" if signal.ema_bullish else "bearish",
            adx=signal.adx_value,
            rsi=signal.rsi_value,
            volume_spike=signal.volume_spike,
            vwap="above" if signal.vwap_bullish else "below",
            trend_4h=signal.trend_4h,
            regime=signal.market_regime,
            confluence=signal.confluence_score,
        )

        try:
            text = self._llm.call(prompt, max_tokens=60)
        except Exception as exc:
            log.warning("[signal_validator] call failed (%s) — approving %s %s", exc, symbol, side)
            return ("APPROVE", "validator unavailable")

        if not text:
            log.warning("[signal_validator] empty response — approving %s %s", symbol, side)
            return ("APPROVE", "validator unavailable")

        text = text.strip()
        if text.upper().startswith("VETO"):
            parts = text.split(": ", 1)
            reason = parts[1].strip() if len(parts) > 1 else "vetoed"
            log.info("[signal_validator] %s %s → VETO: %s", symbol, side, reason)
            return ("VETO", reason)

        parts = text.split(": ", 1)
        reason = parts[1].strip() if len(parts) > 1 else "approved"
        log.info("[signal_validator] %s %s → APPROVE: %s", symbol, side, reason)
        return ("APPROVE", reason)

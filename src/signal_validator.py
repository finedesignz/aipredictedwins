"""
Signal Validator — single-call Claude sanity check before trade entry.

Optional A/B layer. When tradingagents_enabled=True on a bot, every candidate
signal goes through this check. Claude reviews macro context + technicals and
returns APPROVE or VETO with a short reason.

Uses Anthropic SDK directly. Requires ANTHROPIC_API_KEY env var.
Falls back to APPROVE if the API call fails (fail-open to not block trades).
"""

import logging
import os

logger = logging.getLogger(__name__)


class SignalValidator:
    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return None
        try:
            from anthropic import Anthropic
            self._client = Anthropic(api_key=api_key)
        except Exception as e:
            logger.warning(f"[signal_validator] failed to init Anthropic client: {e}")
            return None
        return self._client

    def validate(self, symbol: str, side: str, signal, price: float, change_pct: float) -> tuple[str, str]:
        """
        Returns (decision, reason) where decision is "APPROVE" or "VETO".
        Fails open (returns APPROVE) on any error.

        side: "long" or "short"
        signal: Signal dataclass instance
        """
        client = self._get_client()
        if client is None:
            logger.warning("[signal_validator] no API key — skipping validation")
            return ("APPROVE", "validator unavailable")

        prompt = (
            f"You are a fast trading sanity check. Given these technical signals, decide APPROVE or VETO.\n\n"
            f"Symbol: {symbol}\n"
            f"Side: {side}\n"
            f"Price change 24h: {change_pct:+.1f}%\n"
            f"EMA: {'bullish' if signal.ema_bullish else 'bearish'}\n"
            f"ADX: {signal.adx_value:.1f} (trend strength, >25=strong)\n"
            f"RSI: {signal.rsi_value:.1f} (>70=overbought, <30=oversold)\n"
            f"Volume spike: {signal.volume_spike}\n"
            f"VWAP: {'above' if signal.vwap_bullish else 'below'}\n"
            f"4H trend: {signal.trend_4h}\n"
            f"Market regime: {signal.market_regime}\n"
            f"Confluence: {signal.confluence_score}/4\n\n"
            f"VETO only if there's a clear macro red flag (extreme RSI, weak ADX on ranging market, "
            f"or price chasing after big move).\n"
            f"Respond with exactly: APPROVE or VETO: <one sentence reason>"
        )

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=60,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
        except Exception as e:
            logger.warning(f"[signal_validator] API call failed: {e}")
            return ("APPROVE", "validator unavailable")

        if text.startswith("VETO"):
            parts = text.split(": ", 1)
            reason = parts[1].strip() if len(parts) > 1 else "vetoed by validator"
            decision = "VETO"
        else:
            decision = "APPROVE"
            parts = text.split(": ", 1)
            reason = parts[1].strip() if len(parts) > 1 else text

        logger.info(f"[signal_validator] {symbol} {side} → {decision}: {reason}")
        return (decision, reason)

"""
TradingAgents-style signal adapter — additive 0-4 score for crypto candidates.

Inspired by TauricResearch/TradingAgents (multi-agent LLM trading panel), but:
  - Routes through the existing OpenAI-compatible Claude gateway (no new deps,
    no Finnhub/Alpha Vantage requirement).
  - Tuned for the crypto universe (BTC, ETH, SOL, ...). The upstream framework
    targets equities and won't work cleanly on /USD pairs.
  - Returns a confluence-style score (0-4) and a side ("buy"/"sell"/"none")
    so it composes with `technical_signals.Signal.confluence_score`.

This is a SIGNAL SOURCE, not an execution engine. The orchestrator should call
`evaluate(symbol, bars)` for each technical candidate and feed the result into
its existing risk-gate / sizing logic — same place MiroFish currently slots in.

Four analyst roles vote BUY/HOLD/SELL; the score is the count of BUY votes
(or SELL votes for shorts). Heavy: 4 LLM calls per candidate (~25s). Cache by
(symbol, hour) so repeated cycles within an hour don't re-spend tokens.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Literal, Optional

from openai import OpenAI

from src.config import Config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

Side = Literal["buy", "sell", "none"]


@dataclass
class TradingAgentsScore:
    """Aggregated multi-agent verdict for one symbol."""
    symbol: str
    score: int                 # 0-4: BUY votes (for longs) or SELL votes (for shorts)
    side: Side                 # "buy" | "sell" | "none"
    votes: dict[str, str]      # {"technical": "BUY", "sentiment": "HOLD", ...}
    rationales: dict[str, str] # short reasoning per analyst, for trade-log notes
    raw_decision: str          # final synthesizer's call: BUY / HOLD / SELL


# ---------------------------------------------------------------------------
# Prompt templates — four crypto-tuned analysts
# ---------------------------------------------------------------------------

_TECHNICAL_PROMPT = """You are a crypto Technical Analyst. Vote BUY, HOLD, or SELL on {symbol} based ONLY on the price action below.

Recent 1H OHLCV (oldest -> newest, last {bar_count} bars):
{bars_summary}

Indicators already computed:
- EMA(9) vs EMA(21): {ema_state}
- ADX(14): {adx:.1f} (+DI={plus_di:.1f}, -DI={minus_di:.1f})
- RSI(14): {rsi:.1f}
- VWAP: price is {vwap_state}
- 4H trend: {trend_4h}

In 2-3 sentences, give the dominant technical read. Then on a final line, output exactly one of:
VOTE: BUY
VOTE: HOLD
VOTE: SELL"""


_SENTIMENT_PROMPT = """You are a crypto Sentiment / Social Analyst. Vote BUY, HOLD, or SELL on {symbol}.

You do NOT have live social data. Use your general knowledge of the crypto market climate as of the cutoff date plus the price context below.

Context:
- Symbol: {symbol}
- 24h change: {change_24h_pct:+.1f}%
- Current price: ${price:,.2f}
- Volume vs 20-bar avg: {vol_ratio:.1f}x

Consider:
- Is this asset in a sector currently attracting attention (L1, L2, DeFi, AI tokens, memes)?
- Does the price move look like it's leading or lagging the broader narrative?
- Are retail sentiment dynamics constructive or exhausted?

In 2-3 sentences, give your sentiment read. Then on a final line:
VOTE: BUY
VOTE: HOLD
VOTE: SELL"""


_FUNDAMENTAL_PROMPT = """You are a crypto Fundamentals / On-chain Analyst. Vote BUY, HOLD, or SELL on {symbol}.

You don't have live on-chain feeds. Use what you know about the asset's fundamentals: tokenomics, network usage, recent protocol upgrades, supply schedule, competitive position.

Symbol: {symbol}
Current price: ${price:,.2f}
24h change: {change_24h_pct:+.1f}%

In 2-3 sentences, give the fundamental read for a 1-3 day swing trade horizon. Then on a final line:
VOTE: BUY
VOTE: HOLD
VOTE: SELL"""


_RISK_PROMPT = """You are a Risk Analyst stress-testing a proposed swing trade in {symbol}.

The other analysts said:
- Technical: {tech_vote} — {tech_reason}
- Sentiment: {sent_vote} — {sent_reason}
- Fundamental: {fund_vote} — {fund_reason}

Price: ${price:,.2f}, 24h change: {change_24h_pct:+.1f}%, RSI(14): {rsi:.1f}.

Your job is to find what could go wrong: liquidity traps, news risk, correlation with BTC dumps, exhaustion, fakeouts. Be skeptical.

In 2-3 sentences, summarize the dominant risk. Then on a final line:
VOTE: BUY
VOTE: HOLD
VOTE: SELL"""


_SYNTHESIZER_PROMPT = """You are the Portfolio Manager. Four analysts voted on {symbol}:
- Technical: {tech_vote}
- Sentiment: {sent_vote}
- Fundamental: {fund_vote}
- Risk: {risk_vote}

Output JSON only, no other text:
{{"decision": "BUY" | "HOLD" | "SELL",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>"}}"""


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class TradingAgentsSignal:
    """Multi-analyst LLM signal source for crypto candidates."""

    # In-process cache: {(symbol, hour_bucket): TradingAgentsScore}
    _cache: dict[tuple[str, int], TradingAgentsScore] = {}
    _CACHE_TTL_SECONDS = 3600

    def __init__(self, config: Config, model: Optional[str] = None):
        self.config = config
        self._llm = OpenAI(
            api_key=config.llm_api_key or "not-needed",
            base_url=config.llm_base_url,
        )
        self._model = model or config.llm_model_name

    # -- public API ---------------------------------------------------------

    def evaluate(
        self,
        symbol: str,
        price: float,
        bars: list[dict],
        indicators: dict,
        change_24h_pct: float = 0.0,
    ) -> Optional[TradingAgentsScore]:
        """Run the 4-analyst panel for one symbol.

        Parameters
        ----------
        symbol : str
            e.g. "BTC/USD".
        price : float
            Latest price.
        bars : list[dict]
            Recent OHLCV bars (last ~24 are summarised in the prompt).
        indicators : dict
            Pre-computed indicators from technical_signals.Signal.details:
            ema_state, adx, plus_di, minus_di, rsi, vwap_state, trend_4h, vol_ratio.
        change_24h_pct : float
            24-hour percent change.

        Returns
        -------
        TradingAgentsScore or None on hard failure.
        """
        cache_key = (symbol, int(time.time() // self._CACHE_TTL_SECONDS))
        cached = self._cache.get(cache_key)
        if cached is not None:
            log.info("[TradingAgents] cache hit for %s (score=%d side=%s)",
                     symbol, cached.score, cached.side)
            return cached

        try:
            bars_summary = self._summarize_bars(bars[-12:])
            ctx = {
                "symbol": symbol,
                "price": price,
                "change_24h_pct": change_24h_pct,
                "bar_count": len(bars[-12:]),
                "bars_summary": bars_summary,
                "ema_state": indicators.get("ema_state", "unknown"),
                "adx": indicators.get("adx", 0.0),
                "plus_di": indicators.get("plus_di", 0.0),
                "minus_di": indicators.get("minus_di", 0.0),
                "rsi": indicators.get("rsi", 50.0),
                "vwap_state": indicators.get("vwap_state", "unknown"),
                "trend_4h": indicators.get("trend_4h", "unknown"),
                "vol_ratio": indicators.get("vol_ratio", 1.0),
            }

            tech = self._call(_TECHNICAL_PROMPT.format(**ctx), "Technical")
            sent = self._call(_SENTIMENT_PROMPT.format(**ctx), "Sentiment")
            fund = self._call(_FUNDAMENTAL_PROMPT.format(**ctx), "Fundamental")

            tech_vote, tech_reason = self._parse_vote(tech)
            sent_vote, sent_reason = self._parse_vote(sent)
            fund_vote, fund_reason = self._parse_vote(fund)

            risk_ctx = {
                **ctx,
                "tech_vote": tech_vote, "tech_reason": tech_reason,
                "sent_vote": sent_vote, "sent_reason": sent_reason,
                "fund_vote": fund_vote, "fund_reason": fund_reason,
            }
            risk = self._call(_RISK_PROMPT.format(**risk_ctx), "Risk")
            risk_vote, risk_reason = self._parse_vote(risk)

            synth_raw = self._call(
                _SYNTHESIZER_PROMPT.format(
                    symbol=symbol,
                    tech_vote=tech_vote, sent_vote=sent_vote,
                    fund_vote=fund_vote, risk_vote=risk_vote,
                ),
                "Synthesizer",
            )
            decision = self._parse_decision(synth_raw)

            votes = {
                "technical": tech_vote, "sentiment": sent_vote,
                "fundamental": fund_vote, "risk": risk_vote,
            }
            rationales = {
                "technical": tech_reason, "sentiment": sent_reason,
                "fundamental": fund_reason, "risk": risk_reason,
            }

            buy_count = sum(1 for v in votes.values() if v == "BUY")
            sell_count = sum(1 for v in votes.values() if v == "SELL")

            if decision == "BUY":
                side: Side = "buy"
                score = buy_count
            elif decision == "SELL":
                side = "sell"
                score = sell_count
            else:
                side = "none"
                score = max(buy_count, sell_count)

            result = TradingAgentsScore(
                symbol=symbol,
                score=score,
                side=side,
                votes=votes,
                rationales=rationales,
                raw_decision=decision,
            )
            self._cache[cache_key] = result
            log.info(
                "[TradingAgents] %s -> %s (score=%d, votes=%s)",
                symbol, decision, score, votes,
            )
            return result

        except Exception as exc:
            log.warning("[TradingAgents] evaluate failed for %s: %s", symbol, exc)
            return None

    # -- internals ----------------------------------------------------------

    def _call(self, prompt: str, role: str) -> str:
        try:
            resp = self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.3,
            )
            text = resp.choices[0].message.content.strip()
            log.debug("[TradingAgents:%s] %s", role, text[:200])
            return text
        except Exception as exc:
            log.warning("[TradingAgents:%s] LLM call failed: %s", role, exc)
            return "VOTE: HOLD"

    @staticmethod
    def _parse_vote(text: str) -> tuple[str, str]:
        m = re.search(r"VOTE:\s*(BUY|HOLD|SELL)", text, re.IGNORECASE)
        vote = m.group(1).upper() if m else "HOLD"
        reason = re.split(r"VOTE:", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        reason = reason.replace("\n", " ")[:240]
        return vote, reason

    @staticmethod
    def _parse_decision(raw: str) -> str:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            return "HOLD"
        try:
            obj = json.loads(m.group())
            d = str(obj.get("decision", "HOLD")).upper()
            return d if d in ("BUY", "HOLD", "SELL") else "HOLD"
        except json.JSONDecodeError:
            return "HOLD"

    @staticmethod
    def _summarize_bars(bars: list[dict]) -> str:
        lines = []
        for b in bars:
            lines.append(
                f"  O={b.get('open', 0):.2f} H={b.get('high', 0):.2f} "
                f"L={b.get('low', 0):.2f} C={b.get('close', 0):.2f} "
                f"V={b.get('volume', 0):.0f}"
            )
        return "\n".join(lines) if lines else "  (no bars)"


# ---------------------------------------------------------------------------
# Composition helper — merge with technical confluence
# ---------------------------------------------------------------------------

def merge_with_confluence(
    tech_confluence: int,
    ta_score: Optional[TradingAgentsScore],
    direction: Side = "buy",
    block_on_disagreement: bool = True,
) -> tuple[int, str]:
    """Combine the technical confluence score with the TradingAgents verdict.

    Returns (effective_score, reason).

    Policy:
      - If TA is None (failed): return tech_confluence unchanged.
      - If TA agrees (same side): boost by min(2, ta.score // 2).
      - If TA disagrees (opposite side) and block_on_disagreement: return 0.
      - If TA is HOLD/none: return tech_confluence unchanged.
    """
    if ta_score is None:
        return tech_confluence, "ta_unavailable"

    if ta_score.side == direction:
        boost = min(2, ta_score.score // 2)
        return tech_confluence + boost, f"ta_agree(+{boost})"

    if ta_score.side == "none" or ta_score.raw_decision == "HOLD":
        return tech_confluence, "ta_neutral"

    # Disagreement
    if block_on_disagreement:
        return 0, f"ta_veto({ta_score.raw_decision})"
    return max(0, tech_confluence - 1), f"ta_disagree(-1)"

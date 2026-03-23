"""
Lightweight TradingAgents Gate — 5-agent validation pipeline.

Every trade must pass through this gate before execution.
Five specialized LLM agents evaluate the trade sequentially:
  1. Sentiment Analyst — evaluates MiroFish report quality
  2. News Analyst — evaluates current news landscape
  3. Contrarian Analyst — argues AGAINST the trade
  4. Risk Manager — reviews all three + portfolio state, decides APPROVE/VETO/ADJUST
  5. Portfolio Manager — final call with JSON output

Uses the Claude gateway — 5 LLM calls per trade validation (~30 seconds total).
"""

import json
import logging
import re
from openai import OpenAI
from src.config import Config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt templates — one per agent
# ---------------------------------------------------------------------------

SENTIMENT_ANALYST_PROMPT = """You are a Sentiment Analyst specializing in prediction markets. Evaluate the quality and reliability of this simulation report.

EVENT: {event_title}
TICKER: {ticker}
MIROFISH PROBABILITY: {mirofish_prob:.1%}
KALSHI MARKET PRICE: {kalshi_price:.1%}
GAP: {gap:.1%}
PROPOSED SIDE: {side}

SIMULATION DETAILS:
- Agent count: {agent_count}
- Rounds: {rounds}
- Confidence: {sim_confidence}
- Bull arguments: {bull_arguments}
- Bear arguments: {bear_arguments}
- Trajectory: {trajectory}

Analyze:
1. Is the simulation probability well-supported by the arguments?
2. Are there obvious biases in the crowd (groupthink, anchoring to market price)?
3. Is the confidence level appropriate given the evidence?
4. Rate the simulation quality: HIGH, MEDIUM, or LOW

Provide your analysis in 3-5 sentences. End with: QUALITY: [HIGH/MEDIUM/LOW]"""

NEWS_ANALYST_PROMPT = """You are a News Analyst for prediction markets. Evaluate the current information landscape for this event.

EVENT: {event_title}
TICKER: {ticker}
BINARY QUESTION: {binary_question}
PROPOSED TRADE: {side} at {kalshi_price:.1%} (our model says {mirofish_prob:.1%})

Consider:
1. What major news stories or data releases could affect this event?
2. Is there an information asymmetry the market might be pricing in that our model misses?
3. Are there upcoming catalysts (scheduled events, reports, deadlines) that could move this market?
4. Is the current market price likely reflecting insider or institutional knowledge?

Provide your analysis in 3-5 sentences. End with: NEWS_RISK: [LOW/MEDIUM/HIGH]"""

CONTRARIAN_ANALYST_PROMPT = """You are a Contrarian Analyst. Your ONLY job is to argue AGAINST this proposed trade. Find every reason it could fail.

EVENT: {event_title}
TICKER: {ticker}
PROPOSED TRADE: {side} at {kalshi_price:.1%}
OUR MODEL SAYS: {mirofish_prob:.1%} (gap of {gap:.1%})

SENTIMENT ANALYST SAID: {sentiment_report}
NEWS ANALYST SAID: {news_report}

Argue against this trade by considering:
1. Why the market price might be correct and our model wrong
2. What risks the model is underweighting
3. Historical base rates for similar events
4. Liquidity and execution risks
5. What would have to go wrong for this trade to lose

Be aggressive and thorough. Your job is to stress-test, not to be balanced.
Provide your contrarian case in 4-6 sentences. End with: KILL_STRENGTH: [WEAK/MODERATE/STRONG]"""

RISK_MANAGER_PROMPT = """You are the Risk Manager. Review all analyst reports and the current portfolio state, then decide whether to APPROVE, VETO, or ADJUST this trade.

EVENT: {event_title}
TICKER: {ticker}
PROPOSED TRADE: {side} at {kalshi_price:.1%}
OUR MODEL: {mirofish_prob:.1%} (gap: {gap:.1%})
PROPOSED SIZE: {dollar_amount:.2f} ({kelly_pct:.1%} Kelly)

SENTIMENT ANALYST: {sentiment_report}
NEWS ANALYST: {news_report}
CONTRARIAN ANALYST: {contrarian_report}

PORTFOLIO STATE:
- Open positions: {open_position_count}
- Total exposure: ${total_exposure:.2f}
- Current P&L: ${current_pnl:+.2f}
- Categories in portfolio: {portfolio_categories}
- Correlated positions: {correlated_count}

RISK RULES:
- Max position: 5% of bankroll
- Max correlated positions: 3
- Drawdown stop: 20%
- Minimum gap: 15%

Evaluate:
1. Is the gap large enough to justify the risk?
2. Does the contrarian case raise any deal-breakers?
3. Is the portfolio overexposed to this category or correlated events?
4. Should the position size be adjusted?

Respond with your decision and reasoning in 3-5 sentences.
End with exactly one of:
DECISION: APPROVE
DECISION: VETO — [reason]
DECISION: ADJUST — size_multiplier=[0.1-1.0], reason=[explanation]"""

PORTFOLIO_MANAGER_PROMPT = """You are the Portfolio Manager making the final trading decision. You have reviewed all analyst reports and the risk manager's recommendation.

EVENT: {event_title}
TICKER: {ticker}
PROPOSED TRADE: {side} at {kalshi_price:.1%}
OUR MODEL: {mirofish_prob:.1%} (gap: {gap:.1%})

SENTIMENT ANALYST: {sentiment_report}
NEWS ANALYST: {news_report}
CONTRARIAN ANALYST: {contrarian_report}
RISK MANAGER: {risk_assessment}

Make your final decision. Consider all perspectives but prioritize capital preservation.

Respond with JSON only, no other text:
{{
    "decision": "APPROVE" or "VETO" or "ADJUST",
    "confidence": <number 0.0-1.0>,
    "adjusted_probability": <number 0.0-1.0>,
    "size_multiplier": <number 0.1-1.0>,
    "reasoning": "1-2 sentence final rationale",
    "bull_case": "strongest argument FOR the trade",
    "bear_case": "strongest argument AGAINST the trade",
    "risk_assessment": "LOW" or "MEDIUM" or "HIGH",
    "veto_reason": null or "reason if vetoed",
    "bias_flags": ["list", "of", "detected", "biases"]
}}"""


class TradingAgentsGate:
    """5-agent validation gate for trade decisions."""

    def __init__(self, config: Config):
        self.config = config
        self._llm = OpenAI(
            api_key=config.llm_api_key or "not-needed",
            base_url=config.llm_base_url,
        )
        self._model = config.llm_model_name

    def _call_agent(self, prompt: str, agent_name: str) -> str:
        """Make a single LLM call for one agent. Returns the response text."""
        try:
            response = self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.3,
            )
            result = response.choices[0].message.content.strip()
            log.info("[%s] responded (%d chars)", agent_name, len(result))
            return result
        except Exception as e:
            log.error("[%s] failed: %s", agent_name, e)
            return f"[Agent {agent_name} unavailable: {e}]"

    def validate_trade(self, context: dict) -> dict:
        """Run all 5 agents sequentially to validate a proposed trade.

        Parameters
        ----------
        context : dict
            Must contain: ticker, event_title, mirofish_prob, kalshi_price, gap,
            side, dollar_amount, kelly_pct, agent_count, rounds, sim_confidence,
            bull_arguments, bear_arguments, trajectory, binary_question,
            open_positions (list), total_exposure, current_pnl,
            portfolio_categories, correlated_count.

        Returns
        -------
        dict
            {decision, confidence, adjusted_probability, size_multiplier,
             reasoning, bull_case, bear_case, risk_assessment, veto_reason,
             bias_flags, sentiment_report, news_report, contrarian_report}
        """
        # Defaults for optional context fields
        ctx = {
            "ticker": "",
            "event_title": "",
            "binary_question": "",
            "mirofish_prob": 0.5,
            "kalshi_price": 0.5,
            "gap": 0.0,
            "side": "yes",
            "dollar_amount": 0.0,
            "kelly_pct": 0.0,
            "agent_count": 200,
            "rounds": 10,
            "sim_confidence": "moderate",
            "bull_arguments": "[]",
            "bear_arguments": "[]",
            "trajectory": "stable",
            "open_position_count": 0,
            "total_exposure": 0.0,
            "current_pnl": 0.0,
            "portfolio_categories": "none",
            "correlated_count": 0,
        }
        ctx.update(context)

        # Ensure arguments are strings for prompt formatting
        if isinstance(ctx.get("bull_arguments"), list):
            ctx["bull_arguments"] = json.dumps(ctx["bull_arguments"])
        if isinstance(ctx.get("bear_arguments"), list):
            ctx["bear_arguments"] = json.dumps(ctx["bear_arguments"])

        # --- Agent 1: Sentiment Analyst ---
        sentiment_report = self._call_agent(
            SENTIMENT_ANALYST_PROMPT.format(**ctx),
            "SentimentAnalyst",
        )

        # --- Agent 2: News Analyst ---
        news_report = self._call_agent(
            NEWS_ANALYST_PROMPT.format(**ctx),
            "NewsAnalyst",
        )

        # --- Agent 3: Contrarian Analyst ---
        ctx["sentiment_report"] = sentiment_report
        ctx["news_report"] = news_report
        contrarian_report = self._call_agent(
            CONTRARIAN_ANALYST_PROMPT.format(**ctx),
            "ContrarianAnalyst",
        )

        # --- Agent 4: Risk Manager ---
        ctx["contrarian_report"] = contrarian_report
        risk_assessment = self._call_agent(
            RISK_MANAGER_PROMPT.format(**ctx),
            "RiskManager",
        )

        # --- Agent 5: Portfolio Manager (final decision) ---
        ctx["risk_assessment"] = risk_assessment
        pm_response = self._call_agent(
            PORTFOLIO_MANAGER_PROMPT.format(**ctx),
            "PortfolioManager",
        )

        # --- Parse Portfolio Manager JSON ---
        result = self._parse_pm_response(pm_response)

        # Attach intermediate reports for logging
        result["sentiment_report"] = sentiment_report
        result["news_report"] = news_report
        result["contrarian_report"] = contrarian_report
        result["risk_assessment_report"] = risk_assessment

        log.info(
            "Gate result for %s: %s (confidence=%.2f, size_mult=%.2f)",
            ctx["ticker"],
            result.get("decision", "UNKNOWN"),
            result.get("confidence", 0),
            result.get("size_multiplier", 1.0),
        )

        return result

    def _parse_pm_response(self, raw: str) -> dict:
        """Parse the Portfolio Manager's JSON response. Falls back to APPROVE on parse failure."""
        default = {
            "decision": "APPROVE",
            "confidence": 0.5,
            "adjusted_probability": None,
            "size_multiplier": 1.0,
            "reasoning": "Gate parse failed — defaulting to APPROVE",
            "bull_case": "",
            "bear_case": "",
            "risk_assessment": "MEDIUM",
            "veto_reason": None,
            "bias_flags": [],
        }

        try:
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                parsed = json.loads(json_match.group())
                # Merge with defaults to ensure all keys exist
                for key in default:
                    if key not in parsed:
                        parsed[key] = default[key]
                return parsed
            else:
                log.warning("No JSON in PM response: %s", raw[:200])
                return default
        except (json.JSONDecodeError, Exception) as e:
            log.warning("Failed to parse PM response: %s — %s", e, raw[:200])
            return default

    def check_portfolio_bias(self, open_positions: list) -> dict:
        """Analyze the current portfolio for systematic biases.

        Parameters
        ----------
        open_positions : list[dict]
            List of open position dicts from TradeLogger.get_open_positions().

        Returns
        -------
        dict
            {healthy, force_side, warnings, block_categories}
        """
        if not open_positions:
            return {
                "healthy": True,
                "force_side": None,
                "warnings": [],
                "block_categories": [],
            }

        # Analyze directional bias
        yes_count = sum(1 for p in open_positions if p.get("side") == "yes")
        no_count = sum(1 for p in open_positions if p.get("side") == "no")
        total = yes_count + no_count

        # Analyze category concentration
        categories = {}
        for p in open_positions:
            title = p.get("event_title", "")
            # Extract rough category from title keywords
            cat = self._extract_category(title)
            categories[cat] = categories.get(cat, 0) + 1

        warnings = []
        force_side = None
        block_categories = []

        # Directional bias check
        if total >= 3:
            yes_pct = yes_count / total
            if yes_pct > 0.80:
                warnings.append(f"Heavy YES bias: {yes_count}/{total} positions are YES")
                force_side = "no"
            elif yes_pct < 0.20:
                warnings.append(f"Heavy NO bias: {no_count}/{total} positions are NO")
                force_side = "yes"

        # Category concentration check
        for cat, count in categories.items():
            if count >= self.config.max_correlated_positions:
                warnings.append(f"Over-concentrated in '{cat}': {count} positions")
                block_categories.append(cat)

        healthy = len(warnings) == 0

        return {
            "healthy": healthy,
            "force_side": force_side,
            "warnings": warnings,
            "block_categories": block_categories,
        }

    @staticmethod
    def _extract_category(event_title: str) -> str:
        """Extract a rough category from an event title for correlation detection."""
        title_lower = event_title.lower()
        category_keywords = {
            "politics": ["election", "president", "congress", "senate", "vote", "biden", "trump", "political"],
            "economics": ["gdp", "inflation", "fed", "interest rate", "unemployment", "economic", "recession"],
            "crypto": ["bitcoin", "ethereum", "crypto", "btc", "eth"],
            "sports": ["nfl", "nba", "mlb", "nhl", "super bowl", "world series", "championship"],
            "weather": ["hurricane", "temperature", "weather", "climate", "storm"],
            "tech": ["ai", "apple", "google", "meta", "microsoft", "tech", "software"],
            "entertainment": ["oscar", "emmy", "grammy", "box office", "movie", "film"],
        }
        for category, keywords in category_keywords.items():
            if any(kw in title_lower for kw in keywords):
                return category
        return "other"

"""
Quick single-prompt crowd simulator for rapid market pre-screening.
Replaces the full MiroFish pipeline when you just need a fast signal.
One LLM call per market — screens 50 markets in ~10 minutes.
"""

import json
import logging
import re
from openai import OpenAI
from src.config import Config

log = logging.getLogger(__name__)

QUICK_SIM_PROMPT = """You are a crowd simulation engine. Simulate how {agent_count} diverse people would react to the following event over {rounds} rounds of social media interaction.

EVENT: {event_title}
DESCRIPTION: {event_description}
BINARY QUESTION: {binary_question}
CURRENT MARKET PRICE: {kalshi_price}% (this is what the prediction market currently prices it at)

Create a diverse crowd including:
- Retail investors (30%) — emotional, trend-following, social-media-driven
- Institutional analysts (15%) — data-driven, conservative, slow to change view
- Political commentators (20%) — partisan, narrative-driven, high-confidence
- General public (25%) — low-information, influenced by headlines and peers
- Contrarians (10%) — deliberately skeptical, looks for the opposite view

Simulate {rounds} rounds of interaction where agents:
1. Post initial reactions based on their persona's knowledge and biases
2. Read and respond to each other's posts
3. Update their opinions based on social pressure and new arguments
4. Some agents become more extreme, some moderate, some flip sides

After the simulation, report the crowd's converged view.

Respond with JSON only, no other text:
{{
    "consensus_probability": <number 0-100>,
    "confidence": "weak" or "moderate" or "strong",
    "bull_arguments": ["...", "...", "..."],
    "bear_arguments": ["...", "...", "..."],
    "trajectory": "stable" or "shifting_yes" or "shifting_no" or "polarizing",
    "reasoning": "2-3 sentence summary of how the crowd converged"
}}"""


class QuickSimulator:
    def __init__(self, config: Config):
        self.config = config
        self._llm = OpenAI(
            api_key=config.llm_api_key or "not-needed",
            base_url=config.llm_base_url,
        )
        self._model = config.llm_model_name

    def simulate(self, market: dict, agent_count: int = 200, rounds: int = 10) -> dict:
        """Run a quick single-prompt simulation. Returns dict with consensus_probability, confidence, arguments, etc."""
        title = market.get("title", "")
        subtitle = market.get("subtitle", "")
        question = subtitle if subtitle else title
        price = market.get("yes_price", 0.5)

        prompt = QUICK_SIM_PROMPT.format(
            agent_count=agent_count,
            rounds=rounds,
            event_title=title,
            event_description=f"{title} — {subtitle}",
            binary_question=question,
            kalshi_price=f"{price:.0%}" if price <= 1.0 else f"{price}",
        )

        try:
            response = self._llm.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
                temperature=0.3,
            )
            raw = response.choices[0].message.content.strip()

            # Extract JSON from response (may have markdown wrapping)
            json_match = re.search(r'\{[\s\S]*\}', raw)
            if json_match:
                result = json.loads(json_match.group())
            else:
                log.error("No JSON in quick sim response: %s", raw[:200])
                return {"consensus_probability": 50, "confidence": "weak", "error": "parse_failed"}

            log.info("Quick sim for %s: %d%% (%s confidence)",
                     market.get("ticker", "?"), result.get("consensus_probability", 50), result.get("confidence", "?"))
            return result

        except Exception as e:
            log.error("Quick sim failed for %s: %s", market.get("ticker", "?"), e)
            return {"consensus_probability": 50, "confidence": "weak", "error": str(e)}

    def screen_markets(self, markets: list[dict], min_gap: float = 0.10) -> list[dict]:
        """Screen multiple markets quickly. Returns markets with gaps above min_gap, sorted by gap size."""
        screened = []
        for market in markets:
            result = self.simulate(market)
            quick_prob = result.get("consensus_probability", 50) / 100.0
            kalshi_price = market.get("yes_price", 0.5)
            gap = abs(quick_prob - kalshi_price)

            screened.append({
                "market": market,
                "quick_prob": quick_prob,
                "kalshi_price": kalshi_price,
                "gap": gap,
                "confidence": result.get("confidence", "weak"),
                "bull_arguments": result.get("bull_arguments", []),
                "bear_arguments": result.get("bear_arguments", []),
                "trajectory": result.get("trajectory", "stable"),
                "reasoning": result.get("reasoning", ""),
            })

        # Filter by gap and sort
        screened = [s for s in screened if s["gap"] >= min_gap]
        screened.sort(key=lambda x: x["gap"], reverse=True)
        return screened

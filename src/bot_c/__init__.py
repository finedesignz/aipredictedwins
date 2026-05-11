"""Bot C — TradingAgents (TauricResearch) auto-trader.

Adapter layer bridging the upstream TradingAgents framework
(vendored at vendor/TradingAgents) to our multi-bot infrastructure:

- llm_shim: OpenAI-compatible HTTP shim that routes through ClaudeLLM,
  including tool-calling / structured-output emulation.
- strategy: BotThread strategy that runs `ta.propagate()` per ticker
  and auto-executes the decision on Bot C's dedicated Alpaca account.
"""

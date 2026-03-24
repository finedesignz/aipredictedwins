---
name: analyze-trades
description: Run the 5-role analyst team to review trading performance and recommend optimizations
user_invocable: true
---

# Analyze Trades

Run the trade analyst team to review current performance against the 7-10% weekly return target.

## Instructions

Spawn the `trade-analyst` agent to perform a full portfolio review:

```
Use the Agent tool with subagent_type="trade-analyst" to run a comprehensive trading analysis.

The agent should:
1. Query data/trades.db for all Kalshi and Alpaca trades
2. Read the latest bot logs
3. Play 5 analyst roles (Performance, Signal Quality, Risk, Strategy, Optimization)
4. Output a structured report with metrics and top 5 actions
```

Pass the current date and the weekly target (7-10% = $7K-$10K/week on $100K paper) as context.

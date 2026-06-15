---
phase: 9
slug: bot-d-deployment
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-09
---

# Phase 9 — Validation Strategy

## Test Infrastructure
| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (backend) + grep/build checks (dashboard) |
| **Quick run command** | `python -m pytest tests/ -q` |
| **Estimated runtime** | ~20s |

## Sampling Rate
- After each task commit: quick run
- Before `/gsd-verify-work`: full suite green (261+ baseline)

## Validation Architecture (from RESEARCH.md)
- **BOT-01 (code):** `trade_logger.py` BOT_ID allow-list widened to include "D" (was the blocker rejecting non-A/B). Fail-clear preserved — AlpacaClient raises on empty keys; NO silent A/B fallback. Test: BOT_ID=D constructs without rejection; empty-key path raises.
- **BOT-03:** `KNOWN_BOTS` includes "D" (dashboard/api/db.py); seed_bots.py adds D row; 2 hardcoded A/B UI cells (TradeTable.tsx:116, PositionCard.tsx:22-26) generalized so D labels correctly. Test/grep: "D" in KNOWN_BOTS; UI cells no longer binary A/B.
- **BOT-01/02 (infra, HALT):** documented Coolify env recipe — Bot D service uses BARE ALPACA_API_KEY/SECRET (its own account), BOT_ID=D, BOT_PROFILE=daytrade, LEARNING_SHADOW_UNTIL_TRADES; dashboard gets ALPACA_API_KEY_D/_SECRET_KEY_D. Post-deploy: verify D's Alpaca account number != A/B (one-account-per-bot). These are surfaced as authorized human steps, not faked.
- Suite stays green (261+).

Nyquist floor — code tasks: allow-list, KNOWN_BOTS, UI generalization, suite green. Infra: documented + handed off.

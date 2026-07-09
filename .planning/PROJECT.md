# AI Predicted Wins

## What This Is

Automated crypto trading system on Alpaca. A technical signal engine (EMA/ADX/RSI/Volume/VWAP
confluence) drives entries, a deterministic rules gate vetoes bad trades, and a self-learning
memory adjusts behavior from realized outcomes. Runs paper-only until a promotion gate is met.

## Core Value

Compounding, self-improving automated trading edge — the bot gets measurably better as it
accumulates trade outcomes, without manual retuning.

## Context

- **Stack:** Python, Alpaca (`alpaca-py`), Postgres (Coolify) for trade memory, SQLite legacy
  trade log, Next.js + FastAPI dashboard at app.aipredictedwins.com.
- **Existing bots:** A and B (swing, hourly bars), each with its own Alpaca paper account.
- **Codebase map:** `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS, TESTING,
  INTEGRATIONS, CONCERNS).
- **Paused:** Kalshi prediction-market path (do not run).
- **Hard rule:** one Alpaca account per bot — never share.

## Current Milestone: v1.1 Trustworthy P&L + Profitable Retune

**Goal:** Make the bots' performance measurable, then profitable — fix trade-resolution / P&L
logging so the dashboard matches real Alpaca equity, enforce the asset universe, and retune
entry & sizing on real paper data to stop the drawdown and clear the 40% win-rate gate.

**Evidence (2026-07-06 live audit of app.aipredictedwins.com):**
- **Measurement is broken:** only ~30 of ~300 submitted trades per bot resolve into the P&L
  log. Logged closed-trade P&L reads +$1,296 (A) / +$112 (B), but real Alpaca equity is
  **$85,655 (−14.34%) / $96,178 (−3.82%)**. The trade log badly overstates performance.
- **Sub-gate win rate:** 33% (20W/36L) across 60 resolved trades — below the 40% live gate.
- **Universe leak + dead symbols:** BTC is **0-for-12** (−$479); off-universe TRUMP (−$295)
  and FIL (−$66) are being traded despite the documented 8-asset universe.
- Both A/B bots are currently **stopped**.

**Target features:**
- **Trade resolution fix** — every submitted order resolves to a closed trade with accurate
  realized P&L (fees/slippage included); dashboard total P&L reconciles to Alpaca account equity.
- **Universe enforcement** — hard allowlist at entry; block off-universe symbols; drop or
  quarantine chronic losers (BTC).
- **Profitable retune** — confluence + quarter-Kelly sizing retuned on real paper data to lift
  win rate ≥40% and halt drawdown; validated against the existing backtest harness.
- **Reliable runtime + honest monitoring** — bots stay running, alert on unexpected stop, and
  the dashboard surfaces true (reconciled) P&L.

## Current State

**Shipped: v1.0 Day-Trading Upgrade** (2026-06-15) — 10/10 phases verified, 279 tests green.
The engine is now profile-driven (`SWING` + `DAYTRADE`), the live trading path is LLM-free
(deterministic ATR exits), the self-learning loop is closed (advice vetoes/scales entries with
a shadow→auto gate + intraday dimensions), and a fee gate + 5-min backtest harness are in place.
Bot D is code-complete; its live Alpaca account + Coolify service await provisioning
(`docs/deployment/bot-d-coolify-recipe.md`). Archive: `.planning/milestones/v1.0-*`.

**Next milestone goals (candidates):** provision Bot D live; retune daytrade thresholds on real
paper data; full P&L backtest; Options v3. Run `/gsd-new-milestone` to scope.

## Milestone History: v1.0 Day-Trading Upgrade

**Goal:** Add a self-learning intraday day-trading bot (Bot D) by generalizing the swing engine
into strategy profiles, dropping MiroFish from the trading path, replacing LLM exits with
deterministic ATR logic, and closing the currently-open self-learning loop.

**Design spec:** `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md`

**Target features:**
- `StrategyProfile` abstraction (SWING + DAYTRADE presets) over the existing orchestrator
- Drop MiroFish from the Alpaca path; deterministic ATR-scaled stop/trail + max-hold auto-close
- Close the self-learning loop: wire `get_advice()` + `get_dynamic_thresholds()` into entry & sizing
- Intraday learning dimensions (time-of-day, hold-duration, volatility regime) + shadow→auto mode
- 5-minute signal engine: parameterized indicator periods, session-anchored VWAP, ATR value
- Fee/slippage pre-trade gate
- Bot D: new paper account, daytrade profile, Coolify service, dashboard `KNOWN_BOTS` entry

## Key Decisions

- **5-min bars, ~2-min scan** — balances signal frequency (fast learning) vs noise/fee drag.
- **No overnight holds** — max-hold auto-close (4–8h) makes hold-duration a learnable dimension.
- **Shadow-first learning** — learning logs would-be vetoes/scaling until N closed trades (default
  30), then auto-applies. Guards against overfitting on tiny early samples.
- **Profile abstraction over fork** — one engine, two presets; SWING preset reproduces current
  behavior byte-for-byte so bots A/B are unaffected.
- **MiroFish retained in repo, not in path** — Kalshi paused, files kept but not imported by Alpaca.

## Active Requirements

See `.planning/REQUIREMENTS.md`.

## Validated Requirements

(none yet — first milestone)

## Out of Scope

- Kalshi prediction markets (paused)
- Options v3 (calls/puts/spreads — separate future milestone)
- Live trading (stays paper-gated: 50+ trades, >40% win rate, equity target)

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-09 — Milestone v1.1 Trustworthy P&L + Profitable Retune started*

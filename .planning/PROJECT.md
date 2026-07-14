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

## Current State

**Shipped: v1.1 Trustworthy P&L + Profitable Retune** (2026-07-14) — Phases 11–20, 44 plans,
**13/15 requirements Validated, 2 PARTIAL.** Tests 279 → 541 (zero new skips).
Archive: `.planning/milestones/v1.1-*`.

**What v1.1 fixed:**
- Order-state resolution + realized P&L from actual fills, net of fees (PNL-01/02/04); Alpaca
  reconciliation + stale-trade backfill (PNL-03/05).
- Universe hard-gate at all 5 entry sites + config-driven quarantine + dashboard visibility
  (UNIV-01/02/03) — closed the TRUMP/FIL leak.
- **Found the root cause of the "+$1,296 logged vs −14% real equity" contradiction (TUNE-02):**
  395 of 655 position-closed rows (60%) were external-exit sentinels written as `pnl=0.0`, and the
  dashboard booked every one as a LOSS. Sentinel writer fixed; win-rate denominator fixed at 5 reader
  sites; the paper-trade gate went 655 → 260 (delta exactly −395).
- Runtime honesty: fixed `if not any_alive: return` — all-bots-down was the ONE state guaranteed never
  to alert, which is why four dead bots went unnoticed. Bots A/B/C run, alerts deliver (SES-confirmed),
  headline P&L is reconciled.
- Prod risk-rule breaches remediated: Bot B kelly 0.50→0.25, max_position 0.10→0.05; **Bot E was set to
  put 100% of bankroll into a single position (20x breach) → 0.05.**
- Disarmed `scripts/backfill_trades.py`, which had carried an armed `--apply` since Phase 14 that would
  have closed every HELD position with a fabricated loss (proven by execution).

**What v1.1 did NOT do (honest):**
- **TUNE-01 — PARTIAL.** Quarantine + risk-rule fixes shipped; the **entry-knob retune did not**. The
  backtest engine models −15%/+30% exits while the live bot runs −8% + ATR trailing, so the win-rate
  criterion had only two possible values across all 12 live cells and could not discriminate. Phase 17
  located the real losses on the **EXIT** side — the dimension the harness doesn't model.
- **VERIFY-02 — PARTIAL (scoped).** All-time reconciliation **cannot** close: the 395 fabricated-zero
  rows contribute nothing to `trade_log_pnl` while Alpaca's equity already contains their real outcomes,
  so the delta is a **fixed level offset** (Bot A $8,720.31, B $1,610.22, C $2,039.64) — unreachable
  unless those rows are repaired. The honest path is the anchored post-T0 window (opened 2026-07-14
  07:18 UTC, needs ≥20 resolved trades/bot).
- **Paper gate stays BLOCKED.** Post-fix win rate is **34.6%**, below the 40% gate. It was not tuned back.

## Next Milestone Goals

1. **Phase 21 — Exit-Stack Backtest Fidelity + Real Retune (already opened on the roadmap).** Model the
   live exit stack (soft/hard stops, ATR trailing, ATR fixed, max-hold, exit advisor) in
   `src/backtester/engine.py`, then re-sweep BOTH entry and exit knobs. Only then can TUNE-01 close.
2. **Repair the 395 rows — needs a NEW mechanism.** All 395 are `status='closed'` with
   `order_id IS NULL`, while the shipped backfill selects only
   `status IN ('open','submitted') AND order_id IS NOT NULL` → **recovery ceiling 0/395**. A
   purpose-built **`(symbol, qty, timestamp)` matcher** against Alpaca history is required.
   **Blocker:** the `scripts/backfill.py:153` `TradeLogger(bot_id)` positional-arg attribution bug must
   be fixed before any repair is run, or the repair will mis-attribute trades across bots.
3. **VERIFY-02 dated follow-up** — not before **2026-07-28**: `python scripts/e2e_verify.py --json`.
4. Provision Bot D live infra; Options v3 (separate milestone).

## Milestone History: v1.1 Trustworthy P&L + Profitable Retune

**Goal:** Make performance measurable, then profitable. Shipped 2026-07-14 — 13/15 validated, TUNE-01
and VERIFY-02 partial. Full detail: `.planning/milestones/v1.1-ROADMAP.md` and
`.planning/milestones/v1.1-REQUIREMENTS.md`.

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

- **Measurement before edge** (v1.1) — resolution + realized P&L shipped before any tuning; a retune on
  an untrustworthy log is worse than no retune.
- **Never fabricate a trade outcome** (v1.1) — the 395 zero-P&L sentinels were the milestone's root bug;
  repairing them by guessing (or letting the armed backfill close HELD positions at a fabricated loss)
  would re-create it. Repair only via a real Alpaca-history matcher.
- **Don't tune the gate to pass** (v1.1) — 34.6% < 40% → live trading stays BLOCKED.
- **5-min bars, ~2-min scan** — balances signal frequency (fast learning) vs noise/fee drag.
- **No overnight holds** — max-hold auto-close (4–8h) makes hold-duration a learnable dimension.
- **Shadow-first learning** — learning logs would-be vetoes/scaling until N closed trades (default
  30), then auto-applies. Guards against overfitting on tiny early samples.
- **Profile abstraction over fork** — one engine, two presets; SWING preset reproduces current
  behavior byte-for-byte so bots A/B are unaffected.
- **MiroFish retained in repo, not in path** — Kalshi paused, files kept but not imported by Alpaca.

## Active Requirements

None — v1.1 is archived. A fresh `.planning/REQUIREMENTS.md` is created by the next milestone.

## Validated Requirements

**v1.1 (13/15):** PNL-01, PNL-02, PNL-03, PNL-04, PNL-05, UNIV-01, UNIV-02, UNIV-03, TUNE-02, TUNE-03,
RUN-01, RUN-02, VERIFY-01.

**v1.1 PARTIAL (carried forward, NOT validated):**
- **TUNE-01** — entry-knob retune blocked by backtest exit-model fidelity gap → Phase 21.
- **VERIFY-02** — all-time reconciliation provably unreachable (fixed level offset from 395 unrepairable
  rows); anchored post-T0 window evaluable from 2026-07-28.

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
*Last updated: 2026-07-14 — Milestone v1.1 shipped and archived (13/15 validated, 2 partial). Phase 21 open.*

# Phase 18 — Backtest Sweep (TUNE-01 / TUNE-03)

## Headline

**The grid is 12 LIVE CELLS + 6 STRUCTURALLY EMPTY CELLS.** 18 TRAIN cells were run;
the six `min_confluence=5` cells are provably empty (the confluence score ceiling is 4).

**VERDICT: NO GRID POINT CLEARS THE ACCEPTANCE BAR. SHIP THE QUARANTINE ONLY.**

Not one of the 12 live cells reached a 40% win rate — the best was **4.17%** — and every cell
lost money on TRAIN. The single HOLDOUT shot (baseline + quarantine) also fails, on trade count
and on win rate. `min_confluence` and `kelly_fraction` therefore stay where they are: **no
retune is licensed by this sweep.** The quarantine ships on its own evidence
(`17-04-EVIDENCE.md`'s mechanical rule), which does not need the sweep's permission. Bot B's
`kelly_fraction=0.50` comes down to `<= 0.25` regardless — that is the hardcoded quarter-Kelly
ceiling, not a tuning result.

A negative result, honestly recorded, is the output of this plan.

---

## Reproducibility

| Item | Value |
|---|---|
| Bars | Real Alpaca 1H, cached once by `scripts/fetch_backtest_bars.py` |
| Cache | `data/backtest_bars/<SYM>_1Hour.json` (gitignored, 5.5 MB) |
| Fetch command | `python scripts/fetch_backtest_bars.py --start 2025-10-01 --end 2026-04-30` |
| TRAIN window | 2025-10-01 → 2026-01-31 |
| HOLDOUT window | 2026-02-01 → 2026-04-30 |
| Driver | `python scripts/sweep_backtest.py` (each cell = a FRESH subprocess) |
| git rev | `656231da4b9e430c89410e9716b19bf8058b5345` |
| Engine | FINAL (post-18-05): `entry_allowed` + `rsi_ceiling=65.0`. Baseline AND candidate both run on it. |

One cell, verbatim (note `BAR_CACHE_DIR`, and **no bar-fixture flag** — the cache namespace is
`BTC_USD_1Hour.json`, the fixture namespace is `BTC_USD.json`; passing the fixture flag kills
every cell with `sys.exit(1)` "No bar data available"):

```
BAR_CACHE_DIR=data/backtest_bars python -m src.backtester --phase 0 --train \
  --min-confluence 4 --kelly-fraction 0.20 \
  --symbols "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD" \
  --exclude-symbols "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"
```

### Bar coverage (per-symbol, before cell #1 — assumption A4)

| symbol | bars | first_ts | last_ts | scans_afforded |
|--------|------|----------|---------|----------------|
| BTC/USD | 5064 | 2025-10-01 00:00 | 2026-04-30 00:00 | 167 |
| ETH/USD | 5063 | 2025-10-01 00:00 | 2026-04-30 00:00 | 167 |
| SOL/USD | 5058 | 2025-10-01 00:00 | 2026-04-30 00:00 | 166 |
| XRP/USD | 5063 | 2025-10-01 00:00 | 2026-04-30 00:00 | 167 |
| **ADA/USD** | **1812** | **2026-02-13 12:00** | 2026-04-30 00:00 | 58 |
| AVAX/USD | 5064 | 2025-10-01 00:00 | 2026-04-30 00:00 | 167 |
| DOT/USD | 5056 | 2025-10-01 00:00 | 2026-04-30 00:00 | 166 |
| LINK/USD | 5059 | 2025-10-01 00:00 | 2026-04-30 00:00 | 166 |

**ADA/USD carries NO TRAIN bars** (Alpaca's crypto history for it starts 2026-02-13). It
contributes to HOLDOUT only. Recorded, not silently dropped. With BTC and ETH quarantined,
SOL / XRP / AVAX / DOT / LINK (5 symbols) still trade on TRAIN — the quarantine arm is **not**
vacuous.

---

## Tiebreak rule (stated BEFORE the grid was read)

**Prefer the LOWER `kelly_fraction`; then the HIGHER `min_confluence`.** Break ties toward LESS
RISK and FEWER TRADES.

## Acceptance bar (a CONJUNCTION, all on HOLDOUT; `trades >= 30` is checked FIRST)

1. `trade_count >= 30`
2. `win_rate >= 0.40`
3. `max_drawdown` improved vs baseline **AND** `< 0.20`
4. `return / expectancy >= baseline`

---

## Baseline — the live `bots` rows (READ-ONLY `GET /api/bots`; the REVERT target)

| bot | strategy | min_confluence | kelly_fraction | quarantined_symbols | rsi_ceiling | max_position_pct | enabled |
|-----|----------|----------------|----------------|---------------------|-------------|------------------|---------|
| A | confluence | 4 | 0.25 | `null` | 65.0 | 0.05 | true |
| B | confluence | 4 | **0.50** | `null` | 72.0 | 0.10 | true |
| C | tradingagents | 3 | 0.25 | `null` | 70.0 | 0.05 | true |
| E | copytrade | 3 | 0.25 | `null` | 65.0 | 1.00 | false |

(No Bot D row exists on this deployment.) **Bot B is at half-Kelly, in violation of the
hardcoded quarter-Kelly ceiling.** It comes to `<= 0.25` in the rollout regardless of the sweep.

The backtest BASELINE cell is the confluence bots' live config: `min_confluence=4`,
`kelly_fraction=0.25`, quarantine OFF.

---

## TRAIN — all 18 cells (12 live + 6 structurally empty)

| mc | kelly | quarantine | trades | win_rate | max_dd | expectancy | return | verdict |
|----|-------|------------|--------|----------|--------|------------|--------|---------|
| 4 | 0.25 | OFF | 21 | 0.00% | 16.91% | -769.27 | -16.15% | BASELINE |
| 3 | 0.15 | OFF | 31 | 3.23% | 9.38% | -286.59 | -8.88% | FAIL — win_rate 3.23% < 40% |
| 3 | 0.15 | ON | 24 | 4.17% | 7.47% | -300.20 | -7.20% | FAIL — trade count 24 < 30 |
| 3 | 0.20 | OFF | 31 | 3.23% | 12.35% | -377.89 | -11.71% | FAIL — win_rate 3.23% < 40% |
| 3 | 0.20 | ON | 24 | 4.17% | 9.86% | -396.65 | -9.52% | FAIL — trade count 24 < 30 |
| 3 | 0.25 | OFF | 31 | 3.23% | 15.25% | -467.11 | -14.48% | FAIL — win_rate 3.23% < 40% |
| 3 | 0.25 | ON | 24 | 4.17% | 12.21% | -491.32 | -11.79% | FAIL — trade count 24 < 30 |
| 4 | 0.15 | OFF | 21 | 0.00% | 10.43% | -473.29 | -9.94% | FAIL — trade count 21 < 30 |
| 4 | 0.15 | ON | 16 | 0.00% | 8.03% | -483.70 | -7.74% | FAIL — trade count 16 < 30 |
| 4 | 0.20 | OFF | 21 | 0.00% | 13.72% | -623.19 | -13.09% | FAIL — trade count 21 < 30 |
| 4 | 0.20 | ON | 16 | 0.00% | 10.59% | -638.54 | -10.22% | FAIL — trade count 16 < 30 |
| 4 | 0.25 | OFF | 21 | 0.00% | 16.91% | -769.27 | -16.15% | FAIL — trade count 21 < 30 |
| 4 | 0.25 | ON | 16 | 0.00% | 13.10% | -790.26 | -12.64% | FAIL — trade count 16 < 30 |
| 5 | 0.15 | OFF | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |
| 5 | 0.15 | ON | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |
| 5 | 0.20 | OFF | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |
| 5 | 0.20 | ON | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |
| 5 | 0.25 | OFF | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |
| 5 | 0.25 | ON | 0 | 0.00% | 0.00% | 0.00 | 0.00% | FAIL — trade count 0 < 30 |

### The six `min_confluence=5` rows

`trades=0` — the confluence score **CEILING IS 4** (`src/technical_signals.py:371-406`; the
volume spike is deliberately excluded at `:405-406` because VolSpike=True trades went 0-for-17).
**`min_confluence=5` is STRUCTURALLY UNREACHABLE.** These cells auto-fail on criterion 1
(`>= 30 trades`), which is evaluated FIRST precisely so they read as EMPTY rather than as bad
configs. They were RUN and are RECORDED, not silently dropped. The score was **not** "fixed" to
reach 5 — that would be a new strategy, which the phase fences forbid
(`git diff src/technical_signals.py` is EMPTY).

### What the TRAIN grid actually says

- **No cell clears the bar.** The binding failure is not the tiebreak — it is that the
  strategy's win rate over this period is 0–4%, everywhere in the grid.
- Lower `kelly_fraction` reduces drawdown roughly linearly (16.91% → 10.43% at mc=4) and
  reduces losses proportionally. It does not make the strategy profitable; it makes it lose
  more slowly.
- The quarantine reduces both the trade count and the drawdown at every grid point
  (e.g. mc=4/k=0.25: 16.91% → 13.10% max_dd, -16.15% → -12.64% return). It removes losing
  entries. That is the only consistently favourable effect in the whole grid.
- `min_confluence=3` trades more (31 vs 21) and loses less per trade, but its win rate is still
  3.23%.

---

## Candidate

Because **no cell passed**, no retune candidate exists. The single HOLDOUT shot was spent on the
thing that will actually ship: **the baseline knobs plus the quarantine** (`mc=4`, `k=0.25`,
quarantine ON) — i.e. it measures the quarantine's effect alone, on unseen data, against the
untouched baseline. It is recorded as a measurement, not as a pick.

## HOLDOUT — run ONCE (`18-HOLDOUT.lock`; a second run exits 2)

| mc | kelly | quarantine | trades | win_rate | max_dd | expectancy | return | verdict |
|----|-------|------------|--------|----------|--------|------------|--------|---------|
| 4 | 0.25 | OFF | 14 | 21.43% | 7.52% | -350.22 | -4.90% | BASELINE |
| 4 | 0.25 | ON | 11 | 9.09% | 6.36% | -452.01 | -4.97% | FAIL — trade count 11 < 30 |

Four-criterion verdict for the candidate:

| # | Criterion | Result |
|---|-----------|--------|
| 1 | `trade_count >= 30` | **FAIL** — 11 |
| 2 | `win_rate >= 40%` | **FAIL** — 9.09% |
| 3 | `max_drawdown` improved AND `< 20%` | PASS — 6.36% vs 7.52% baseline |
| 4 | `return >= baseline` | **FAIL** — -4.97% vs -4.90% |

The quarantine improves drawdown on unseen data (6.36% vs 7.52%) but the sample is far too thin
(11 trades) to conclude anything from the holdout, and the return is a wash. **The holdout does
not license a retune, and it is not the basis on which the quarantine ships** — that basis is
`17-04-EVIDENCE.md`'s per-symbol, real-trade mechanical rule.

---

## FIDELITY GAP — what the engine does NOT model

The backtester's entry predicate is a subset of the live bot's. 18-05 closed the two gaps the
sweep depends on (`entry_allowed`, `rsi_ceiling`). **Four remain, deliberately unclosed** —
closing them would be a new strategy model, not a retune:

1. **The loss cooldown** (`db.get_recent_loss_symbols`, `bot_thread.py:143`) — the live bot
   refuses to re-enter a symbol it just lost on. The engine re-enters immediately.
2. **The 4H trend filter** (`bot_thread.py:148`) — the engine passes `bars_4h=None`, so
   `trend_4h` is ALWAYS `"unknown"` and the filter never bites.
3. **The SHORT side** (`select_short_candidates`, `bot_thread.py:152-167`) — every live short is
   invisible to the backtest.
4. **The ENTIRE exit stack.** The engine imports `HARD_STOP_PCT = -0.15` and
   `HARD_TAKE_PROFIT_PCT = +0.30` (`src/exit_advisor.py:27-28`) and has ONLY those two
   thresholds (`src/backtester/engine.py:18,100,103`). The LIVE swing bot exits on a
   **`hard_stop_pct = -0.08`** (`src/strategy_profile.py:62`, enforced at
   `src/alpaca_orchestrator.py:322`) PLUS an **ATR trailing stop** PLUS an **ATR fixed stop**
   PLUS a max-hold — **none of which the engine models**. So the engine's stop is nearly
   **twice as wide** as the live bot's and it has no trailing behaviour at all. Its exits are
   not an approximation of the live exits; they are a different, much cruder mechanism.

   *(An earlier revision of this document stated the engine's hard exits were "-4% / +10%".
   That was FALSE — those are the SOFT advisory thresholds, not the engine's. Corrected here.)*

**The holdout number is the LONG-ONLY, WIDE-STOP (-15%/+30%) LOWER BOUND — it is not a promise
about live P&L.** And note the sharpest edge of this: Phase 17 found the SOL/AVAX/ADA losses to be
**EXIT-side** (avg_loss > avg_win) — precisely the dimension the engine models least faithfully.
A sweep over ENTRY knobs cannot be expected to fix an EXIT-side defect, and this grid is
consistent with that: no entry configuration rescued the P&L.

---

## CRITERION 2 NEVER DISCRIMINATED — read this before citing any cell above

**`win_rate >= 40%` was unreachable BY CONSTRUCTION. It tested nothing.**

- **Kelly cannot move win rate.** `kelly_fraction` scales POSITION SIZE. It does not change
  which trades are taken, when they exit, or whether they win. Sweeping kelly across a win-rate
  criterion is a no-op by definition.
- **Only `min_confluence` moved, and it moved to two values.** Across the 12 live cells there
  are exactly **TWO distinct win rates**: **3.23% at `mc=3`** and **0.00% at `mc=4`**. Every
  kelly column within a given `mc` row is identical on criterion 2. The grid contains two
  observations of win rate, not twelve.
- **Neither is within 36 points of the 40% bar.** No cell could have passed. The criterion
  produced 12 FAILs and zero information.

### What the negative result DOES support

> **No entry-knob configuration rescues a long-only, wide-stop (-15%/+30%) model over a crash
> window.** Entry tuning is not where the money is.

That is a real, useful finding, and it is why 18-07 is held and why the recommendation is "ship
the quarantine only, tune nothing."

### What the negative result does NOT support

- **It CANNOT show the current knobs (`min_confluence=4`, `kelly_fraction=0.25`) are optimal.**
  "Everything failed" is not evidence that the incumbent is best; it is evidence the harness
  could not separate the candidates. Leaving the knobs alone is the correct action because the
  sweep licensed no *change* — not because the sweep endorsed the incumbent.
- **It CANNOT rule out that a different exit stack is profitable on the same entries.** The
  harness never modeled the exit stack — no -8% hard stop, no ATR trailing stop, no ATR fixed
  stop, no max-hold — and the exit stack is exactly where Phase 17 located the actual losses.
  The sweep looked for the losses in the one place Phase 17 said they were not.
- **It CANNOT speak to the short side at all** (gap 3), and its win rates are inflated-or-
  deflated by unknown amounts from gaps 1 and 2.

**The honest summary: this was a well-run experiment on the wrong variable.** It is retained as a
genuine negative result — it kills entry-knob tuning — and it must not be cited as validation of
the current configuration or as evidence that the strategy is unfixable. The EXIT stack is
untested. That is Phase 19's question.

---

## Recommendation

1. **Ship the quarantine only** — `quarantined_symbols = "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"`
   on every `strategy == "confluence"` bot (A, B). Independently justified by 17-04-EVIDENCE.md.
2. **Leave `min_confluence` at 4 and `kelly_fraction` at 0.25** — the sweep licenses no change.
3. **Bring Bot B's `kelly_fraction` 0.50 → 0.25** — the hardcoded ceiling, not a tuning result.
   (Bot B's `max_position_pct=0.10` also exceeds the hardcoded 5% rule — flagged for the rollout.)
4. **Do not tune further against this engine.** The evidence points at the EXIT stack, which the
   backtester does not model. That is a Phase-19+ question, not something to force through here.

**The rollout (Plan 18-07) is held for explicit human authorization — it writes the prod `bots`
row. Nothing in Phase 18 plans 01-06 wrote to any prod resource.**

---

## Rollout — APPLIED 2026-07-13 (Plan 18-07, human-authorized)

Written via `PUT /api/bots/{bot_id}` against `https://app.aipredictedwins.com`.
Auth: `Authorization: Bearer $DASHBOARD_TOKEN` (the dashboard service's Coolify env var —
NOT stored in this repo). Cloudflare rejects a default `python-urllib`/curl UA with error
1010, so a browser `User-Agent` is required to reach the origin at all.

No deploy, no restart, no migration, no DDL. The 395 sentinel rows are untouched.
The bots remain PAPER-gated (50 trades / 40% / $100k) — unchanged.

### What was written

| bot | strategy | field | before | after | why |
|-----|----------|-------|--------|-------|-----|
| B | confluence | `kelly_fraction` | **0.50** | **0.25** | Hardcoded quarter-Kelly ceiling (CLAUDE.md). Not a tuning result. |
| B | confluence | `max_position_pct` | **0.10** | **0.05** | Hardcoded "max 5% bankroll per position". |
| E | copytrade | `max_position_pct` | **1.00** | **0.05** | Same rule — E was at **100% of bankroll per position**, a 20x breach. Found during the pre-write baseline read; unrelated to the sweep. Bot E is `enabled=false`, so nothing was sized off it, but the row was one enable away from a catastrophic position. |

`min_confluence` was NOT changed on any bot (criterion 2 never discriminated — see above).
`kelly_fraction` was NOT changed on any bot already `<= 0.25` (A, C, E).
Bots C (`tradingagents`) and E (`copytrade`) are NOT confluence bots — no quarantine applies.

### Verified after the write (`GET /api/bots`)

| bot | strategy | min_confluence | kelly_fraction | max_position_pct | quarantined_symbols |
|-----|----------|----------------|----------------|------------------|---------------------|
| A | confluence | 4 | 0.25 | 0.05 | `null` |
| B | confluence | 4 | **0.25** | **0.05** | `null` |
| C | tradingagents | 3 | 0.25 | 0.05 | `null` |
| E | copytrade | 3 | 0.25 | **0.05** | `null` |

**CEILING HOLDS** — no bot above `kelly_fraction` 0.25. **MAXPOS HOLDS** — no bot above 0.05.
Nothing else changed. `git diff --stat src/` for the rollout itself is EMPTY: it shipped as DATA.

### ⚠️ The QUARANTINE DID NOT APPLY — blocked on a stale prod container

`PUT /api/bots/A` with `{"quarantined_symbols": "..."}` returned **422 `{"detail":"No fields
to update"}`**. That is decisive: the **deployed** `BotUpdate` model does not have a
`quarantined_symbols` field, so pydantic dropped the only key in the payload, leaving an empty
SET clause. The same key was therefore silently dropped from Bot B's PUT too (B's PUT returned
200 only because its `kelly_fraction` / `max_position_pct` keys are valid on the old model).
`GET /api/bots` confirms `quarantined_symbols` is still `null` on every bot.

The column EXISTS (migration 018 ran — the key is present-and-null in the GET response), but the
running container predates **986fd69 `feat(15-02): plumb quarantined_symbols through API + seed`**.
Coolify reports `git_branch=main, git_commit_sha=HEAD, status=running:healthy` — the image is
simply stale relative to `main`.

**To apply the quarantine, the dashboard service must be redeployed** (which picks up 986fd69 and
this plan's `le=0.25` bounds at the same time). Plan 18-07 explicitly forbids a deploy/restart, so
this was NOT done. After a redeploy, the quarantine is one PUT per confluence bot:

```bash
# A and B — AFTER the dashboard is redeployed (will 422 against the current stale image)
for BOT in A B; do
  curl -X PUT "https://app.aipredictedwins.com/api/bots/$BOT" \
    -H "Authorization: Bearer $DASHBOARD_TOKEN" \
    -H 'Content-Type: application/json' \
    -H 'User-Agent: Mozilla/5.0' \
    -d '{"quarantined_symbols": "BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"}'
done
```

### REVERT — copy-paste, per bot

Restores the Baseline exactly. **Reverting Bot B re-arms a half-Kelly, 10%-per-position bot and
reverting Bot E re-arms a 100%-per-position bot — both violate the hardcoded CLAUDE.md risk rules.
Do not run these without a deliberate reason.** Once the redeploy lands, the `le=0.25` bound will
itself reject the Bot B kelly revert with a 422 (by design — Kelly may only go DOWN).

```bash
# REVERT Bot B -> baseline (kelly 0.50, max_position_pct 0.10)  [RISK-RULE VIOLATING]
curl -X PUT "https://app.aipredictedwins.com/api/bots/B" \
  -H "Authorization: Bearer $DASHBOARD_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: Mozilla/5.0' \
  -d '{"kelly_fraction": 0.50, "max_position_pct": 0.10}'

# REVERT Bot E -> baseline (max_position_pct 1.00)  [RISK-RULE VIOLATING]
curl -X PUT "https://app.aipredictedwins.com/api/bots/E" \
  -H "Authorization: Bearer $DASHBOARD_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'User-Agent: Mozilla/5.0' \
  -d '{"max_position_pct": 1.00}'

# Bots A and C were never written. Nothing to revert.
```

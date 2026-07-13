---
phase: 16-effective-universe-dashboard
verified: 2026-07-12T18:05:00Z
status: human_needed
score: 17/18 must-haves verified (1 UNCERTAIN — environment-limited)
requirement: UNIV-03
verifier: Claude (gsd-verifier, independent)
commits_verified: [1e186a6, 2f07854, 6384cdb, 551fa17, 49bc61a]
human_verification:
  - test: "Run `TEST_DATABASE_URL=<local pg> python -m pytest tests/test_effective_universe.py -q` against a real local/test Postgres"
    expected: "19 passed, 0 skipped — cases 14-17 (route 200/404/read-only/openapi) execute the exposure SQL incl. the \"timestamp\"::timestamptz cast"
    why_human: "No Postgres listening on this host (5432/5433 refuse connections). Route tests ERROR on connect, so the exposure SQL has no execution path here. 16-03-SUMMARY claims a real 0-skipped run; the tests exist and are correctly written, but I could not independently reproduce that run."
---

# Phase 16: Effective-Universe Dashboard Visibility — Verification Report

**Phase Goal:** The dashboard exposes the effective live universe per bot so a leak is visible (UNIV-03).
**Verified:** 2026-07-12
**Status:** PASS with one environment-limited UNCERTAIN
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Anti-lie invariant: every allow/block verdict delegates to `src.universe.entry_allowed` | ✓ PASS | `src/effective_universe.py:164` — single call `ok, reason = entry_allowed(sym, allow, quar)`. No set-math re-derivation anywhere in the module. Gate verdict is only ever **downgraded** (shadow sets can turn allow→block, never block→allow), so "a symbol the gate blocks is never reported effective" holds by construction. |
| 2 | Case 13 test is real and non-vacuous | ✓ PASS | `test_resolver_agrees_with_gate` loops all 4 strategies, asserts `gate_blocked_seen > 0` per strategy, `result["blocked"]` non-empty, `total_blocked_by_gate >= 4`, and re-checks every effective symbol against `entry_allowed(...) == (True, None)`. Vacuity guards are genuine. |
| 3 | Shadow deny-lists are STRATEGY-CONDITIONAL (case 18) | ✓ PASS | `shadow_applies_to()` returns False for `copytrade`/`trend_btc`/`tradingagents`. **Independently confirmed against source**, not just the test: `grep MEME_CRYPTO\|_ALPACA_UNTRADEABLE src/` shows usage ONLY in `alpaca_evaluator.py`, the CLI `alpaca_orchestrator.py`, and `bot_thread.py:144-145,163-164` (the confluence selectors). Zero hits in `copytrade_thread.py`, `trend_strategy.py`, `bot_c/strategy.py`. Dispatch confirmed: `bot_thread.py:552/561` return early into `run_trend_cycle`/`run_tradingagents_cycle`; selectors only run at `:647/:652` (confluence path). |
| 4 | copytrade effective INCLUDES ETH/USD; `shadow_applied` False for the 3 non-confluence strategies | ✓ PASS | `test_shadow_sets_confluence_only` asserts `"ETH/USD" in copy["effective"]`, `"ETH/USD" not in reasons(copy)`, `copy["shadow_applied"] is False`, and loops trend_btc/tradingagents asserting no meme/untradeable reasons. Passes. |
| 5 | `GET /api/bots/{bot_id}/universe` is read-only | ✓ PASS | `dashboard/api/routes/bots.py` — two `SELECT`s only. No INSERT/UPDATE/DELETE, no Alpaca client, no BotManager. |
| 6 | Payload carries `shadow_applied` + `exposure_loaded`, no secret/key leak | ✓ PASS | `BotUniverse` model (`models.py`) has both flags + `shadow_sets_loaded`. Handler selects `_BOT_COLS`, which is explicitly key-free ("never expose raw alpaca keys"); no `*` select. No key/secret field in the model. |
| 7 | `exposure_loaded=false` does NOT read as "no leak" (case 11b) | ✓ PASS | Resolver docstring + return flag; route sets `exposure_loaded=False` on query failure inside its own `with get_db()` block (so a failed cast can't poison the row-fetch txn). `test_exposure_unloaded_is_unknown_not_no_leak` passes. UI renders an explicit footnote: "an empty leak list here means UNKNOWN, not clear" (`UniversePanel.tsx:107-112`). |
| 8 | Panel renders server payload verbatim (no client-side allow/block derivation) | ✓ PASS | `UniversePanel.tsx` — `REASON_ORDER` used **only** for display sort; `bySymbol` is a render-only lookup. Effective/blocked/leak/starvation all come straight from the API. |
| 9 | Phase-15 gate, P&L, reconciliation, backfill, sizing, exits UNCHANGED | ✓ PASS | `git diff --stat 00e2714..49bc61a` touches exactly 6 files: `effective_universe.py` (new), `models.py`, `routes/bots.py`, `BotCard.tsx`, `UniversePanel.tsx` (new), `types/index.ts`. Zero changes to `universe.py`, `bot_thread.py`, `db.py`, backfill, sizing or exit code. |
| 10 | `Badge.tsx` diff is EMPTY | ✓ PASS | `git log 2f399c1..HEAD -- dashboard/web/components/shared/Badge.tsx` → 0 commits. Untouched. Panel uses existing `variant` + `className="line-through"`; no hover-only `title`. |
| 11 | Blocked reasons are visible, not hover-only | ✓ PASS | Reason rendered as adjacent `<span className="text-[10px]">{b.reason}</span>` — visible text, confirmed in all 3 screenshots. |
| 12 | Evidence screenshots exist and show the claimed states | ✓ PASS | All 4 present and inspected. `A-normal.png`: "4 of 8 tradeable", AVAX struck `quarantined`, ETH/DOT/LINK struck `untradeable`. `B-leak.png`: red LEAK alarm "TRUMP/USD (1 open, 3 in 30d) traded outside this bot's universe", "3 of 4 tradeable". `C-starvation.png`: amber "No tradeable symbols…", "0 of 2 tradeable", BTC+SOL struck `quarantined`. States match claims. |
| 13 | Full suite green | ✓ PASS | Ran myself: **373 passed, 9 skipped** — exactly the expected baseline. |
| 14 | Pure resolver suite green | ✓ PASS | Ran myself: `tests/test_effective_universe.py` → **15 passed, 4 skipped**. |
| 15 | Route integration cases 14-17 execute the exposure SQL | ? UNCERTAIN | Cannot reproduce: no Postgres listening on this host (5432/5433 refuse). Tests correctly `skipif` without `TEST_DATABASE_URL`; with it set they ERROR at connect (`psycopg_pool`), not silently pass. 16-03-SUMMARY claims a real 0-skipped run. See Gaps. |

**Score:** 17/18 verified, 1 UNCERTAIN (environment-limited, not a code defect).

### Key Link Verification

| From | To | Via | Status |
|------|-----|-----|--------|
| `UniversePanel.tsx` | `/api/bots/{id}/universe` | `useAPI<BotUniverse>(..., 30_000)` | ✓ WIRED |
| `BotCard.tsx` | `UniversePanel` | import + `<UniversePanel botId={bot.bot_id} />` replacing the raw `Assets:` string | ✓ WIRED |
| `routes/bots.py` | `src.effective_universe.resolve_universe` | function-local import, result → `BotUniverse` | ✓ WIRED |
| `effective_universe.py` | `src.universe.entry_allowed` | line 164, the sole verdict source | ✓ WIRED (anti-lie invariant intact) |

### Data-Flow Trace (Level 4)

Real data flows end-to-end: `bots` row + `alpaca_trades` exposure aggregate → `resolve_universe` → `BotUniverse` → `useAPI` → chips/alarms. No hardcoded arrays, no empty-prop stubs. The screenshots show three *different* payload-driven states (normal / leak / starvation), which is itself proof the panel is not static.

### Anti-Patterns Found

None blocking. No TODO/FIXME/XXX/placeholder in the phase's 6 files. `except Exception` in `_load_shadow_sets` is deliberate and **reports** failure via `shadow_sets_loaded=False` (surfaced in the UI) rather than swallowing it — the correct pattern, not a silent catch.

### Known Over-Report (carried from VALIDATION, W2)

`trend_btc` reports `allowlist = cfg.symbols + [trend_symbol]` because that is what the **gate** permits (`trend_strategy.py:103`), though the trend cycle only ever *enters* `trend_symbol`. Deliberate (CONTEXT Decision 2: mirror the gate, not the strategy's appetite). Recorded, not a defect.

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| UNIV-03 | Dashboard exposes the effective live universe per bot so a leak is visible | ✓ SATISFIED | Leak is visibly surfaced with evidence counts (`B-leak.png`); starvation surfaced (`C-starvation.png`); every block carries a visible reason. |

### Gaps Summary

One gap, and it is an **environment limitation, not a code defect**:

Route cases 14-17 (`test_universe_route_200`, `_404`, `_readonly`, `test_openapi_contains_universe_route`) require `TEST_DATABASE_URL`. No Postgres is listening on this host, so they skip (unset) or error at connect (set). VALIDATION line 19 says the exposure SQL — including the `"timestamp"::timestamptz` cast — has **no other execution path**, so that SQL is unproven *in my run*. `16-03-SUMMARY.md` claims a real 0-skipped run against `postgresql://postgres@127.0.0.1:5433/aipw_test`, and reports a genuine bug found and fixed during it (the poisoned-transaction → `exposure_loaded=False` fix), which is corroborating but not proof.

I verified by inspection that the route is read-only, key-free, and 404s correctly, and the SQL is syntactically sound with the required cast. Risk is confined to the exposure query executing correctly at runtime; the resolver, the shadow-set conditionality, and the whole UI path are fully proven.

Note `nyquist_compliant` in 16-VALIDATION.md is still `false` and flips true only on an 18/18, 0-skipped run — that flag has not been flipped.

---

## SHIP VERDICT

**SHIP — with one follow-up.** The phase goal is achieved. The anti-lie invariant holds at the code level (single delegation to `entry_allowed`, gate verdicts only downgraded, never re-derived), and the strategy-conditional shadow-set correction is real — I confirmed it against `src/` directly, not just against the tests: `MEME_CRYPTO`/`_ALPACA_UNTRADEABLE` genuinely appear nowhere outside the confluence selectors and the CLI orchestrator, so copytrade's ETH/USD is correctly *not* struck through. The route is read-only and key-free, `exposure_loaded=false` correctly reads as UNKNOWN rather than "no leak", Badge.tsx is untouched, Phase-15 and the P&L/reconciliation/backfill/sizing/exit surfaces are byte-for-byte unchanged, and the full suite is green at 373 passed / 9 skipped exactly as expected. The screenshots show the three claimed states and match the payload semantics.

**Follow-up (does not block ship):** re-run `tests/test_effective_universe.py` with a live `TEST_DATABASE_URL` to execute cases 14-17 and prove the exposure SQL (the `"timestamp"::timestamptz` cast in particular) against a real Postgres, then flip `nyquist_compliant: true`. Until then the exposure query is verified by inspection only.

---

_Verified: 2026-07-12_
_Verifier: Claude (gsd-verifier) — independent, goal-backward_

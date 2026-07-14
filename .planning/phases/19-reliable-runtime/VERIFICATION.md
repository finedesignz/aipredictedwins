---
phase: 19-reliable-runtime
verified: 2026-07-13T00:00:00Z
status: human_needed
score: 12/12 must-haves verified
scope: plans 19-01..19-06 (RUN-01 + RUN-02). 19-07 deliberately NOT executed (blocking human checkpoint).
commits: fc806c0, 63afa1c, d141a1d, 65c84d2, 47766c4, 8fe0007, 84b2557, 2b6be6f
human_verification:
  - test: "Load app.aipredictedwins.com /settings and /bots against a live Postgres with migration 019 applied"
    expected: "BotManager health indicator shows N/M bots alive; Alerts indicator shows configured/NOT configured; unresolved-trades note renders when unresolved > 0; a keyless bot on /bots shows its status_detail"
    why_human: "Requires a live Postgres. TEST_DATABASE_URL is unset and prod is off-limits for writes. This is precisely what 19-07 exists for."
  - test: "Confirm an ALL BOTS DOWN email actually ARRIVES in the inbox (not merely that send_alert was called)"
    expected: "Email delivered from alerts@emails4agents.com. If SES identity is unverified, the Alerts health indicator must show the swallowed error."
    why_human: "End-to-end SES delivery cannot be proven without sending a real email from the prod container."
---

# Phase 19: Reliable Runtime & Honest Monitoring — Verification Report

**Phase Goal:** RUN-01 — an all-bots-down state actually alerts. RUN-02 — the headline P&L is honest (reconciled, not the trade-log sum), and the 395 `pnl=0.0` sentinels stop being booked as losses.
**Verified:** 2026-07-13
**Status:** human_needed (all automated must-haves VERIFIED; UI render + real SES delivery need a live environment — 19-07)

## THE CENTRAL CLAIM — FALSIFICATION ATTEMPT

**Claim:** an all-bots-down state now ACTUALLY ALERTS.

I did not trust the summaries. I read `src/bot_manager.py` in full and then wrote my **own** integrated test that drives the **real** `_tick()` (fake pool, fake threads, patched notifier) and tried hard to construct a silent all-bots-down sequence. **I could not.**

| # | Adversarial scenario | Result |
|---|---|---|
| 1 | All threads dead, revive **SUCCEEDS** in the same tick (fake `start()` flips `is_alive`→True) | **ALERT FIRED.** Threads `{A: True, B: True}` after tick — yet the alert still went out, because `alive_before` was snapshotted first. This is the exact re-silencing bug the phase had to avoid. |
| 2 | Crash-loop: dead→revived→dead across 5 cooldown-expired ticks | **5/5 ticks alerted.** "Repeats hourly until one bot is alive" is true, not a lie. |
| 3 | Does a successful revive reset the cooldown? | **No.** Cooldown preserved. |
| 4 | One genuinely-alive bot at snapshot | Cooldown correctly reset to 0; no false alert. |
| 5 | `_maybe_reconcile` **raises** AND `_heartbeat` **raises** | **ALERT STILL FIRED.** Both explosions logged as tick-step errors; the alert ran first and was unaffected. |
| 6 | Bot with api key + **EMPTY secret** | `_has_keys` → False. **Zero threads spawned** (no 60s hot loop), misconfig alert fired, and ALL BOTS DOWN also fired (enabled=1, alive=0). |

### Mechanism audit (`src/bot_manager.py`)

| Required property | Status | Evidence |
|---|---|---|
| `alive_before` snapshotted BEFORE `_revive_dead_bots`, passed as a PARAMETER | ✓ PASS | `:162-163` snapshot under lock; `:174` `lambda: self._check_bots_down(alive_before, ...)` is the **first** step in the tuple; revive is second. |
| `_check_bots_down` contains **NO** `is_alive()` call | ✓ PASS | `:185-210` — reads only the `alive_before` param. Zero liveness reads. Verified by grep and by Scenario 1. |
| Cooldown resets ONLY when `alive_before > 0` | ✓ PASS | `:209-210`. Confirmed by Scenarios 3 + 4. |
| `_maybe_reconcile` is LAST | ✓ PASS | `:178` — last element of the step tuple. Each step has its own `try/except` (`:180-183`), so a slow/raising reconcile cannot delay or suppress the alert. Confirmed by Scenario 5. |
| Alert path can actually be DELIVERED | ✓ PASS (with honest caveat) | `send_alert` still swallows (by design — an alert must not crash the bot), **but** it now records the exception in `_last_error` and `last_alert_error()` surfaces it; `alerts_configured()` mirrors `_get_ses_client()`'s resolution order exactly. Both are surfaced on `/settings` health with **pessimistic** defaults. The system can no longer believe it is alerting while silently dropping every email. Real inbox delivery = human item. |

**Verdict on the central claim: NOT FALSIFIED. It holds.**

## Other Must-Haves

| # | Must-have | Status | Evidence |
|---|---|---|---|
| 1 | `_has_keys` requires BOTH key and secret, in BOTH `start_all` and `_revive_dead_bots` | ✓ PASS | `:98` `bool(row["alpaca_api_key"] and row["alpaca_secret_key"])`; called at `:113` (start_all) and `:262` (revive, **before** `_spawn`). |
| 2 | `config.py` frozen dataclass does NOT raise on empty keys (so the guard is the only thing preventing the hot loop) | ✓ PASS | `src/config.py`: `alpaca_api_key: str = ""`, `alpaca_secret_key: str = ""` — plain defaults, no `__post_init__` raise. Confirms `_has_keys` is load-bearing, not belt-and-braces. |
| 3 | `reconcile()` has a PER-BOT try | ✓ PASS | `src/reconciliation.py:135-153` — `try/except/continue` inside the per-bot loop. One keyless bot costs exactly one bot's reconciliation. |
| 4 | RESOLVED predicate (`pnl IS NOT NULL AND pnl <> 0`) at all FIVE reader sites | ✓ PASS | `src/db.py:95` (`is_resolved`, canonical) + `portfolio.py:87`, `portfolio.py:127` (the 5th reader — daily P&L, previously had **no** pnl filter at all) + `settings.py:47`. Sentinels leave numerator **and** denominator, and are surfaced as `unresolved`, never folded into losses. |
| 5 | Headline P&L is Alpaca-derived/reconciled, NOT the trade-log sum | ✓ PASS | `portfolio.py` reads the `reconciliation` table (`_reconciliation_for_bot`) and tags the response `pnl_source ∈ {reconciled, alpaca_live, trade_log}` + `stale`. The old silent Alpaca→trade-log fallback is now flagged. |
| 6 | `settings.py:65`'s hardcoded `100_000.0 * len(bot_ids)` is GONE | ✓ PASS | Source grep: **zero** hits in `dashboard/` or `src/` — the only remaining occurrences are in `test_routes.py:224`, a **fence asserting its absence**. Replaced by per-bot `starting_equity` from the already-fetched rows, with a missing-row-only default. |
| 7 | Every new payload field defaults PESSIMISTIC | ✓ PASS | `models.py`: `manager_alive=False`, `alerts_configured=False`, `stale=True`, `pnl_source="trade_log"`, `reconciled=None`, `bots_alive=0`. `heartbeat_is_fresh(None)` → **False** (`db.py:98-99`). A missing signal can never read as "reconciled and fresh". |
| 8 | Migration 019 + `db_schema.sql` mirror both present | ✓ PASS | `dashboard/api/migrations/019_runtime_heartbeat.sql` + mirrored block at `src/db_schema.sql:226-231` (needed because `_bootstrap_schema()` runs the schema file wholesale). |
| 9 | NO prod DB writes; 395 sentinels byte-identical | ✓ PASS | Migration 019 is `CREATE TABLE IF NOT EXISTS` only — no UPDATE/DELETE/DROP/ALTER, `alpaca_trades` never referenced. The sentinel fix is a **read-side predicate**, not a data mutation. |
| 10 | `git diff src/backfill.py` EMPTY | ✓ PASS | Empty diff across the whole phase range. Fence `test_f1_backfill_is_never_imported_by_the_runtime` locks it. |
| 11 | Risk rules + paper gate pinned; no plan "fixed" the gate reading worse | ✓ PASS | No diff on `src/risk_rules.py` / `src/config.py` risk constants. `win_rate_target=40.0` and `_LIVE_THRESHOLD=100000` unchanged. Fences `test_f2_risk_rules_unchanged`, `test_f3_paper_gate_pinned`, `test_f5_no_retune`. The honest predicate **may make the gate read worse — that is intended and was not tuned away.** |
| 12 | NO test constructs a real BotThread or touches live Alpaca | ✓ PASS | `test_bot_manager.py` / `test_phase19_fences.py` use fakes only; no `BotThread(...)` or `TradingClient(...)` construction. Fence `test_f6_one_alpaca_account_per_bot` holds the one-account-per-bot rule. |

## Independent Runs (mine, not the implementer's)

| Check | Result |
|---|---|
| `python -m pytest tests/ dashboard/api/tests/ -q` | **477 passed, 29 skipped** — matches expectation exactly |
| `npm run build` (dashboard/web) | **Clean.** 9 routes prerendered, no type errors |
| My own adversarial `_tick()` harness | **6/6 scenarios — alert fires in every all-bots-down case** |

## Judgment on the Two Implementer-Flagged Items

**(a) No browser screenshots — ACCEPTABLE, not a gap.** Rendering the new health fields needs a live Postgres with migration 019; `TEST_DATABASE_URL` is unset and prod is write-off-limits under the phase's own no-prod-writes fence. `npm run build` passes and the API contract is covered by tests. This is exactly the gap that **19-07 (the blocking human checkpoint) exists to close** — it is deferred by design, not missed. Carried as a human-verification item.

**(b) `status_detail` not rendered in `BotStatus.tsx` — NOT a gap; the premise is wrong.** `status_detail` **is** rendered, in `dashboard/web/components/bots/BotCard.tsx:40-41`, gated on `status === "error"` — which is precisely the state `_mark_misconfigured` writes (`status='error'`, detail `"missing alpaca keys"`). So a keyless bot surfaces its reason on `/bots`, **and** emails a misconfig alert, **and** shows up in the `/settings` BotManager indicator as `alive < enabled`. Adding it to the settings health panel too would be cosmetic redundancy. No action needed.

## Anti-Patterns / Residual Observations

| Severity | Finding |
|---|---|
| ℹ️ INFO | `_tick`: if `_enabled_rows()` raises (DB down), `enabled` falls to `0`, so `_check_bots_down` does not fire that tick. This is a **defensible** tradeoff (avoids emailing "ALL BOTS DOWN" on every transient DB blip), and the failure is still observable out-of-process: the heartbeat row goes stale → `heartbeat_is_fresh` → `manager_alive=False` on `/settings`. Worth a comment; not a defect. |
| ℹ️ INFO | `send_alert` still swallows exceptions. Correct by design (an alerter must not crash the trader) and now fully compensated by `last_alert_error()` surfacing on the dashboard. |

No TODO/FIXME/XXX/PLACEHOLDER debt markers introduced. No stubs. No hollow props. No orphaned artifacts — every new function is imported and used.

## Ship Verdict

**SHIP — 19-01..19-06 achieve the phase goal. Proceed to 19-07 (human checkpoint).**

The bug that let four dead bots go unnoticed is dead. I attacked the fix from six directions, including the one that would have quietly resurrected it — a revive that succeeds inside the same tick — and the alert fired anyway. The ordering is not merely documented as load-bearing; it **is** load-bearing, and the code holds when reconcile and heartbeat both explode. The empty-secret hot loop is closed at both call sites, and `config.py` confirms that guard is the only thing standing between the system and a 60-second respawn loop. The 395 sentinels are corrected read-side, with zero rows touched, and the paper gate was left free to read worse — the single most important thing a team fixing its own scoreboard can get right.

Remaining work is environmental, not structural: nobody has yet watched the new health panel render against a live DB, and nobody has confirmed an ALL BOTS DOWN email lands in an inbox. Both are 19-07's job. Do not skip 19-07 — "the alert fires" is proven; "the alert arrives" is not.

---

_Verified: 2026-07-13_
_Verifier: Claude (gsd-verifier) — goal-backward, adversarial. SUMMARY.md claims were not used as evidence._

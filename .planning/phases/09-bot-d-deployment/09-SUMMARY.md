---
phase: 09-bot-d-deployment
plans_executed: ["09-01 (all)", "09-02 (all)", "09-03 Task 1 only"]
plans_deferred: ["09-03 Task 2 (human HALT)"]
subsystem: bot-deployment
requirements: [BOT-01 (code), BOT-03]
requirements_deferred: [BOT-01 (live account), BOT-02]
status: code-complete; infra-deferred
tests: { baseline: 261, final: 272, skipped: 2 }
date: 2026-06-15
---

# Phase 9: Bot D Deployment — Execution Summary

One-liner: Bot D is fully wired in code — orchestrator boots on `BOT_ID=D`
(fail-clear bare keys), dashboard lists/attributes/labels it correctly, and the
exact Coolify provisioning recipe is documented. Only the outward-facing infra
(Alpaca account + Coolify service) is deferred to the human HALT.

## What was done

### 09-01 — BOT-01 code (orchestrator allow-list)
- `src/trade_logger.py`: added module-level `KNOWN_BOT_IDS = ("A","B","C","D")`;
  env-path now uppercase-normalizes `BOT_ID` and checks membership (replaces
  `not in ("A","B")`). `bot_id` kwarg path untouched. `config.py` NOT touched —
  orchestrator stays bare-key, no `_D` suffix, no A/B fallback.
- `tests/test_trade_logger_shim.py`: invalid-id test migrated `C`→`Z`; added
  `test_valid_bot_id_d` + `test_lowercase_bot_id_normalized`.
- `tests/test_alpaca_client_failclear.py` (new): empty bare `ALPACA_API_KEY`/
  `ALPACA_SECRET_KEY` raise `ValueError` naming the keys — no silent A/B reuse.
- Commits: `6bf3fa6` (feat), `e211ec0` (test).

### 09-02 — BOT-03 (dashboard, fully code-complete)
- `dashboard/api/db.py`: `KNOWN_BOTS` → `("A","B","C","D")`; `is_specific_bot("D")`
  now True.
- `dashboard/api/seed_bots.py`: extracted DB-free `build_bots()`; added env-gated,
  idempotent Bot D block (daytrade defaults, `asset_class="crypto"`, `BOT_D_*`
  overrides). Fallback log updated to mention D.
- `dashboard/web/lib/botBadge.ts` (new): shared normalize→letter + per-letter
  color map (A=blue, B=amber, C=green, D=red, neutral fallback).
- `TradeTable.tsx` + `PositionCard.tsx`: replaced binary `isB`/`=== "Agent A"`
  logic with `botBadge()`. `bot_id="D"` now renders a "D" badge.
- `tests/test_dashboard_db.py` + `tests/test_seed_bots.py` (new): KNOWN_BOTS /
  is_specific_bot("D") + D-row built only when `_D` env present.
- `tsc --noEmit` clean; no binary A/B branching remains.
- Commits: `ccfc368` (feat db+seed+tests), `45ccee9` (feat UI).

### 09-03 Task 1 — docs (Task 2 deferred)
- `CLAUDE.md`: added Bot C + Bot D rows to the Alpaca Accounts table; documented
  suffixed (dashboard) vs bare (orchestrator) key scheme and the fail-clear rule;
  documented `LEARNING_SHADOW_UNTIL_TRADES` (default 30).
- `docs/deployment/bot-d-coolify-recipe.md` (new): HALT-1 (Alpaca paper account),
  HALT-2 (Coolify orchestrator service mirror of Bot B) with both env tables,
  anti-patterns, and the mandatory post-deploy `/v2/account` account-number check.
- Commit: `899a42e` (docs).

## Verification
- `python -m pytest tests/ -q` → **272 passed, 2 skipped** (baseline 261; +11 new).
- `tsc --noEmit` (dashboard/web) → exit 0.
- Doc grep checks (Bot D, LEARNING_SHADOW_UNTIL_TRADES, account number, ALPACA_API_KEY) → all pass.

## Deviations
- CLAUDE.md: also added the **Bot C** row (table previously only listed A/B; C
  already exists in seed_bots/KNOWN_BOTS). Minor accuracy fix alongside the D row.
- `botBadge.ts` color for D uses `loss-red` token (plan suggested "distinct accent";
  `accent-purple` is not a defined theme token — verified available tokens first).
- No package installs. No architectural changes.

## Self-Check: PASSED
- All new files exist (trade_logger, 4 test files, botBadge.ts, recipe doc).
- All 5 commits present: 6bf3fa6, e211ec0, ccfc368, 45ccee9, 899a42e.

---

## HANDOFF / HALT — 2 infra steps left for the human (09-03 Task 2)

These are outward-facing and were intentionally NOT executed. Full recipe:
`docs/deployment/bot-d-coolify-recipe.md`.

1. **HALT-1 — Create Bot D's Alpaca PAPER account** at https://app.alpaca.markets
   (a NEW account, NOT A/B/C's — one account per bot HARD RULE). Generate keys;
   record KEY + SECRET (secret shown once). Cannot be automated.

2. **HALT-2 — Create Bot D's Coolify orchestrator service** (project
   `u7x0xw0y4qvcgeh8vyidsgyi`), mirroring Bot B. Command
   `python -m src.alpaca_orchestrator --mode paper`.
   - Orchestrator env (**BARE**): `BOT_ID=D`, `BOT_PROFILE=daytrade`,
     `BOT_LABEL=Agent D`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_ENV=paper`,
     shared `DATABASE_URL`, `LEARNING_SHADOW_UNTIL_TRADES=30`.
   - Dashboard env (**SUFFIXED**, add to EXISTING dashboard service):
     `ALPACA_API_KEY_D`, `ALPACA_SECRET_KEY_D`.
   - Anti-patterns: no `_D` suffix / no A/B fallback in orchestrator `config.py`;
     never reuse A/B/C's account.

3. **Mandatory post-deploy check:** GET Bot D's Alpaca `/v2/account` (D's keys),
   confirm `account_number` differs from A/B/C. If identical → STOP (HARD RULE
   violation).

Verify Assumption A1 first: confirm Bot B's live orchestrator uses bare keys
before mirroring.

**Infra-deferred:** BOT-02 + the live-account half of BOT-01.

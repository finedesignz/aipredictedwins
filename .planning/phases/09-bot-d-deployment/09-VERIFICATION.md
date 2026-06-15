---
phase: 09-bot-d-deployment
verified: 2026-06-15T00:00:00Z
status: passed
score: 7/7 must-haves verified (code/docs scope; 2 infra steps properly deferred)
re_verification: null
scope_note: >
  CONTEXT-sanctioned code/infra split. Phase 9 deliverable = Bot D wired in
  code + Coolify recipe documented. The 2 outward-facing infra steps (Alpaca
  paper account, Coolify orchestrator service) are an intentional documented
  human HALT, not expected in code. PASS requires code/docs delivered AND the
  2 infra steps documented + deferred.
deferred:
  - truth: "Bot D runs on its own LIVE Alpaca paper account (account_number distinct)"
    addressed_in: "Human HALT-1 (docs/deployment/bot-d-coolify-recipe.md)"
    evidence: "Recipe HALT-1 + mandatory post-deploy /v2/account account_number check"
  - truth: "BOT-02 — Bot D deployed as separate Coolify orchestrator service"
    addressed_in: "Human HALT-2 (docs/deployment/bot-d-coolify-recipe.md)"
    evidence: "Recipe HALT-2 with bare/suffixed env tables + anti-patterns"
---

# Phase 9: Bot D Deployment Verification Report

**Phase Goal:** Wire Bot D end-to-end in code (orchestrator allow-list, dashboard
attribution/labeling) and document the exact Coolify provisioning recipe; defer
the 2 outward-facing infra steps to a human HALT.
**Verified:** 2026-06-15
**Status:** passed (code/docs scope)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | trade_logger BOT_ID allow-list includes "D", uppercase-normalized | VERIFIED | `src/trade_logger.py:14` `KNOWN_BOT_IDS=("A","B","C","D")`; L28 `os.environ.get("BOT_ID","").upper()`; L29 `not in KNOWN_BOT_IDS` raise |
| 2 | Invalid id (Z) still rejected; D + lowercase valid | VERIFIED | `tests/test_trade_logger_shim.py:49` Z raises; L57 `test_valid_bot_id_d`; L64 `test_lowercase_bot_id_normalized` — all green |
| 3 | config.py has NO `_D` suffix / NO A/B fallback (bare keys) | VERIFIED | `src/config.py:155` `_env("ALPACA_API_KEY","")` bare only; no `_D`/fallback present |
| 4 | AlpacaClient raises on empty bare keys (fail-clear) | VERIFIED | `src/alpaca_client.py:94-97` `if not api_key or not secret_key: raise ValueError(...naming both keys...)` |
| 5 | BOT-03: "D" in KNOWN_BOTS + is_specific_bot("D") True | VERIFIED | `dashboard/api/db.py:18` `KNOWN_BOTS=("A","B","C","D")`; L21-23 `is_specific_bot` |
| 6 | BOT-03: D seed row, idempotent, env-gated | VERIFIED | `seed_bots.py:91` `ALPACA_API_KEY_D` gate, L95 `bot_id:"D"`; L130-133 COUNT-before-INSERT idempotency |
| 7 | BOT-03: hardcoded A/B UI cells generalized; D labels | VERIFIED | `botBadge.ts` D=loss-red + neutral fallback; `TradeTable.tsx:117` + `PositionCard.tsx:20` use `botBadge()`; no `isB`/`==="Agent A"` remain |

**Score:** 7/7 truths verified

### Deferred Items (CONTEXT-sanctioned human HALT)

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | BOT-01 live account (Alpaca paper acct + keys) | HALT-1 | recipe L17-26; post-deploy `/v2/account` account_number check L88 |
| 2 | BOT-02 Coolify orchestrator service | HALT-2 | recipe L33-69 bare(L49-50) vs suffixed(L62-63) env tables + anti-patterns |

### Documentation Verification

| Doc | Expected | Status | Details |
|-----|----------|--------|---------|
| `CLAUDE.md` | Bot C+D rows, bare-vs-suffixed scheme, fail-clear, shadow gate | VERIFIED | L35-36 rows; L38 bare/suffixed + fail-clear; L47 LEARNING_SHADOW_UNTIL_TRADES |
| `docs/deployment/bot-d-coolify-recipe.md` | HALT-1, HALT-2, /v2/account check | VERIFIED | HALT-1 L17; HALT-2 L33; account_number check L88-89; BOT-02/live-acct deferral L102-103 |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite | `python -m pytest tests/ -q` | 272 passed, 2 skipped | PASS (matches claim) |

### Requirements Coverage

| Req | Description | Status | Evidence |
|-----|-------------|--------|----------|
| BOT-01 (code) | BOT_ID=D allow-list, bare fail-clear keys | SATISFIED | truths 1-4 |
| BOT-01 (live) | Distinct Alpaca paper account | DEFERRED | HALT-1 documented |
| BOT-02 | Separate Coolify service | DEFERRED | HALT-2 documented |
| BOT-03 | KNOWN_BOTS+D, attribution, labeling | SATISFIED | truths 5-7 |

### Anti-Patterns Found

None. No stubs, no unreferenced debt markers, no faked infra. botBadge D color
uses `loss-red` (documented deviation — `accent-purple` not a theme token).

### Gaps Summary

No gaps within the sanctioned code/docs scope. All 7 observable truths verified
against actual code; 272/2 test result reproduced; both deferred infra steps are
fully documented with a mandatory account-isolation safety check — not faked.

**SHIP VERDICT: PASS (code/docs).** Bot D is code-complete and the provisioning
recipe is auditable. BOT-02 + the live Bot D Alpaca account remain pending human
action (HALT-1/HALT-2) — outward-facing, correctly deferred. No next-phase block
within scope.

---

_Verified: 2026-06-15_
_Verifier: Claude (gsd-verifier)_

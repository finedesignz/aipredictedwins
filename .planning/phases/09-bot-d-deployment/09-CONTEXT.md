# Phase 9: Bot D Deployment - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up **Bot D** — the day-trade bot — alongside the existing swing bots A/B.

- **BOT-01:** Bot D runs on its OWN Alpaca paper account (`ALPACA_API_KEY_D` /
  `ALPACA_SECRET_KEY_D`), `BOT_ID=D`, `BOT_PROFILE=daytrade`. (Code already supports
  BOT_PROFILE/BOT_ID; this is config + the env-var plumbing that selects the D account.)
- **BOT-02:** Bot D deployed as a SEPARATE Coolify service.
- **BOT-03:** Dashboard `KNOWN_BOTS` includes "D" and attributes its trades/equity correctly.

## Code vs Infra split (IMPORTANT)

This phase has two layers:
1. **Code/config (automatable now):** dashboard `KNOWN_BOTS` + equity/trade attribution for D
   (BOT-03); any per-bot Alpaca-key selection plumbing so `BOT_ID=D` → `ALPACA_API_KEY_D`
   (BOT-01 code side); deployment artifacts (compose/env templates) + docs.
2. **Outward-facing infra (needs human auth — HALT boundary):** creating the real Alpaca
   PAPER account for Bot D (browser signup → produces the D keys) and provisioning the new
   Coolify service. Per global rules, creating a brokerage account and a new prod service are
   outward-facing/irreversible actions requiring explicit authorization — surface exact steps,
   do not fabricate.

The phase delivers all CODE/CONFIG/DOCS; the live account+service creation is handed to the
user (or done via Coolify API only if explicitly authorized + keys provided).
</domain>

<decisions>
## Implementation Decisions

- **D-01:** RESEARCH must find how the per-bot Alpaca keys are selected today (Bot A uses
  `ALPACA_API_KEY_A`, Bot B `_B` — find the selection logic by BOT_ID) and add the `D` case so
  `BOT_ID=D` resolves `ALPACA_API_KEY_D`/`ALPACA_SECRET_KEY_D`. NEVER let D share A/B's account
  (hard rule). Verify no fallback silently reuses A/B keys when D keys are absent — fail clearly.
- **D-02:** Dashboard `KNOWN_BOTS` (RESEARCH: locate it — likely dashboard/api or a config) adds
  "D"; equity-curve + trade attribution must key off bot_id="D" correctly (no overlap with A/B).
- **D-03:** Deployment artifact: mirror Bot B's Coolify service definition as the template for
  D, with env `BOT_ID=D`, `BOT_PROFILE=daytrade`, `ALPACA_API_KEY_D`/`_SECRET_KEY_D`,
  `LEARNING_SHADOW_UNTIL_TRADES` default. Document it; do not assume secrets.
- **D-04 (HALT items):** the actual Alpaca paper-account signup and Coolify service creation are
  surfaced as explicit human/auth steps in the SUMMARY — not faked. If Coolify API creds are
  available AND user authorizes, the service can be created via API in a follow-up.
- **D-05:** Update CLAUDE.md Alpaca-accounts table + the new env vars (`LEARNING_SHADOW_UNTIL_TRADES`
  from Phase 8 too) and project memory/coolify-infra docs so future sessions know Bot D exists.

### Claude's Discretion
- Exact deployment-artifact format (compose snippet, Coolify env list, or docs) — planner's call;
  prefer documenting the precise Coolify env set + a repeatable recipe.
</decisions>

<canonical_refs>
## Canonical References

- `docs/superpowers/specs/2026-06-08-day-trading-upgrade-design.md` §6 (Bot D deployment).
- `.planning/REQUIREMENTS.md` — BOT-01, BOT-02, BOT-03.
- `CLAUDE.md` — Alpaca Accounts table (one-account-per-bot HARD RULE) + Coolify infra.
- Bot A/B Alpaca-key selection logic (RESEARCH locates — likely src/config.py or alpaca_client.py keyed on BOT_ID).
- Dashboard `KNOWN_BOTS` + equity/trade attribution (RESEARCH locates — dashboard/api).
- Project memory: `~/.claude/projects/.../memory/project_coolify_infra.md`, `project_ab_testing.md`.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- BOT_PROFILE (Phase 2) + BOT_ID already exist; daytrade profile ready (Phases 2–8).
- Bot B's Coolify service is the deployment template for D.

### Established Patterns
- Per-bot env-var suffix (`_A`/`_B`) for Alpaca keys; bot_id partitions trade_memory + dashboard.

### Integration Points
- Dashboard reads bots from KNOWN_BOTS; trade_logger/trade_memory partition by bot_id.
</code_context>

<specifics>
## Specific Ideas
Code tests/checks: BOT_ID=D resolves D keys (and does NOT fall back to A/B); dashboard lists D and
attributes its rows; suite stays green (261+). Infra: documented, exact Coolify env set; live
account+service creation surfaced as explicit authorized steps.
</specifics>

<deferred>
## Deferred Ideas
- Backtest + final verification — Phase 10.
- Live trading promotion — out of scope (paper-gated).

None outside phase scope.
</deferred>

---

*Phase: 9-Bot D Deployment*
*Context gathered: 2026-06-09*

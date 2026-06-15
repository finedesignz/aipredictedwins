# Bot D Deployment Recipe (Coolify) — HALT Handoff

Bot D is a **daytrade-profile** crypto bot. All CODE is complete (Phase 9 plans
09-01, 09-02). The two remaining steps below are **outward-facing infra** and
require human authorization — they are NOT performed by code and MUST NOT be
faked. Follow this recipe exactly, then run the mandatory post-deploy check.

Coolify project: **AI Predicted Wins** — UUID `u7x0xw0y4qvcgeh8vyidsgyi`.

> **Assumption A1 — verify first:** Confirm Bot B's existing orchestrator service
> literally reads **bare** `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` (not suffixed)
> before mirroring it for Bot D. If B uses a different scheme, reconcile before
> proceeding.

---

## HALT-1 — Create Bot D's Alpaca PAPER account

**One account per bot is a HARD RULE.** Bot D must have its OWN paper account —
never A's, B's, or C's.

1. Go to https://app.alpaca.markets and create a **NEW paper trading account**
   dedicated to Bot D (distinct from A/B/C).
2. Generate API keys for that account.
3. Record the **API key** and **secret** (the secret is shown only once).
4. Store them in Coolify env only (see HALT-2). **Never commit keys to git**;
   for local reference use `~/.claude/secrets/` only.

This step cannot be automated — brokerage signup is outward-facing.

---

## HALT-2 — Create Bot D's Coolify orchestrator service

Mirror **Bot B's** orchestrator service in project `u7x0xw0y4qvcgeh8vyidsgyi`.
Start command:

```bash
python -m src.alpaca_orchestrator --mode paper
```

### Orchestrator service env (BARE keys)

| Env var | Value | Notes |
|---------|-------|-------|
| `BOT_ID` | `D` | Now accepted by the widened allow-list (09-01) |
| `BOT_PROFILE` | `daytrade` | Daytrade profile |
| `BOT_LABEL` | `Agent D` | Display label |
| `ALPACA_API_KEY` | *(Bot D's key from HALT-1)* | **BARE — no `_D` suffix** |
| `ALPACA_SECRET_KEY` | *(Bot D's secret from HALT-1)* | **BARE — no `_D` suffix** |
| `ALPACA_ENV` | `paper` | Paper mode |
| `DATABASE_URL` | *(shared — same as A/B/C)* | Shared Postgres |
| `LEARNING_SHADOW_UNTIL_TRADES` | `30` | Shadow-mode learning gate (Phase 8) |

### Dashboard service env addition (SUFFIXED keys)

Add to the **EXISTING** dashboard service — do NOT recreate it. These let
`seed_bots.py` build and attribute the Bot D row:

| Env var | Value |
|---------|-------|
| `ALPACA_API_KEY_D` | *(Bot D's key from HALT-1)* |
| `ALPACA_SECRET_KEY_D` | *(Bot D's secret from HALT-1)* |

Optional dashboard overrides (sensible daytrade defaults already baked into
`seed_bots.py`): `BOT_D_LABEL` (default `Agent D — Daytrade`), `BOT_D_KELLY`
(`0.25`), `BOT_D_CONFLUENCE` (`3`), `BOT_D_CRYPTO_UNIVERSE`, etc.

> Coolify-API automation of HALT-2 is allowed **only if** explicitly authorized
> AND creds are present in `~/.claude/secrets/services.json`. HALT-1 cannot be
> automated.

---

## Anti-patterns (do NOT do these)

- ❌ Do **not** add a `_D` suffix or any A/B/C key fallback to the orchestrator's
  `src/config.py`. The orchestrator stays bare-key and fail-clear; empty keys
  must raise, never silently reuse another bot's credentials.
- ❌ Do **not** point Bot D at A/B/C's Alpaca account. One account per bot.

---

## MANDATORY post-deploy check — account-number verification

After the orchestrator service is up, confirm Bot D is on its OWN account:

1. Query Bot D's Alpaca `GET /v2/account` (using D's bare keys) and read the
   `account_number`.
2. Compare against A/B/C's account numbers.
3. If Bot D's **account number** matches any of A/B/C → **STOP immediately**:
   the one-account-per-bot HARD RULE is violated. Swap in the correct Bot D
   keys before letting it trade.

Only after the account number is confirmed **distinct** is Bot D considered
correctly provisioned.

---

## Infra-deferred status

- **BOT-02** (Coolify orchestrator service creation): deferred to this human step.
- **Live-account half of BOT-01** (Alpaca account + keys): deferred to HALT-1.

The code half of BOT-01 (allow-list) and all of BOT-03 (dashboard) are complete.

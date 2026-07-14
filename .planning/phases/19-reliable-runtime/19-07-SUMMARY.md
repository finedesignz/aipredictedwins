---
phase: 19-reliable-runtime
plan: 07
subsystem: verification
tags: [run-01, run-02, human-checkpoint, alert-delivery]
requires: [19-05, 19-06]
provides: [alert-path-proven, 395-row-authorization-withheld]
key-files: {}
metrics:
  commit: "not recorded — this plan produced no code and no committed artifact at execution time"
reconstructed: true
reconstructed-note: "Written 2026-07-14 during the v1.1 milestone archive. The implementer never wrote a SUMMARY for this plan; this one is reconstructed from 19-07-PLAN.md, .planning/phases/19-reliable-runtime/VERIFICATION.md, 20-EVIDENCE.md, and the recorded facts of the deploy session that carried out the checkpoint. Where the plan called for something that was NOT produced, this SUMMARY says so rather than claiming it."
---

# Phase 19 Plan 07: The Human Checkpoint Summary

## What this plan was, and what actually happened

19-07 was the blocking human checkpoint: deploy the phase, prove the alert path *arrives* (not merely
that `send_alert` is called), and put the 395-row repair in front of a human for an explicit yes/no.

The **checkpoint** was carried out. The plan's **written artifact was not**.

## Done

**1. Deployed.** Phase 19 (plans 19-01..19-06) shipped to the Coolify dashboard service. Migration
**019** (`runtime_heartbeat`) was applied. The bots came back up under the fixed `BotManager` — the
`if not any_alive: return` that had let four dead bots go unnoticed is gone from the running system,
not just from `main`.

**2. The alert path is PROVEN to deliver — not merely configured.** Within ~60 seconds of boot, SES
**accepted four real alert emails** from the live container:

| # | Alert | Bot |
|---|-------|-----|
| 1 | trade-silence | — |
| 2 | reconciliation breach | A |
| 3 | reconciliation breach | B |
| 4 | reconciliation breach | C |

This is the one thing the gsd-verifier explicitly could **not** establish. Its report closes with:
*"'the alert fires' is proven; 'the alert arrives' is not."* It is now proven. The four alerts were
also, in themselves, the system's first honest report on itself: it booted and immediately told a human
that three bots were out of reconciliation tolerance and that nothing had traded.

**3. The 395-row backfill was NOT authorized.** Checkpoint decision (a) — *"Do you authorize a FUTURE,
SEPARATE task to repair the 395 historical `pnl = 0.0` rows from Alpaca activity history?"* — was
answered **NO**. The default held. `src/backfill.py` was not run, not with `--apply` and not at all.
`alpaca_trades` is byte-identical over Phase 19.

That refusal turned out to be correct, for reasons Phase 20 later established from prod:

- **The recovery ceiling is 0 of 395** (`20-EVIDENCE.md` §4). All 395 sentinel rows are
  `status='closed'` with `order_id IS NULL`. `db.get_stale_alpaca_candidates` (`src/db.py:186-207`)
  selects only `status IN ('open','submitted') AND order_id IS NOT NULL`. The shipped backfill cannot
  select **even one** of those rows. `resolved: 0` is not a low ceiling — it is the wrong tool pointed
  at the wrong set.
- **And the tool is broken anyway.** `src/backfill.py:153` calls `TradeLogger(bot_id)` **positionally**.
  `TradeLogger.__init__`'s first positional parameter is `db_path`, not `bot_id`
  (`src/trade_logger.py:18`). The loop's `bot_id` is silently discarded and the logger falls back to the
  `BOT_ID` env var — an attribution bug that would misattribute writes across bots. Any future repair
  is blocked on fixing this first.

So the authorization that was withheld would, if granted, have fired a gun that could hit nothing it
was aimed at and would have mislabelled anything it did hit.

## NOT done

- **`19-EVIDENCE.md` was never written.** The plan's sole artifact — the RED→GREEN table for the eleven
  must-fail cases, the 29-case matrix, the F1-F8 fence sweep, the Coolify read-only restart-policy
  report, the container-log diagnosis (mechanism (i) vs B1), the paper-trade-counter caveat, and the
  `REQUIRES HUMAN AUTHORIZATION` section — does not exist on disk and was not committed. The phase's
  `VERIFICATION.md` states plainly: *"19-07 deliberately NOT executed (blocking human checkpoint)."*
  Much of what that document was to contain is nonetheless recorded elsewhere: the fences live as
  executable tests in `tests/test_phase19_fences.py`, the adversarial proof of the killer-bug fix lives
  in `VERIFICATION.md`'s six-scenario falsification attempt, and the 395-row facts were superseded by
  the real prod measurement in `20-EVIDENCE.md`.
- **The Coolify restart-policy read-only report** — **not recorded**. Whether the policy was ever queried
  is not established by any artifact. It remains, per RESEARCH N4, a red herring for this outage: the
  container was up the whole time; only the threads were dead, and no restart policy restarts a thread.
- **Checkpoint decisions (b) and (d)** — the restart-policy follow-up and the
  `paper_trades_completed = COUNT(*)` over-count — **not recorded**. Decision (c), the SES alert
  configuration, is answered by fact rather than by a recorded reply: the alerts sent, so SES was
  configured on the dashboard service.
- The dashboard render evidence the verifier deferred to this plan (badges, stale flag, `manager_alive`)
  — **not recorded** as captured screenshots.

## Deviations

The whole plan is one deviation: the human checkpoint ran, the human answered the question that mattered
(no), and the implementer never produced the evidence document that was supposed to accompany it. This
SUMMARY exists to say that out loud rather than to leave a PLAN with no trace. The gap was carried openly
into `.planning/milestones/v1.1-ROADMAP.md` at archive time.

## Self-Check: PARTIAL

Deploy, migration 019, bots up, four SES-accepted alerts, and the withheld 395-row authorization are all
established. `19-EVIDENCE.md` is not on disk, and the Coolify report, the log-mechanism diagnosis, and
checkpoint answers (b)/(d) are not recorded anywhere. Nothing above is asserted beyond the evidence.

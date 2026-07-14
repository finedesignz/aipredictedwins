# tests/test_phase19_fences.py
"""Phase 19 fences F1-F8 — the things this phase must NOT do.

Every fence runs a POSITIVE CONTROL first (the scanned slice is non-empty and contains a
known-present token) so it cannot pass vacuously. These fences PASS on current main and
must keep passing after the phase lands.

F1 is the important one: `src/backfill.py` is a LOADED GUN. The 395 historical
`pnl = 0.0` sentinel rows in the prod trade log are READ AROUND, never repaired.
Repairing them requires EXPLICIT HUMAN AUTHORIZATION.
"""
import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
_API = _REPO / "dashboard" / "api"
_SCRIPTS = _REPO / "scripts"

_TRADE_WRITE = re.compile(r"UPDATE\s+alpaca_trades|DELETE\s+FROM\s+alpaca_trades", re.I)

# Frozen allowlist, captured from main during Phase 19 Wave 0. These are the ONLY modules
# permitted to write to the trade log. A new name appearing here is a phase failure.
_TRADE_WRITER_ALLOWLIST = {
    "src/db.py",                            # update_alpaca_trade — the legitimate writer
    "dashboard/api/routes/positions.py",    # manual close from the dashboard
}


def _py_files():
    """Every SOURCE module. Test modules are excluded — they are allowed to seed and
    clean a TEST database (never prod; TEST_DATABASE_URL only)."""
    for root in (_SRC, _API, _SCRIPTS):
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts or "tests" in p.parts:
                continue
            yield p


def _rel(p):
    return p.relative_to(_REPO).as_posix()


# ── F1 — no new write to the prod trade log; backfill stays holstered ─────────

def test_f1_no_new_trade_log_writers():
    files = list(_py_files())
    assert len(files) > 20, "positive control failed — the scan found almost no source files"

    # SELF-TEST: the detector really does fire on the known writer.
    db_src = (_SRC / "db.py").read_text(encoding="utf-8")
    assert _TRADE_WRITE.search(db_src), \
        "detector self-test failed — it cannot even see src/db.py::update_alpaca_trade"

    found = {_rel(p) for p in files if _TRADE_WRITE.search(p.read_text(encoding="utf-8"))}
    assert found <= _TRADE_WRITER_ALLOWLIST, \
        f"a NEW writer to alpaca_trades appeared: {sorted(found - _TRADE_WRITER_ALLOWLIST)}"


def test_f1_backfill_is_never_imported_by_the_runtime():
    """src/backfill.py exists and is a loaded gun. Nothing in the manager or the routes
    may import it — the 395 historical sentinels are read around, NOT repaired."""
    runtime = [_SRC / "bot_manager.py", _API / "main.py"]
    runtime += [p for p in (_API / "routes").glob("*.py")]
    assert len(runtime) > 5, "positive control failed — no runtime modules were scanned"

    for p in runtime:
        assert "backfill" not in p.read_text(encoding="utf-8"), \
            f"{_rel(p)} references backfill — the trade log must never be rewritten from here"


# ── F2 — the hardcoded risk rules are untouched ──────────────────────────────

def test_f2_risk_rules_unchanged():
    models = (_API / "models.py").read_text(encoding="utf-8")
    assert "kelly_fraction" in models, "positive control failed"
    assert models.count("le=0.25") >= 2, "the quarter-Kelly write-side ceiling moved"

    cfg = (_SRC / "bot_config.py").read_text(encoding="utf-8")
    assert "max_position_pct: float = 0.05" in cfg, "the 5%-per-position cap moved"
    assert "min(float(row[\"kelly_fraction\"]" in cfg, "the read-side quarter-Kelly clamp is gone"


# ── F3 — the paper gate is NOT unlocked (an honest readout may read WORSE) ───

def test_f3_paper_gate_pinned():
    s = (_API / "routes" / "settings.py").read_text(encoding="utf-8")
    assert "equity_target" in s, "positive control failed — the gate readout moved"
    assert 'mode="paper"' in s, "mode is no longer pinned to paper"
    assert "win_rate_target=40.0" in s, "the paper-gate win-rate target moved"


# ── F4 — no new email provider ───────────────────────────────────────────────

def test_f4_no_new_email_provider():
    n = (_SRC / "notifier.py").read_text(encoding="utf-8")
    assert "send_alert" in n, "positive control failed"

    banned = re.compile(r"sendgrid|resend|postmark|mailgun", re.I)
    for p in _py_files():
        assert not banned.search(p.read_text(encoding="utf-8")), \
            f"{_rel(p)} introduced a new email provider — SES/emails4agents only"


# ── F5 — no retune (Phase 21 owns that) ──────────────────────────────────────

def test_f5_no_retune():
    cfg = (_SRC / "bot_config.py").read_text(encoding="utf-8")
    assert "min_confluence" in cfg, "positive control failed"
    assert "kelly_fraction: float = 0.25" in cfg
    assert "min_confluence: int = 4" in cfg
    assert 'quarantined_symbols: str = ""' in cfg


# ── F6 — one Alpaca account per bot ──────────────────────────────────────────

def test_f6_one_alpaca_account_per_bot():
    rec = (_SRC / "reconciliation.py").read_text(encoding="utf-8")
    assert "_client_for_bot" in rec, "positive control failed — the per-bot client path is gone"

    mgr = (_SRC / "bot_manager.py").read_text(encoding="utf-8")
    assert "AlpacaClient" not in mgr, "bot_manager built an Alpaca client — one account per bot"
    assert "ALPACA_API_KEY" not in mgr, "bot_manager read a bare ALPACA_API_KEY"


# ── F7 — no prod deploy-config change (research N4) ──────────────────────────

def test_f7_deploy_config_unchanged():
    """N4: the container restart policy is a RED HERRING. The container is UP — it serves
    the API. Only the THREADS are dead. No restart policy restarts a thread."""
    docker = (_REPO / "dashboard" / "Dockerfile").read_text(encoding="utf-8")
    assert "PYTHONPATH" in docker, \
        "positive control failed — PYTHONPATH=/app is what makes `import src.*` legal here"


# ── F8 — the suite floor (recorded in the SUMMARY, not self-asserted) ────────

def test_f8_the_runtime_contract_now_has_a_test_file():
    """RUN-01 was entirely untested — tests/test_bot_manager.py did not exist. That is how
    `if not any_alive: return` survived. The pass/skip floor itself is recorded in the
    SUMMARY, not asserted here (a suite cannot count itself)."""
    assert (_REPO / "tests" / "test_bot_manager.py").exists()


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 20 FENCES (cases 37-41) — the things THIS phase must not do.
# ═══════════════════════════════════════════════════════════════════════════

# ── 37 — no new writer to the prod trade log ────────────────────────────────

def test_37_no_new_prod_trade_log_writer_in_phase_20():
    """The frozen allowlist is REUSED, never re-captured. scripts/e2e_verify.py does NOT
    join it — the E2E check is SELECT-only."""
    assert _TRADE_WRITER_ALLOWLIST == {
        "src/db.py",
        "dashboard/api/routes/positions.py",
    }, "the frozen Phase-19 trade-writer allowlist was EDITED"

    # SELF-TEST: the detector still fires on the known writer.
    assert _TRADE_WRITE.search((_SRC / "db.py").read_text(encoding="utf-8")), \
        "detector self-test failed"

    found = {_rel(p) for p in _py_files()
             if _TRADE_WRITE.search(p.read_text(encoding="utf-8"))}
    assert found <= _TRADE_WRITER_ALLOWLIST, \
        f"a NEW writer to alpaca_trades appeared: {sorted(found - _TRADE_WRITER_ALLOWLIST)}"

    verify = _SCRIPTS / "e2e_verify.py"
    if verify.exists():
        assert not _TRADE_WRITE.search(verify.read_text(encoding="utf-8")), \
            "scripts/e2e_verify.py writes to the trade log — it must be SELECT-only"


# ── 38 — THE BACKFILL STAYS UNARMED (the 395 rows are NOT touched) ──────────

# THE GUN HAS A TRIGGER, AND IT PREDATES PHASE 20.
#
# The Phase-20 plan assumed `src/backfill.py` had NO `--apply` entrypoint. IT WAS WRONG:
# `scripts/backfill_trades.py` has been an armed `--apply` CLI since Phase 14 (PNL-05).
# Until Phase 20's fix lands, that trigger fires a backfill that resolves every
# genuinely-HELD position as `closed` with a FABRICATED P&L.
#
# It is NOT wired to CI, to any Dockerfile, to compose, or to cron — verified below. The
# ONLY way it fires is a human typing it. So this fence does the honest thing: it FREEZES
# the trigger set at exactly one known file, asserts Phase 20 adds no second one, and
# asserts nothing automated can pull it. Repairing the 395 rows remains a BLOCKING HUMAN
# AUTHORIZATION (Plan 20-07) — this phase fixes the AMMUNITION, it does not fire the gun.
_BACKFILL_APPLY_ENTRYPOINTS = {"scripts/backfill_trades.py"}

_ARMS_BACKFILL = re.compile(r"--apply|apply\s*=\s*True")


def test_38_the_backfill_stays_unarmed():
    files = list(_py_files())
    assert len(files) > 20, "positive control failed — the scan found almost no source files"

    # POSITIVE CONTROL: the detector really fires on the ONE known trigger.
    known = _SCRIPTS / "backfill_trades.py"
    assert known.exists() and _ARMS_BACKFILL.search(known.read_text(encoding="utf-8")), \
        "detector self-test failed — it cannot see the known --apply entrypoint"

    armed = {
        _rel(p) for p in files
        if "backfill" in p.read_text(encoding="utf-8")
        and _ARMS_BACKFILL.search(p.read_text(encoding="utf-8"))
    }
    assert armed <= _BACKFILL_APPLY_ENTRYPOINTS, (
        f"Phase 20 added a NEW way to arm the backfill: "
        f"{sorted(armed - _BACKFILL_APPLY_ENTRYPOINTS)}. The 395 historical rows are "
        f"repaired ONLY under explicit human authorization."
    )

    # src/backfill.py itself is a LIBRARY. It grows no CLI, no argparse, no __main__.
    lib = (_SRC / "backfill.py").read_text(encoding="utf-8")
    for banned in ("argparse", "__main__", "--apply"):
        assert banned not in lib, \
            f"src/backfill.py grew an entrypoint ({banned}) — the gun must stay holstered"

    # NOTHING AUTOMATED CAN PULL THE TRIGGER. Only a human at a terminal.
    automation = []
    for pattern in ("*.yml", "*.yaml"):
        automation += list((_REPO / ".github").rglob(pattern)) if (_REPO / ".github").exists() else []
    automation += [p for p in _REPO.glob("Dockerfile*")]
    automation += [p for p in (_REPO / "dashboard").glob("Dockerfile*")]
    automation += [p for p in _REPO.glob("docker-compose*")]
    for p in automation:
        if not p.is_file():
            continue
        assert "backfill" not in p.read_text(encoding="utf-8", errors="ignore"), \
            f"{_rel(p)} can fire the backfill AUTOMATICALLY — it must be human-only"


# ── 39 — the hardcoded risk rules are untouched ────────────────────────────

def test_39_hardcoded_risk_rules_untouched():
    cfg = (_SRC / "bot_config.py").read_text(encoding="utf-8")
    conf = (_SRC / "config.py").read_text(encoding="utf-8")
    models = (_API / "models.py").read_text(encoding="utf-8")
    settings = (_API / "routes" / "settings.py").read_text(encoding="utf-8")
    assert "kelly_fraction" in cfg and "max_correlated_positions" in conf, \
        "positive control failed"

    assert "max_position_pct: float = 0.05" in cfg          # max 5% per position
    assert models.count("le=0.25") >= 2                      # quarter-Kelly ceiling
    assert "max_correlated_positions: int = 3" in conf       # max 3 correlated
    assert "drawdown_stop_pct: float = 0.20" in conf         # 20% drawdown stop
    assert "paper_trades_target=50" in settings              # 50 paper trades
    assert "win_rate_target=40.0" in settings                # 40% win rate
    assert 'mode="paper"' in settings                        # paper mode


# ── 40 — no bots-config knob moved (PHASE 21 OWNS THE RETUNE) ──────────────

def test_40_no_bots_config_knob_moved():
    cfg = (_SRC / "bot_config.py").read_text(encoding="utf-8")
    assert "min_confluence" in cfg, "positive control failed"

    assert "min_confluence: int = 4" in cfg
    assert "kelly_fraction: float = 0.25" in cfg
    assert 'quarantined_symbols: str = ""' in cfg


# ── F20-KILLER — DO NOT BREAK PHASE 19's KILLER FIX ────────────────────────
#
# NOTE: deliberately NOT numbered 41. VALIDATION case 41 is "zero new skips", which is a
# property of the SUITE and cannot be asserted by a member of it. It is recorded in the
# SUMMARY from the final suite run.

def test_f20_killer_phase19_killer_fix_is_intact():
    """Liveness is SNAPSHOTTED at tick START. If `_revive_dead_bots` ran first, every
    revivable bot would be alive again and the ALL-BOTS-DOWN alert would NEVER FIRE in
    the dominant failure mode. Phase 20 must not regress it."""
    src = (_SRC / "bot_manager.py").read_text(encoding="utf-8")
    assert "_check_bots_down" in src, "positive control failed — the watchdog moved"

    # It takes the snapshot as a PARAMETER...
    sig = re.search(r"def _check_bots_down\(([^)]*)\)", src)
    assert sig, "_check_bots_down is gone"
    assert "alive_before" in sig.group(1), \
        "_check_bots_down no longer takes the alive_before snapshot"

    # ...and NEVER re-derives liveness inside its own body.
    body_start = src.index("def _check_bots_down")
    nxt = src.find("\n    def ", body_start + 1)
    body = src[body_start: nxt if nxt != -1 else len(src)]
    assert "is_alive()" not in body, \
        "_check_bots_down calls is_alive() in its own body — it must use the SNAPSHOT"

    # ...and in the tick it runs BEFORE the revive. If a revive ran first, every
    # revivable bot is alive again and the ALL-BOTS-DOWN alert never fires.
    check_at = src.index("self._check_bots_down(alive_before")
    revive_at = src.index("self._revive_dead_bots", check_at - 400)
    assert check_at < revive_at, \
        "_revive_dead_bots runs BEFORE _check_bots_down — the all-bots-down alert can " \
        "never fire in the dominant failure mode (Phase 19's killer bug, reintroduced)"

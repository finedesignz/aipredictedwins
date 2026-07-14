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

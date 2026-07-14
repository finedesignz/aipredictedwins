# tests/test_reconciliation.py
"""Phase 13 reconciliation contract — Wave 0 (RED), PNL-03 cases 1-10.

Trade-log realized P&L vs Alpaca-derived realized P&L per bot, with a dollar
tolerance breach flag. Pure math cases pass plain floats; the three-state sum
and driver cases use zero-network in-memory doubles (mirroring
tests/test_close_pnl.py) plus a DATABASE_URL-gated integration guard.

RED until Plan 02 (reconcile_bot + db accessors) and Plan 03 (driver + alert +
entrypoint) land. The pure cases lock the derivation; case 6 locks the
three-state realized-P&L set so a 'closed'-only regression cannot pass.
"""
import os
from contextlib import contextmanager

import pytest

# ─────────────────────────────────────────────────────────────────────────────
# Pure reconcile_bot math cases (1-5, 10)
#   alpaca_realized_pnl = (equity - starting_equity) - unrealized_pnl
#   delta               = trade_log_pnl - alpaca_realized_pnl
#   within_tolerance    = abs(delta) <= tolerance   (inclusive)
# ─────────────────────────────────────────────────────────────────────────────

_KEYS = {"trade_log_pnl", "alpaca_realized_pnl", "delta", "within_tolerance", "tolerance"}


def test_reconcile_within_tolerance():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = (100500 - 100000) - 0 = 500 ; delta = 490 - 500 = -10
    r = reconcile_bot(trade_log_pnl=490.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["alpaca_realized_pnl"] == pytest.approx(500.0, abs=1e-9)
    assert r["delta"] == pytest.approx(-10.0, abs=1e-9)
    assert r["within_tolerance"] is True


def test_reconcile_over_tolerance():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 560 - 500 = 60 > 25 -> breach
    r = reconcile_bot(trade_log_pnl=560.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(60.0, abs=1e-9)
    assert r["within_tolerance"] is False


def test_reconcile_boundary():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 525 - 500 = 25 == tolerance -> inclusive True
    r = reconcile_bot(trade_log_pnl=525.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(25.0, abs=1e-9)
    assert r["within_tolerance"] is True


def test_reconcile_negative_delta():
    from src.reconciliation import reconcile_bot

    # alpaca_realized = 500 ; delta = 450 - 500 = -50 ; abs 50 > 25 -> breach via abs()
    r = reconcile_bot(trade_log_pnl=450.0, equity=100500.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["delta"] == pytest.approx(-50.0, abs=1e-9)
    assert r["within_tolerance"] is False


def test_reconcile_alpaca_derivation():
    from src.reconciliation import reconcile_bot

    # Long, positive unrealized: (101000 - 100000) - 300 = 700
    long = reconcile_bot(trade_log_pnl=700.0, equity=101000.0,
                         starting_equity=100000.0, unrealized_pnl=300.0, tolerance=25.0)
    assert long["alpaca_realized_pnl"] == pytest.approx(700.0, abs=1e-9)
    assert long["within_tolerance"] is True

    # Short / losing open, negative unrealized: (100800 - 100000) - (-200) = 1000
    short = reconcile_bot(trade_log_pnl=1000.0, equity=100800.0,
                          starting_equity=100000.0, unrealized_pnl=-200.0, tolerance=25.0)
    assert short["alpaca_realized_pnl"] == pytest.approx(1000.0, abs=1e-9)
    assert short["within_tolerance"] is True


def test_reconcile_guards():
    from src.reconciliation import reconcile_bot

    # Zero unrealized / empty-positions path -> realized == equity - starting_equity
    r = reconcile_bot(trade_log_pnl=0.0, equity=100000.0,
                      starting_equity=100000.0, unrealized_pnl=0.0, tolerance=25.0)
    assert r["alpaca_realized_pnl"] == pytest.approx(0.0, abs=1e-9)
    assert r["delta"] == pytest.approx(0.0, abs=1e-9)
    assert r["within_tolerance"] is True
    # Result shape: exactly the 5 documented keys
    assert set(r.keys()) == _KEYS
    assert r["trade_log_pnl"] == pytest.approx(0.0, abs=1e-9)
    assert r["tolerance"] == pytest.approx(25.0, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# Case 6 — three-state realized-P&L sum (closed + stopped + target_hit)
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    """Mimics psycopg dict_row semantics for the get_realized_pnl SELECT.

    Applies the SAME three-state status filter Postgres would, over an
    in-memory row set, so the Python summation + NULL guard are exercised
    with zero network. The real WHERE clause is guarded separately by the
    DATABASE_URL-gated integration test below.
    """

    _THREE_STATE = ("closed", "stopped", "target_hit")

    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=None):
        bot_id = params[0]
        matched = [
            {"pnl": r["pnl"]}
            for r in self._rows
            if r["bot_id"] == bot_id and r["status"] in self._THREE_STATE
        ]
        return _FakeResult(matched)


def _fake_connection_factory(rows):
    @contextmanager
    def _conn():
        yield _FakeConn(rows)

    return _conn


def test_realized_pnl_three_states(monkeypatch):
    from src import db

    rows = [
        {"bot_id": "A", "status": "closed", "pnl": 100.0},
        {"bot_id": "A", "status": "stopped", "pnl": 50.0},
        {"bot_id": "A", "status": "target_hit", "pnl": 25.0},
        {"bot_id": "A", "status": "canceled", "pnl": None},
        {"bot_id": "A", "status": "rejected", "pnl": None},
        {"bot_id": "A", "status": "expired", "pnl": None},
    ]
    monkeypatch.setattr(db, "connection", _fake_connection_factory(rows))
    # Only closed+stopped+target_hit contribute: 100 + 50 + 25 = 175
    assert db.get_realized_pnl("A") == pytest.approx(175.0, abs=1e-9)

    # Removing the three non-position terminals does NOT change the sum.
    monkeypatch.setattr(db, "connection", _fake_connection_factory(rows[:3]))
    assert db.get_realized_pnl("A") == pytest.approx(175.0, abs=1e-9)


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping Postgres three-state integration guard",
)
def test_realized_pnl_three_states_db():
    """Real-SQL guard: a regression to 'closed'-only is caught when a DB is present."""
    from src import db

    bot = "A"
    inserted: list[int] = []
    try:
        baseline = db.get_realized_pnl(bot)
        seed = [
            ("closed", 100.0),
            ("stopped", 50.0),
            ("target_hit", 25.0),
            ("canceled", None),
            ("rejected", None),
            ("expired", None),
        ]
        for status, pnl in seed:
            tid = db.log_alpaca_trade(bot, {
                "symbol": "BTC/USD", "asset_class": "crypto", "side": "buy",
                "qty": 1.0, "entry_price": 100.0, "mirofish_prob": 0.5,
            })
            inserted.append(tid)
            db.update_alpaca_trade(bot, tid, status, pnl=pnl)

        after = db.get_realized_pnl(bot)
        # Only closed+stopped+target_hit summed: 100 + 50 + 25 = 175
        assert after - baseline == pytest.approx(175.0, abs=1e-9)
    finally:
        if inserted:
            with db.connection() as conn:
                conn.execute(
                    "DELETE FROM alpaca_trades WHERE id = ANY(%s)", (inserted,)
                )


# ─────────────────────────────────────────────────────────────────────────────
# Driver cases (7-9) — persist + alert + multi-bot isolation
# ─────────────────────────────────────────────────────────────────────────────

class _FakeAlpaca:
    """Per-bot Alpaca double returning fixed equity + open-position unrealized."""

    def __init__(self, equity, positions):
        self._equity = equity
        self._positions = positions

    def get_account(self):
        return {"equity": self._equity}

    def get_positions(self):
        return [{"unrealized_pnl": u} for u in self._positions]


@pytest.fixture
def driver_env(monkeypatch):
    """Wire the src.reconciliation driver against fakes: db reads, persist capture,
    and a send_alert call-counter. Returns handles the tests assert against."""
    from src import reconciliation, notifier
    from src import db

    recorded: list[tuple[str, dict]] = []
    alerts: list[tuple] = []

    # Per-bot db inputs
    realized = {"A": 500.0, "B": 500.0}
    starting = {"A": 100000.0, "B": 100000.0}

    monkeypatch.setattr(db, "get_realized_pnl", lambda bot_id: realized[bot_id])
    monkeypatch.setattr(db, "get_starting_equity", lambda bot_id: starting[bot_id])
    monkeypatch.setattr(
        db, "record_reconciliation",
        lambda bot_id, result: recorded.append((bot_id, result)),
    )
    monkeypatch.setattr(
        notifier, "send_alert",
        lambda subject, body: alerts.append((subject, body)) or True,
    )
    monkeypatch.setenv("RECONCILIATION_TOLERANCE_USD", "25.0")

    return {
        "reconciliation": reconciliation,
        "recorded": recorded,
        "alerts": alerts,
        "realized": realized,
        "starting": starting,
    }


def test_persist_reconciliation(driver_env, caplog):
    reconciliation = driver_env["reconciliation"]
    recorded = driver_env["recorded"]

    # equity 100600, unrealized 0 -> alpaca_realized 600 ; trade_log 500 -> delta -100 breach
    alpaca = _FakeAlpaca(equity=100600.0, positions=[])
    with caplog.at_level("WARNING"):
        result = reconciliation.reconcile_bot_live("A", alpaca)

    assert result["within_tolerance"] is False
    assert len(recorded) == 1
    bot_id, rec = recorded[0]
    assert bot_id == "A"
    assert rec["delta"] == pytest.approx(-100.0, abs=1e-9)
    assert rec["within_tolerance"] is False
    assert rec["tolerance"] == pytest.approx(25.0, abs=1e-9)


def test_breach_alerts(driver_env, caplog):
    reconciliation = driver_env["reconciliation"]
    alerts = driver_env["alerts"]

    # Breach -> WARNING + exactly one alert
    breaching = _FakeAlpaca(equity=100600.0, positions=[])
    with caplog.at_level("INFO"):
        reconciliation.reconcile_bot_live("A", breaching)
    assert len(alerts) == 1
    assert any(r.levelname == "WARNING" for r in caplog.records)

    # Within tolerance -> INFO, no additional alert
    alerts.clear()
    caplog.clear()
    clean = _FakeAlpaca(equity=100500.0, positions=[])  # realized 500 == trade_log 500
    with caplog.at_level("INFO"):
        reconciliation.reconcile_bot_live("A", clean)
    assert alerts == []
    assert any(r.levelname == "INFO" for r in caplog.records)


def test_multi_bot_independent(driver_env, monkeypatch):
    reconciliation = driver_env["reconciliation"]
    recorded = driver_env["recorded"]
    alerts = driver_env["alerts"]

    # Bot A clean (realized 500, equity 100500 -> alpaca 500), Bot B breaching
    # (realized 500, equity 100600 -> alpaca 600 -> delta -100).
    clients = {
        "A": _FakeAlpaca(equity=100500.0, positions=[]),
        "B": _FakeAlpaca(equity=100600.0, positions=[]),
    }

    def fake_enabled_bots():
        return ["A", "B"]

    def fake_client_for(bot_id):
        return clients[bot_id]

    # The driver enumerates enabled bots and builds one client per bot; patch
    # both seams so no real DB/Alpaca is touched.
    monkeypatch.setattr(reconciliation, "_enabled_bot_ids", fake_enabled_bots, raising=False)
    monkeypatch.setattr(reconciliation, "_client_for_bot", fake_client_for, raising=False)

    results = reconciliation.reconcile()

    by_bot = {bot_id: res for bot_id, res in results}
    assert by_bot["A"]["within_tolerance"] is True
    assert by_bot["B"]["within_tolerance"] is False
    assert by_bot["B"]["delta"] == pytest.approx(-100.0, abs=1e-9)

    # Two independent rows recorded; only the breaching bot alerted.
    assert {b for b, _ in recorded} == {"A", "B"}
    assert len(alerts) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Phase 19 (RUN-02) — case 23: reconcile() needs a PER-BOT guard (research N1)
#
# reconcile() (:139-143) has NO per-bot try. _client_for_bot RAISES ValueError on a
# keyless bot (:86-90), and _enabled_bot_ids (:51-59) selects `enabled = TRUE` with NO
# key predicate. So ONE misconfigured bot already reconciles ZERO bots today — including
# the healthy ones. 19-03 makes keyless-enabled bots VISIBLE, and 19-05 schedules this
# hourly, so the landmine must be defused BEFORE the schedule steps on it.
#
# Keep _client_for_bot RAISING — it is the one-account-per-bot enforcement point.
# The CALLER is what changes.
# ─────────────────────────────────────────────────────────────────────────────

def test_reconcile_is_guarded_per_bot(monkeypatch):
    from src import reconciliation

    persisted: list[str] = []

    def fake_enabled_bots():
        return ["A", "X"]

    def fake_client_for(bot_id):
        if bot_id == "X":
            raise ValueError(f"No Alpaca keys for bot {bot_id}")
        return object()

    def fake_live(bot_id, client, tolerance=None):
        persisted.append(bot_id)
        return {"trade_log_pnl": 0.0, "alpaca_realized_pnl": 0.0, "delta": 0.0,
                "within_tolerance": True, "tolerance": 25.0}

    monkeypatch.setattr(reconciliation, "_enabled_bot_ids", fake_enabled_bots)
    monkeypatch.setattr(reconciliation, "_client_for_bot", fake_client_for)
    monkeypatch.setattr(reconciliation, "reconcile_bot_live", fake_live)

    results = reconciliation.reconcile()      # must NOT raise

    assert [b for b, _ in results] == ["A"], "the healthy bot must still reconcile"
    assert persisted == ["A"]
    assert "X" not in [b for b, _ in results], "the broken bot must be logged and SKIPPED"


def test_reconcile_survives_a_raising_reconcile_bot_live(monkeypatch):
    """An Alpaca timeout for one bot is caught the same way — it costs exactly one bot."""
    from src import reconciliation

    monkeypatch.setattr(reconciliation, "_enabled_bot_ids", lambda: ["A", "B"])
    monkeypatch.setattr(reconciliation, "_client_for_bot", lambda b: object())

    def fake_live(bot_id, client, tolerance=None):
        if bot_id == "A":
            raise TimeoutError("alpaca timed out")
        return {"trade_log_pnl": 0.0, "alpaca_realized_pnl": 0.0, "delta": 0.0,
                "within_tolerance": True, "tolerance": 25.0}

    monkeypatch.setattr(reconciliation, "reconcile_bot_live", fake_live)

    results = reconciliation.reconcile()
    assert [b for b, _ in results] == ["B"]


# ═══════════════════════════════════════════════════════════════════════════
# PHASE 20 — G4: THE ANCHORED RECONCILIATION WINDOW (cases 17-30)
#
# `reconcile_bot` compares two CUMULATIVE-SINCE-INCEPTION quantities. The 395
# historical sentinel rows carry pnl = 0.0 and contribute EXACTLY ZERO to
# trade_log_pnl, while Alpaca's (equity - starting_equity) already contains their
# true outcome. The delta is therefore a FIXED LEVEL OFFSET: let any future trade be
# recorded perfectly and it adds x to BOTH sides, leaving the offset unchanged. The
# offset is INVARIANT UNDER ALL FUTURE CORRECT BEHAVIOR. `abs(delta) <= $25` on the
# all-time window is UNSATISFIABLE for A/B/C forever, absent a write to those rows.
#
# So the all-time check KEEPS BREACHING, is relabelled `legacy`, and its offset is
# SURFACED. **THE BREACH IS THE FINDING.**
#
# The anchor table is a FORCED MOVE, not a preference: the entire AlpacaClient surface
# was enumerated and there is NO activities call and NO portfolio-history call. There
# is literally no way to ask Alpaca "what did you realize since T0". It must be
# snapshotted.
#
# TWO MOVES WOULD MAKE A "GREEN" RESULT A LIE, and both are pinned here:
#   · UPSERTing the anchor  -> re-anchors T0 every run -> an empty window -> vacuously green
#   · widening the tolerance -> the breach disappears instead of being reported
# Cases 29 and 24 are the pins.
# ═══════════════════════════════════════════════════════════════════════════

import pathlib  # noqa: E402
import re  # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parents[1]
_RECON_SRC = (_REPO / "src" / "reconciliation.py").read_text(encoding="utf-8")
_DB_SRC = (_REPO / "src" / "db.py").read_text(encoding="utf-8")

_ANCHOR_T0 = {"equity": 100_000.0, "unrealized_pnl": 0.0, "trade_log_pnl": 0.0,
              "anchored_at": "2026-07-12T00:00:00+00:00"}


def _window(**over):
    """reconcile_window kwargs with a clean, sufficient-sample default."""
    from src.reconciliation import reconcile_window

    kw = dict(
        anchor=dict(_ANCHOR_T0),
        trade_log_pnl_now=0.0,
        equity_now=100_000.0,
        unrealized_now=0.0,
        resolved_post_t0=25,
        unresolved_post_t0=0,
        legacy_offset_usd=-8_720.0,
    )
    kw.update(over)
    return reconcile_window(**kw)


# ── cases 17-18: the windowed arithmetic and the SIGN TRAP ──────────────────

def test_window_arithmetic_is_cent_exact():
    """Case 17. alpaca_realized_window = (equity_now - equity_T0) - (unrealized_now - unrealized_T0)."""
    r = _window(trade_log_pnl_now=850.0, equity_now=101_000.0, unrealized_now=200.0)

    assert r["alpaca_realized_window"] == pytest.approx(800.0, abs=1e-9)
    assert r["trade_log_window"] == pytest.approx(850.0, abs=1e-9)
    assert r["delta_window"] == pytest.approx(50.0, abs=1e-9)


def test_a_losing_open_position_raises_derived_realized():
    """Case 18 — THE SIGN TRAP. unrealized_pnl is SIGNED: a LOSING open position
    (negative unrealized) INCREASES derived realized. The window differences BOTH
    unrealized terms, so a sign slip here is SILENT.
    """
    flat = _window(trade_log_pnl_now=0.0, equity_now=101_000.0, unrealized_now=0.0)
    losing = _window(trade_log_pnl_now=0.0, equity_now=101_000.0, unrealized_now=-500.0)

    assert losing["alpaca_realized_window"] == pytest.approx(
        flat["alpaca_realized_window"] + 500.0, abs=1e-9)


# ── cases 19-21: the tolerance floor, the band, the inclusive boundary ──────

def test_tolerance_floor_binds_on_small_windows():
    """Case 19. A $100 window -> the $25 FLOOR binds (not 0.5% = $0.50)."""
    from src.reconciliation import window_tolerance

    assert window_tolerance(100.0) == pytest.approx(25.0, abs=1e-9)


def test_tolerance_band_binds_on_large_windows():
    """Case 20. A $100k window -> the 0.5% BAND binds ($500). Symmetric under sign."""
    from src.reconciliation import window_tolerance

    assert window_tolerance(100_000.0) == pytest.approx(500.0, abs=1e-9)
    assert window_tolerance(-100_000.0) == pytest.approx(500.0, abs=1e-9)


def test_boundary_is_inclusive():
    """Case 21. abs(delta_window) EXACTLY == tolerance_window -> within. Matches
    reconcile_bot's inclusive `<=` (src/reconciliation.py:35)."""
    # equity_now 100_100 -> alpaca_realized_window = 100. tolerance = the $25 floor.
    r = _window(trade_log_pnl_now=125.0, equity_now=100_100.0, unrealized_now=0.0)

    assert r["tolerance_window"] == pytest.approx(25.0, abs=1e-9)
    assert r["delta_window"] == pytest.approx(25.0, abs=1e-9)
    assert r["within_tolerance_window"] is True


# ── case 22: INSUFFICIENT_SAMPLE IS NOT A PASS ──────────────────────────────

def test_insufficient_sample_is_not_a_pass():
    """Case 22 — THE ONE THE HONESTY OF THE PHASE RESTS ON.

    19 post-T0 resolved trades with a PERFECT ZERO delta is STILL NOT A PASS. A perfect
    delta on a thin sample has not earned a verdict. The verdict must flip ONLY on the
    sample count.
    """
    from src.reconciliation import MIN_WINDOW_SAMPLE

    assert MIN_WINDOW_SAMPLE == 20

    thin = _window(resolved_post_t0=19)
    assert thin["delta_window"] == pytest.approx(0.0, abs=1e-9)
    assert thin["verdict"] == "INSUFFICIENT_SAMPLE"
    assert thin["verdict"] != "PASS"

    fat = _window(resolved_post_t0=20)
    assert fat["delta_window"] == pytest.approx(0.0, abs=1e-9)
    assert fat["verdict"] == "PASS"

    # The ONLY thing that changed is the sample count.
    assert thin["delta_window"] == fat["delta_window"]


# ── case 23: the resolution-rate bar ────────────────────────────────────────

def test_resolution_rate_bar():
    """Case 23. rate = resolved / (resolved + unresolved); the bar is 0.95."""
    from src.reconciliation import RESOLUTION_RATE_BAR

    assert RESOLUTION_RATE_BAR == 0.95

    ok = _window(resolved_post_t0=20, unresolved_post_t0=1)     # 0.952 -> PASS
    assert ok["resolution_rate_post_t0"] == pytest.approx(20 / 21, abs=1e-9)
    assert ok["verdict"] == "PASS"

    bad = _window(resolved_post_t0=20, unresolved_post_t0=5)    # 0.80 -> FAIL
    assert bad["resolution_rate_post_t0"] == pytest.approx(0.80, abs=1e-9)
    assert bad["verdict"] == "FAIL"

    # Zero denominator -> 0.0, never a ZeroDivisionError.
    empty = _window(resolved_post_t0=0, unresolved_post_t0=0)
    assert empty["resolution_rate_post_t0"] == 0.0
    assert empty["verdict"] == "INSUFFICIENT_SAMPLE"


# ── case 24: THE TOLERANCE CANNOT BE WIDENED TO FORCE A PASS ────────────────

def test_the_tolerance_cannot_be_widened_to_force_a_pass():
    """Case 24 — FENCE, BANNED MOVE.

    Widening a tolerance until the breach disappears is the single most tempting and
    most dishonest move available in this phase. THE BREACH IS THE FINDING.

    NOTE the LIMIT of this fence, stated out loud: it greps COMMITTED FILES. `_tolerance()`
    reads os.environ AT CALL TIME, so a Coolify `RECONCILIATION_TOLERANCE_USD=100000` is a
    lever THIS TEST CANNOT SEE. That door is closed by case 42 in
    tests/test_e2e_verify_fences.py, which makes the REPORT fail loudly on any env override.
    """
    from src.reconciliation import DEFAULT_TOLERANCE_PCT, DEFAULT_TOLERANCE_USD

    # POSITIVE CONTROL FIRST.
    assert "reconcile_bot" in _RECON_SRC, "positive control failed — the file is empty"

    assert DEFAULT_TOLERANCE_USD == 25.0, "the $25 all-time tolerance MOVED"
    assert DEFAULT_TOLERANCE_PCT == 0.005, "the 0.5% band MOVED"

    # No COMMITTED file raises the tolerance.
    raiser = re.compile(r"RECONCILIATION_TOLERANCE_(USD|PCT)\s*[=:]\s*['\"]?[0-9]")
    for p in (_REPO / "src").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        for m in raiser.finditer(text):
            raise AssertionError(f"{p.name} sets a tolerance override: {m.group(0)!r}")


# ── cases 25-26: the legacy offset is SURFACED, never hidden ────────────────

def test_legacy_offset_is_surfaced_never_hidden():
    """Case 25. A number EXCLUDED from a check must be VISIBLE NEXT TO the check, or
    the exclusion is a LIE OF OMISSION."""
    r = _window(legacy_offset_usd=-8_720.55)

    assert r["legacy_offset_usd"] == pytest.approx(-8_720.55, abs=1e-9)
    assert r["legacy_note"], "the legacy offset carries no explanation"
    assert isinstance(r["legacy_note"], str)
    assert r["anchored_at"] == _ANCHOR_T0["anchored_at"]


def test_an_alltime_breach_alongside_a_windowed_pass_is_an_overall_pass():
    """Case 26. The permanent all-time offset is REPORTED with `legacy: true`, not
    counted as a fresh regression. The WINDOW is what earns the verdict."""
    from src.reconciliation import reconcile_bot

    # The all-time row: a huge fixed offset from the 395 unrecorded exits.
    alltime = reconcile_bot(trade_log_pnl=0.0, equity=108_720.0,
                            starting_equity=100_000.0, unrealized_pnl=0.0,
                            tolerance=25.0)
    assert alltime["within_tolerance"] is False   # it breaches. FOREVER. That is the finding.

    window = _window(resolved_post_t0=25)
    assert window["verdict"] == "PASS"
    assert window["legacy_offset_usd"] != 0.0     # and the offset rides along, visible


# ── the anchor: a SQL-honouring fake that implements ON CONFLICT for real ───

class _FakeAnchorResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return dict(self._rows[0]) if self._rows else None


class _FakeAnchorConn:
    """Implements ON CONFLICT (bot_id) DO NOTHING **for real**.

    If the INSERT it is handed says DO NOTHING, a second write is a no-op. If it says
    DO UPDATE (or says neither), the row is OVERWRITTEN — so case 29(b) genuinely FAILS
    against an UPSERT implementation rather than passing vacuously.
    """

    def __init__(self, store, trades=None):
        self.store = store
        self.trades = trades or []
        self._clock = 0

    def execute(self, sql, params=None):
        s = " ".join(sql.split())

        if "INSERT INTO reconciliation_anchor" in s:
            bot_id, equity, unrealized, tl = params[0], params[1], params[2], params[3]
            exists = bot_id in self.store
            if exists and "DO NOTHING" in s.upper():
                return _FakeAnchorResult([])          # the pre-existing T0 STANDS
            self._clock += 1
            self.store[bot_id] = {
                "bot_id": bot_id,
                "anchored_at": f"2026-07-12T00:00:0{self._clock}+00:00",
                "equity": equity,
                "unrealized_pnl": unrealized,
                "trade_log_pnl": tl,
            }
            return _FakeAnchorResult([])

        if "FROM reconciliation_anchor" in s:
            row = self.store.get(params[0]) if params else None
            return _FakeAnchorResult([row] if row else [])

        if "FROM alpaca_trades" in s:
            rows = [r for r in self.trades if r["status"] in ("closed", "stopped", "target_hit")]
            if "pnl IS NULL OR pnl = 0" in s:
                rows = [r for r in rows if r["pnl"] is None or r["pnl"] == 0]
            elif "pnl IS NOT NULL AND pnl <> 0" in s:
                rows = [r for r in rows if r["pnl"] is not None and r["pnl"] != 0]
            elif "COUNT(*)" in s:
                rows = list(self.trades)          # the RAW count — no status filter
            return _FakeAnchorResult([{"n": len(rows)}] if "COUNT(*)" in s else rows)

        return _FakeAnchorResult([])


def _anchor_conn_factory(store, trades=None):
    @contextmanager
    def _conn():
        yield _FakeAnchorConn(store, trades)

    return _conn


# ── cases 27-28: the migration AND the schema MIRROR ────────────────────────

def test_migration_020_is_additive_and_idempotent():
    """Case 27. Additive, idempotent, no bot_id CHECK (migration 009 dropped it for C/D)."""
    migrations = _REPO / "dashboard" / "api" / "migrations"

    # POSITIVE CONTROL FIRST — the precedent migration really is there and in this shape.
    prior = (migrations / "017_reconciliation.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS reconciliation" in prior

    path = migrations / "020_reconciliation_anchor.sql"
    assert path.exists(), "migration 020 does not exist"
    sql = path.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS reconciliation_anchor" in sql
    for banned in ("DROP", "DELETE", "ALTER", "UPDATE", "CHECK"):
        assert banned not in sql.upper(), \
            f"migration 020 contains {banned} — it must be purely additive"


def test_the_schema_mirror_exists():
    """Case 28 — THE MIGRATION-ONLY-TABLE TRAP.

    src/db.py:61-66 `_bootstrap_schema()` executes src/db_schema.sql WHOLESALE. A
    migration-only table is absent from EVERY fresh-DB bootstrap and EVERY test DB — it
    would exist in PROD AND NOWHERE ELSE. Prior phases DID remember (reconciliation at
    db_schema.sql:215, runtime_heartbeat at :231).
    """
    schema = (_REPO / "src" / "db_schema.sql").read_text(encoding="utf-8")

    # POSITIVE CONTROL FIRST — the mirror precedent is real.
    assert "CREATE TABLE IF NOT EXISTS reconciliation" in schema
    assert "runtime_heartbeat" in schema

    assert "reconciliation_anchor" in schema, \
        "reconciliation_anchor is in the migration but NOT in the bootstrap schema — " \
        "it would exist in PROD AND NOWHERE ELSE"


# ── case 29: THE ANCHOR IS WRITTEN ONCE, NEVER UPSERTED ─────────────────────

def test_the_anchor_is_written_once_never_upserted(monkeypatch):
    """Case 29 — THE VACUOUS-GREEN TRAP.

    An UPSERT re-anchors T0 to "now" on EVERY run, permanently resetting the window to
    zero samples and making the entire check VACUOUSLY GREEN. That is the same class of
    self-defeating move as widening the tolerance. Re-anchoring must require an explicit,
    separate, human-authorized action.
    """
    from src import db

    # (a) STATIC — the writer says DO NOTHING and never DO UPDATE.
    fn = _DB_SRC[_DB_SRC.index("def write_reconciliation_anchor"):]
    fn = fn[:fn.index("\ndef ", 1)] if "\ndef " in fn[1:] else fn
    assert "DO NOTHING" in fn, "write_reconciliation_anchor is not ON CONFLICT DO NOTHING"
    assert "DO UPDATE" not in fn, \
        "write_reconciliation_anchor UPSERTs — it would re-anchor T0 on every run"

    # (b) BEHAVIORAL — a second, DIFFERENT write cannot move T0.
    store: dict = {}
    monkeypatch.setattr(db, "connection", _anchor_conn_factory(store))

    first = db.write_reconciliation_anchor("A", equity=100_000.0,
                                           unrealized_pnl=0.0, trade_log_pnl=0.0)
    second = db.write_reconciliation_anchor("A", equity=999_999.0,
                                            unrealized_pnl=42.0, trade_log_pnl=7.0)

    for key in ("anchored_at", "equity", "unrealized_pnl", "trade_log_pnl"):
        assert second[key] == first[key], f"the second write MOVED T0's {key}"
    assert second["equity"] == pytest.approx(100_000.0, abs=1e-9)


def test_get_reconciliation_anchor_is_none_when_never_anchored(monkeypatch):
    """`None` is a real, reportable state (the CLI emits NO_ANCHOR) — not an error to be
    papered over with a default."""
    from src import db

    monkeypatch.setattr(db, "connection", _anchor_conn_factory({}))
    assert db.get_reconciliation_anchor("A") is None


# ── case 30: ONE ALPACA ACCOUNT PER BOT ─────────────────────────────────────

def test_the_anchor_uses_per_bot_alpaca_keys(monkeypatch):
    """Case 30. ensure_anchor sources its client via `_client_for_bot` — NEVER a bare
    shared ALPACA_API_KEY. One account per bot is a HARD RULE."""
    from src import db, reconciliation

    # STATIC: no bare key read anywhere in the module.
    assert 'os.environ.get("ALPACA_API_KEY")' not in _RECON_SRC
    assert "ALPACA_API_KEY_" in _RECON_SRC, "positive control failed — the suffixed read is gone"

    # BEHAVIORAL: a keyless bot RAISES rather than silently anchoring against another
    # bot's account.
    monkeypatch.delenv("ALPACA_API_KEY_Z", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY_Z", raising=False)
    monkeypatch.setattr(db, "connection", _anchor_conn_factory({}))

    with pytest.raises(ValueError):
        reconciliation._client_for_bot("Z")


def test_ensure_anchor_returns_an_existing_anchor_unchanged(monkeypatch):
    """ensure_anchor is READ-OR-CREATE. An EXISTING anchor is NEVER MOVED."""
    from src import db, reconciliation

    store = {"A": {
        "bot_id": "A", "anchored_at": "2026-07-12T00:00:00+00:00",
        "equity": 100_000.0, "unrealized_pnl": 0.0, "trade_log_pnl": 0.0,
    }}
    monkeypatch.setattr(db, "connection", _anchor_conn_factory(store))

    class _Client:
        def get_account(self):
            raise AssertionError("ensure_anchor must NOT re-snapshot an existing anchor")

        def get_positions(self):
            raise AssertionError("ensure_anchor must NOT re-snapshot an existing anchor")

    anchor = reconciliation.ensure_anchor("A", _Client())
    assert anchor["equity"] == pytest.approx(100_000.0, abs=1e-9)
    assert anchor["anchored_at"] == "2026-07-12T00:00:00+00:00"


def test_ensure_anchor_does_not_write_under_readonly(monkeypatch):
    """Under AIPW_DB_READONLY it must NOT attempt the INSERT — Postgres would refuse it
    with SQLSTATE 25006. It reads, and reports absence honestly (NO_ANCHOR)."""
    from src import db, reconciliation

    monkeypatch.setenv("AIPW_DB_READONLY", "1")
    store: dict = {}
    monkeypatch.setattr(db, "connection", _anchor_conn_factory(store))

    class _Client:
        def get_account(self):
            return {"equity": 100_000.0}

        def get_positions(self):
            return []

    assert reconciliation.ensure_anchor("A", _Client()) is None
    assert store == {}, "a write was attempted under AIPW_DB_READONLY"

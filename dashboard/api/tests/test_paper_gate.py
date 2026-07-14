# dashboard/api/tests/test_paper_gate.py
"""Phase 20 — G2: the PAPER GATE, the gate that guards LIVE TRADING (cases 9-11).

`dashboard/api/routes/settings.py:36` is a bare
``SELECT COUNT(*) AS n FROM alpaca_trades WHERE bot_id IN (...)`` — NO status filter,
NO P&L filter — surfaced at :192 as ``paper_trades_completed`` against the 50-trade
gate. It counts ``submitted`` rows, ``rejected`` gate-blocks and canceled 0-fill
entries: rows that NEVER BECAME A POSITION. ``src/bot_thread.py:362,376,382`` provably
writes them.

**A gate satisfied by rows that were never trades is not a gate.** And until this file
existed, NO TEST ASSERTED OTHERWISE — which is exactly why the bug shipped.

THE GATE WILL READ WORSE AFTER THE FIX. That is the INTENDED outcome and it is NOT to
be tuned back. Making the gate HONEST is not the same as OPENING it: `paper_trades_target`
stays 50, `win_rate_target` stays 40.0, `mode` stays "paper".

NO LIVE MAGNITUDE IS ASSERTED HERE. RESEARCH R1 REFUTED the "655 -> ~260" arithmetic:
`dashboard/api/db.py:19` KNOWN_BOTS=("A","B","C","D") over an UNFILTERED COUNT(*), versus
Phase 17's 655 *position-closed* rows for bots A/B/C/**E** — a different bot set AND a
different status filter. The BUG is established by the code; the MAGNITUDE is established
by nothing. `scripts/e2e_verify.py` MEASURES the before/after per bot.

Zero network, zero Postgres, zero skips.
"""
import contextlib
import os
import pathlib
import sys
from types import SimpleNamespace

# Same import shim as dashboard/api/tests/test_routes.py:15.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_API = pathlib.Path(__file__).resolve().parents[1]


def _settings_src() -> str:
    return (_API / "routes" / "settings.py").read_text(encoding="utf-8")


# ── the SQL-honouring fake connection (the tests/test_db.py:103-126 idiom) ────

_TERMINAL = ("closed", "stopped", "target_hit")


def _row(pnl, status="closed"):
    return {"pnl": pnl, "status": status}


def _fixture_rows():
    """9 rows. Exactly THREE of them are resolved trades.

    3 x closed with real pnl        -> RESOLVED  (+10, -5, +20)
    1 x submitted, pnl NULL         -> never became a POSITION AT ALL
    1 x rejected,  pnl 0            -> never became a POSITION AT ALL (a gate block)
    1 x open,      pnl NULL         -> still live
    2 x closed,    pnl 0.0          -> the historical sentinel shape
    1 x closed,    pnl NULL         -> unresolvable
    """
    return [
        _row(10.0), _row(-5.0), _row(20.0),
        _row(None, "submitted"),
        _row(0.0, "rejected"),
        _row(None, "open"),
        _row(0.0), _row(0.0),
        _row(None),
    ]


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Honours the SQL it is handed — it does not merely replay a canned answer.

    The status / pnl clauses are applied ONLY when the query actually asks for them,
    so on current `main` the bare COUNT(*) really does return 9 and the RESOLVED query
    really does return 3. A test that passes here proves the SQL changed; it cannot
    pass vacuously.
    """

    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        if "FROM bots" in sql:
            return _FakeResult([{
                "bot_id": "A", "starting_equity": 100000.0, "status": "stopped",
                "kelly_fraction": 0.25, "min_confluence": 4,
            }])
        if "FROM signals" in sql:
            return _FakeResult([{"n": 0}])
        if "FROM alpaca_trades" not in sql:
            return _FakeResult([])          # SELECT 1 / heartbeat probes

        rows = list(self.rows)
        if "status IN" in sql:
            rows = [r for r in rows if r["status"] in _TERMINAL]
        if "pnl IS NULL OR pnl = 0" in sql:
            rows = [r for r in rows if r["pnl"] is None or r["pnl"] == 0]
        else:
            if "pnl IS NOT NULL" in sql:
                rows = [r for r in rows if r["pnl"] is not None]
            if "pnl <> 0" in sql:
                # SQL semantics: NULL <> 0 is NULL, so a NULL row fails this too.
                rows = [r for r in rows if r["pnl"] is not None and r["pnl"] != 0]

        if "COUNT(*)" in sql:
            # Serve BOTH spellings: the current `AS n` and any honest rename of the
            # REPORTED total (e.g. `AS total`). The fence in case 10 is what pins that
            # the bare count is no longer the GATE query.
            n = len(rows)
            return _FakeResult([{"n": n, "total": n}])
        if "SELECT timestamp" in sql:
            return _FakeResult([{"timestamp": "2026-07-01T00:00:00+00:00"}])
        return _FakeResult(rows)


# ── case 9 — BEHAVIORAL, through the REAL route ──────────────────────────────

def test_non_trade_rows_are_excluded_from_the_paper_gate(monkeypatch):
    """Case 9. The REAL `get_settings` route, driven against a SQL-honouring fake.

    9 rows in the log. THREE of them are trades. The gate must read 3.

    RED on main: the bare COUNT(*) returns **9**. Six of those nine never became a
    resolved trade, and two of them (`submitted`, `rejected`) never became a POSITION
    at all — yet all nine count toward the 50-trade gate that guards LIVE TRADING.
    """
    import routes.settings as settings

    @contextlib.contextmanager
    def _fake_db():
        yield _FakeConn(_fixture_rows())

    monkeypatch.setattr(settings, "get_db", _fake_db)
    monkeypatch.setattr(settings, "get_heartbeat", lambda conn: None)
    monkeypatch.setattr(settings, "get_account_health", lambda: "ok")

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    envelope = settings.get_settings(request, bot="A")
    data = envelope.data

    assert data.paper_trades_completed == 3, (
        "the paper gate counted rows that were never trades — submitted, rejected, "
        "open, and the pnl=0.0/NULL sentinels"
    )
    # The gate was made HONEST, not OPEN.
    assert data.paper_trades_target == 50
    assert data.win_rate_target == 40.0
    assert data.mode == "paper"


# ── case 10 — STATIC FENCE (the test_routes.py:224 idiom) ────────────────────

def test_the_bare_count_star_never_returns():
    """Case 10. The bare COUNT(*) must never again BE the gate figure.

    RED on main: settings.py:36 is exactly this string, and :192 feeds it straight to
    `paper_trades_completed`.
    """
    src = _settings_src()

    # POSITIVE CONTROL FIRST — the fence cannot pass on an empty or renamed file.
    assert "paper_trades_completed=" in src, \
        "positive control failed — the gate readout moved or the file is empty"

    assert "SELECT COUNT(*) AS n FROM alpaca_trades" not in src, \
        "the bare, unfiltered COUNT(*) is still the paper-gate query"
    assert "paper_trades_completed=total_trades" not in src, \
        "the gate is still fed the raw row count"


# ── case 11 — the gate is made HONEST, not UNLOCKED ─────────────────────────

def test_the_gate_is_made_honest_not_unlocked():
    """Case 11. The canonical RESOLVED predicate drives the gate; no target moved."""
    src = _settings_src()
    assert "alpaca_trades" in src, "positive control failed — the file is empty"

    # THE canonical predicate (src/db.py:95 is_resolved). Not a sixth spelling.
    assert "pnl IS NOT NULL AND pnl <> 0" in src
    assert "status IN ('closed', 'stopped', 'target_hit')" in src

    # Making the gate honest is NOT the same as opening it. The number will read
    # WORSE. That is the intended outcome of this phase and it is NOT to be tuned back.
    assert "paper_trades_target=50" in src, "the 50-trade paper gate moved"
    assert "win_rate_target=40.0" in src, "the 40% win-rate gate moved"
    assert 'mode="paper"' in src, "mode is no longer pinned to paper"

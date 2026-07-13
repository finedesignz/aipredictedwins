"""Phase 18 — the rollout is CONFIG-ONLY, and Kelly may only go DOWN
(VALIDATION cases 26-29, plus 28b / 28c / 28d).

Cases 28 / 28b / 28c / 28d are closed by Plan 18-07 (the API + seed + read-side
Kelly clamps). 18-07 is HELD for explicit human authorization because its later
tasks write to the PROD bots row, so those four cases are marked xfail(strict)
here: they FAIL today, they are recorded, and the moment 18-07 lands they flip
green (a strict xfail that starts passing is itself a failure, so this cannot rot).
"""
import os
import pathlib
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping rollout API tests")

_deferred_to_18_07 = pytest.mark.xfail(
    reason="closed by Plan 18-07 (held for human authorization — it writes the prod bots row)",
    strict=True,
)


def _sig(symbol, confluence=4, rsi=50.0):
    return types.SimpleNamespace(
        symbol=symbol, confluence_score=confluence, rsi_value=rsi,
        trend_4h="unknown", short_score=0, price=100.0,
    )


def _row(**over):
    row = {
        "bot_id": "A", "label": "Agent A",
        "alpaca_api_key": "k", "alpaca_secret_key": "s",
        "min_confluence": 3, "kelly_fraction": 0.25,
    }
    row.update(over)
    return row


# --- case 26: the quarantine ships as DATA (zero src/ diff required)

def test_quarantine_is_config_only():
    from src.bot_config import BotConfig
    from src.bot_thread import select_long_candidates

    cfg = BotConfig.from_row(_row(
        quarantined_symbols="BTC/USD,ETH/USD,TRUMP/USD,FIL/USD,ARB/USD"))
    assert cfg.quarantined == ["BTC/USD", "ETH/USD", "TRUMP/USD", "FIL/USD", "ARB/USD"]

    picked = select_long_candidates(
        [_sig("BTC/USD"), _sig("SOL/USD")], cfg, open_symbols=set(),
        recent_loss_symbols=set())
    syms = [s.symbol for s in picked]
    assert "BTC/USD" not in syms
    assert "SOL/USD" in syms


# --- case 27 / 28: the rollout PUT

@_needs_db
def test_put_bots_accepts_all_three_knobs():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    import sys
    sys.path.insert(0, str(_ROOT / "dashboard" / "api"))
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.put("/api/bots/A", json={
        "min_confluence": 4, "kelly_fraction": 0.20,
        "quarantined_symbols": "BTC/USD,ETH/USD"})
    assert resp.status_code == 200


@_deferred_to_18_07
def test_kelly_above_ceiling_cannot_be_rolled_out():
    """case 28 — the API-side mirror of the CLI ceiling."""
    import pydantic
    import sys
    sys.path.insert(0, str(_ROOT / "dashboard" / "api"))
    from models import BotUpdate

    BotUpdate(kelly_fraction=0.25)
    with pytest.raises(pydantic.ValidationError):
        BotUpdate(kelly_fraction=0.50)


@_deferred_to_18_07
def test_kelly_ceiling_on_bot_create():
    """case 28b — BotCreate/BotFull are unbounded today: a bot can be CREATED at 0.50."""
    import pydantic
    import sys
    sys.path.insert(0, str(_ROOT / "dashboard" / "api"))
    from models import BotCreate

    BotCreate(bot_id="Z", label="Z", alpaca_api_key="k", alpaca_secret_key="s",
              kelly_fraction=0.25)
    with pytest.raises(pydantic.ValidationError):
        BotCreate(bot_id="Z", label="Z", alpaca_api_key="k", alpaca_secret_key="s",
                  kelly_fraction=0.50)


@_deferred_to_18_07
def test_seed_cannot_restore_bot_b_at_half_kelly(monkeypatch):
    """case 28c — seed_bots.py writes by RAW SQL and never sees pydantic."""
    import sys
    sys.path.insert(0, str(_ROOT / "dashboard" / "api"))
    import importlib
    import seed_bots

    monkeypatch.delenv("BOT_B_KELLY", raising=False)
    importlib.reload(seed_bots)
    b = [x for x in seed_bots.build_bots() if x["bot_id"] == "B"][0]
    assert b["kelly_fraction"] == 0.25

    monkeypatch.setenv("BOT_B_KELLY", "0.50")
    importlib.reload(seed_bots)
    b = [x for x in seed_bots.build_bots() if x["bot_id"] == "B"][0]
    assert b["kelly_fraction"] <= 0.25


@_deferred_to_18_07
def test_kelly_clamped_on_read():
    """case 28d — the READ-side clamp: a row written BEFORE the bounds existed
    (Bot B's live 0.50) must be clamped at from_row, not merely rejected at write."""
    from src.bot_config import BotConfig
    assert BotConfig.from_row(_row(kelly_fraction=0.50)).kelly_fraction == 0.25


# --- case 29: no prod write anywhere (static fence + SELF-TEST)

_WRITE = ("INSERT", "UPDATE ", "DELETE ", "submit_order", "place_order")


def _writes(text: str) -> bool:
    return any(w in text for w in _WRITE)


def test_no_prod_write_anywhere():
    # SELF-TEST: the detector must FIRE on a known writer (src/db.py:101-122).
    db_src = (_ROOT / "src" / "db.py").read_text(encoding="utf-8")
    start = db_src.index("def update_alpaca_trade")
    end = db_src.index("def get_open_alpaca_positions")
    assert _writes(db_src[start:end]), "the write detector does not fire — it is vacuous"

    # No test may POINT the pool at a database that is not TEST_DATABASE_URL.
    # Read-only gating (`skipif(not os.environ.get("DATABASE_URL"))`) is fine; what is
    # forbidden is SETTING DATABASE_URL to anything but the test database.
    scanned = 0
    me = pathlib.Path(__file__).resolve()
    for path in sorted((_ROOT / "tests").rglob("*.py")):
        if path.resolve() == me:   # the detector's own source is not a subject
            continue
        src = path.read_text(encoding="utf-8")
        scanned += 1
        for ln in src.splitlines():
            if "DATABASE_URL" not in ln:
                continue
            sets_it = ('setenv("DATABASE_URL"' in ln
                       or 'environ["DATABASE_URL"] =' in ln.replace("'", '"'))
            if not sets_it:
                continue
            # The value must come from TEST_DATABASE_URL — directly on the line, or
            # via a local bound to it. A literal connection string is never allowed.
            assert "://" not in ln, f"{path.name}: hardcodes a connection string"
            assert "TEST_DATABASE_URL" in src, \
                f"{path.name}: sets DATABASE_URL without sourcing TEST_DATABASE_URL"

    for path in sorted((_ROOT / "scripts").glob("sweep*.py")):
        src = path.read_text(encoding="utf-8")
        scanned += 1
        assert not _writes(src), f"{path.name}: has a write surface"
        for flag in ("--apply", "--write", "--fix"):
            assert flag not in src, f"{path.name}: has a {flag} surface"

    assert scanned > 0

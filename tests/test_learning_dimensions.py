"""Phase 8 — intraday learning dimensions.

Unit tests for the pure entry-dimension helpers + the additive migration 014
text contract. No DB required (string-level idempotency assertion).
"""

from pathlib import Path

import pytest

from src.learning_loop import _hold_minutes
from src.trade_memory import time_of_day_bucket, volatility_regime


# --- time_of_day_bucket ----------------------------------------------------

@pytest.mark.parametrize("iso,expected", [
    ("2026-06-08T02:00:00+00:00", "asia"),
    ("2026-06-08T09:00:00+00:00", "eu"),
    ("2026-06-08T14:00:00+00:00", "us_am"),
    ("2026-06-08T19:00:00+00:00", "us_pm"),
    ("2026-06-08T23:00:00+00:00", "off"),
])
def test_time_of_day_bucket_sessions(iso, expected):
    assert time_of_day_bucket(iso) == expected


def test_time_of_day_bucket_none_and_garbage():
    assert time_of_day_bucket(None) == "unknown"
    assert time_of_day_bucket("garbage") == "unknown"


# --- volatility_regime -----------------------------------------------------

@pytest.mark.parametrize("atr,price,expected", [
    (0.5, 100.0, "low"),
    (1.5, 100.0, "med"),
    (3.0, 100.0, "high"),
    (0.0, 100.0, "unknown"),
    (1.0, 0.0, "unknown"),
])
def test_volatility_regime(atr, price, expected):
    assert volatility_regime(atr, price) == expected


# --- migration 014 text contract (string-level idempotency) ----------------

def test_migration_014_additive_columns():
    mig = Path("dashboard/api/migrations/014_intraday_learning_dims.sql")
    text = mig.read_text()
    for col in ("time_of_day_bucket", "hold_minutes", "volatility_regime"):
        assert col in text
    assert text.count("ADD COLUMN IF NOT EXISTS") >= 3
    # additive only — never destructive
    assert "DROP COLUMN" not in text.upper()
    # no NOT NULL on the ADD COLUMN statements (nullable, no backfill)
    add_stmts = [ln for ln in text.splitlines()
                 if ln.strip().upper().startswith("ALTER TABLE")
                 and "ADD COLUMN" in ln.upper()]
    assert add_stmts
    assert all("NOT NULL" not in ln.upper() for ln in add_stmts)


def test_db_schema_mirrors_dimension_columns():
    text = Path("src/db_schema.sql").read_text()
    for col in ("time_of_day_bucket", "hold_minutes", "volatility_regime"):
        assert col in text


# --- entry dimension wiring (record sites carry atr_value) -----------------

def test_record_dimensions_thin_dict_is_unknown():
    # orchestrator thin path without atr_value -> regime "unknown" (Pitfall 3)
    assert volatility_regime(0.0, 100.0) == "unknown"


def test_all_record_sites_pass_atr_value():
    src = Path("src/bot_thread.py").read_text()
    orch = Path("src/alpaca_orchestrator.py").read_text()
    # 2 record dicts in each runtime, each must carry atr_value
    assert src.count('"atr_value": signal.atr_value') == 2
    assert orch.count('"atr_value": signal.atr_value') == 2


def test_record_trade_context_persists_entry_dimensions():
    # INSERT must list both entry dimension columns
    tm = Path("src/trade_memory.py").read_text()
    assert "time_of_day_bucket, volatility_regime, outcome" in tm


# --- hold_minutes at close -------------------------------------------------

def test_hold_minutes_basic():
    assert _hold_minutes(
        "2026-06-08T14:00:00+00:00", "2026-06-08T15:30:00+00:00"
    ) == 90.0


def test_hold_minutes_none_and_bad():
    assert _hold_minutes(None, "2026-06-08T15:30:00+00:00") is None
    assert _hold_minutes("2026-06-08T14:00:00+00:00", None) is None
    assert _hold_minutes("bad", "bad") is None


def test_update_trade_outcome_back_compat_kwarg():
    import inspect
    from src.trade_memory import TradeMemory
    sig = inspect.signature(TradeMemory.update_trade_outcome)
    assert sig.parameters["hold_minutes"].default is None

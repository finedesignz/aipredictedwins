"""Phase 8 — intraday learning dimensions.

Unit tests for the pure entry-dimension helpers + the additive migration 014
text contract. No DB required (string-level idempotency assertion).
"""

from pathlib import Path

import pytest

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
    assert "NOT NULL" not in text.upper()


def test_db_schema_mirrors_dimension_columns():
    text = Path("src/db_schema.sql").read_text()
    for col in ("time_of_day_bucket", "hold_minutes", "volatility_regime"):
        assert col in text

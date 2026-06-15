"""
BOT-03: seed_bots must build a bot_id='D' row only when the suffixed
ALPACA_API_KEY_D / ALPACA_SECRET_KEY_D env vars are present.

Tests the DB-free build_bots() assembly (no psycopg.connect involved).
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "api")
)

import seed_bots  # noqa: E402  (dashboard/api/seed_bots.py)

_ALL_KEYS = [
    f"ALPACA_API_KEY_{x}" for x in ("A", "B", "C", "D")
] + [f"ALPACA_SECRET_KEY_{x}" for x in ("A", "B", "C", "D")]


def _clear(monkeypatch):
    for k in _ALL_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_d_row_built_when_env_present(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY_D", "pk_d")
    monkeypatch.setenv("ALPACA_SECRET_KEY_D", "sk_d")
    bots = seed_bots.build_bots()
    d = [b for b in bots if b["bot_id"] == "D"]
    assert len(d) == 1
    assert d[0]["label"] == "Agent D — Daytrade"
    assert d[0]["asset_class"] == "crypto"
    assert d[0]["kelly_fraction"] == 0.25


def test_no_d_row_when_env_absent(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY_A", "pk_a")
    monkeypatch.setenv("ALPACA_SECRET_KEY_A", "sk_a")
    bots = seed_bots.build_bots()
    assert all(b["bot_id"] != "D" for b in bots)


def test_d_label_overridable(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ALPACA_API_KEY_D", "pk_d")
    monkeypatch.setenv("ALPACA_SECRET_KEY_D", "sk_d")
    monkeypatch.setenv("BOT_D_LABEL", "Custom D")
    bots = seed_bots.build_bots()
    assert bots[0]["label"] == "Custom D"

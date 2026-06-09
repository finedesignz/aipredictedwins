"""Phase 8 — shadow gate (LEARN-06)."""

import pytest

from src.trade_memory import should_enforce_learning


def test_count_closed_trades_injectable(fake_memory):
    assert fake_memory(closed_count=0).count_closed_trades() == 0
    assert fake_memory(closed_count=29).count_closed_trades() == 29
    assert fake_memory(closed_count=30).count_closed_trades() == 30


def test_shadow_below_threshold(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.delenv("LEARNING_SHADOW_UNTIL_TRADES", raising=False)
    assert should_enforce_learning(fake_memory(closed_count=29), "A") is False


def test_enforce_at_threshold(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.delenv("LEARNING_SHADOW_UNTIL_TRADES", raising=False)
    assert should_enforce_learning(fake_memory(closed_count=30), "A") is True


def test_explicit_zero_forces_shadow(fake_memory, monkeypatch):
    monkeypatch.setenv("LEARNING_ENFORCE", "0")
    # well above threshold but explicit 0 wins (D-06 precedence)
    assert should_enforce_learning(fake_memory(closed_count=999), "A") is False


def test_shadow_until_env_override(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.setenv("LEARNING_SHADOW_UNTIL_TRADES", "5")
    assert should_enforce_learning(fake_memory(closed_count=4), "A") is False
    assert should_enforce_learning(fake_memory(closed_count=5), "A") is True


def test_shadow_until_arg_overrides_env(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.setenv("LEARNING_SHADOW_UNTIL_TRADES", "100")
    assert should_enforce_learning(fake_memory(closed_count=10), "A", shadow_until=10) is True


def test_memory_none_noop(monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    assert should_enforce_learning(None, "A") is False

"""Phase 8 — shadow gate (LEARN-06)."""

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


def _advice_consume(enforce, advice):
    """Mirror of the runtime seam contract (veto + scale under the gate)."""
    adj = 1.0
    skip = False
    if not advice["should_trade"]:
        if enforce:
            skip = True
    elif enforce:
        adj = advice.get("confidence_adjustment", 1.0)
    return skip, adj


def test_shadow_below_threshold_no_veto_no_scale(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.delenv("LEARNING_SHADOW_UNTIL_TRADES", raising=False)
    mem = fake_memory(closed_count=5)  # below default 30 -> shadow
    enforce = should_enforce_learning(mem, "A")
    assert enforce is False
    # veto advice in shadow -> not skipped
    skip, adj = _advice_consume(enforce, {"should_trade": False, "confidence_adjustment": 0.0})
    assert skip is False and adj == 1.0
    # scale advice in shadow -> adj stays 1.0
    skip, adj = _advice_consume(enforce, {"should_trade": True, "confidence_adjustment": 0.5})
    assert adj == 1.0


def test_enforce_above_threshold_applies(fake_memory, monkeypatch):
    monkeypatch.delenv("LEARNING_ENFORCE", raising=False)
    monkeypatch.delenv("LEARNING_SHADOW_UNTIL_TRADES", raising=False)
    mem = fake_memory(closed_count=30)
    enforce = should_enforce_learning(mem, "A")
    assert enforce is True
    skip, adj = _advice_consume(enforce, {"should_trade": False, "confidence_adjustment": 0.0})
    assert skip is True
    skip, adj = _advice_consume(enforce, {"should_trade": True, "confidence_adjustment": 0.5})
    assert adj == 0.5

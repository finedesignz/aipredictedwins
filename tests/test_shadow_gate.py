"""Phase 8 — shadow gate (LEARN-06).

Wave-0 scaffold: assert FakeTradeMemory.count_closed_trades is injectable.
Full should_enforce_learning behavior tests are added in 08-03.
"""


def test_count_closed_trades_injectable(fake_memory):
    assert fake_memory(closed_count=0).count_closed_trades() == 0
    assert fake_memory(closed_count=29).count_closed_trades() == 29
    assert fake_memory(closed_count=30).count_closed_trades() == 30

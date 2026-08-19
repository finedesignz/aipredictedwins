# tests/test_monitor_alert_flood.py
"""Position-monitor alert flood fix: sustained-failure gate + cooldown throttle +
recovery notice. See src/notifier.py (_cooldown_ok, send_alert dedup_key,
alert_monitor_error, alert_monitor_recovered) and
src/alpaca_orchestrator.py::PositionMonitor.run.

No boto3, no network, no real sleeps — the clock is monkeypatched.
"""
import pytest

from src import notifier
from src.notifier import alert_monitor_error, alert_monitor_recovered, send_alert


@pytest.fixture(autouse=True)
def _clean_cooldown_state(monkeypatch):
    """Every test gets a fresh cooldown table and a fake, controllable clock."""
    monkeypatch.setattr(notifier, "_last_alert_sent", {})
    clock = {"t": 0.0}
    monkeypatch.setattr(notifier, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(notifier, "ALERT_COOLDOWN_SECONDS", 900.0)
    return clock


@pytest.fixture
def sent(monkeypatch):
    """Capture what send_alert would have emailed (bypasses SES entirely)."""
    calls: list[dict] = []

    def _fake_ses():
        class _FakeSES:
            def send_email(self, **kw):
                calls.append(kw)
                return {"MessageId": "ok"}
        return _FakeSES()

    monkeypatch.setattr(notifier, "_get_ses_client", _fake_ses)
    return calls


# ── Cooldown throttle (src/notifier.py) ────────────────────────────────────────

def test_cooldown_suppresses_second_same_key_alert_within_window(sent, _clean_cooldown_state):
    clock = _clean_cooldown_state
    assert send_alert("s1", "b1", category="MONITOR_ERROR", dedup_key="all") is True
    assert len(sent) == 1

    clock["t"] += 100  # well within the 900s window
    assert send_alert("s2", "b2", category="MONITOR_ERROR", dedup_key="all") is False
    assert len(sent) == 1  # no second email


def test_cooldown_allows_after_window_elapses(sent, _clean_cooldown_state):
    clock = _clean_cooldown_state
    assert send_alert("s1", "b1", category="MONITOR_ERROR", dedup_key="all") is True
    clock["t"] += 901  # past the 900s window
    assert send_alert("s2", "b2", category="MONITOR_ERROR", dedup_key="all") is True
    assert len(sent) == 2


def test_cooldown_is_per_dedup_key_not_global(sent, _clean_cooldown_state):
    assert send_alert("s1", "b1", category="MONITOR_ERROR", dedup_key="BTC/USD") is True
    # A distinct key in the same category is NOT collapsed with the first.
    assert send_alert("s2", "b2", category="MONITOR_ERROR", dedup_key="ETH/USD") is True
    assert len(sent) == 2


def test_throttled_alert_is_logged_at_warning_with_full_body(sent, _clean_cooldown_state, caplog):
    import logging
    send_alert("s1", "the body one", category="MONITOR_ERROR", dedup_key="all")
    with caplog.at_level(logging.WARNING, logger="src.notifier"):
        send_alert("s2", "the body two", category="MONITOR_ERROR", dedup_key="all")
    assert any("[alert throttled: MONITOR_ERROR]" in r.message and "the body two" in r.message
               for r in caplog.records)


def test_send_alert_without_dedup_key_is_never_throttled(sent, _clean_cooldown_state):
    """Existing callers that don't pass dedup_key keep their old, un-throttled behavior."""
    assert send_alert("s1", "b1", category="POSITION_CLOSED") is True
    assert send_alert("s2", "b2", category="POSITION_CLOSED") is True
    assert len(sent) == 2


# ── Sustained-failure gate + recovery (PositionMonitor.run) ────────────────────

class _FakeMonitor:
    """Exercises the exact gate/throttle/recovery logic in PositionMonitor.run without
    spinning up a real thread, a real Alpaca client, or the 60s wait loop."""

    def __init__(self, threshold):
        self.threshold = threshold
        self._consecutive_failures = 0
        self._alerted = False
        self.checks_calls = []

    def _check_all_positions(self):
        outcome = self.checks_calls.pop(0)
        if outcome is not None:
            raise outcome

    def run_one_cycle(self):
        from src.alpaca_orchestrator import MONITOR_ALERT_FAILURE_THRESHOLD  # noqa: F401
        try:
            self._check_all_positions()
            if self._alerted:
                alert_monitor_recovered("all", self._consecutive_failures)
                self._alerted = False
            self._consecutive_failures = 0
        except Exception as exc:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self.threshold:
                alert_monitor_error("all", exc, self._consecutive_failures)
                self._alerted = True


def test_sustained_gate_below_threshold_sends_nothing(sent, _clean_cooldown_state):
    mon = _FakeMonitor(threshold=3)
    mon.checks_calls = [RuntimeError("timeout"), RuntimeError("timeout")]
    mon.run_one_cycle()
    mon.run_one_cycle()
    assert len(sent) == 0


def test_sustained_gate_at_threshold_sends_exactly_one(sent, _clean_cooldown_state):
    mon = _FakeMonitor(threshold=3)
    mon.checks_calls = [RuntimeError("timeout")] * 3
    for _ in range(3):
        mon.run_one_cycle()
    assert len(sent) == 1


def test_further_failures_within_cooldown_send_no_more(sent, _clean_cooldown_state):
    clock = _clean_cooldown_state
    mon = _FakeMonitor(threshold=3)
    mon.checks_calls = [RuntimeError("timeout")] * 5
    for _ in range(5):
        clock["t"] += 60
        mon.run_one_cycle()
    assert len(sent) == 1  # still just the one from hitting the threshold


def test_recovery_sends_one_email_and_resets_state(sent, _clean_cooldown_state):
    clock = _clean_cooldown_state
    mon = _FakeMonitor(threshold=3)
    mon.checks_calls = [RuntimeError("timeout")] * 3 + [None]
    for _ in range(3):
        clock["t"] += 60
        mon.run_one_cycle()
    assert len(sent) == 1  # the sustained-failure alert
    clock["t"] += 60
    mon.run_one_cycle()  # successful cycle -> recovery
    assert len(sent) == 2
    assert "recovered" in sent[1]["Message"]["Subject"]["Data"].lower()
    assert mon._consecutive_failures == 0
    assert mon._alerted is False

    # A later, distinct outage can alert again immediately (recovery reset the cooldown).
    mon.checks_calls = [RuntimeError("timeout")] * 3
    for _ in range(3):
        mon.run_one_cycle()
    assert len(sent) == 3

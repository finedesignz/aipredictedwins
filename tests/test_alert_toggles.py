# tests/test_alert_toggles.py
"""Per-category alert toggles — the mute must be VISIBLE, SCOPED, and FAIL-SAFE.

Alert email became spam because RECONCILIATION fires hourly forever on a permanent,
known, unrepairable level offset. The fix is a config-driven mute — NOT a deletion, and
NOT a mute that hides itself:

  * The gate is at the SEND step, never the DETECT step. `_check_bots_down` still runs.
  * A suppressed alert is LOGGED AT WARNING WITH ITS FULL BODY. Silence about silence is
    the exact failure Phase 19 exists to kill.
  * Every switch DEFAULTS ON. The absence of config can never mute a safety alert — and
    `test_bots_down_defaults_on` pins that for ALL BOTS DOWN specifically, so nobody can
    quietly default-mute the one alert that four dead bots depended on.

No boto3. No network. No DB. No email is ever sent.
"""
import logging

import pytest

from src import notifier
from src.notifier import alerts_enabled, alerts_suppressed

_SWITCHES = ("ALERTS_ENABLED",) + tuple(
    f"ALERT_{c}_ENABLED" for c in notifier.ALERT_CATEGORIES
)

# The categories the operator can address by name, per the spec.
_REQUIRED = ("BOTS_DOWN", "BOT_DEATH", "BOT_MISCONFIGURED", "RECONCILIATION",
             "TRADE_SILENCE", "MANAGER_NEVER_STARTED")


@pytest.fixture
def clean_env(monkeypatch):
    """No alert env vars set at all — the DEFAULT, i.e. the production fail-safe."""
    for v in _SWITCHES:
        monkeypatch.delenv(v, raising=False)


@pytest.fixture
def spy_ses(monkeypatch):
    """Capture what would have been emailed. Nothing leaves the process."""
    sent: list[dict] = []

    class _FakeSES:
        def send_email(self, **kw):
            sent.append(kw)
            return {"MessageId": "ok"}

    monkeypatch.setattr(notifier, "_get_ses_client", lambda: _FakeSES())
    return sent


# ── Defaults: absence of config must never mute ───────────────────────────────

def test_default_everything_sends(clean_env, spy_ses):
    for cat in notifier.ALERT_CATEGORIES:
        assert alerts_enabled(cat) is True, f"{cat} must default ON"
        assert notifier.send_alert("subj", "body", category=cat) is True
    assert len(spy_ses) == len(notifier.ALERT_CATEGORIES)
    assert alerts_suppressed() == []


def test_bots_down_defaults_on(clean_env, spy_ses):
    """THE PIN. ALL BOTS DOWN is the alert whose silence let four dead bots sit for weeks.

    Its default must be ON, and it must remain ON even while the noisy categories are
    muted — muting the spam must never take the safety alert with it.
    """
    assert alerts_enabled("BOTS_DOWN") is True
    assert "BOTS_DOWN" not in alerts_suppressed()
    assert notifier.alert_all_bots_down(4, 72.0) is True
    assert "ALL BOTS DOWN" in spy_ses[0]["Message"]["Subject"]["Data"]


# ── Global kill switch ────────────────────────────────────────────────────────

def test_global_off_sends_nothing_but_logs_the_body(clean_env, spy_ses, monkeypatch, caplog):
    monkeypatch.setenv("ALERTS_ENABLED", "0")
    caplog.set_level(logging.WARNING, logger=notifier.__name__)

    for cat in notifier.ALERT_CATEGORIES:
        assert alerts_enabled(cat) is False
        assert notifier.send_alert(f"subj-{cat}", f"body-{cat}", category=cat) is False

    assert spy_ses == [], "global kill switch must send NO email"

    blob = caplog.text
    for cat in notifier.ALERT_CATEGORIES:
        # Suppression is never silent: prefix + subject + FULL BODY all reach the logs.
        assert f"[alert suppressed: {cat}]" in blob
        assert f"subj-{cat}" in blob
        assert f"body-{cat}" in blob
    assert all(r.levelno == logging.WARNING for r in caplog.records)


def test_global_off_beats_per_category_on(clean_env, spy_ses, monkeypatch):
    """Precedence: the global switch off => everything off, whatever the per-category says."""
    monkeypatch.setenv("ALERTS_ENABLED", "0")
    monkeypatch.setenv("ALERT_BOTS_DOWN_ENABLED", "1")
    assert alerts_enabled("BOTS_DOWN") is False
    assert notifier.alert_all_bots_down(4, 1.0) is False
    assert spy_ses == []


# ── Per-category: scoped mute — the others STILL SEND ─────────────────────────

def test_per_category_off_does_not_mute_the_others(clean_env, spy_ses, monkeypatch, caplog):
    """The real-world fix: kill the reconciliation spam, keep every safety alert alive."""
    monkeypatch.setenv("ALERT_RECONCILIATION_ENABLED", "0")
    caplog.set_level(logging.WARNING, logger=notifier.__name__)

    assert alerts_enabled("RECONCILIATION") is False
    assert notifier.alert_reconciliation_breach("A", 8720.31, 50.0, 0.0, 8720.31) is False
    assert spy_ses == [], "the muted category must not email"
    assert "[alert suppressed: RECONCILIATION]" in caplog.text
    assert "8,720.31" in caplog.text, "the muted alert's full body must still be logged"

    # ...and everything else is untouched.
    for cat in notifier.ALERT_CATEGORIES:
        if cat == "RECONCILIATION":
            continue
        assert alerts_enabled(cat) is True, f"{cat} was collaterally muted"
        assert notifier.send_alert("subj", "body", category=cat) is True
    assert len(spy_ses) == len(notifier.ALERT_CATEGORIES) - 1


@pytest.mark.parametrize("cat", _REQUIRED)
def test_every_required_category_is_individually_mutable(clean_env, spy_ses, monkeypatch, cat):
    monkeypatch.setenv(f"ALERT_{cat}_ENABLED", "0")
    assert alerts_enabled(cat) is False
    assert notifier.send_alert("s", "b", category=cat) is False
    # A sibling still sends — the mute is scoped to exactly one category.
    sibling = next(c for c in _REQUIRED if c != cat)
    assert alerts_enabled(sibling) is True
    assert notifier.send_alert("s", "b", category=sibling) is True
    assert len(spy_ses) == 1


@pytest.mark.parametrize("raw,expect_enabled", [
    ("0", False), ("false", False), ("FALSE", False), ("no", False), ("off", False),
    ("1", True), ("true", True), ("yes", True), ("", True), ("   ", True),
])
def test_flag_parsing(clean_env, monkeypatch, raw, expect_enabled):
    """Empty/whitespace => the DEFAULT (on). An operator who blanks the var is not muting."""
    monkeypatch.setenv("ALERT_RECONCILIATION_ENABLED", raw)
    assert alerts_enabled("RECONCILIATION") is expect_enabled


# ── The health surface reflects the env accurately ────────────────────────────

def test_alerts_suppressed_reflects_the_env(clean_env, monkeypatch):
    assert alerts_suppressed() == []

    monkeypatch.setenv("ALERT_RECONCILIATION_ENABLED", "0")
    monkeypatch.setenv("ALERT_TRADE_SILENCE_ENABLED", "0")
    assert sorted(alerts_suppressed()) == ["RECONCILIATION", "TRADE_SILENCE"]
    assert "BOTS_DOWN" not in alerts_suppressed()

    monkeypatch.setenv("ALERTS_ENABLED", "0")
    assert sorted(alerts_suppressed()) == sorted(notifier.ALERT_CATEGORIES)


# ── The gate is at the SEND step, NEVER the DETECT step ───────────────────────

def test_suppression_never_disables_detection(clean_env, spy_ses, monkeypatch, caplog):
    """Muting BOTS_DOWN mutes the EMAIL. The watchdog must still DETECT and still LOG.

    Phase 19's killer fix was that all-bots-down had disabled its own detection. A mute
    that reaches back into _check_bots_down would re-create that exact bug, so the gate
    lives in send_alert alone: the check runs, log.error fires, the wrapper is called,
    and only the SES call is skipped.
    """
    from src.bot_manager import BotManager

    monkeypatch.setenv("ALERT_BOTS_DOWN_ENABLED", "0")
    caplog.set_level(logging.WARNING)

    mgr = object.__new__(BotManager)          # no DB, no pool, no threads
    mgr._last_bots_down_alert = 0.0

    mgr._check_bots_down(alive_before=0, enabled=4, hours_since_trade=72.0)

    assert spy_ses == [], "the email is muted"
    # DETECTION still happened, at ERROR, from the watchdog itself...
    assert "ALL BOTS DOWN" in caplog.text
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    # ...and the alert body still reached the logs via the suppression path.
    assert "[alert suppressed: BOTS_DOWN]" in caplog.text
    assert "NO BOT THREADS ARE ALIVE" in caplog.text
    # The cooldown still advanced — muted or not, the check behaves identically.
    assert mgr._last_bots_down_alert > 0.0


def test_health_payload_carries_alerts_suppressed(clean_env, monkeypatch):
    """The dashboard SHOWS what is muted rather than hiding it. Names only, no env values."""
    import sys
    sys.path.insert(0, "dashboard/api")
    from models import HealthStatus

    assert HealthStatus().alerts_suppressed == []      # pessimistic default: nothing muted

    monkeypatch.setenv("ALERT_RECONCILIATION_ENABLED", "0")
    h = HealthStatus(alerts_suppressed=alerts_suppressed())
    assert h.alerts_suppressed == ["RECONCILIATION"]
    assert all(isinstance(c, str) for c in h.alerts_suppressed)

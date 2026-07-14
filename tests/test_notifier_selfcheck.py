# tests/test_notifier_selfcheck.py
"""Phase 19 (RUN-01) — the alerter must be able to prove it can send. Cases 10-12b.

`src/notifier.py::send_alert` (:47-61) SWALLOWS every exception. An unconfigured — or
merely MIS-configured — SES therefore produces a system that BELIEVES it is alerting and
is not. A silent alerter and a silent bot are the same outage twice.

CONFIG PRESENCE != DELIVERY. A valid-LOOKING config still 403s on an unverified SES
identity, and send_alert swallows that too. `alerts_configured()` cannot see it — which
is why `last_alert_error()` (case 12b) exists.

No boto3. No network. No email is ever sent.
"""
import pathlib

import pytest

from src import notifier
from src.notifier import (
    alert_all_bots_down,
    alert_bot_misconfigured,
    alert_manager_never_started,
    alerts_configured,
    last_alert_error,
)

_AWS_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")


@pytest.fixture
def no_config(monkeypatch, tmp_path):
    monkeypatch.setattr(notifier, "SECRETS_PATH", tmp_path / "nope.json")
    for v in _AWS_VARS:
        monkeypatch.delenv(v, raising=False)


# ── Case 10 ───────────────────────────────────────────────────────────────────

def test_ses_unconfigured_reports_false(no_config):
    assert alerts_configured() is False


# ── Case 11 — mirrors _get_ses_client's resolution order (notifier.py:27-39) ──

def test_ses_configured_reports_true_on_either_channel(monkeypatch, tmp_path):
    secrets = tmp_path / "services.json"
    secrets.write_text("{}", encoding="utf-8")

    # (a) the secrets file exists -> configured, regardless of env
    monkeypatch.setattr(notifier, "SECRETS_PATH", secrets)
    for v in _AWS_VARS:
        monkeypatch.delenv(v, raising=False)
    assert alerts_configured() is True

    # (b) file absent, BOTH env vars set -> configured (the container path)
    monkeypatch.setattr(notifier, "SECRETS_PATH", tmp_path / "absent.json")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE123")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    assert alerts_configured() is True

    # (c) only ONE of the two -> NOT configured
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY")
    assert alerts_configured() is False


# ── Case 12 — a bool, and no credential material in any body ──────────────────

def test_alerts_configured_is_a_bool_and_leaks_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(notifier, "SECRETS_PATH", tmp_path / "absent.json")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAEXAMPLE123")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3tvalue")

    assert isinstance(alerts_configured(), bool)

    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        notifier, "send_alert",
        lambda subject, body, category="GENERAL": sent.append((subject, body)) or True)

    alert_bot_misconfigured("X", "Bot X", "missing alpaca keys")
    alert_all_bots_down(2, 30.0)
    alert_manager_never_started("DATABASE_URL not set")

    blob = " ".join(s + " " + b for s, b in sent)
    for secret in ("AKIAEXAMPLE123", "AKIA", "s3cr3tvalue"):
        assert secret not in blob, f"credential material {secret!r} leaked into an alert body"

    subject, body = sent[0]
    assert "missing alpaca keys" in body
    assert "died" not in (subject + body).lower()
    assert "dead" not in (subject + body).lower()
    assert "ALL BOTS DOWN" in sent[1][0]


# ── Case 12b — config presence != delivery ────────────────────────────────────

def test_send_alert_records_its_last_error(monkeypatch):
    """A valid-LOOKING config still 403s on an unverified SES identity, and send_alert
    swallows it (:59-61). alerts_configured() cannot see that; last_alert_error() can."""

    def _boom():
        raise RuntimeError("An error occurred (MessageRejected): Email address not verified")

    monkeypatch.setattr(notifier, "_get_ses_client", _boom)

    assert notifier.send_alert("subject", "body") is False       # never raises
    err = last_alert_error()
    assert err is not None and "not verified" in err

    class _FakeSES:
        def send_email(self, **kw):
            return {"MessageId": "ok"}

    monkeypatch.setattr(notifier, "_get_ses_client", lambda: _FakeSES())
    assert notifier.send_alert("subject", "body") is True
    assert last_alert_error() is None                            # cleared on success

"""Phase 19 (RUN-01) — the heartbeat readers. Cases 26, 27.

ABSENCE IS THE SIGNAL (research N10). `self._watchdog.start()` (bot_manager.py:79) sits
AFTER the start_all query that can throw (:67-70), so the watchdog CANNOT report its own
non-existence. A reader that defaults healthy on a missing row reintroduces the exact
silent failure this phase exists to kill.

Pure. No psycopg connection, no boto3, no network, no DATABASE_URL.
"""
import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import HEARTBEAT_STALE_SECONDS, get_heartbeat, heartbeat_is_fresh  # noqa: E402


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        assert "runtime_heartbeat" in sql
        return _FakeResult(self.rows)


# ── Case 26 — absence means DEAD ─────────────────────────────────────────────

def test_absence_of_row_means_dead():
    assert heartbeat_is_fresh(None) is False
    assert get_heartbeat(_FakeConn([])) is None


def test_a_present_row_is_returned_as_a_dict():
    row = {"component": "bot_manager", "beat_at": dt.datetime.now(dt.timezone.utc),
           "bots_alive": 2, "bots_enabled": 2}
    assert get_heartbeat(_FakeConn([row]))["bots_alive"] == 2


# ── Case 27 — staleness means DEAD ───────────────────────────────────────────

@pytest.mark.parametrize("age_s,expected", [(300, False), (30, True)])
def test_stale_heartbeat_means_dead(age_s, expected):
    now = dt.datetime.now(dt.timezone.utc)
    beat = now - dt.timedelta(seconds=age_s)
    assert heartbeat_is_fresh(beat, now=now, stale_seconds=180) is expected


@pytest.mark.parametrize("age_s,expected", [(300, False), (30, True)])
def test_naive_beat_at_is_treated_as_utc(age_s, expected):
    now = dt.datetime.now(dt.timezone.utc)
    naive = (now - dt.timedelta(seconds=age_s)).replace(tzinfo=None)
    assert heartbeat_is_fresh(naive, now=now, stale_seconds=180) is expected


def test_default_stale_window_is_180s():
    assert HEARTBEAT_STALE_SECONDS == 180

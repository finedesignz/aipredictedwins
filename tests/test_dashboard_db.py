"""
BOT-03: dashboard 'all' aggregate must include Bot D.

Verifies KNOWN_BOTS membership and is_specific_bot() without touching a DB
(only the module-level constant + pure function are exercised).
"""
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "api")
)

import db  # noqa: E402  (dashboard/api/db.py)


def test_known_bots_includes_d():
    assert db.KNOWN_BOTS == ("A", "B", "C", "D")


def test_is_specific_bot_d_true():
    assert db.is_specific_bot("D") is True


def test_is_specific_bot_aggregate_false():
    assert db.is_specific_bot("both") is False
    assert db.is_specific_bot("all") is False

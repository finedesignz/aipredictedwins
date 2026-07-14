"""Phase 19 (RUN-01) — case 28. The manager cannot report its own non-existence.

`dashboard/api/main.py:65-66` swallows a BotManager start failure into a `_log.warning`
— into the void. And `:55`'s `if db_url:` gate skips the whole block silently when
DATABASE_URL is absent. Research N10: this alert MUST fire from main.py's lifespan, NOT
from BotManager, because `self._watchdog.start()` (bot_manager.py:79) sits AFTER the
start_all query that can throw (:67-70).

No network, no DB, no SES.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _run_lifespan(app_module):
    async def _go():
        async with app_module.lifespan(app_module.app):
            pass
    asyncio.run(_go())


@pytest.fixture
def captured(monkeypatch):
    from src import notifier
    calls: list[str] = []
    monkeypatch.setattr(notifier, "alert_manager_never_started",
                        lambda error: calls.append(str(error)) or True, raising=False)
    return calls


def test_lifespan_alerts_when_the_manager_never_starts(monkeypatch, captured):
    import main as api_main
    from src import bot_manager as bm

    monkeypatch.setenv("DATABASE_URL", "postgresql://fake/fake")

    def _boom(db_url):
        raise RuntimeError("kaboom: could not connect")

    monkeypatch.setattr(bm, "BotManager", _boom)

    _run_lifespan(api_main)          # must NOT raise — the dashboard still serves

    assert captured, "BotManager never started and NOTHING said a word"
    assert "kaboom" in captured[0]
    assert api_main.app.state.bot_manager is None


def test_lifespan_alerts_when_database_url_is_absent(monkeypatch, captured):
    import main as api_main

    monkeypatch.delenv("DATABASE_URL", raising=False)

    _run_lifespan(api_main)

    assert captured, "no DATABASE_URL means NO BOTS RUN AT ALL, and today that is silent"
    assert api_main.app.state.bot_manager is None

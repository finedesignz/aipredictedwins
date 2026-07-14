"""Phase 19 — `GET /api/bots` must never call a LIVE, CYCLING bot 'stopped'.

THE BUG (observed in prod, 2026-07-14): bots A/B/C reported `status: "stopped"` with
`thread_alive: true` while running technical scans and completing cycles.

THE REAL ROOT CAUSE: `bots.status` is PROCESS-SCOPED state stored in a GLOBALLY SHARED
column. Every process that has ever managed these bots writes it, keyed on bot_id alone.
On a Coolify rolling deploy the OLD container overlaps the new one: the new container's
BotManager spawns and writes 'running' (05:40:51.38), then ~9s later the OUTGOING
container shuts down, `BotManager.stop_all` / the thread epilogues fire, and it writes
'stopped' for A/B/C (05:41:00.35 — DB `updated_at`, proven). Nothing in the live process
ever writes the column again (spawn happens once, at boot), so the lie is PERMANENT.

commit ba4cdcd's diagnosis (a retired thread of the SAME process outliving its 5s join)
was WRONG — its `_status_writer` guard is INTRA-process and cannot see, let alone drop, a
write issued by a different container. The clobber is INTER-process, and no in-process
lock can prevent it: the dying process is not lying, its bots really did stop.

THE FIX: the API DERIVES status from THREAD LIVENESS — the only authority that exists in
the process actually answering the request. A stale DB column can no longer contradict a
running thread.

Pure unit tests: no BotThread, no Alpaca, no DB.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class FakeManager:
    """Stands in for BotManager — only `status()` is consumed by the route layer."""

    def __init__(self, alive: dict[str, bool]):
        self._alive = alive

    def status(self) -> dict[str, dict]:
        return {
            bot_id: {"thread_alive": alive, "config_label": f"Bot {bot_id}"}
            for bot_id, alive in self._alive.items()
        }


def _row(bot_id="A", status="stopped", status_detail="", enabled=True):
    return {
        "bot_id": bot_id,
        "label": f"Bot {bot_id}",
        "enabled": enabled,
        "status": status,
        "status_detail": status_detail,
    }


def test_live_thread_is_running_even_when_the_column_says_stopped():
    """THE BUG. A dead container's parting 'stopped' must not bury a live bot."""
    from routes.bots import _enrich

    out = _enrich(_row("A", status="stopped"), FakeManager({"A": True}))

    assert out.thread_alive is True
    assert out.status == "running", (
        "a bot whose thread is alive was reported as 'stopped' — the exact prod lie"
    )


def test_live_thread_beats_a_stale_error_too():
    """'error' is written immediately before the thread RETURNS (bot_thread.py:404-405),
    so a live thread can never legitimately be in 'error'. A stale one must not stick."""
    from routes.bots import _enrich

    out = _enrich(_row("B", status="error", status_detail="401 unauthorized"),
                  FakeManager({"B": True}))

    assert out.status == "running"
    assert not out.status_detail, "stale failure detail must not ride along with 'running'"


def test_dead_thread_keeps_the_columns_verdict():
    """The death path is UNTOUCHED. A dead thread still reports the DB's error+detail —
    that is the only place the reason survives."""
    from routes.bots import _enrich

    out = _enrich(_row("C", status="error", status_detail="missing alpaca keys"),
                  FakeManager({"C": False}))

    assert out.thread_alive is False
    assert out.status == "error"
    assert out.status_detail == "missing alpaca keys"


def test_bot_the_manager_does_not_track_keeps_the_columns_verdict():
    """A disabled/never-spawned bot has no thread. The column is all there is."""
    from routes.bots import _enrich

    out = _enrich(_row("E", status="stopped", enabled=False), FakeManager({"A": True}))

    assert out.thread_alive is False
    assert out.status == "stopped"


def test_no_manager_at_all_keeps_the_columns_verdict():
    """Read-only mode (BotManager failed to start): no liveness source, no override."""
    from routes.bots import _enrich

    out = _enrich(_row("A", status="running"), None)

    assert out.thread_alive is False
    assert out.status == "running"


@pytest.mark.parametrize("boom", [RuntimeError("pool exhausted")])
def test_a_raising_manager_never_500s_the_endpoint(boom):
    from routes.bots import _enrich

    class Exploding:
        def status(self):
            raise boom

    out = _enrich(_row("A", status="stopped"), Exploding())

    assert out.thread_alive is False
    assert out.status == "stopped"

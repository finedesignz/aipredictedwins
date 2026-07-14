# tests/test_bot_manager.py
"""Phase 19 (RUN-01) — the BotManager runtime contract. NEW FILE.

`tests/test_bot_manager.py` did not exist before this phase. That is precisely how
`src/bot_manager.py:186-190` survived:

    # Check at least one bot is running — silence expected if all bots are down
    with self._lock:
        any_alive = any(t.is_alive() for t in self._threads.values())
    if not any_alive:
        return  # bots are down; death alert handles that separately

The ONLY alert that fires on "nothing is happening" disables itself precisely when
nothing is happening for the worst possible reason. All-bots-down is GUARANTEED
SILENT today. Four bots stopped and nothing said a word.

Two traps a careless fix walks into, and the two tests that catch them:

  * CASE 1b — TICK ORDER. `_revive_dead_bots` respawns via `_spawn` -> `thread.start()`,
    so any bot revived earlier in the SAME tick is `is_alive() == True` by the time a
    later check runs. In the DOMINANT failure mode (threads crash-loop every cycle on
    bad keys / a 401 / an unhandled exception) that means alive > 0 on EVERY tick and
    the alert NEVER fires in production. Case 1 (which drives `_check_bots_down`
    directly with an empty thread dict) cannot see that. Case 1b drives the WHOLE
    integrated tick with a SUCCEEDING revive and is the phase's real proof.

  * CASE 5b — THE KEYLESS PREDICATE MUST CHECK **BOTH** KEYS. A row with an api_key and
    an EMPTY secret passes an api-key-only check and gets SPAWNED. Traced:
    src/bot_config.py:46-47 coerces the missing secret to `or ""` (EMPTY IS LEGAL) ->
    src/bot_thread.py:118-126 builds Config straight from the row with NO env reads ->
    src/config.py:74-76 Config is a frozen dataclass whose keys default to "" and
    **DOES NOT RAISE**. Result: 401 -> run() catches -> status='error' -> thread exits
    -> revived again next tick, FOREVER (the 1h cooldown throttles the EMAIL, not the
    SPAWN). CLAUDE.md's "empty bare keys fail-clear (raise)" is the ORCHESTRATOR
    SERVICE's config path — it does NOT hold for BotConfig/BotThread.

NO NETWORK. NO DATABASE. NO SES. NO REAL BotThread — `BotManager._spawn` is
monkeypatched to a FakeThread installer for EVERY case by default (a real `_spawn`
constructs a live BotThread and starts a LIVE TRADING LOOP). `ConnectionPool` is
monkeypatched before any BotManager is constructed. The watchdog thread is never started.
"""
import contextlib
import datetime as dt
import pathlib
import types

import pytest

from src import bot_manager as bm
from src import notifier as notifier_mod
from src.bot_manager import BotManager

_REPO = pathlib.Path(__file__).resolve().parents[1]


# ── Fakes ─────────────────────────────────────────────────────────────────────

class FakeThread:
    """A bot thread stand-in. start() FLIPS is_alive() to True — exactly like a real
    revive does (BotManager._spawn:296 calls thread.start()). That is what makes
    case 1b meaningful."""

    def __init__(self, alive=False, label="Bot", strategy="confluence"):
        self._alive = bool(alive)
        self.started = 0
        self.config = types.SimpleNamespace(label=label, strategy=strategy)

    def is_alive(self):
        return self._alive

    def start(self):
        self.started += 1
        self._alive = True

    def stop(self):
        self._alive = False

    def join(self, timeout=None):
        return None

    def kill(self):
        """Test helper — simulate the thread crashing out between ticks."""
        self._alive = False


class FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    """HONOURS the SQL it is handed (mirroring tests/test_db.py:103-115).

    Crucially: when the query text carries `alpaca_api_key IS NOT NULL` it FILTERS
    those rows out. Without that, cases 5/6's stated RED reason would be FALSE (on
    current main the keyless rows would come back anyway and the tests would fail for
    an unrelated reason) and case 8 would be VACUOUS.
    """

    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "runtime_heartbeat" in s or s.startswith("UPDATE") or s.startswith("INSERT"):
            self.store["writes"].append((s, params))
            return FakeResult([])
        if "MAX(timestamp)" in s:
            return FakeResult([{"last_trade": self.store.get("last_trade")}])
        if "FROM bots" in s:
            rows = [r for r in self.store["rows"] if r.get("enabled")]
            if "alpaca_api_key IS NOT NULL" in s:
                rows = [r for r in rows if r.get("alpaca_api_key")]
            return FakeResult(rows)
        return FakeResult([])


class FakePool:
    def __init__(self, store):
        self.store = store

    def connection(self):
        store = self.store

        @contextlib.contextmanager
        def _cm():
            yield FakeConn(store)

        return _cm()


def _row(bot_id="A", enabled=True, api="AKTEST", sec="SKTEST", strategy="confluence"):
    return {
        "bot_id": bot_id,
        "label": f"Bot {bot_id}",
        "enabled": enabled,
        "alpaca_api_key": api,
        "alpaca_secret_key": sec,
        "strategy": strategy,
    }


def _hours_ago(h):
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=h)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def capture_alerts(monkeypatch):
    """Record every alert as (subject, body). boto3 is NEVER imported."""
    sent: list[tuple[str, str]] = []

    def _send(subject, body):
        sent.append((subject, body))
        return True

    monkeypatch.setattr(notifier_mod, "send_alert", _send, raising=False)
    monkeypatch.setattr(
        notifier_mod, "alert_all_bots_down",
        lambda enabled, hours: _send(
            "ALL BOTS DOWN — no bot threads alive",
            f"enabled={enabled} hours_since_trade={hours}"),
        raising=False,
    )
    monkeypatch.setattr(
        notifier_mod, "alert_bot_misconfigured",
        lambda bot_id, label, reason: _send(
            f"Bot {bot_id} misconfigured — not trading", f"{label}: {reason}"),
        raising=False,
    )
    monkeypatch.setattr(
        notifier_mod, "alert_manager_never_started",
        lambda error: _send("BotManager NEVER STARTED — no bots are running", str(error)),
        raising=False,
    )
    return sent


@pytest.fixture
def clock(monkeypatch):
    """Frozen, advanceable time. Never sleep."""
    now = [1_000_000.0]
    monkeypatch.setattr(bm.time, "time", lambda: now[0])
    return now


@pytest.fixture
def make_manager(monkeypatch):
    """Build a BotManager with a FakePool and a STUBBED _spawn.

    _spawn is stubbed BY DEFAULT for every case. The real `_spawn`
    (src/bot_manager.py:274-297) constructs a REAL BotThread/CopyTraderThread and calls
    .start() — which pulls in AlpacaClient and runs a LIVE TRADING LOOP. Cases 1b, 2
    and 25 drive a whole tick with dead threads and WOULD reach `_revive_dead_bots`.
    No test in this file may ever construct a real BotThread.
    """

    def _make(rows, threads=None, last_trade=None, stub_spawn=True):
        store = {"rows": list(rows), "writes": [], "last_trade": last_trade}
        monkeypatch.setattr(bm, "ConnectionPool", lambda **kw: FakePool(store))

        if stub_spawn:
            def _fake_spawn(self, cfg):
                t = FakeThread(alive=False, label=cfg.label, strategy=cfg.strategy)
                self._threads[cfg.bot_id] = t
                t.start()          # a revive really does make the bot look alive
            monkeypatch.setattr(BotManager, "_spawn", _fake_spawn)

        mgr = BotManager("postgresql://fake/fake")
        mgr._threads = dict(threads or {})
        return mgr, store

    return _make


def _subjects(sent):
    return [s for s, _ in sent]


def _kill_all(mgr):
    for t in mgr._threads.values():
        t.kill()


# ── Case 1 — THE KILLER BUG (unit shape) ──────────────────────────────────────

def test_all_bots_down_alerts(make_manager, capture_alerts, clock):
    """One enabled+keyed bot, ZERO live threads, 30h of silence -> ALL BOTS DOWN.

    RED on main: bot_manager.py:189-190 `if not any_alive: return` bails out before any
    alert can fire, and `_check_bots_down` does not exist at all.
    """
    mgr, _ = make_manager([_row("A")], threads={})
    mgr._check_bots_down(0, 1, 30.0)

    assert any("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)), \
        "all-bots-down is the single most important state in the system and it is silent"


# ── Case 1b — THE ONE THAT ACTUALLY MATTERS ───────────────────────────────────

def test_all_bots_down_alerts_through_a_whole_tick(make_manager, capture_alerts, clock):
    """The INTEGRATED tick, with a SUCCEEDING revive — the only call shape prod has.

    `_revive_dead_bots` (:101-119) respawns via `_spawn` (:117) -> `thread.start()`, so
    every revivable bot is `is_alive() == True` again by the end of the tick. If liveness
    is evaluated AFTER the revive (or recomputed inside `_check_bots_down`), then in the
    DOMINANT failure mode — threads crash-loop every cycle on bad keys / a 401 / an
    unhandled exception in `_main_loop` — alive > 0 on EVERY tick and the ALL BOTS DOWN
    alert NEVER FIRES. Same silence, reintroduced.

    Liveness MUST be snapshotted at tick START, before revive, and passed as a PARAMETER.
    A "fix" that merely reorders the alert after the revive FAILS this test.
    """
    mgr, _ = make_manager(
        [_row("A"), _row("B")],
        threads={"A": FakeThread(alive=False, label="Bot A"),
                 "B": FakeThread(alive=False, label="Bot B")},
    )

    mgr._tick()

    # The revive SUCCEEDED — both threads are alive again right now...
    assert all(t.is_alive() for t in mgr._threads.values()), \
        "the revive must actually succeed, or this test proves nothing"
    # ...and the alert STILL fired, because liveness was snapshotted BEFORE the revive.
    assert sum("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)) == 1

    # Second tick: they crash-dead again. The cooldown must NOT have been reset merely
    # because a revive briefly succeeded — the outage is continuous.
    _kill_all(mgr)
    mgr._tick()
    assert sum("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)) == 1, \
        "cooldown reset by a transient revive — 'repeats until one is alive' is a lie"


# ── Case 2 — the cooldown window ──────────────────────────────────────────────

def test_all_bots_down_repeats_each_cooldown_window(make_manager, capture_alerts, clock):
    mgr, _ = make_manager([_row("A")], threads={"A": FakeThread(alive=False)})

    mgr._tick()
    assert sum("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)) == 1

    _kill_all(mgr)
    mgr._tick()                       # inside the cooldown window
    assert sum("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)) == 1

    clock[0] += bm._BOTS_DOWN_COOLDOWN + 1
    _kill_all(mgr)
    mgr._tick()
    assert sum("ALL BOTS DOWN" in s for s in _subjects(capture_alerts)) == 2


# ── Case 3 — do not cry wolf ──────────────────────────────────────────────────

def test_one_bot_alive_means_no_all_bots_down_alert(make_manager, capture_alerts, clock):
    mgr, _ = make_manager([_row("A")], threads={"A": FakeThread(alive=True)})
    mgr._tick()
    assert not any("ALL BOTS DOWN" in s for s in _subjects(capture_alerts))


# ── Case 4 — trade silence stands on its own merits ───────────────────────────

def test_trade_silence_is_evaluated_on_its_own_merits(make_manager, capture_alerts, clock):
    """Bots ALIVE, last trade 30h ago -> the trade-silence alert fires, and it is NOT
    an all-bots-down alert. The two alerts are INDEPENDENT, never mutually suppressing."""
    mgr, _ = make_manager(
        [_row("A")], threads={"A": FakeThread(alive=True)}, last_trade=_hours_ago(30),
    )
    mgr._tick()

    subs = _subjects(capture_alerts)
    assert any("No trades in" in s for s in subs), subs
    assert not any("ALL BOTS DOWN" in s for s in subs)


# ── Case 5 — a keyless bot is LOUDLY BROKEN, not invisible ────────────────────

def test_keyless_enabled_bot_is_error_and_alerts(make_manager, capture_alerts, clock, monkeypatch):
    """RED on main: the key predicate at :104-107 removes the row entirely (the FakeConn
    HONOURS that WHERE clause), so nothing is called at all. Invisible is not a state we ship."""
    mgr, _ = make_manager([_row("X", api="", sec="")], threads={})
    statuses = []
    monkeypatch.setattr(mgr, "_on_status_change",
                        lambda b, s, d: statuses.append((b, s, d)))

    mgr._revive_dead_bots()

    assert ("X", "error", "missing alpaca keys") in statuses
    assert sum("misconfigured" in s for s in _subjects(capture_alerts)) == 1


# ── Case 5b — THE HOT LOOP A NAIVE FIX LEAVES OPEN ────────────────────────────

def test_api_key_without_secret_is_also_keyless(make_manager, capture_alerts, clock, monkeypatch):
    """api_key SET, secret EMPTY. `if not row.get("alpaca_api_key")` lets this through.

    bot_config.py:46-47 coerces the missing secret to "" (LEGAL); bot_thread.py:118-126
    passes it straight into Config; config.py:74-76's frozen dataclass DOES NOT RAISE.
    So the bot spawns -> 401 on its first Alpaca call -> run() catches -> status='error'
    -> the thread exits -> it is revived AGAIN in 60s, FOREVER. The 1h cooldown throttles
    the EMAIL, not the SPAWN.
    """
    mgr, _ = make_manager([_row("Y", api="AKTEST", sec="")], threads={})
    statuses, spawned = [], []
    monkeypatch.setattr(mgr, "_on_status_change",
                        lambda b, s, d: statuses.append((b, s, d)))
    monkeypatch.setattr(mgr, "_spawn", lambda cfg: spawned.append(cfg.bot_id))

    mgr._revive_dead_bots()

    assert ("Y", "error", "missing alpaca keys") in statuses
    assert spawned == [], "an empty-SECRET bot was spawned into a permanent 401 revive loop"
    assert sum("misconfigured" in s for s in _subjects(capture_alerts)) == 1


# ── Case 6 — never spawned, never death-alerted (research N5) ─────────────────

def test_keyless_bot_is_not_spawned_and_gets_no_death_alert(
        make_manager, capture_alerts, clock, monkeypatch):
    """A keyless bot NEVER LIVED, so a "thread died" alert about it is a lie — and
    _spawn must never be reached, or a credential-less bot is respawned every 60s forever."""
    mgr, _ = make_manager(
        [_row("X", api="", sec=""), _row("Y", api="AKTEST", sec="")], threads={},
    )
    spawned = []
    monkeypatch.setattr(mgr, "_on_status_change", lambda b, s, d: None)
    monkeypatch.setattr(mgr, "_spawn", lambda cfg: spawned.append(cfg.bot_id))

    mgr._revive_dead_bots()

    assert spawned == []
    for subject, body in capture_alerts:
        blob = f"{subject} {body}".lower()
        assert "died" not in blob and "dead" not in blob, subject


# ── Case 7 — the misconfig alert cooldown ─────────────────────────────────────

def test_keyless_alert_respects_the_one_hour_cooldown(
        make_manager, capture_alerts, clock, monkeypatch):
    mgr, _ = make_manager([_row("X", api="", sec="")], threads={})
    statuses = []
    monkeypatch.setattr(mgr, "_on_status_change",
                        lambda b, s, d: statuses.append((b, s, d)))

    mgr._revive_dead_bots()
    mgr._revive_dead_bots()

    assert sum("misconfigured" in s for s in _subjects(capture_alerts)) == 1
    # status stays authoritative on EVERY tick, cooldown or not
    assert statuses.count(("X", "error", "missing alpaca keys")) == 2


# ── Case 8 — healthy bots are byte-for-byte unaffected ────────────────────────

def test_healthy_keyed_bot_is_unaffected(make_manager, capture_alerts, clock, monkeypatch):
    """Non-vacuous ONLY because the FakeConn honours the key predicate: on main this row
    survives the filter, and post-fix it survives the filter's absence."""
    mgr, _ = make_manager([_row("A")], threads={"A": FakeThread(alive=True)})
    statuses, spawned = [], []
    monkeypatch.setattr(mgr, "_on_status_change",
                        lambda b, s, d: statuses.append((b, s, d)))
    monkeypatch.setattr(mgr, "_spawn", lambda cfg: spawned.append(cfg.bot_id))

    mgr._revive_dead_bots()

    assert statuses == []
    assert spawned == []
    assert capture_alerts == []


# ── Case 9 — a dead KEYED thread is revived, with a death alert ───────────────

def test_dead_thread_is_revived(make_manager, capture_alerts, clock, monkeypatch):
    mgr, _ = make_manager([_row("A")], threads={"A": FakeThread(alive=False)})
    spawned = []
    monkeypatch.setattr(mgr, "_spawn", lambda cfg: spawned.append(cfg.bot_id))

    mgr._revive_dead_bots()

    assert spawned == ["A"]
    assert any("died" in s for s in _subjects(capture_alerts))


# ── Case 9b — refutation C1: TWO thread classes ──────────────────────────────

def test_revive_dispatches_on_strategy(make_manager, capture_alerts, clock, monkeypatch):
    """RESEARCH REFUTED the CONTEXT claim that BotThread is the only status writer:
    CopyTraderThread (Bot E) has its own _set_status (copytrade_thread.py:140-144).
    _spawn must keep dispatching on cfg.strategy. Both classes are replaced by recording
    stand-ins — no real BotThread is ever constructed."""
    built = []

    class _RecBot(FakeThread):
        def __init__(self, cfg, on_status_change=None, **kw):
            super().__init__(label=cfg.label, strategy=cfg.strategy)
            built.append(("BotThread", cfg.bot_id))

    class _RecCopy(FakeThread):
        def __init__(self, cfg, pool=None, on_status_change=None, **kw):
            super().__init__(label=cfg.label, strategy=cfg.strategy)
            built.append(("CopyTraderThread", cfg.bot_id))

    monkeypatch.setattr(bm, "BotThread", _RecBot)
    monkeypatch.setattr(bm, "CopyTraderThread", _RecCopy)

    mgr, _ = make_manager(
        [_row("E", strategy="copytrade")],
        threads={"E": FakeThread(alive=False)},
        stub_spawn=False,           # exercise the REAL _spawn's strategy dispatch
    )
    mgr._revive_dead_bots()

    assert built == [("CopyTraderThread", "E")]


# ── Case 24 — the reconcile step self-throttles and cannot kill the tick ──────

def test_reconcile_step_self_throttles_and_never_kills_the_watchdog(
        make_manager, capture_alerts, clock, monkeypatch):
    """Three calls inside one hour -> reconcile() runs ONCE.

    Then a RAISING reconcile: the tick swallows it (each step has its own try/except)
    and the heartbeat written EARLIER in that same tick is unaffected. (`_maybe_reconcile`
    is deliberately the LAST step — it runs AFTER the heartbeat and long after
    `_check_bots_down`, so a slow or throwing reconcile can never suppress the alert.)
    """
    from src import reconciliation as rc

    calls = []
    monkeypatch.setattr(rc, "reconcile", lambda *a, **kw: calls.append(1) or [])

    mgr, store = make_manager([_row("A")], threads={"A": FakeThread(alive=True)})
    mgr._maybe_reconcile()
    mgr._maybe_reconcile()
    mgr._maybe_reconcile()
    assert len(calls) == 1

    def _boom(*a, **kw):
        raise RuntimeError("alpaca timeout")

    monkeypatch.setattr(rc, "reconcile", _boom)
    clock[0] += bm._RECONCILE_INTERVAL_HOURS * 3600 + 1
    before = len(store["writes"])

    mgr._tick()                       # must NOT raise

    beats = [w for w in store["writes"][before:] if "runtime_heartbeat" in w[0]]
    assert beats, "a raising reconcile wiped out the heartbeat written earlier in the tick"


# ── Case 25 — the heartbeat UPSERT ────────────────────────────────────────────

def test_heartbeat_upserts_a_row(make_manager, capture_alerts, clock):
    """Two ENABLED bots (the query has no key predicate any more), only one of which can
    actually run — B is keyless, so it is never spawned and never becomes alive."""
    mgr, store = make_manager(
        [_row("A"), _row("B", api="", sec="")],
        threads={"A": FakeThread(alive=True)},
    )
    mgr._tick()

    beats = [w for w in store["writes"] if "runtime_heartbeat" in w[0]]
    assert beats, "no heartbeat was written — the manager cannot be seen from outside"
    sql, params = beats[-1]
    assert "ON CONFLICT (component)" in sql
    assert params[0] == bm._HEARTBEAT_COMPONENT == "bot_manager"
    assert tuple(params[1:]) == (1, 2)     # bots_alive, bots_enabled


# ── Case 29 — migration 019 must exist in BOTH files (research N3) ────────────

def test_migration_019_exists_in_both_files():
    """src/db.py:61-66 `_bootstrap_schema()` executes src/db_schema.sql WHOLESALE, so a
    table added ONLY as a migration is absent from every fresh-DB bootstrap."""
    schema = (_REPO / "src" / "db_schema.sql").read_text(encoding="utf-8")

    # POSITIVE CONTROL — the schema file really does hand-mirror the migration chain.
    assert "CREATE TABLE IF NOT EXISTS reconciliation" in schema, \
        "positive control failed — db_schema.sql no longer mirrors migration 017"

    mig = _REPO / "dashboard" / "api" / "migrations" / "019_runtime_heartbeat.sql"
    assert mig.exists(), "migration 019_runtime_heartbeat.sql does not exist"
    assert "CREATE TABLE IF NOT EXISTS runtime_heartbeat" in mig.read_text(encoding="utf-8")
    assert "runtime_heartbeat" in schema, \
        "runtime_heartbeat is migration-only — every fresh DB bootstrap lacks it"


# ── Cases 30-34 — bots.status must not LIE about a live thread ────────────────
#
# Observed in the Phase-19 deploy verification: bots A/B/C had `thread_alive: true`,
# were logging technical scans and completing cycles, and `bots.status` read 'stopped'.
#
# ROOT CAUSE. `bots.status` is written ONLY by the thread itself
# (bot_thread.py:398/404/407 and copytrade_thread.py:429/434/436 -> _set_status ->
# BotManager._on_status_change), and `_on_status_change` writes UNCONDITIONALLY keyed on
# bot_id — it has no idea WHICH thread is calling. `_spawn` retires the previous thread
# with `old.stop(); old.join(timeout=5)` and then starts the new one. A retired thread
# that is mid-cycle (an Alpaca scan easily outlives a 5s join) unwinds LATER and runs its
# epilogue `self._set_status("stopped", "")` — landing AFTER the new, live thread already
# wrote 'running'. Last writer wins, and the last writer is a corpse. The DB then reports
# 'stopped' for a bot that is alive and cycling.
#
# The fix makes the MANAGER — which knows it just started the thread — assert 'running' at
# spawn, and ignores status writes from any thread that is no longer the registered thread
# for that bot_id. `_check_bots_down` is untouched: it still takes `alive_before` and reads
# THREAD LIVENESS, never this column.

class SpyThread:
    """Stand-in for BotThread/CopyTraderThread — accepts BOTH constructor shapes
    (`BotThread(cfg, on_status_change=...)` and
    `CopyTraderThread(cfg, pool=..., on_status_change=...)`), records the status callback,
    and NEVER touches Alpaca, the DB, or a real trading loop."""

    def __init__(self, config, pool=None, on_status_change=None):
        self.config = config
        self.on_status_change = on_status_change
        self._alive = False
        self.started = 0

    def is_alive(self):
        return self._alive

    def start(self):
        self.started += 1
        self._alive = True

    def stop(self):
        self._alive = False

    def join(self, timeout=None):
        return None

    def emit(self, status, detail=""):
        """Simulate the thread calling _set_status (bot_thread.py:240)."""
        self.on_status_change(self.config.bot_id, status, detail)


def _status_writes(store, bot_id):
    """Every (status, detail) written to `bots.status` for one bot, in order."""
    out = []
    for sql, params in store["writes"]:
        if sql.startswith("UPDATE bots SET status") and params and params[-1] == bot_id:
            out.append((params[0], params[1]))
    return out


def _spawn_row(mgr, row):
    mgr._spawn(bm.BotConfig.from_row(row))
    return mgr._threads[row["bot_id"]]


# ── Case 30 — a spawned, ALIVE bot must read 'running' in the DB ──────────────

def test_spawned_bot_is_running_in_db(make_manager, monkeypatch):
    """THE BUG. After _spawn the thread is alive — the DB must say so.

    RED on main: _spawn (bot_manager.py:466-489) starts the thread and writes NOTHING.
    The column is left at whatever the last writer said — for A/B/C, the 'stopped' that
    seed_bots.py:158 inserted, or a retired thread's epilogue.
    """
    mgr, store = make_manager([_row("A")], stub_spawn=False)
    monkeypatch.setattr(bm, "BotThread", SpyThread)

    thread = _spawn_row(mgr, _row("A"))

    assert thread.is_alive(), "precondition — _spawn must start the thread"
    writes = _status_writes(store, "A")
    assert writes, "a spawned bot wrote NO status — the DB still claims 'stopped'"
    assert writes[-1][0] == "running", f"alive bot reported as {writes[-1][0]!r}"


# ── Case 31 — a RETIRED thread may not clobber the live one's 'running' ───────

def test_retired_thread_cannot_clobber_running_status(make_manager, monkeypatch):
    """The production mechanism. `old.join(timeout=5)` gives up on a mid-cycle thread;
    that thread later runs `_set_status("stopped")` (bot_thread.py:407) and overwrites the
    LIVE thread's 'running'."""
    mgr, store = make_manager([_row("A")], stub_spawn=False)
    monkeypatch.setattr(bm, "BotThread", SpyThread)

    old = _spawn_row(mgr, _row("A"))       # cycle 1 thread — will be retired
    new = _spawn_row(mgr, _row("A"))       # respawn (restart / revive / config change)
    assert new is not old and new.is_alive()

    old.emit("stopped", "")                # the corpse's epilogue, after the 5s join gave up

    writes = _status_writes(store, "A")
    assert writes[-1][0] == "running", \
        f"a retired thread wrote {writes[-1][0]!r} over the live thread's 'running'"


# ── Case 32 — the DEATH path must still work (do not break Phase 19) ──────────

def test_live_thread_can_still_report_error_and_stopped(make_manager, monkeypatch):
    """The CURRENT thread's own status writes must still land — a bot that dies has to be
    able to say so."""
    mgr, store = make_manager([_row("A")], stub_spawn=False)
    monkeypatch.setattr(bm, "BotThread", SpyThread)

    thread = _spawn_row(mgr, _row("A"))
    thread.emit("error", "boom")
    assert _status_writes(store, "A")[-1] == ("error", "boom")

    thread.emit("stopped", "")
    assert _status_writes(store, "A")[-1] == ("stopped", "")


# ── Case 33 — CopyTraderThread (Bot E) is covered too ─────────────────────────

def test_spawned_copytrade_bot_is_running_in_db(make_manager, monkeypatch):
    """_spawn dispatches on cfg.strategy (bot_manager.py:479-486). Bot E's class must get
    the same treatment — it has a byte-identical _set_status (copytrade_thread.py:140)."""
    mgr, store = make_manager([_row("E", strategy="copytrade")], stub_spawn=False)
    monkeypatch.setattr(bm, "CopyTraderThread", SpyThread)

    thread = _spawn_row(mgr, _row("E", strategy="copytrade"))

    assert isinstance(thread, SpyThread) and thread.is_alive()
    writes = _status_writes(store, "E")
    assert writes and writes[-1][0] == "running", "copytrade bot alive but not 'running'"


# ── Case 34 — a DELIBERATE stop must still land as 'stopped' ──────────────────

def test_stop_bot_writes_stopped(make_manager, monkeypatch):
    """stop_bot POPS the thread from the registry, so the thread's own epilogue is (now,
    correctly) ignored as a retired writer. The manager must therefore record the stop
    itself — or a stopped bot would read 'running' forever, the same lie inverted."""
    mgr, store = make_manager([_row("A")], stub_spawn=False)
    monkeypatch.setattr(bm, "BotThread", SpyThread)

    _spawn_row(mgr, _row("A"))
    mgr.stop_bot("A")

    writes = _status_writes(store, "A")
    assert writes[-1][0] == "stopped", f"stopped bot reported as {writes[-1][0]!r}"

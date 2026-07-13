"""Phase 16 (UNIV-03) — the effective-universe contract.

Cases 1-13 + 18 are PURE: zero I/O, no DB, no Alpaca, no env reads. The two shadow
deny-lists (MEME_CRYPTO / _ALPACA_UNTRADEABLE) are always INJECTED via the
``meme=`` / ``untradeable=`` kwargs so nothing here imports src.alpaca_orchestrator
(which pulls the Alpaca SDK and reads env at import time).

Cases 14-17 exercise the HTTP route through the FastAPI TestClient and are gated on
TEST_DATABASE_URL — they seed and read a LOCAL/TEST Postgres, never the prod DB.
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.bot_config import BotConfig
from src.effective_universe import allowlist_for, resolve_universe, shadow_applies_to
from src.universe import entry_allowed, normalize

# The real default shadow sets, as literals (src/alpaca_evaluator.py:42 and
# src/alpaca_orchestrator.py:79-84). Copied here so the pure tests stay zero-I/O.
REAL_MEME = {"DOGE/USD", "SHIB/USD", "PEPE/USD", "BONK/USD", "WIF/USD", "FLOKI/USD"}
REAL_UNTRADEABLE = {
    "LDO/USD", "POL/USD", "ONDO/USD", "RENDER/USD", "DOT/USD",
    "ARB/USD", "SUSHI/USD", "HYPE/USD", "LINK/USD", "ETH/USD",
}

DEFAULT_CRYPTO = "BTC/USD,ETH/USD,SOL/USD,XRP/USD,ADA/USD,AVAX/USD,DOT/USD,LINK/USD"
DEFAULT_STOCK = "SPY,QQQ,NVDA,AAPL,MSFT,TSLA"


def _cfg(**overrides) -> BotConfig:
    """Build a BotConfig with no Alpaca keys and sane test defaults."""
    base = dict(
        bot_id="T",
        label="Test Bot",
        alpaca_api_key="",
        alpaca_secret_key="",
        crypto_universe=DEFAULT_CRYPTO,
        stock_universe=DEFAULT_STOCK,
        asset_class="crypto",
        strategy="confluence",
        quarantined_symbols="",
        trend_symbol="BITX",
    )
    base.update(overrides)
    return BotConfig(**base)


def _reasons(result) -> dict:
    return {b["symbol"]: b["reason"] for b in result["blocked"]}


# ── Case 1 ──────────────────────────────────────────────────────────────────

def test_effective_confluence():
    r = resolve_universe(
        _cfg(quarantined_symbols="AVAX/USD"),
        meme={"DOGE/USD"},
        untradeable={"DOT/USD", "LINK/USD", "ETH/USD"},
    )
    assert r["effective"] == ["BTC/USD", "SOL/USD", "XRP/USD", "ADA/USD"]
    assert len(r["blocked"]) == 4
    assert r["shadow_applied"] is True
    assert r["starvation"] is False


# ── Case 2 ──────────────────────────────────────────────────────────────────

def test_blocked_reason_quarantined():
    r = resolve_universe(_cfg(quarantined_symbols="AVAX/USD"), meme=set(), untradeable=set())
    assert _reasons(r)["AVAX/USD"] == "quarantined"
    assert "AVAX/USD" not in r["effective"]


# ── Case 3 (Decision 3b — the DOT/LINK/ETH lie) ─────────────────────────────

def test_blocked_reason_shadow_sets():
    """A confluence bot with 8 configured symbols really only scans 5."""
    r = resolve_universe(_cfg(), meme=REAL_MEME, untradeable=REAL_UNTRADEABLE)
    reasons = _reasons(r)
    for sym in ("DOT/USD", "LINK/USD", "ETH/USD"):
        assert reasons[sym] == "untradeable", sym
        assert sym not in r["effective"]
    # The panel cannot claim "8 of 8 tradeable".
    assert len(r["effective"]) == 5

    r2 = resolve_universe(
        _cfg(crypto_universe="BTC/USD,DOGE/USD"), meme=REAL_MEME, untradeable=REAL_UNTRADEABLE
    )
    assert _reasons(r2)["DOGE/USD"] == "meme"


# ── Case 4 ──────────────────────────────────────────────────────────────────

def test_reason_precedence():
    """quarantined > off_universe > meme > untradeable."""
    # quarantined AND untradeable
    r = resolve_universe(
        _cfg(crypto_universe="BTC/USD,ETH/USD", quarantined_symbols="ETH/USD"),
        meme=set(), untradeable={"ETH/USD"},
    )
    assert _reasons(r)["ETH/USD"] == "quarantined"

    # meme AND untradeable -> meme wins
    r = resolve_universe(
        _cfg(crypto_universe="BTC/USD,DOGE/USD"),
        meme={"DOGE/USD"}, untradeable={"DOGE/USD"},
    )
    assert _reasons(r)["DOGE/USD"] == "meme"

    # off-universe AND untradeable -> off_universe (arrives via exposure)
    r = resolve_universe(
        _cfg(crypto_universe="BTC/USD"),
        exposure={"ETHUSD": {"open": 0, "recent": 0, "display": "ETH/USD"}},
        meme=set(), untradeable={"ETH/USD"},
    )
    assert _reasons(r)["ETH/USD"] == "off_universe"


# ── Case 5 ──────────────────────────────────────────────────────────────────

def test_effective_trend_carveout():
    r = resolve_universe(
        _cfg(strategy="trend_btc", asset_class="stock", trend_symbol="BITX"),
        meme=set(), untradeable=set(),
    )
    assert "BITX" not in DEFAULT_STOCK.split(",")
    assert "BITX" in r["allowlist"]
    assert "BITX" in r["effective"]


# ── Case 6 ──────────────────────────────────────────────────────────────────

def test_effective_copytrade_union():
    cfg = _cfg(strategy="copytrade", asset_class="crypto")
    r = resolve_universe(cfg, meme=set(), untradeable=set())
    assert r["allowlist"] == cfg.all_symbols
    assert "BTC/USD" in r["allowlist"] and "SPY" in r["allowlist"]


# ── Case 7 ──────────────────────────────────────────────────────────────────

def test_effective_bot_c():
    cfg = _cfg(strategy="tradingagents", asset_class="stock")
    r = resolve_universe(cfg, meme=set(), untradeable=set())
    assert r["allowlist"] == cfg.symbols == DEFAULT_STOCK.split(",")
    assert "BTC/USD" not in r["allowlist"]


# ── Case 8 ──────────────────────────────────────────────────────────────────

def test_allowlist_by_strategy_column():
    """Dispatch is purely on the bots.strategy column — no thread, no manager, no DB."""
    lists = {}
    for strat in ("confluence", "trend_btc", "tradingagents", "copytrade"):
        lists[strat] = allowlist_for(_cfg(strategy=strat, asset_class="stock"))
    assert lists["confluence"] == DEFAULT_STOCK.split(",")
    assert lists["tradingagents"] == DEFAULT_STOCK.split(",")
    assert lists["trend_btc"] == DEFAULT_STOCK.split(",") + ["BITX"]
    assert lists["copytrade"] == _cfg().all_symbols
    # trend_btc and copytrade are each distinct from the plain symbol list
    assert lists["trend_btc"] != lists["confluence"]
    assert lists["copytrade"] != lists["confluence"]


# ── Case 9 ──────────────────────────────────────────────────────────────────

def test_starvation_flag():
    r = resolve_universe(
        _cfg(crypto_universe="BTC/USD,ETH/USD", quarantined_symbols="BTC/USD,ETH/USD"),
        meme=set(), untradeable=set(),
    )
    assert r["effective"] == []
    assert r["starvation"] is True

    healthy = resolve_universe(_cfg(), meme=set(), untradeable=set())
    assert healthy["starvation"] is False


# ── Case 10 ─────────────────────────────────────────────────────────────────

def test_leak_flag():
    """The TRUMP/FIL case: an off-universe symbol carrying real exposure."""
    r = resolve_universe(
        _cfg(),
        exposure={
            "TRUMPUSD": {"open": 1, "recent": 3, "display": "TRUMP/USD"},
            "FILUSD": {"open": 0, "recent": 2, "display": "FIL/USD"},
        },
        meme=set(), untradeable=set(),
    )
    reasons = _reasons(r)
    assert reasons["TRUMP/USD"] == "off_universe"
    assert reasons["FIL/USD"] == "off_universe"
    blocked = {b["symbol"]: b for b in r["blocked"]}
    assert blocked["TRUMP/USD"]["open_positions"] == 1
    assert blocked["TRUMP/USD"]["recent_trades"] == 3
    assert "TRUMP/USD" in r["leak"]
    assert "FIL/USD" in r["leak"]   # recent-trade-only leak


# ── Case 11 ─────────────────────────────────────────────────────────────────

def test_no_false_leak():
    r = resolve_universe(
        _cfg(quarantined_symbols="AVAX/USD"),
        exposure={
            "TRUMPUSD": {"open": 0, "recent": 0, "display": "TRUMP/USD"},
            "AVAXUSD": {"open": 1, "recent": 1, "display": "AVAX/USD"},
        },
        meme=set(), untradeable=set(),
    )
    reasons = _reasons(r)
    assert reasons["TRUMP/USD"] == "off_universe"
    assert "TRUMP/USD" not in r["leak"]          # no exposure -> not a leak
    assert reasons["AVAX/USD"] == "quarantined"
    assert "AVAX/USD" not in r["leak"]           # expected wind-down, NOT a leak


# ── Case 11b (B3) ───────────────────────────────────────────────────────────

def test_exposure_unloaded_is_unknown_not_no_leak():
    r = resolve_universe(_cfg(), exposure={}, exposure_loaded=False, meme=set(), untradeable=set())
    assert r["exposure_loaded"] is False
    assert r["leak"] == []   # UNKNOWN, not "no leak" — the flag is what says so


# ── Case 12 ─────────────────────────────────────────────────────────────────

def test_leak_normalization():
    r = resolve_universe(
        _cfg(),
        exposure={
            "TRUMPUSD": {"open": 2, "recent": 2, "display": "TRUMPUSD"},
            "BTCUSD": {"open": 1, "recent": 4, "display": "BTCUSD"},
        },
        meme=set(), untradeable=set(),
    )
    assert "TRUMPUSD" in r["leak"]
    assert "BTC/USD" in r["effective"]
    assert "BTCUSD" not in r["effective"]     # original allowlist spelling wins
    assert "BTC/USD" not in r["leak"] and "BTCUSD" not in r["leak"]


# ── Case 18 (B1 — the false-strike guard) ───────────────────────────────────

def test_shadow_sets_confluence_only():
    """MEME_CRYPTO / _ALPACA_UNTRADEABLE are enforced ONLY at
    src/bot_thread.py:144-145 and :163-164 (select_long_candidates /
    select_short_candidates — the confluence cycle) and in the CLI orchestrator.

    copytrade_thread.py / trend_strategy.py / bot_c/strategy.py never reference
    them: bot_thread dispatches trend_btc -> run_trend_cycle (:551) and
    tradingagents -> run_tradingagents_cycle (:560), both bypassing the selectors.
    Subtracting the sets for those strategies would strike ETH/USD through on Bot E
    (copytrade), which really DOES trade ETH/USD when its leader does — a brand-new
    lie in the anti-lie phase.
    """
    meme = {"DOGE/USD"}
    untradeable = {"ETH/USD", "DOT/USD", "LINK/USD"}

    conf = resolve_universe(_cfg(strategy="confluence"), meme=meme, untradeable=untradeable)
    assert _reasons(conf)["ETH/USD"] == "untradeable"
    assert conf["shadow_applied"] is True

    copy = resolve_universe(_cfg(strategy="copytrade"), meme=meme, untradeable=untradeable)
    assert "ETH/USD" in copy["effective"]
    assert "ETH/USD" not in _reasons(copy)
    assert copy["shadow_applied"] is False

    for strat in ("trend_btc", "tradingagents"):
        r = resolve_universe(_cfg(strategy=strat), meme=meme, untradeable=untradeable)
        assert r["shadow_applied"] is False, strat
        assert not {v for v in _reasons(r).values()} & {"meme", "untradeable"}, strat

    assert shadow_applies_to("confluence") is True
    assert shadow_applies_to(None) is True
    for strat in ("copytrade", "trend_btc", "tradingagents"):
        assert shadow_applies_to(strat) is False, strat


# ── Case 13 — THE ANTI-LIE INVARIANT ────────────────────────────────────────

def test_resolver_agrees_with_gate():
    """The resolver may never report a symbol effective that the gate blocks."""
    off_universe = ["TRUMP/USD", "FIL/USD"]
    total_iterated = 0
    total_blocked_by_gate = 0

    for strat in ("confluence", "trend_btc", "tradingagents", "copytrade"):
        cfg = _cfg(strategy=strat, quarantined_symbols="AVAX/USD")
        exposure = {normalize(s): {"open": 1, "recent": 1, "display": s} for s in off_universe}
        result = resolve_universe(
            cfg, exposure=exposure, meme={"DOGE/USD"}, untradeable={"ETH/USD"}
        )
        allow = allowlist_for(cfg)
        reasons = _reasons(result)

        candidates = list(dict.fromkeys(allow + cfg.quarantined + off_universe))
        assert candidates, strat
        gate_blocked_seen = 0

        for sym in candidates:
            total_iterated += 1
            ok, reason = entry_allowed(sym, allow, cfg.quarantined)
            if not ok:
                gate_blocked_seen += 1
                total_blocked_by_gate += 1
                assert sym not in result["effective"], (strat, sym)
                assert reasons.get(sym) == reason, (strat, sym, reasons.get(sym), reason)

        assert gate_blocked_seen > 0, f"vacuous: no gate-blocked symbol for {strat}"
        assert result["blocked"], f"vacuous: nothing blocked for {strat}"

        for sym in result["effective"]:
            assert entry_allowed(sym, allow, cfg.quarantined) == (True, None), (strat, sym)

    assert total_iterated > 0
    assert total_blocked_by_gate >= 4


# ══ Route cases 14-17 (TEST_DATABASE_URL-gated) ═════════════════════════════

REPO_ROOT = Path(__file__).resolve().parents[1]

_needs_db = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL not set — skipping route integration tests",
)

TEST_BOT = "UNIVTEST"


@pytest.fixture(scope="module")
def client():
    """TestClient over a LOCAL/TEST Postgres. Never the prod DB."""
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ.pop("DASHBOARD_TOKEN", None)

    sys.path.insert(0, str(REPO_ROOT / "dashboard" / "api"))

    from main import app  # noqa: PLC0415
    from db import get_db  # noqa: PLC0415
    from fastapi.testclient import TestClient  # noqa: PLC0415

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO bots (id, bot_id, label, alpaca_api_key, alpaca_secret_key,
                              crypto_universe, quarantined_symbols, strategy,
                              asset_class, enabled, status)
            VALUES (%s, %s, 'Universe Test Bot', '', '',
                    'BTC/USD,ETH/USD,SOL/USD,AVAX/USD', 'AVAX/USD', 'confluence',
                    'crypto', FALSE, 'stopped')
            ON CONFLICT DO NOTHING
            """,
            (TEST_BOT, TEST_BOT),
        )
        conn.execute(
            """
            INSERT INTO alpaca_trades (bot_id, timestamp, symbol, asset_class, side,
                                       qty, entry_price, mirofish_prob, status)
            VALUES (%s, %s, 'TRUMP/USD', 'crypto', 'buy', 1.0, 10.0, 0.6, 'open')
            ON CONFLICT DO NOTHING
            """,
            (TEST_BOT, datetime.now(timezone.utc).isoformat()),
        )

    return TestClient(app)


@_needs_db
def test_universe_route_200(client):
    r = client.get(f"/api/bots/{TEST_BOT}/universe")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "data" in body and "meta" in body
    d = body["data"]
    assert set(d) == {
        "bot_id", "strategy", "asset_class", "allowlist", "quarantined", "effective",
        "blocked", "starvation", "leak", "shadow_applied", "shadow_sets_loaded",
        "exposure_loaded",
    }
    assert "exposure_loaded" in d and "shadow_applied" in d
    assert not [k for k in d if re.search(r"key|secret", k, re.I)]
    for b in d["blocked"]:
        assert set(b) == {"symbol", "reason", "open_positions", "recent_trades"}
    assert body["meta"]["count"] == len(d["effective"])
    assert "AVAX/USD" in [b["symbol"] for b in d["blocked"]]
    assert "TRUMP/USD" in d["leak"]


@_needs_db
def test_universe_route_404(client):
    r = client.get("/api/bots/ZZZ/universe")
    assert r.status_code == 404
    assert "ZZZ" in r.json()["detail"]


@_needs_db
def test_universe_route_readonly(client):
    from db import get_db  # noqa: PLC0415

    def counts():
        with get_db() as conn:
            b = conn.execute("SELECT COUNT(*) AS c FROM bots").fetchone()["c"]
            t = conn.execute("SELECT COUNT(*) AS c FROM alpaca_trades").fetchone()["c"]
        return b, t

    before = counts()
    assert client.get(f"/api/bots/{TEST_BOT}/universe").status_code == 200
    assert counts() == before

    src = (REPO_ROOT / "dashboard" / "api" / "routes" / "bots.py").read_text(encoding="utf-8")
    handler = src.split('@router.get("/bots/{bot_id}/universe")', 1)[1]
    handler = handler.split("\n@router.", 1)[0]
    for banned in ("INSERT", "UPDATE", "DELETE", "AlpacaClient"):
        assert banned not in handler, banned


@_needs_db
def test_openapi_contains_universe_route(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/api/bots/{bot_id}/universe" in paths
    assert "get" in paths["/api/bots/{bot_id}/universe"]

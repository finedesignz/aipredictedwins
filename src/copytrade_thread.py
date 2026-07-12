"""CopyTraderThread — Bot E's poll loop, sibling to BotThread.

Bot E does not run technical scans or the risk gate. It polls the
ai4trade.ai signals feed (followed-leaders only), maps each new signal
to an Alpaca-tradeable symbol, and places a proportional market order.

State lives in `copytrade_state` (one row, keyed by bot_id). Every
observed platform signal is appended to `copytrade_signals` with the
outcome — executed, skipped, or errored.

Threshold/sizing philosophy: pure copy with proportional sizing.
  - Leader's quantity * entry_price = their notional commitment.
  - We replicate the same % of our equity that the leader committed
    of their initial_balance (100k by default). That keeps shares
    sane even when the leader is much larger or smaller than us.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from typing import Callable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from src.ai4trade_client import AI4TradeClient, AI4TradeError
from src.alpaca_client import AlpacaClient
from src.bot_config import BotConfig
from src.bot_thread import _make_alpaca_config
from src.claude_copytrade import pick_leaders
from src.universe import entry_allowed, normalize

log = logging.getLogger(__name__)

# Polling cadence — chosen above the 30-min scan cycle of A/B because copy-trade
# signals are described as "realtime" by the platform. 60s matches PositionMonitor.
POLL_INTERVAL_SECONDS = 60

# Refresh leader picks weekly.
LEADER_REFRESH_SECONDS = 7 * 24 * 3600

# Retry leader selection at most this often when no leaders are currently
# followed (the /api/agents/top endpoint is known-flaky — it 504s often).
LEADER_RETRY_SECONDS = 3600

# Cap how many signals we'll act on per poll tick — prevents a burst of platform
# signals from blowing through our buying power before the next tick.
MAX_ACTIONS_PER_TICK = 5

# Assumed leader account size when sizing proportionally. Matches the
# `initial_balance` field returned by selfRegister.
ASSUMED_LEADER_EQUITY = 100_000.0


# ---------------------------------------------------------------------------
# Symbol mapping (platform symbol -> Alpaca symbol)
# ---------------------------------------------------------------------------

# Crypto symbols the platform publishes bare; Alpaca expects FOO/USD.
_KNOWN_CRYPTO = {
    "BTC", "ETH", "SOL", "XRP", "ADA", "AVAX", "DOT", "LINK", "DOGE", "LTC",
    "BCH", "AAVE", "UNI", "MATIC", "ATOM", "FIL", "XTZ", "ALGO", "EOS", "MKR",
    "COMP", "GRT", "SNX", "YFI", "USDC", "USDT",
}


def map_platform_symbol(market: str | None, symbol: str | None) -> str | None:
    """Translate an ai4trade signal symbol to an Alpaca-tradeable symbol.

    Returns None when Alpaca paper cannot trade this asset (forex, futures,
    options, exotic alts not on Alpaca crypto). The caller logs and skips.
    """
    if not symbol:
        return None
    sym = symbol.strip().upper()

    market_norm = (market or "").strip().lower()
    if market_norm == "crypto" or sym in _KNOWN_CRYPTO:
        # Alpaca crypto uses BASE/USD
        if "/" in sym:
            return sym  # already formatted
        return f"{sym}/USD"

    if market_norm in {"us-stock", "stock", "stocks", "equity", "us-equity", ""}:
        # Stock or unknown — treat as equity. The Alpaca place_market_order
        # call will reject if it isn't tradeable, and we'll log it.
        if "/" in sym:
            return None
        return sym

    # forex / futures / options / prediction-market token — unsupported
    return None


# ---------------------------------------------------------------------------
# CopyTraderThread
# ---------------------------------------------------------------------------


class CopyTraderThread(threading.Thread):
    """Bot E poll loop. Same lifecycle contract as BotThread."""

    def __init__(
        self,
        config: BotConfig,
        pool: ConnectionPool,
        on_status_change: Callable[[str, str, str], None] | None = None,
        base_url: str = "https://ai4trade.ai",
    ):
        super().__init__(daemon=True, name=f"copytrade-{config.bot_id}")
        self._config_lock = threading.Lock()
        self._config = config
        self._pool = pool
        self._on_status_change = on_status_change or (lambda *args, **kwargs: None)
        self._stop_event = threading.Event()
        self._base_url = base_url

    # -- BotManager compatibility -----------------------------------------

    @property
    def bot_id(self) -> str:
        return self._config.bot_id

    @property
    def config(self) -> BotConfig:
        with self._config_lock:
            return self._config

    def update_config(self, new_config: BotConfig) -> None:
        with self._config_lock:
            self._config = new_config
        log.info("[bot:%s] copytrade config updated", new_config.bot_id)

    def stop(self) -> None:
        self._stop_event.set()

    def _set_status(self, status: str, detail: str) -> None:
        try:
            self._on_status_change(self.bot_id, status, detail)
        except Exception as exc:
            log.warning("[bot:%s] on_status_change raised: %s", self.bot_id, exc)

    # -- State helpers (Postgres) -----------------------------------------

    def _load_state(self) -> dict:
        with self._pool.connection() as conn:
            conn.row_factory = dict_row
            row = conn.execute(
                "SELECT * FROM copytrade_state WHERE bot_id = %s",
                (self.bot_id,),
            ).fetchone()
        if not row:
            raise RuntimeError(
                f"copytrade_state row missing for bot_id={self.bot_id}. "
                f"Run scripts/seed_bot_e.py first."
            )
        return dict(row)

    def _save_cursor(self, last_signal_id: int) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE copytrade_state SET last_signal_id = GREATEST(last_signal_id, %s), "
                "updated_at = NOW() WHERE bot_id = %s",
                (last_signal_id, self.bot_id),
            )

    def _save_leaders(self, leader_ids: list[int]) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE copytrade_state SET followed_leaders = %s, "
                "last_leader_pick_at = NOW(), updated_at = NOW() WHERE bot_id = %s",
                (json.dumps(leader_ids), self.bot_id),
            )

    def _log_signal(self, row: dict) -> None:
        """Insert into copytrade_signals; idempotent on (bot_id, platform_signal_id)."""
        with self._pool.connection() as conn:
            conn.execute(
                """
                INSERT INTO copytrade_signals (
                    bot_id, platform_signal_id, leader_agent_id, leader_name,
                    market, symbol, mapped_symbol, signal_type, side,
                    entry_price, quantity, executed_at, action,
                    alpaca_order_id, alpaca_qty, error_detail
                ) VALUES (
                    %(bot_id)s, %(platform_signal_id)s, %(leader_agent_id)s, %(leader_name)s,
                    %(market)s, %(symbol)s, %(mapped_symbol)s, %(signal_type)s, %(side)s,
                    %(entry_price)s, %(quantity)s, %(executed_at)s, %(action)s,
                    %(alpaca_order_id)s, %(alpaca_qty)s, %(error_detail)s
                )
                ON CONFLICT (bot_id, platform_signal_id) DO NOTHING
                """,
                row,
            )

    # -- Leader selection -------------------------------------------------

    def _discover_leaders_from_feed(self, client: AI4TradeClient, n: int = 3) -> list[int]:
        """Fallback when /api/agents/top is broken: pick most-active publishers
        from the public firehose. An agent posting frequently is at least
        verifiably active, which beats nothing.
        """
        try:
            signals = client.get_feed(limit=100, sort="new")
        except AI4TradeError as exc:
            log.warning("[bot:%s] fallback feed discovery failed: %s", self.bot_id, exc)
            return []
        counts: dict[int, int] = {}
        for sig in signals:
            aid = sig.get("agent_id")
            if isinstance(aid, int) and aid > 0:
                counts[aid] = counts.get(aid, 0) + 1
        return [aid for aid, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]

    def _ensure_leaders(self, client: AI4TradeClient, state: dict) -> list[int]:
        existing = state.get("followed_leaders") or []
        if isinstance(existing, str):
            try:
                existing = json.loads(existing)
            except Exception:
                existing = []

        last_pick = state.get("last_leader_pick_at")
        # Cooldown: if we have leaders and they were picked recently, keep them.
        # If we have NO leaders, retry on a shorter cooldown so we recover from
        # transient leaderboard failures without spamming the endpoint.
        cooldown = LEADER_REFRESH_SECONDS if existing else LEADER_RETRY_SECONDS
        if last_pick is not None:
            try:
                age = (dt.datetime.now(dt.timezone.utc) - last_pick).total_seconds()
            except Exception:
                age = cooldown + 1
            if age < cooldown:
                return existing

        log.info("[bot:%s] picking leaders (existing=%d)", self.bot_id, len(existing))

        # Primary source: /api/agents/top — known to 504. Treat as best-effort.
        leaderboard: list[dict] = []
        try:
            leaderboard = client.get_top_agents(limit=15, sort="return")
        except AI4TradeError as exc:
            log.warning("[bot:%s] /api/agents/top failed (%s) — will try feed fallback", self.bot_id, exc)

        leader_ids: list[int] = []
        rationale = ""
        if leaderboard:
            leader_ids, rationale = pick_leaders(leaderboard, n=3)
            if not leader_ids:
                # Try deterministic top-N from whatever id field exists
                for key in ("agent_id", "id", "user_id"):
                    candidates = []
                    for row in leaderboard[:3]:
                        v = row.get(key)
                        try:
                            candidates.append(int(v))
                        except (TypeError, ValueError):
                            continue
                    if candidates:
                        leader_ids = candidates
                        rationale = f"top-N from leaderboard ({key})"
                        break

        if not leader_ids:
            # Fallback: most active publishers from the global firehose
            leader_ids = self._discover_leaders_from_feed(client, n=3)
            if leader_ids:
                rationale = "fallback: most-active publishers"

        # Always update the cooldown timestamp — even when we found nothing —
        # so we don't hammer ai4trade every poll cycle.
        self._save_leaders(leader_ids)

        if not leader_ids:
            log.warning("[bot:%s] no leaders selected — will retry in %ds", self.bot_id, LEADER_RETRY_SECONDS)
            return existing

        log.info("[bot:%s] following %s — %s", self.bot_id, leader_ids, rationale)
        for lid in leader_ids:
            try:
                client.follow(lid)
            except AI4TradeError as exc:
                log.warning("[bot:%s] follow(%s) failed: %s", self.bot_id, lid, exc)

        for old in existing:
            if old not in leader_ids:
                try:
                    client.unfollow(int(old))
                except Exception as exc:
                    log.debug("[bot:%s] unfollow(%s) failed: %s", self.bot_id, old, exc)

        return leader_ids

    # -- Signal execution -------------------------------------------------

    def _execute_signal(
        self,
        signal: dict,
        alpaca: AlpacaClient,
        equity: float,
    ) -> dict:
        """Map a single ai4trade signal to an Alpaca order. Returns the row to log."""
        bot_id = self.bot_id
        platform_id = int(signal.get("id") or 0)
        symbol = signal.get("symbol")
        market = signal.get("market")
        side = (signal.get("side") or "").lower()
        entry_price = float(signal.get("entry_price") or 0) or None
        quantity = float(signal.get("quantity") or 0) or None
        leader_id = signal.get("agent_id")
        leader_name = signal.get("agent_name")
        signal_type = signal.get("signal_type")
        executed_at = signal.get("executed_at")

        base = {
            "bot_id": bot_id,
            "platform_signal_id": platform_id,
            "leader_agent_id": leader_id,
            "leader_name": leader_name,
            "market": market,
            "symbol": symbol,
            "signal_type": signal_type,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "executed_at": executed_at,
            "mapped_symbol": None,
            "action": "skipped_unsupported",
            "alpaca_order_id": None,
            "alpaca_qty": None,
            "error_detail": None,
        }

        mapped = map_platform_symbol(market, symbol)
        if mapped is None:
            base["error_detail"] = f"unsupported market/symbol: {market}/{symbol}"
            return base
        base["mapped_symbol"] = mapped

        if side not in {"buy", "sell"} or not entry_price or not quantity:
            base["error_detail"] = "missing side/price/qty"
            return base

        # Proportional sizing: leader committed (entry_price * quantity) of their
        # equity. Replicate the same fraction of our paper equity.
        notional_leader = entry_price * quantity
        fraction = notional_leader / ASSUMED_LEADER_EQUITY
        # Clamp fraction so a single signal can't consume the account.
        fraction = max(0.0, min(fraction, 0.10))
        dollar_amount = fraction * equity

        if dollar_amount < 10:
            base["action"] = "skipped_unsupported"
            base["error_detail"] = f"sized below $10 (fraction={fraction:.4f})"
            return base

        try:
            # Get live price; the platform price may be stale by minutes.
            live_price = alpaca.get_latest_price(mapped)
        except Exception as exc:
            base["action"] = "error"
            base["error_detail"] = f"price fetch failed: {exc}"
            return base

        if live_price <= 0:
            base["action"] = "error"
            base["error_detail"] = "live price <= 0"
            return base

        qty = dollar_amount / live_price
        if "/" not in mapped:
            # Equities: prefer whole shares for non-fractionable safety.
            qty = max(1.0, round(qty))
        else:
            qty = round(qty, 6)

        # Phase 15 (UNIV-01): hard-gate the ENTRY. A copytrade order has no
        # open/close concept, so the discriminator is whether it REDUCES an already
        # held position — get_positions() returns a SIGNED qty (negative for a short).
        # Skip the gate IFF (held>0 and sell) or (held<0 and buy): a reduce/close must
        # never be stranded. Everything else is gated, including a BUY that ADDS to a
        # held off-universe long (the audited TRUMP case) and a SELL on a not-held
        # symbol (a short-to-open). FAIL CLOSED if positions can't be read.
        try:
            held = {normalize(p.get("symbol")): float(p.get("qty"))
                    for p in (alpaca.get_positions() or [])}
        except Exception as exc:
            log.warning("[bot:%s] positions fetch failed (%s) — gating %s", bot_id, exc, mapped)
            held = {}
        held_qty = held.get(normalize(mapped), 0.0)
        reduces = (held_qty > 0 and side == "sell") or (held_qty < 0 and side == "buy")

        if not reduces:
            allowed, reason = entry_allowed(
                mapped, self.config.all_symbols, self.config.quarantined)
            if not allowed:
                base["action"] = "blocked"
                base["error_detail"] = reason
                log.warning(
                    "[bot:%s] ENTRY BLOCKED %s side=%s — reason=%s (universe hard-gate)",
                    bot_id, mapped, side, reason,
                )
                return base

        try:
            order = alpaca.place_market_order(symbol=mapped, qty=qty, side=side)
            base["action"] = "executed"
            base["alpaca_order_id"] = str(order.get("order_id") or "")
            base["alpaca_qty"] = qty
            log.info(
                "[bot:%s] COPIED leader=%s %s %s qty=%s @ $%.2f (notional=$%.2f, frac=%.3f%%)",
                bot_id, leader_id, side.upper(), mapped, qty, live_price,
                dollar_amount, fraction * 100,
            )
        except Exception as exc:
            base["action"] = "error"
            base["error_detail"] = f"alpaca order failed: {exc}"
            log.warning("[bot:%s] alpaca order failed for %s: %s", bot_id, mapped, exc)
        return base

    # -- Main loop --------------------------------------------------------

    def run(self) -> None:
        bot_id = self.bot_id
        log.info("[bot:%s] copytrade thread starting", bot_id)
        self._set_status("running", "")
        try:
            self._main_loop()
        except Exception as exc:
            log.exception("[bot:%s] copytrade unhandled exception", bot_id)
            self._set_status("error", str(exc))
            return
        self._set_status("stopped", "")
        log.info("[bot:%s] copytrade thread stopped cleanly", bot_id)

    def _main_loop(self) -> None:
        bot_id = self.bot_id
        cfg = self.config

        # Build per-bot Alpaca client (own paper account)
        alpaca = AlpacaClient(_make_alpaca_config(cfg))

        # Load state — must exist (created by scripts/seed_bot_e.py)
        state = self._load_state()
        client = AI4TradeClient(
            base_url=state.get("base_url") or self._base_url,
            token=state.get("claw_token"),
        )

        # Pick leaders if we don't have any or they're stale
        self._ensure_leaders(client, state)

        cycle = 0
        while not self._stop_event.is_set():
            cycle += 1
            try:
                # Reload state each cycle (cursor + leaders may have been
                # updated by another path, e.g. seed re-run, weekly cron).
                state = self._load_state()
                last_id = int(state.get("last_signal_id") or 0)
                followed = state.get("followed_leaders") or []
                if isinstance(followed, str):
                    try:
                        followed = json.loads(followed)
                    except Exception:
                        followed = []

                # If we have no followed leaders, don't waste a 45s API call
                # on an empty `sort=following` feed. Retry leader selection
                # (cooldown-gated inside _ensure_leaders) and sleep.
                if not followed:
                    self._ensure_leaders(client, state)
                    self._stop_event.wait(POLL_INTERVAL_SECONDS)
                    continue

                feed = client.get_feed(limit=50, sort="following")
                if not feed:
                    log.debug("[bot:%s] feed empty", bot_id)
                    self._stop_event.wait(POLL_INTERVAL_SECONDS)
                    continue

                # Process oldest -> newest so cursor advances monotonically
                new_signals = sorted(
                    (s for s in feed if int(s.get("id") or 0) > last_id),
                    key=lambda s: int(s.get("id") or 0),
                )

                if not new_signals:
                    self._stop_event.wait(POLL_INTERVAL_SECONDS)
                    continue

                log.info(
                    "[bot:%s] cycle %d: %d new signals (cursor=%d)",
                    bot_id, cycle, len(new_signals), last_id,
                )

                account = alpaca.get_account()
                equity = float(account.get("equity") or 0)

                acted = 0
                highest_seen = last_id
                for sig in new_signals:
                    sig_id = int(sig.get("id") or 0)
                    highest_seen = max(highest_seen, sig_id)
                    if acted >= MAX_ACTIONS_PER_TICK:
                        # Log remaining as skipped so we don't lose them silently
                        self._log_signal({
                            "bot_id": bot_id,
                            "platform_signal_id": sig_id,
                            "leader_agent_id": sig.get("agent_id"),
                            "leader_name": sig.get("agent_name"),
                            "market": sig.get("market"),
                            "symbol": sig.get("symbol"),
                            "mapped_symbol": None,
                            "signal_type": sig.get("signal_type"),
                            "side": (sig.get("side") or "").lower(),
                            "entry_price": sig.get("entry_price"),
                            "quantity": sig.get("quantity"),
                            "executed_at": sig.get("executed_at"),
                            "action": "skipped_dup",
                            "alpaca_order_id": None,
                            "alpaca_qty": None,
                            "error_detail": f"per-tick cap ({MAX_ACTIONS_PER_TICK}) reached",
                        })
                        continue

                    row = self._execute_signal(sig, alpaca, equity)
                    self._log_signal(row)
                    if row["action"] == "executed":
                        acted += 1

                self._save_cursor(highest_seen)
            except Exception as exc:
                log.exception("[bot:%s] copytrade cycle %d error: %s", bot_id, cycle, exc)

            self._stop_event.wait(POLL_INTERVAL_SECONDS)

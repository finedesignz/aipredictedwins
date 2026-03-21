"""
Kalshi API client wrapper for the trading system.

Uses the kalshi-python-sync SDK (imports as kalshi_python_sync) with RSA key
authentication.  All prices on Kalshi are in cents (1-99).  Methods that
return probabilities convert to 0.0-1.0.
"""

import threading
import time
import logging
from datetime import datetime, timezone

from src.config import Config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry / rate-limit settings
# ---------------------------------------------------------------------------
MAX_RETRIES = 3
RETRY_BACKOFF = 1.0  # seconds; doubles each retry


class _RateLimiter:
    """Token-bucket rate limiter.  Thread-safe, ~10 requests/second."""

    def __init__(self, rps: float = 10.0):
        self._min_interval = 1.0 / rps
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter(rps=10.0)


def _retry(fn, *args, **kwargs):
    """Call *fn* with exponential backoff on failure (max 3 attempts).

    Respects the global rate limiter before each attempt.
    """
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            _rate_limiter.wait()
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            wait = RETRY_BACKOFF * (2 ** attempt)
            log.warning(
                "Kalshi API call failed (attempt %d/%d): %s -- retrying in %.1fs",
                attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
    raise last_exc


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class KalshiClient:
    """Wrapper around the kalshi-python-sync SDK."""

    def __init__(self, config: Config):
        self.config = config
        self._init_client()

    def _init_client(self):
        """Initialize the SDK client with RSA key auth."""
        try:
            from kalshi_python_sync import Configuration, KalshiClient as _KalshiClient
        except ImportError:
            raise ImportError(
                "kalshi-python-sync is not installed.  "
                "Run:  pip install kalshi-python-sync"
            )

        cfg = Configuration(host=self.config.kalshi_api_host)

        with open(self.config.kalshi_private_key_path, "r") as f:
            private_key = f.read()

        cfg.api_key_id = self.config.kalshi_api_key_id
        cfg.private_key_pem = private_key

        self.client = _KalshiClient(cfg)
        log.info(
            "Kalshi client initialized (env=%s, host=%s)",
            self.config.kalshi_env,
            self.config.kalshi_api_host,
        )

    # ── Market Data ───────────────────────────────────────────────────────

    def get_active_markets(
        self,
        min_volume: int = 10_000,
        min_hours_to_close: int = 24,
    ) -> list[dict]:
        """Fetch open events with nested markets, filtered by volume and
        time-to-close.

        Returns a list of dicts, each with keys:
            ticker, title, subtitle, category, yes_price, volume,
            close_time, event_ticker
        """
        now_ts = int(datetime.now(timezone.utc).timestamp())
        min_close_ts = now_ts + (min_hours_to_close * 3600)

        events_resp = _retry(
            self.client.get_events,
            status="open",
            with_nested_markets=True,
            limit=200,
            min_close_ts=min_close_ts,
        )

        markets: list[dict] = []
        for event in events_resp.events or []:
            for mkt in event.markets or []:
                vol = (
                    getattr(mkt, "volume", 0)
                    or getattr(mkt, "volume_24h", 0)
                    or 0
                )
                if vol < min_volume:
                    continue

                yes_price = (
                    getattr(mkt, "yes_price", None)
                    or getattr(mkt, "last_price", 0)
                    or 0
                )

                markets.append({
                    "ticker": mkt.ticker,
                    "title": getattr(event, "title", ""),
                    "subtitle": getattr(mkt, "subtitle", getattr(mkt, "title", "")),
                    "category": getattr(
                        event, "category", getattr(event, "series_ticker", ""),
                    ),
                    "yes_price": yes_price,
                    "volume": vol,
                    "close_time": (
                        getattr(mkt, "close_time", None)
                        or getattr(mkt, "expiration_time", "")
                    ),
                    "event_ticker": getattr(
                        event, "event_ticker", getattr(event, "ticker", ""),
                    ),
                })

        log.info(
            "Found %d markets (filtered from events, min_vol=%d, min_hours=%d)",
            len(markets), min_volume, min_hours_to_close,
        )
        return markets

    def get_market_price(self, ticker: str) -> float:
        """Return the current YES price as a probability (0.0 -- 1.0)."""
        resp = _retry(self.client.get_market, ticker=ticker)
        mkt = resp.market if hasattr(resp, "market") else resp
        price_cents = (
            getattr(mkt, "yes_price", None)
            or getattr(mkt, "last_price", 50)
        )
        return price_cents / 100.0

    def get_orderbook(self, ticker: str) -> dict:
        """Return the current orderbook with yes/no bid and ask arrays."""
        resp = _retry(self.client.get_market_orderbook, ticker=ticker, depth=10)
        ob = resp.orderbook if hasattr(resp, "orderbook") else resp
        return {
            "yes": getattr(ob, "yes", None),
            "no": getattr(ob, "no", None),
        }

    # ── Trading ───────────────────────────────────────────────────────────

    def place_order(
        self,
        ticker: str,
        side: str,
        contracts: int,
        price_cents: int,
    ) -> dict:
        """Place a LIMIT order.

        Parameters
        ----------
        ticker : str
            Market ticker (e.g. ``"KXBTC-26MAR21-T45000"``).
        side : str
            ``"yes"`` or ``"no"``.
        contracts : int
            Number of contracts (>= 1).
        price_cents : int
            Limit price in cents (1-99).

        Returns
        -------
        dict
            Keys: order_id, ticker, side, contracts, price_cents, status.

        Notes
        -----
        Only limit orders are supported.  Market orders are never sent.
        """
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got '{side}'")
        if not 1 <= price_cents <= 99:
            raise ValueError(f"price_cents must be 1-99, got {price_cents}")
        if contracts < 1:
            raise ValueError(f"contracts must be >= 1, got {contracts}")

        order_params: dict = {
            "ticker": ticker,
            "side": side,
            "action": "buy",
            "count": contracts,
            "type": "limit",
        }

        if side == "yes":
            order_params["yes_price"] = price_cents
        else:
            order_params["no_price"] = price_cents

        resp = _retry(self.client.create_order, **order_params)
        order = resp.order if hasattr(resp, "order") else resp

        result = {
            "order_id": getattr(order, "order_id", None),
            "ticker": ticker,
            "side": side,
            "contracts": contracts,
            "price_cents": price_cents,
            "status": getattr(order, "status", "unknown"),
        }
        log.info(
            "Order placed: %s %d contracts %s @ %dc on %s -> %s",
            side.upper(), contracts, "YES" if side == "yes" else "NO",
            price_cents, ticker, result["status"],
        )
        return result

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order.  Returns ``True`` on success."""
        try:
            _retry(self.client.cancel_order, order_id=order_id)
            log.info("Order cancelled: %s", order_id)
            return True
        except Exception as exc:
            log.error("Failed to cancel order %s: %s", order_id, exc)
            return False

    # ── Portfolio ─────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Return all open positions as a list of dicts.

        Each dict contains: ticker, yes_count, no_count, market_exposure.
        """
        resp = _retry(self.client.get_positions, limit=200)
        raw = resp.market_positions if hasattr(resp, "market_positions") else None
        if raw is None:
            raw = getattr(resp, "positions", []) or []

        positions: list[dict] = []
        for pos in raw:
            positions.append({
                "ticker": getattr(pos, "ticker", ""),
                "yes_count": getattr(pos, "yes_count", getattr(pos, "position", 0)),
                "no_count": getattr(pos, "no_count", 0),
                "market_exposure": getattr(pos, "market_exposure", 0),
            })
        return positions

    def get_balance(self) -> float:
        """Return available balance in dollars (converted from cents)."""
        resp = _retry(self.client.get_balance)
        balance_cents = resp.balance if hasattr(resp, "balance") else 0
        return balance_cents / 100.0

    def get_market_settlement(self, ticker: str) -> dict | None:
        """Check whether a market has settled and return the result.

        Returns
        -------
        dict | None
            ``None`` if the market has not settled.  Otherwise a dict with
            keys: ticker, result, settled_time, revenue.
        """
        try:
            resp = _retry(self.client.get_settlements, ticker=ticker, limit=1)
        except Exception as exc:
            log.warning("Failed to fetch settlement for %s: %s", ticker, exc)
            return None

        settlements = getattr(resp, "settlements", []) or []
        if not settlements:
            return None

        s = settlements[0]
        return {
            "ticker": getattr(s, "ticker", ticker),
            "result": getattr(s, "result", ""),
            "settled_time": getattr(s, "settled_time", ""),
            "revenue": getattr(s, "revenue", 0),
        }

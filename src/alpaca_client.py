"""
Alpaca Markets API client for the AI Predicted Wins trading system.

Supports both paper and live trading for stocks (us_equity) and crypto.
Uses the alpaca-py SDK with exponential backoff retry logic matching
the existing kalshi_client.py patterns.
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
    """Token-bucket rate limiter.  Thread-safe, ~5 requests/second for Alpaca."""

    def __init__(self, rps: float = 5.0):
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


_rate_limiter = _RateLimiter(rps=5.0)


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
                "Alpaca API call failed (attempt %d/%d): %s -- retrying in %.1fs",
                attempt + 1, MAX_RETRIES, exc, wait,
            )
            time.sleep(wait)
    raise last_exc


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class AlpacaClient:
    """Wrapper around the alpaca-py SDK for stocks and crypto trading."""

    def __init__(self, config: Config):
        self.config = config
        self._trading_client = None
        self._stock_data_client = None
        self._crypto_data_client = None
        self._init_clients()

    def _init_clients(self):
        """Initialize Alpaca SDK clients."""
        try:
            from alpaca.trading.client import TradingClient
            from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
        except ImportError:
            raise ImportError(
                "alpaca-py is not installed.  "
                "Run:  pip install alpaca-py"
            )

        api_key = self.config.alpaca_api_key
        secret_key = self.config.alpaca_secret_key
        paper = self.config.alpaca_env != "live"

        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in .env"
            )

        self._trading_client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
        )
        self._stock_data_client = StockHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )
        self._crypto_data_client = CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=secret_key,
        )

        log.info(
            "Alpaca client initialized (env=%s, paper=%s, host=%s)",
            self.config.alpaca_env,
            paper,
            self.config.alpaca_api_host,
        )

    # ── Account ───────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Return account details: balance, buying power, equity, day trading status."""
        acct = _retry(self._trading_client.get_account)
        return {
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "equity": float(acct.equity),
            "portfolio_value": float(acct.portfolio_value),
            "day_trading_buying_power": float(getattr(acct, "daytrading_buying_power", 0) or 0),
            "pattern_day_trader": getattr(acct, "pattern_day_trader", False),
            "trading_blocked": getattr(acct, "trading_blocked", False),
            "account_blocked": getattr(acct, "account_blocked", False),
            "currency": getattr(acct, "currency", "USD"),
            "status": getattr(acct, "status", ""),
        }

    # ── Positions ─────────────────────────────────────────────────────────

    def get_positions(self) -> list[dict]:
        """Return all open positions with ticker, qty, current_price, unrealized_pnl, avg_entry_price."""
        raw_positions = _retry(self._trading_client.get_all_positions)
        positions = []
        for pos in raw_positions:
            positions.append({
                "symbol": pos.symbol,
                "asset_class": getattr(pos, "asset_class", ""),
                "qty": float(pos.qty),
                "side": getattr(pos, "side", "long"),
                "current_price": float(pos.current_price),
                "avg_entry_price": float(pos.avg_entry_price),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_pct": float(getattr(pos, "unrealized_plpc", 0) or 0),
                "market_value": float(pos.market_value),
                "cost_basis": float(pos.cost_basis),
            })
        return positions

    # ── Asset Discovery ───────────────────────────────────────────────────

    def get_tradeable_assets(self, asset_class: str = "crypto") -> list[dict]:
        """List tradeable assets filtered by asset_class ('us_equity' or 'crypto').

        Returns: symbol, name, tradable, fractionable
        """
        from alpaca.trading.requests import GetAssetsRequest
        from alpaca.trading.enums import AssetClass

        ac = AssetClass.CRYPTO if asset_class == "crypto" else AssetClass.US_EQUITY

        request = GetAssetsRequest(
            asset_class=ac,
            status="active",
        )
        raw_assets = _retry(self._trading_client.get_all_assets, filter=request)

        assets = []
        for asset in raw_assets:
            if not asset.tradable:
                continue
            assets.append({
                "symbol": asset.symbol,
                "name": getattr(asset, "name", ""),
                "tradable": asset.tradable,
                "fractionable": getattr(asset, "fractionable", False),
                "asset_class": asset_class,
                "exchange": getattr(asset, "exchange", ""),
            })

        log.info("Found %d tradeable %s assets", len(assets), asset_class)
        return assets

    # ── Market Data ───────────────────────────────────────────────────────

    def get_latest_price(self, symbol: str) -> float:
        """Return the current price for a symbol.

        Crypto symbols use 'BTC/USD' format. Stocks use ticker like 'AAPL'.
        """
        if "/" in symbol:
            # Crypto
            from alpaca.data.requests import CryptoLatestTradeRequest
            request = CryptoLatestTradeRequest(symbol_or_symbols=symbol)
            trades = _retry(self._crypto_data_client.get_crypto_latest_trade, request)
            if symbol in trades:
                return float(trades[symbol].price)
            raise ValueError(f"No price data for crypto symbol: {symbol}")
        else:
            # Stock
            from alpaca.data.requests import StockLatestTradeRequest
            request = StockLatestTradeRequest(symbol_or_symbols=symbol)
            trades = _retry(self._stock_data_client.get_stock_latest_trade, request)
            if symbol in trades:
                return float(trades[symbol].price)
            raise ValueError(f"No price data for stock symbol: {symbol}")

    def get_bars(
        self,
        symbol: str,
        timeframe: str = "1Day",
        limit: int = 30,
    ) -> list[dict]:
        """Fetch historical bars (open, high, low, close, volume, timestamp).

        Parameters
        ----------
        symbol : str
            Ticker symbol. Crypto uses 'BTC/USD' format.
        timeframe : str
            One of: '1Min', '5Min', '15Min', '30Min', '1Hour', '4Hour', '1Day', '1Week'.
        limit : int
            Number of bars to fetch (max 10000).
        """
        from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

        tf_map = {
            "1Min": TimeFrame(1, TimeFrameUnit.Minute),
            "5Min": TimeFrame(5, TimeFrameUnit.Minute),
            "15Min": TimeFrame(15, TimeFrameUnit.Minute),
            "30Min": TimeFrame(30, TimeFrameUnit.Minute),
            "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
            "4Hour": TimeFrame(4, TimeFrameUnit.Hour),
            "1Day": TimeFrame(1, TimeFrameUnit.Day),
            "1Week": TimeFrame(1, TimeFrameUnit.Week),
        }
        tf = tf_map.get(timeframe, TimeFrame(1, TimeFrameUnit.Day))

        if "/" in symbol:
            from alpaca.data.requests import CryptoBarsRequest
            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                limit=limit,
            )
            bar_set = _retry(self._crypto_data_client.get_crypto_bars, request)
        else:
            from alpaca.data.requests import StockBarsRequest
            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=tf,
                limit=limit,
            )
            bar_set = _retry(self._stock_data_client.get_stock_bars, request)

        bars = []
        # BarSet uses .data dict, not direct indexing
        data = bar_set.data if hasattr(bar_set, "data") else bar_set
        raw_bars = data.get(symbol, []) if isinstance(data, dict) else (bar_set[symbol] if symbol in bar_set else [])
        for bar in raw_bars:
            bars.append({
                "timestamp": bar.timestamp.isoformat() if hasattr(bar.timestamp, "isoformat") else str(bar.timestamp),
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "vwap": float(getattr(bar, "vwap", 0) or 0),
            })
        return bars

    # ── Order Execution ───────────────────────────────────────────────────

    def place_market_order(self, symbol: str, qty: float, side: str) -> dict:
        """Place a market buy or sell order.

        Parameters
        ----------
        symbol : str
            Ticker (e.g. 'AAPL', 'BTC/USD').
        qty : float
            Quantity to buy/sell. Supports fractional for crypto and fractionable stocks.
        side : str
            'buy' or 'sell'.
        """
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got '{side}'")
        if qty <= 0:
            raise ValueError(f"qty must be > 0, got {qty}")

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        # Crypto uses GTC, stocks use DAY
        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY

        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=tif,
        )
        order = _retry(self._trading_client.submit_order, order_data=request)
        result = self._parse_order(order)
        log.info(
            "Market order placed: %s %.4f %s @ market -> %s",
            side.upper(), qty, symbol, result["status"],
        )
        return result

    def place_limit_order(
        self,
        symbol: str,
        qty: float,
        side: str,
        limit_price: float,
    ) -> dict:
        """Place a limit buy or sell order.

        Parameters
        ----------
        symbol : str
            Ticker (e.g. 'AAPL', 'BTC/USD').
        qty : float
            Quantity to buy/sell.
        side : str
            'buy' or 'sell'.
        limit_price : float
            The limit price.
        """
        from alpaca.trading.requests import LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got '{side}'")
        if qty <= 0:
            raise ValueError(f"qty must be > 0, got {qty}")
        if limit_price <= 0:
            raise ValueError(f"limit_price must be > 0, got {limit_price}")

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY

        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=tif,
            limit_price=limit_price,
        )
        order = _retry(self._trading_client.submit_order, order_data=request)
        result = self._parse_order(order)
        log.info(
            "Limit order placed: %s %.4f %s @ $%.2f -> %s",
            side.upper(), qty, symbol, limit_price, result["status"],
        )
        return result

    def close_position(self, symbol: str) -> dict:
        """Close the entire position for a symbol."""
        resp = _retry(self._trading_client.close_position, symbol_or_asset_id=symbol)
        result = self._parse_order(resp)
        log.info("Position closed: %s -> %s", symbol, result["status"])
        return result

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order. Returns True on success."""
        try:
            _retry(self._trading_client.cancel_order_by_id, order_id=order_id)
            log.info("Order cancelled: %s", order_id)
            return True
        except Exception as exc:
            log.error("Failed to cancel order %s: %s", order_id, exc)
            return False

    def get_open_orders(self) -> list[dict]:
        """Return all open/pending orders."""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        raw_orders = _retry(self._trading_client.get_orders, filter=request)

        orders = []
        for order in raw_orders:
            orders.append(self._parse_order(order))
        return orders

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_order(order) -> dict:
        """Normalize an Alpaca order object into a plain dict."""
        return {
            "order_id": str(getattr(order, "id", "")),
            "client_order_id": getattr(order, "client_order_id", ""),
            "symbol": getattr(order, "symbol", ""),
            "side": str(getattr(order, "side", "")),
            "type": str(getattr(order, "type", "")),
            "qty": float(getattr(order, "qty", 0) or 0),
            "filled_qty": float(getattr(order, "filled_qty", 0) or 0),
            "filled_avg_price": float(getattr(order, "filled_avg_price", 0) or 0),
            "limit_price": float(getattr(order, "limit_price", 0) or 0),
            "status": str(getattr(order, "status", "unknown")),
            "created_at": str(getattr(order, "created_at", "")),
            "submitted_at": str(getattr(order, "submitted_at", "")),
            "filled_at": str(getattr(order, "filled_at", "")),
            "time_in_force": str(getattr(order, "time_in_force", "")),
        }

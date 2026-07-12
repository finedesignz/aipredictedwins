# src/universe.py
"""Pure universe gate — Phase 15 (UNIV-01 entry allowlist, UNIV-02 quarantine).

Two total, side-effect-free functions. No I/O, no config reads, no logging, no
Alpaca, no DB — importable with zero side effects and exhaustively unit-testable.

The gate belongs at the ENTRY sites only. It must NEVER be called from
src/alpaca_client.py: three exit paths call ``place_market_order`` directly, so a
gate at the client layer would strand open positions in a quarantined symbol.
"""

from __future__ import annotations

from typing import Iterable


def normalize(symbol: str | None) -> str:
    """Canonicalize a symbol: uppercase, strip whitespace, drop the slash.

    ``BTC/USD`` / ``btc/usd`` / ``BTCUSD`` all collapse to ``BTCUSD``; ``SPY``
    stays ``SPY``. Idempotent and total — ``None``/``""`` yield ``""``.
    """
    return (symbol or "").strip().upper().replace("/", "")


def entry_allowed(
    symbol: str | None,
    allowlist: Iterable[str],
    quarantined: Iterable[str],
) -> tuple[bool, str | None]:
    """Return ``(allowed, reason)`` for an ENTRY order on ``symbol``.

    ``reason`` is exactly one of ``None`` / ``"off_universe"`` / ``"quarantined"``.

    Quarantine is checked BEFORE the allowlist, so a symbol that is both
    in-universe and quarantined reports ``"quarantined"``.

    An EMPTY ``allowlist`` means "no allowlist restriction" (the dynamic-universe
    safety net) — the quarantine deny-list still applies.
    """
    s = normalize(symbol)

    deny = {normalize(q) for q in (quarantined or []) if normalize(q)}
    if s in deny:
        return False, "quarantined"

    allow = {normalize(a) for a in (allowlist or []) if normalize(a)}
    if allow and s not in allow:
        return False, "off_universe"

    return True, None

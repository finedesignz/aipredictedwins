# src/effective_universe.py
"""Pure effective-universe resolver — Phase 16 (UNIV-03).

Answers one question: *what can this bot ACTUALLY trade right now, and why not the
rest?* It is the single place that answer is computed; the API route and the
dashboard panel are thin transports over it.

Pure and zero-I/O: no DB, no Alpaca, no HTTP, no logging, no filesystem, no env
reads at import. Its only inputs are a ``BotConfig``, an exposure map, and
(optionally) the two shadow deny-lists.

DELEGATION RULE (the anti-lie invariant, VALIDATION case 13)
------------------------------------------------------------
Every quarantine/allowlist verdict is delegated to ``src.universe.entry_allowed`` —
the gate of record. This module MUST NEVER re-derive that set math. If the resolver
computed its own membership test it could drift from the gate, which is exactly the
class of bug this phase exists to kill.

The four gate call sites this resolver mirrors::

    confluence     src/bot_thread.py:355            allowlist = cfg.symbols
    trend_btc      src/trend_strategy.py:103-104    allowlist = cfg.symbols + [cfg.trend_symbol]
    tradingagents  src/bot_c/strategy.py:289        allowlist = cfg.symbols
    copytrade      src/copytrade_thread.py:397-398  allowlist = cfg.all_symbols

SHADOW DENY-LISTS — CONFLUENCE ONLY (VALIDATION case 18)
--------------------------------------------------------
``MEME_CRYPTO`` (src/alpaca_evaluator.py:42) and ``_ALPACA_UNTRADEABLE``
(src/alpaca_orchestrator.py:79-84) are hardcoded sets that silently shrink a bot's
tradeable universe. They are ENFORCED at exactly one place in the bot threads:
``select_long_candidates`` / ``select_short_candidates`` at
**src/bot_thread.py:144-145 and :163-164** — the CONFLUENCE cycle — plus the CLI
orchestrator. They appear NOWHERE in ``src/copytrade_thread.py``,
``src/trend_strategy.py`` or ``src/bot_c/strategy.py``; bot_thread dispatches
``trend_btc`` -> ``run_trend_cycle`` (:551) and ``tradingagents`` ->
``run_tradingagents_cycle`` (:560), both of which bypass the selectors entirely.

So the subtraction is STRATEGY-CONDITIONAL (see ``shadow_applies_to``). Applying it
to every strategy would strike ETH/USD through on a copytrade bot that really does
trade ETH/USD when its leader does — a brand-new lie.

They are SURFACED here (as blocked reasons ``meme`` / ``untradeable``), never
refactored, copied or moved. Consolidating them into ``quarantined_symbols`` is
Phase 17/18 work, NOT this phase.

Reason precedence (first match wins):
    ``quarantined`` > ``off_universe`` > ``meme`` > ``untradeable``
"""

from __future__ import annotations

from typing import Iterable

from src.universe import entry_allowed, normalize

# Strategies that BYPASS the confluence selectors, and therefore never apply the
# shadow deny-lists. See the module docstring.
_NON_CONFLUENCE = frozenset({"copytrade", "trend_btc", "tradingagents"})


def shadow_applies_to(strategy: str | None) -> bool:
    """Do MEME_CRYPTO / _ALPACA_UNTRADEABLE apply to this strategy?

    True ONLY for the confluence path — the one that actually runs
    ``select_long_candidates`` / ``select_short_candidates``
    (src/bot_thread.py:144-145, :163-164), the sole enforcement site.

    ``copytrade`` / ``trend_btc`` / ``tradingagents`` bypass those selectors, so
    subtracting the shadow sets for them would falsely strike through symbols they
    really do trade (e.g. ETH/USD on Bot E).
    """
    return (strategy or "confluence") not in _NON_CONFLUENCE


def allowlist_for(cfg) -> list[str]:
    """Return the ENTRY allowlist the gate would use for this bot's strategy.

    Mirrors the four gate call sites exactly (see the module docstring). Dispatches
    ONLY on ``cfg.strategy`` — no thread, no BotManager, no DB. Order-stable and
    original spelling preserved.
    """
    strategy = cfg.strategy or "confluence"
    if strategy == "copytrade":
        return list(cfg.all_symbols)
    if strategy == "trend_btc":
        allow = list(cfg.symbols)
        trend = (cfg.trend_symbol or "").strip()
        if trend and normalize(trend) not in {normalize(s) for s in allow}:
            allow.append(trend)
        return allow
    return list(cfg.symbols)


def _load_shadow_sets() -> tuple[frozenset[str], frozenset[str], bool]:
    """Lazily load the two shadow deny-lists.

    Function-local imports: ``src.alpaca_orchestrator`` pulls the Alpaca SDK and
    reads env at import time, so it must never be imported at module scope here.
    A failure is REPORTED (``loaded=False``), never swallowed into an
    over-optimistic answer.
    """
    try:
        from src.alpaca_evaluator import MEME_CRYPTO  # noqa: PLC0415
        from src.alpaca_orchestrator import _ALPACA_UNTRADEABLE  # noqa: PLC0415

        return frozenset(MEME_CRYPTO), frozenset(_ALPACA_UNTRADEABLE), True
    except Exception:
        return frozenset(), frozenset(), False


def _norm_set(values: Iterable[str] | None) -> set[str]:
    return {normalize(v) for v in (values or []) if normalize(v)}


def resolve_universe(
    cfg,
    *,
    exposure: dict[str, dict] | None = None,
    exposure_loaded: bool = True,
    meme: Iterable[str] | None = None,
    untradeable: Iterable[str] | None = None,
) -> dict:
    """Resolve the effective universe for one bot.

    ``exposure`` is keyed by NORMALIZED symbol ->
    ``{"open": int, "recent": int, "display": str}``. ``exposure_loaded=False``
    means the CALLER's exposure query FAILED: ``leak`` will be ``[]`` by
    construction, and the flag is what tells the panel that means UNKNOWN, not
    "no leak".

    ``meme`` / ``untradeable`` are injectable. When BOTH are None the real sets are
    lazily loaded; ``shadow_sets_loaded`` reports whether that succeeded.
    """
    exposure = exposure or {}

    if meme is None and untradeable is None:
        meme_set, untradeable_set, shadow_sets_loaded = _load_shadow_sets()
    else:
        meme_set, untradeable_set, shadow_sets_loaded = meme, untradeable, True

    meme_norm = _norm_set(meme_set)
    untradeable_norm = _norm_set(untradeable_set)

    allow = allowlist_for(cfg)
    quar = list(cfg.quarantined)
    shadow_applied = shadow_applies_to(cfg.strategy)

    # Candidate list: allowlist, then quarantined extras, then anything with
    # exposure. Order-stable, deduped by normalize(); first spelling seen wins
    # (so the allowlist spelling beats the trade-history spelling).
    candidates: list[str] = []
    seen: set[str] = set()
    for sym in allow + quar + [v.get("display", k) for k, v in exposure.items()]:
        key = normalize(sym)
        if key and key not in seen:
            seen.add(key)
            candidates.append(sym)

    effective: list[str] = []
    blocked: list[dict] = []

    for sym in candidates:
        key = normalize(sym)
        ok, reason = entry_allowed(sym, allow, quar)   # THE GATE — never re-derived
        if not ok:
            pass                                        # reason verbatim from the gate
        elif shadow_applied and key in meme_norm:
            ok, reason = False, "meme"
        elif shadow_applied and key in untradeable_norm:
            ok, reason = False, "untradeable"

        if ok:
            effective.append(sym)
            continue

        exp = exposure.get(key) or {}
        blocked.append({
            "symbol": sym,
            "reason": reason,
            "open_positions": int(exp.get("open") or 0),
            "recent_trades": int(exp.get("recent") or 0),
        })

    leak = [
        b["symbol"]
        for b in blocked
        if b["reason"] == "off_universe" and (b["open_positions"] > 0 or b["recent_trades"] > 0)
    ]

    return {
        "bot_id": cfg.bot_id,
        "strategy": cfg.strategy or "confluence",
        "asset_class": cfg.asset_class or "crypto",
        "allowlist": allow,
        "quarantined": quar,
        "effective": effective,
        "blocked": blocked,
        "starvation": not effective,
        "leak": leak,
        "shadow_applied": shadow_applied,
        "shadow_sets_loaded": bool(shadow_sets_loaded),
        "exposure_loaded": bool(exposure_loaded),
    }

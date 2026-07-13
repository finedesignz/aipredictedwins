"""Deterministic synthetic 1H bars for Phase-18 engine/CLI tests.

NOT the sweep's data (that is 18-02's real Alpaca cache in data/backtest_bars).
These are unit-test bars: a pure closed-form price path — no RNG, no I/O — chosen
so the fixture universe actually produces entries at confluence 3 AND 4, and
carries signals both below and above the 65.0 RSI ceiling.
"""
from __future__ import annotations

import datetime
import math

START = datetime.datetime(2025, 11, 1)
START_ISO = "2025-11-01"
END_ISO = "2026-01-31"


def synth_bars(n: int = 800, base: float = 100.0, amp: float = 0.04,
               period: int = 29, drift: float = 0.0009,
               phase: float = 0.0) -> list[dict]:
    bars: list[dict] = []
    for i in range(n):
        p = base * (1 + drift * i) * (1 + amp * math.sin(2 * math.pi * (i + phase) / period))
        ts = (START + datetime.timedelta(hours=i)).isoformat() + "+00:00"
        bars.append({
            "timestamp": ts,
            "open": p, "high": p * 1.004, "low": p * 0.996, "close": p,
            "volume": 1000.0 + (i % 7) * 50,
            "vwap": p * (1 + 0.001 * math.cos(2 * math.pi * i / period)),
        })
    return bars


def synth_universe() -> dict[str, list[dict]]:
    return {
        "BTC/USD": synth_bars(),
        "ETH/USD": synth_bars(base=50.0, phase=11),
    }

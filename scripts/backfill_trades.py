"""One-shot stale-trade backfill entrypoint (PNL-05).

Resolves genuinely-stale ``alpaca_trades`` rows to their true terminal state
from Alpaca history, writing realized P&L via the Phase-12 path. Dry-run is the
DEFAULT (no writes); pass ``--apply`` to persist. NEVER deletes rows — all logic
lives in ``src.backfill.backfill``.

    python scripts/backfill_trades.py            # dry-run preview
    python scripts/backfill_trades.py --apply    # persist resolved rows
    python -m scripts.backfill_trades
"""
import argparse
import sys

from src.backfill import backfill


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot stale-trade backfill (PNL-05).")
    ap.add_argument(
        "--apply", action="store_true",
        help="Actually write resolved rows. Default: dry-run (no writes).",
    )
    args = ap.parse_args()

    results = backfill(apply=args.apply)

    print(f"{'Bot':<6} {'Resolved':>9} {'Unchanged':>10} {'Unresolvable':>13} {'Residue':>8}")
    print("-" * 50)
    totals = {"resolved": 0, "unchanged": 0, "unresolvable": 0, "residue": 0}
    for bot_id, c in results:
        for k in totals:
            totals[k] += c[k]
        print(f"{bot_id:<6} {c['resolved']:>9} {c['unchanged']:>10} "
              f"{c['unresolvable']:>13} {c['residue']:>8}")
    print("-" * 50)
    print(f"{'ALL':<6} {totals['resolved']:>9} {totals['unchanged']:>10} "
          f"{totals['unresolvable']:>13} {totals['residue']:>8}")

    if not args.apply:
        print("\nDRY RUN — no rows written. Re-run with --apply to persist.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

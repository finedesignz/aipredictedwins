"""Reconcile trade-log realized P&L vs Alpaca realized P&L per bot (PNL-03).

Runs the per-bot reconciliation against each enabled bot's OWN paper account,
persists the latest result row, and prints a per-bot delta + PASS/FAIL line.
Read-only against Alpaca; the only DB write is the reconciliation row (done
inside the driver). Exits non-zero if any bot breaches (cron/CI signal).

    python scripts/reconcile.py
    python -m scripts.reconcile
"""
import sys

from src.reconciliation import reconcile


def main() -> int:
    results = reconcile()
    if not results:
        print("No enabled bots to reconcile.")
        return 0

    any_breach = False
    print(f"{'Bot':<6} {'Delta':>14} {'Tolerance':>12}  Result")
    print("-" * 44)
    for bot_id, result in results:
        status = "PASS" if result["within_tolerance"] else "FAIL"
        if not result["within_tolerance"]:
            any_breach = True
        print(
            f"{bot_id:<6} ${result['delta']:>+12,.2f} ${result['tolerance']:>10,.2f}  {status}"
        )
    return 1 if any_breach else 0


if __name__ == "__main__":
    sys.exit(main())

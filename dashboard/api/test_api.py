"""
Smoke test for the dashboard API.

Verifies that all modules import correctly and the FastAPI app can be
instantiated with all routes mounted. Does NOT require a live database --
it only checks that the Python import graph is sound.

Run:
    python -m dashboard.api.test_api
"""

import sys


def test_imports():
    """Verify all dashboard API modules can be imported."""
    errors: list[str] = []

    modules = [
        "dashboard.api.db",
        "dashboard.api.models",
        "dashboard.api.routes.portfolio",
        "dashboard.api.routes.positions",
        "dashboard.api.routes.trades",
        "dashboard.api.routes.signals",
        "dashboard.api.routes.risk_gate",
        "dashboard.api.routes.settings",
        "dashboard.api.routes.activity",
        "dashboard.api.main",
    ]

    for module_name in modules:
        try:
            __import__(module_name)
            print(f"  OK  {module_name}")
        except Exception as exc:
            errors.append(f"  FAIL  {module_name}: {exc}")
            print(f"  FAIL  {module_name}: {exc}")

    return errors


def test_app_routes():
    """Verify the FastAPI app has all expected routes registered."""
    from main import app

    routes = [r.path for r in app.routes if hasattr(r, "path")]
    expected = [
        "/api/portfolio",
        "/api/positions/open",
        "/api/positions/closed",
        "/api/trades",
        "/api/trades/csv",
        "/api/signals",
        "/api/risk-gate",
        "/api/risk-gate/{record_id}",
        "/api/settings",
        "/api/activity/stream",
        "/api/health",
    ]

    missing: list[str] = []
    for path in expected:
        if path not in routes:
            missing.append(path)
            print(f"  MISSING  {path}")
        else:
            print(f"  FOUND    {path}")

    return missing


def main():
    print("=== Dashboard API Smoke Test ===\n")

    print("1. Import check:")
    import_errors = test_imports()

    print("\n2. Route check:")
    missing_routes = test_app_routes()

    print()
    if import_errors or missing_routes:
        print("FAILED -- see errors above")
        sys.exit(1)
    else:
        print("ALL CHECKS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    main()

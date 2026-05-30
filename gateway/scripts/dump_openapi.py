"""Dump app.openapi() to docs/openapi.json — no server boot required.

Imports the FastAPI app and calls .openapi() in-process. Avoids the network
round-trip + uvicorn startup that a full `curl :9122/openapi.json` would need.
Module-load side effects are sidestepped via harmless placeholder env vars.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Placeholder env so any module-load defaults don't crash on a fresh checkout.
os.environ.setdefault("PROJECTS_DIR", "/tmp/aipredictedwins-docs-build")
os.environ.setdefault("CLI_TIMEOUT", "300")
os.environ.setdefault("DEFAULT_PROJECT", "mirofish")

ROOT = Path(__file__).resolve().parent.parent  # gateway/
sys.path.insert(0, str(ROOT))

from main import app  # noqa: E402

OUT = ROOT / "docs" / "openapi.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
spec = app.openapi()
OUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")

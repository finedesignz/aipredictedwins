.PHONY: docs-sync

# Regenerate docs/openapi.json from the in-process FastAPI app.
# Idempotent: re-running produces a byte-identical file unless routes changed.
docs-sync:
	python scripts/dump_openapi.py

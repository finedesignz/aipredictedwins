# Docs Standardization Plan — aipredictedwins

## Goal
Wire Scalar UI on top of FastAPI's built-in OpenAPI for gateway (9122) + Next.js dashboard (9123).

## Current state
- Root `README.md`, `CLAUDE.md`, `docs/`.
- FastAPI gateway + Next.js dashboard.
- FastAPI emits OpenAPI natively at `/openapi.json` (default); needs Scalar mounted at `/docs` (replacing Swagger).

## Target state
- Gateway: `/openapi.json` (native FastAPI) + `/docs` (Scalar via `scalar-fastapi`).
- Dashboard: Storybook + `docs/components.md`.
- `docs/api.md` regenerated from gateway's openapi.json.

## Tasks
1. Gateway `requirements.txt` — add `scalar-fastapi`.
2. Gateway `main.py` — disable FastAPI's default swagger (`docs_url=None`), mount `Scalar` at `/docs`.
3. Ensure every Pydantic model + path-op has docstring/examples (drift CI flags `TODO: document`).
4. Dashboard — `npx storybook@latest init`; 2 stories.
5. Root `Makefile` `docs:sync` — `curl :9122/openapi.json > docs/openapi.json && widdershins docs/openapi.json -o docs/api.md`.
6. `.github/workflows/docs-drift.yml` — `stack: fastapi`, `start_cmd: 'uvicorn gateway.main:app --port 9122'`, `health_url: 'http://localhost:9122/healthz'`.

## Acceptance
- `make docs:sync` clean.
- `/docs` renders Scalar.
- Storybook builds.

## Effort: S

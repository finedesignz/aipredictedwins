# Claude Code Bridge (gateway)

OpenAI-compatible API backed by the Claude CLI subprocess. Sub-app of `aipredictedwins`.

**Port:** 9122

## API docs convention

- OpenAPI 3.1 spec at `GET /openapi.json` (in-process, FastAPI-emitted).
- Scalar UI at `GET /docs` (Swagger + ReDoc disabled).
- Routes use `response_model=<PydanticModel>` + `tags=[...]` + `summary=...`. See `main.py::health` as the canonical reference.
- `docs/openapi.json` is a committed snapshot; `make docs-sync` regenerates it in-process.
- CI guards drift in `.github/workflows/docs-drift.yml`.

## Regenerate docs

```bash
cd gateway
make docs-sync
```

## Run locally

```bash
uvicorn main:app --port 9122 --reload
```

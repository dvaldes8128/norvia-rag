# Norvia RAG

Multi-tenant RAG assistant for insurance policy and circular lookups, with async
ingestion and end-to-end traceability.

**Stack:** FastAPI · Celery (Redis broker) · PostgreSQL + pgvector · React (Vite + TS) · OpenTelemetry

> Technical test for TopDevCrew. Requirements are tracked in [`SPEC.md`](./SPEC.md);
> design decisions and trade-offs in [`DECISIONS.md`](./DECISIONS.md).

## Architecture

```
          upload PDF                     ask question
Tenant ─────────────▶ FastAPI ─────┐     ─────────────▶ FastAPI
                         │ enqueue  │                       │ retrieve (tenant-scoped, hybrid)
                         ▼          │                       ▼
                     Celery worker ─┘                     LLM (fake | real adapter)
                     extract → chunk → embed → upsert        │
                         │                                   ▼
                         ▼                        validated answer + verifiable citations
                 PostgreSQL + pgvector  ◀───────────────────┘

Observability: one OpenTelemetry trace spans API → Celery (context propagated over Redis)
→ DB query → LLM call.
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000  (health: `/health`)
- Frontend: http://localhost:5173

Everything runs with **deterministic fake** LLM + embedding providers by default — no
external API keys required. Set `LLM_PROVIDER=real` / `EMBEDDINGS_PROVIDER=real` and the
`REAL_*` vars to use the custom real adapter.

## Tests

```bash
cd backend
uv sync --all-extras --dev
uv run pytest -q          # unit + integration (integration uses the Compose Postgres)
```

## Evaluation

```bash
cd backend
uv run python -m eval.run   # recall@k over the synthetic corpus → reproducible report
```

## Repository layout

```
backend/    FastAPI app, Celery workers, ingestion/retrieval/qa, providers, tests, corpus, eval
frontend/   Vite + React + TypeScript SPA (upload, document status, chat with citations)
infra        docker-compose.yml, .github/workflows/ci.yml
```

## Status

Scaffolding in place. See `SPEC.md` §8 for the requirement → implementation checklist.

- [ ] Backend endpoints, ingestion pipeline, retrieval, QA
- [ ] Provider abstraction (fake + real adapter)
- [ ] Frontend (upload / status / chat)
- [ ] Tests (unit, integration, tenant isolation)
- [ ] OpenTelemetry end-to-end trace
- [ ] Evaluation + synthetic corpus
- [ ] CI green

## Known limitations

_To be documented as the project progresses._

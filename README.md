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

## API (authenticated)

Auth: `X-API-Key: <key>` (see `TENANT_API_KEYS` in `.env.example`) **or**
`Authorization: Bearer <jwt>` from `POST /auth/token`.

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/auth/token` | Exchange API key → JWT |
| POST | `/upload` | Upload PDF → `202 {job_id}` (Celery ingest) |
| GET | `/jobs/{job_id}` | Job status (`pending\|processing\|completed\|failed`) |
| GET | `/jobs` | Recent jobs for the tenant |
| POST | `/ask` | Question → answer + verifiable citations + confidence |
| POST | `/ask/stream` | Streaming answer + meta trailer |
| GET | `/health` | Liveness |

## Status

See `SPEC.md` §8 for the requirement → implementation checklist.

- [x] Backend endpoints (upload / jobs / ask), ingestion pipeline, hybrid retrieval, QA
- [x] Provider abstraction (fake + real adapter)
- [x] Frontend (upload / status polling / chat with citations)
- [ ] Tests (integration + tenant isolation against Compose Postgres)
- [ ] OpenTelemetry end-to-end trace
- [ ] Evaluation + synthetic corpus
- [x] CI workflow present (unit tests + lint)

## Known limitations

- Chunk text is reconstructed from alphanumeric tokens (lowercased) — citations work
  but lose original punctuation/casing. Planned fix: slice original page text by offsets.
- Integration / RLS isolation tests and OpenTelemetry wiring are still pending.
- Frontend is wired (API key → JWT, upload, job polling, `/ask` + citations).

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

CI is the source of truth (see `AGENTS.md`): unit tests run without Postgres; integration
tests start Compose Postgres (`docker compose up -d db`), migrate, then exercise RLS +
ingest/retrieve + recall@k.

```bash
# What CI runs (prefer waiting for GitHub Actions rather than local runs):
cd backend && uv sync --all-extras --dev
uv run pytest tests/unit -q
# with Compose Postgres up + DATABASE_URL/ADMIN_DATABASE_URL pointing at localhost:
uv run pytest tests/integration -q
```

## Evaluation

```bash
# Requires migrated Compose Postgres (same URLs as integration tests).
cd backend
uv run python -m corpus.build_pdfs
uv run python -m eval.run --k 5 --fail-under 0.8
# → backend/eval/reports/latest.md
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
- [x] Tests (unit + integration + RLS isolation against Compose Postgres)
- [ ] OpenTelemetry end-to-end trace
- [x] Evaluation + synthetic corpus (recall@k report via `python -m eval.run`)
- [x] CI workflow (unit, integration+eval on Compose Postgres, frontend lint/build)

## Known limitations

- Chunk text is reconstructed from alphanumeric tokens (lowercased) — citations work
  but lose original punctuation/casing. Planned fix: slice original page text by offsets.
- OpenTelemetry end-to-end wiring is still pending.
- Frontend is wired (API key → JWT, upload, job polling, `/ask` + citations).

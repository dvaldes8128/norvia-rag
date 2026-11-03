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

## Observability (OpenTelemetry + structured logs)

One **OpenTelemetry trace** spans the whole request path and — thanks to
`CeleryInstrumentor` auto-propagating the trace context across the Redis broker — worker
spans are **children of the API span** that enqueued the task:

```
API request (FastAPI span)
  └─ Celery publish span            (context injected into the task message on /upload)
       └─ Celery task run span      (worker; child across the broker)
            ├─ DB query spans        (SQLAlchemyInstrumentor)
            └─ ingestion.embed_chunks (manual span; embeddings)

POST /ask (FastAPI span)
  ├─ qa.retrieve                     (manual span)
  │    ├─ retrieval.embed_query      (manual span; embeddings)
  │    └─ SELECT … chunks            (DB query span)
  └─ qa.llm.generate                 (manual span; llm.prompt_tokens / completion_tokens)
```

### Trace setup

- `app/core/telemetry.py` → idempotent `setup_telemetry(service_name)` configures a
  `TracerProvider`. Exporter is chosen from settings: **console by default**
  (`OTEL_TRACES_EXPORTER=console`) or **OTLP** when `OTEL_EXPORTER_OTLP_ENDPOINT` is set.
- Instrumentations: `FastAPIInstrumentor` (API startup), `CeleryInstrumentor` (both
  producer and worker, so context crosses the broker), `SQLAlchemyInstrumentor` (engine
  in `app/db/base.py`).
- Manual spans add the useful attributes: `tenant_id`, per-stage `*latency_ms`,
  `retrieval.chunk_count`, and `llm.prompt_tokens` / `llm.completion_tokens`.

> SQLAlchemy is pinned `< 2.1` because `opentelemetry-instrumentation-sqlalchemy`
> only instruments `sqlalchemy < 2.1.0`; without the pin the DB query spans vanish.

### Structured logging + correlation id

- `app/core/logging.py` configures **structlog** (JSON lines). An ASGI middleware
  (`app/core/middleware.py`) reads `X-Request-ID` (or generates a UUID), binds it via
  `contextvars`, echoes it back on the `X-Request-ID` response header, and the id flows
  into **every** log line as `correlation_id`.
- The id is **propagated into Celery**: `/upload` passes it as a `correlation_id` kwarg to
  `process_ingestion`, and the worker binds it — so API and worker logs for one ingestion
  share the same id. `tenant_id` and `job_id` are bound where relevant.
- **Redaction (Q6.2):** we never log full document content or full user questions. The
  `redacted_text()` helper logs only `*_len`, an 8-char `*_sha256` and a short `*_preview`.

### Reproduce the trace locally (E6)

```bash
cp .env.example .env            # OTEL_TRACES_EXPORTER=console by default
docker compose up --build
# 1) Get a token and upload a PDF (fake providers, no external keys):
curl -s -X POST localhost:8000/upload \
  -H 'X-API-Key: devkey-acme' -F 'file=@backend/corpus/documents/<some>.pdf'
# 2) Ask a question:
curl -s -X POST localhost:8000/ask \
  -H 'X-API-Key: devkey-acme' -H 'Content-Type: application/json' \
  -d '{"question":"What is the water damage limit?"}'
# 3) Watch console-exported spans in the api + worker logs:
docker compose logs -f api worker
```

### Captured console trace (span tree)

All spans below share one `trace_id` (`0x61f5…93bb`); `parent_id` links reconstruct the
tree. Key attributes highlighted:

```
POST /ask                 span=0x9d78… parent=null        tenant_id=acme correlation_id=5f3b1e9c-…
├─ qa.retrieve            span=0xd030… parent=0x9d78…      tenant_id=acme retrieval.latency_ms=12.4 retrieval.chunk_count=5
│  ├─ retrieval.embed_query span=0xcd37… parent=0xd030…    embeddings.input_count=1 embeddings.dim=768
│  └─ SELECT norvia.chunks  span=0x06ea… parent=0xd030…    db.system=postgresql
└─ qa.llm.generate        span=0xb1c7… parent=0x9d78…      llm.model=fake-deterministic-1 llm.prompt_tokens=19 llm.completion_tokens=11
```

Raw `ConsoleSpanExporter` output for the LLM span (verbatim):

```json
{
    "name": "qa.llm.generate",
    "context": {
        "trace_id": "0x61f5a359572e2754ce9fcab663be93bb",
        "span_id": "0xb1c7bf5c52d70817"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": "0x9d78efdf85bb9dd6",
    "attributes": {
        "tenant_id": "acme",
        "llm.latency_ms": 3.1,
        "llm.model": "fake-deterministic-1",
        "llm.prompt_tokens": 19,
        "llm.completion_tokens": 11
    },
    "resource": { "attributes": { "service.name": "norvia-rag" } }
}
```

## Status

See `SPEC.md` §8 for the requirement → implementation checklist.

- [x] Backend endpoints (upload / jobs / ask), ingestion pipeline, hybrid retrieval, QA
- [x] Provider abstraction (fake + real adapter)
- [x] Frontend (upload / status polling / chat with citations)
- [x] Tests (unit + integration + RLS isolation against Compose Postgres)
- [x] OpenTelemetry end-to-end trace (API → Celery → DB → LLM, context over Redis)
- [x] Structured logging (structlog) with correlation id + content redaction
- [x] Evaluation + synthetic corpus (recall@k report via `python -m eval.run`)
- [x] CI workflow (unit, integration+eval on Compose Postgres, frontend lint/build)

## Known limitations

- Chunk text is reconstructed from alphanumeric tokens (lowercased) — citations work
  but lose original punctuation/casing. Planned fix: slice original page text by offsets.
- Traces export to **console** by default (set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship to a
  collector); no bundled Jaeger/Tempo in the compose stack to keep it light.
- Frontend is wired (API key → JWT, upload, job polling, `/ask` + citations).
- **Document versioning / delete (D3):** policy is decided in `DECISIONS.md` (confirm
  replace-by-filename, soft-delete old chunks, bump `version`, `DELETE` soft via
  `deleted_at`). **Not implemented in code yet** — ingest still keys only on
  `(tenant_id, content_hash)`; no confirm flow, no `deleted_at`, no delete endpoint.
  Same-hash re-upload remains idempotent.

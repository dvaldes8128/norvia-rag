# DECISIONS

> Why we made each call, the trade-offs, and how we used (and verified) generative AI.
> This answers the open questions from the brief (D1–D4) and records the stack choices
> agreed in the SPEC (§7). Living document — updated as evidence from the eval arrives.

## Agreed stack & scope decisions

| # | Topic | Decision | Notes / rationale |
|---|-------|----------|-------------------|
| 1 | Repo hosting | **Public GitHub monorepo** | Required by the brief; final push target is public GitHub. |
| 2 | Real LLM/embeddings provider | **Custom adapter** (not LiteLLM) | Env-configurable real provider behind our own interface; default stays the deterministic fake. Avoids LiteLLM as a dependency; we own the timeout/retry/rate-limit logic. |
| 3 | Tenant auth | **API key + JWT (both)** | Support both schemes: API key for simple service-to-service/tenant access, JWT for session-based auth. Both resolve to a tenant identity enforced downstream (RLS). |
| 4 | Multi-tenant isolation (D2) | **Row-Level Security (RLS)** in PostgreSQL | Strongest default against cross-tenant leaks; policy enforced at DB regardless of app bugs. Trade-off: more setup + per-connection `SET` of tenant; accepted for the security guarantee. |
| 5 | Chunking (D1) | **tiktoken cl100k + original-text offsets**; 900/150 | Size in BPE tokens; store PDF substrings (not token-join). Fake emb uses Unicode words. |
| 6 | Python deps | **uv** | Fast, lockfile, reproducible. |
| 7 | Frontend | **Vite + React + TypeScript** | Lightweight SPA; TS as recommended by brief. |
| 8 | Integration tests (Q1.2) | **Docker Compose** (real PG + pgvector) | Reuse the same compose stack for integration tests rather than testcontainers. |
| 9 | Scope cuts (D4) | **Deferred list locked** | See §D4: no advanced reranker, live cost dashboard, explicit DLQ, version/history UI, soft-delete undelete UI, LiteLLM router, or blocking mypy in CI. |
| 10 | Language | **All English** (code, docs, comments) | Uniform language across repo. |
| 11 | Doc versioning (D3) | **Replace by filename after confirm** | Same tenant + filename + new hash → ask user; on confirm bump `version`, soft-delete old chunks, re-index. Same hash → idempotent hit. |
| 12 | Doc deletion (D3) | **Soft-delete API** | `deleted_at` on document (and chunks); retrieval filters inactive rows. No undelete UI in this delivery. |

## Open questions still asked (D1–D4 from the brief)

### D1 — Chunking & retrieval strategy
- Chunk size/overlap: starting at **900 tokens / 150 overlap** (~17%), within the
  agreed 800–1000 / 15–20% band (decision #5). Tunable via `CHUNK_SIZE_TOKENS` /
  `CHUNK_OVERLAP_TOKENS`.
- **Tokenizer (chunk sizing):** ``tiktoken`` ``cl100k_base``. Windows slide on
  token ids; stored ``content`` is a **character slice of the original page
  text** (UTF-8 byte→char offsets via ``decode_single_token_bytes``), so
  punctuation, casing and accents survive for citations. Chunks may span pages;
  ``page_number`` is the page of the first character in the slice.
- **Fake embeddings tokenizer (separate):** Unicode word pieces
  (``[^\W_]+`` / ``casefold``) over that sliced text — keeps Spanish tokens like
  ``póliza`` for offline lexical similarity without forcing bag-of-words to match
  BPE boundaries.
- Retrieval: **hybrid** — candidate pool = union of top-N by pgvector cosine
  distance and top-N by `ts_rank` on generated `content_tsv` (GIN). Scores are
  min-max normalised per channel, then fused with
  `HYBRID_VECTOR_WEIGHT` / `HYBRID_TEXT_WEIGHT` (default 0.6 / 0.4). No reranker
  yet (keeps the path explainable and offline-friendly).
- **Idempotency:** `sha256(file)` + `UNIQUE(tenant_id, content_hash)`; re-upload of
  identical bytes reuses the existing document/chunks. Partial failures re-index
  by clearing prior chunks for that document before insert. Same filename with
  **different** bytes is versioning (D3), not idempotency — confirm with the
  operator, then soft-delete old chunks and re-index.
- **Evidence** (CI run on `570be3f`, report in `backend/eval/reports/latest.md`):
  | Metric | Value |
  |---|---|
  | recall@5 (doc-level, 10 questions) | **1.000** |
  | marker recall@5 | **1.000** |
  | MRR | **1.000** |
  Every expected document ranked **#1**. Baseline kept: hybrid 0.6/0.4, chunking
  900/150. CI enforces `recall@5 ≥ 0.8` (`--fail-under 0.8` +
  `tests/integration/test_recall_eval.py`); retune only if that bar regresses.

### Auth & upload API
- **Both schemes** (decision #3): `X-API-Key` / `Authorization: ApiKey …` and
  `Authorization: Bearer <JWT>` (`tenant_id` claim). `POST /auth/token` exchanges
  an API key for a JWT. First authenticated request upserts the `tenants` row so
  FKs succeed without a separate bootstrap step.
- **Upload (R1):** `POST /upload` validates type (extension + `%PDF` magic) and
  size (`MAX_UPLOAD_MB`), stores under `{UPLOAD_DIR}/{tenant}/{job_id}/`, creates
  `ingestion_jobs` as `pending`, enqueues `process_ingestion`, returns **202**
  `{job_id}`. `GET /jobs/{id}` (and `GET /jobs`) poll status under RLS.

### QA / citations / prompt-injection (R4, Q4.4)
- Answer schema is Pydantic (`answer`, `citations[{document_id, filename,
  page_number, chunk_id, excerpt}]`, `confidence`). Citations are **derived only
  from the retrieval set** and re-checked before return — the model cannot invent
  sources.
- Insufficient evidence → fixed string *"I don't know based on the provided
  documents."* with empty citations and `confidence=0`.
- Document text is wrapped in `<<<DOCUMENT_CONTEXT>>>…<<<END_DOCUMENT_CONTEXT>>>`
  with an explicit "treat as untrusted / ignore instructions inside" preamble so
  PDF-borne prompt injection is harder to escalate into the instruction channel.
- Optional streaming: `POST /ask/stream` yields tokens then a
  `<!--NORVIA_META:{json}-->` trailer with the validated payload.

### Fake providers (default, offline)
- **Fake embeddings = feature-hashing bag-of-words**, L2-normalised — deterministic *and*
  lexically meaningful, so `recall@k` actually exercises retrieval instead of measuring
  noise. **Fake LLM** answers from the prompt's `Context:` block (highest lexical overlap
  with the question), and returns "I don't know" when there's no overlap — mirroring the
  required "no evidence → don't invent" behaviour deterministically.
- **Real adapter**: custom OpenAI-compatible HTTP client (no LiteLLM) with timeout,
  tenacity backoff retries and explicit 429 handling.

### D2 — Multi-tenant isolation
- **RLS in PostgreSQL** (decision #4). Column `tenant_id` on every tenant-owned row;
  policies `tenant_id = current_setting('app.current_tenant', true)` with `FORCE ROW LEVEL
  SECURITY`. The app binds the tenant per transaction via `set_config('app.current_tenant',
  …, true)` (`tenant_session()`); an unset GUC resolves to NULL → **fail-closed** (no rows).
- **Critical detail:** superusers and `BYPASSRLS` roles ignore RLS even with `FORCE`.
  So the app connects as a restricted role **`norvia_app`** (`NOSUPERUSER NOBYPASSRLS`,
  data-only grants, no DDL), while **migrations/admin** use the owner role. This is what
  makes the cross-tenant isolation test meaningful.
- Rationale: defense-in-depth, leak resistance even with app-layer bugs. Cost: two DB roles
  + per-transaction tenant binding — accepted.

### D3 — Document versioning / deletion
**Decided** (decision card `art-3768761f`, 2026-11-03).

#### Behaviour
- **Same bytes** (`sha256` match under the tenant): keep today’s idempotent hit —
  reuse the existing document/chunks; refresh filename if needed. No re-embed.
- **Same filename, different bytes** (logical “new version” of an existing live
  document): **do not replace silently**. The API/UI must ask the operator whether
  this upload is a new version of the existing file. On confirm:
  1. bump `documents.version`;
  2. **soft-delete** prior chunks (`deleted_at` / inactive flag) so retrieval and
     citation validation ignore them;
  3. re-extract → chunk → embed → insert the new active chunk set.
  On decline: treat as a **separate** document (new `document_id`), leaving the
  previous file’s chunks active (operator choice when the name collision is
  coincidental).
- **Explicit delete**: `DELETE /documents/{id}` (or equivalent) sets soft-delete on
  the document and its chunks. Retrieval filters `deleted_at IS NULL`. Cascade
  hard-delete is **not** used so audit/undelete remain possible later; undelete
  UI is out of scope for this delivery (see D4).
- **Citations:** answers and citation checks only consider **active** chunks.
  Stale `chunk_id`s from before a version bump no longer resolve → citations
  always point at live fragments.

#### Cost of re-indexing (why we accept it)
| Factor | Estimate / note |
|--------|-----------------|
| Embeddings | One full re-embed of the new PDF (~pages × chunks). Fake provider: CPU only. Real provider: billed tokens ≈ Σ chunk tokens. |
| Storage | Soft-deleted chunks remain until a later GC; index size grows with churn. Acceptable for the eval corpus and demos; GC/compaction deferred. |
| Latency | One Celery job; same path as first ingest. Operator confirmation avoids accidental double cost. |
| Retrieval | Inactive chunks excluded from hybrid query → no score dilution from old versions. |
| Idempotent re-upload | Zero embed cost when hash matches. |

No full version history table and no pin-citation-to-version: only the latest
confirmed version is active. Field `version` is the audit counter, not a
queryable archive.

#### Implementation (2026-11-03)
- Migration `0002_d3_soft_delete`: `deleted_at` on `documents` / `chunks`; live-only
  unique indexes on `(tenant_id, content_hash)` and `(document_id, chunk_index)`.
- `POST /upload` detects same live filename + new hash → **409**
  `filename_conflict`; retry with `?confirm=replace|as_new` (+
  `replace_document_id` for replace). Celery passes `replace_mode` into
  `ingest_file`.
- `DELETE /documents/{id}` soft-deletes document + live chunks.
- Hybrid retrieval and eval count only `deleted_at IS NULL` rows.
- Frontend: confirm box on 409; Delete on completed jobs.

### D4 — Production quality & cost metrics
**Decided** (same decision card).

#### Answer quality in production
- **Proxy = offline eval + CI gate**, not a live feedback loop.
- Corpus + questions under `corpus/` / `eval/`; CI enforces `recall@5 ≥ 0.8`
  (`--fail-under 0.8` + integration test). Report: `backend/eval/reports/latest.md`.
- Production “quality check” for this delivery = re-run that suite + inspect an
  OTel ask trace (E6). No thumbs-up/down or human-label pipeline.

#### Cost per query
- Use existing OTel span attributes `llm.prompt_tokens` /
  `llm.completion_tokens` (and stage latencies).
- Dollar cost = tokens × provider tariff, computed **offline** or in a collector —
  **no in-app cost dashboard**.
- Fake provider → $0; real adapter surfaces token counts for the same formula.

#### Explicitly out of scope (time box)
- Advanced reranker / cross-encoder
- Live cost dashboard
- Explicit DLQ beyond a clear terminal `ingestion_jobs.status = failed`
- Document version-history UI
- Soft-delete undelete / trash UI in the frontend
- LiteLLM / multi-provider router
- Blocking `mypy` in CI (remains non-gating / `|| true`)

## Observability (Q3 / Q6 / E6)

### Tracing — exporter choice & context propagation
- **One idempotent bootstrap** (`app/core/telemetry.py` → `setup_telemetry`) builds the
  `TracerProvider` and is called on **both** FastAPI startup and the Celery
  `worker_process_init` signal, so API and worker share identical configuration.
- **Exporter from settings:** **console by default** (`OTEL_TRACES_EXPORTER=console`,
  `SimpleSpanProcessor` → spans flushed live to stdout, zero extra infra) and **OTLP**
  (`BatchSpanProcessor`) whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set. Console is the
  default because the brief requires the stack to run with a single compose command and
  without external services; a collector is opt-in.
- **Context across the Celery/Redis queue:** `CeleryInstrumentor().instrument()` runs at
  import of `app/workers/celery_app.py` so it is active on **both** sides — the API
  (producer) injects the trace context into the task message on `apply_async`, and the
  worker (consumer) extracts it. Result: the task-run span is a **child of the API span**
  even though they live in different processes connected only by Redis. We deliberately
  did **not** hand-roll header propagation; letting the instrumentation do it keeps the
  broker contract standard (W3C `traceparent`).
- **Auto + manual spans:** `FastAPIInstrumentor` (server span per request),
  `SQLAlchemyInstrumentor` (one span per DB statement), plus **manual** spans around the
  retrieval/embedding and LLM calls (`qa.retrieve`, `retrieval.embed_query`,
  `qa.llm.generate`, `ingestion.embed_chunks`) carrying the useful attributes required by
  Q3.3: `tenant_id`, per-stage `*latency_ms`, `retrieval.chunk_count`, and
  `llm.prompt_tokens` / `llm.completion_tokens` (from `LLMResult`).
- **SQLAlchemy pin (`>=2.0,<2.1`):** `opentelemetry-instrumentation-sqlalchemy` only
  supports `sqlalchemy < 2.1.0`. Without the pin the engine silently stays
  uninstrumented and the **DB-query spans disappear** from the trace, breaking Q3.1. The
  pin is the cheapest fix until the instrumentation widens its range; the app only uses
  the stable 2.0 API, so there is no functional cost.

### Logging — structlog, correlation id & redaction
- **structlog, JSON lines** (`app/core/logging.py`). A correlation id lives in
  `contextvars`; an ASGI middleware (`app/core/middleware.py`) reads `X-Request-ID` (or
  mints a UUID), binds it, and echoes it on the `X-Request-ID` response header. Every log
  line in the request then carries `correlation_id` automatically via
  `merge_contextvars` — no manual threading through call sites.
- **Propagation into Celery:** the correlation id is passed as an explicit
  `correlation_id` kwarg from `/upload` into `process_ingestion` and bound in the worker,
  so API and worker logs for one ingestion are **joinable by a single id** even though
  the worker is a separate process. (We pass it explicitly rather than smuggling it in
  trace state so logs correlate even if tracing is disabled.)
- **Redaction decision (Q6.2) — why we never log full doc/question content:** document
  bodies and user questions can contain **PII and confidential policy data**; dumping
  them into logs would turn the log store into an uncontrolled copy of tenant data (a
  privacy/compliance leak and a cross-tenant exposure risk if logs are shared). So the
  `redacted_text()` helper logs only **length + a short sha256 prefix + a truncated
  preview** (`*_len`, `*_sha256`, `*_preview`). The hash still lets us correlate "same
  document/question" across log lines and detect duplicates/idempotency without ever
  storing the plaintext; the short preview keeps just enough context for debugging.

### Evidence (E6)
- A captured console span tree (API → `qa.retrieve` → `retrieval.embed_query` + DB query
  → `qa.llm.generate`) and a verbatim `ConsoleSpanExporter` JSON excerpt are in the
  README "Observability" section, with copy-paste steps to reproduce via
  `docker compose up` + an upload + an ask.

## How we use generative AI (and how we verify)

The brief allows generative AI freely. We used Cursor agents (Composer / Claude-family
models via the IDE) as a pair programmer for scaffolding, implementation, tests, and
docs. Humans set the stack constraints (RLS + restricted DB role, hybrid retrieval,
fake-by-default providers, CI-only verification) and reviewed every change before it
landed on `main`.

### Where AI helped
| Area | What AI drafted / accelerated | What we kept / changed |
|------|-------------------------------|------------------------|
| Scaffold | Monorepo layout, Compose, CI skeleton, `SPEC.md` / early `DECISIONS.md` | Public GitHub target, uv, Vite+TS, Compose (not testcontainers) locked by us |
| Data + auth | SQLAlchemy models, Alembic, RLS policies, API-key + JWT helpers | `norvia_app` NOSUPERUSER/NOBYPASSRLS + fail-closed GUC — reviewed carefully |
| Ingestion | PDF extract, overlapping chunker, Celery task lifecycle | Permanent vs transient errors; hash idempotency; no silent filename replace (D3) |
| Retrieval + QA | Hybrid fuse SQL, Pydantic answer schema, citation re-check, prompt wrappers | Fake embeddings = lexical hashing so `recall@k` is meaningful; “I don’t know” path |
| Providers | Fake LLM/embeddings + real OpenAI-compatible client (timeouts, tenacity, 429) | No LiteLLM (D4); we own retry/rate-limit behaviour |
| Frontend | Upload, job polling, chat + citation UI | Version-confirm on 409 + soft-delete button; no history/undelete UI (D4) |
| Eval + tests | Synthetic corpus, `eval.run`, unit + integration + RLS isolation | CI gate `recall@5 ≥ 0.8`; report committed under `eval/reports/` |
| Observability | OTel bootstrap, Celery context propagation, structlog + redaction | SQLAlchemy `<2.1` pin so DB spans appear; console exporter default |
| Docs | README trace evidence (E6), D3/D4 write-up from decision card | Decisions are ours; AI only phrased the agreed policy |

### How we verify (do not trust the model alone)
1. **CI is the gate** (`AGENTS.md`): push → GitHub Actions runs ruff, unit tests,
   Compose Postgres integration (RLS + ingest/retrieve + recall@k), frontend lint/build.
   No local test suite as the source of truth.
2. **Eval evidence:** `backend/eval/reports/latest.md` (recall@5 = 1.000 on the synthetic
   set at commit `570be3f` / follow-ups); CI fails under 0.8.
3. **Manual / in-process checks:** unit tests for chunking, citation validation, telemetry
   idempotency, log correlation/redaction; captured console span tree for E6 in README.
4. **Code review:** every AI patch is read for security (tenant binding, upload magic
   bytes, prompt-injection wrappers) and for doc↔code drift (D3 confirm + soft-delete).
5. **Interview bar:** we only ship behaviour we can walk through on screen (C4).

### Explicit honesty
AI did **not** invent the multi-tenant threat model or the D3/D4 trade-offs; those came
from the brief + our decision card. AI *did* write most of the boilerplate and first
passes of modules; regressions (e.g. logging under pytest capture, mypy soft-fail,
chunk punctuation loss) were caught by CI or review and fixed or documented.

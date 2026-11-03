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
| 5 | Chunking (D1, initial) | **800–1000 tokens, 15–20% overlap** | Starting point; will tune against recall@k and record evidence here. |
| 6 | Python deps | **uv** | Fast, lockfile, reproducible. |
| 7 | Frontend | **Vite + React + TypeScript** | Lightweight SPA; TS as recommended by brief. |
| 8 | Integration tests (Q1.2) | **Docker Compose** (real PG + pgvector) | Reuse the same compose stack for integration tests rather than testcontainers. |
| 9 | Scope cuts (D4) | **None planned for now** | Per explicit instruction: don't plan cuts yet; revisit near the deadline and document anything dropped here. |
| 10 | Language | **All English** (code, docs, comments) | Uniform language across repo. |

## Open questions still asked (D1–D4 from the brief)

### D1 — Chunking & retrieval strategy
- Chunk size/overlap: starting at **900 tokens / 150 overlap** (~17%), within the
  agreed 800–1000 / 15–20% band (decision #5). Tunable via `CHUNK_SIZE_TOKENS` /
  `CHUNK_OVERLAP_TOKENS`.
- **Tokenizer:** same alphanumeric regex as the fake embeddings provider (not
  tiktoken) so offline chunk boundaries and lexical similarity stay aligned.
  Chunks stream across page boundaries; `page_number` is the page of the first
  token (citation-friendly).
- Retrieval: **hybrid** — candidate pool = union of top-N by pgvector cosine
  distance and top-N by `ts_rank` on generated `content_tsv` (GIN). Scores are
  min-max normalised per channel, then fused with
  `HYBRID_VECTOR_WEIGHT` / `HYBRID_TEXT_WEIGHT` (default 0.6 / 0.4). No reranker
  yet (keeps the path explainable and offline-friendly).
- **Idempotency:** `sha256(file)` + `UNIQUE(tenant_id, content_hash)`; re-upload of
  identical bytes reuses the existing document/chunks. Partial failures re-index
  by deleting prior chunks for that document before insert.
- **Evidence:** produced by `uv run python -m eval.run` (CI job `backend-integration`).
  Document-level **recall@5** over the 10 synthetic questions must stay ≥ **0.8**
  (enforced in CI with `--fail-under 0.8` and
  `tests/integration/test_recall_eval.py`). The markdown report is uploaded as the
  `eval-report` artifact and written to `backend/eval/reports/latest.md`. Hybrid
  fusion (0.6 vector / 0.4 text) with 900/150 chunking is the baseline; tune weights
  or chunk size only if recall regresses, and record the new numbers here.

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
- **Not yet decided** (was not in the decision card). Proposal to confirm: on re-upload of a
  changed document, **re-index** the new version and **invalidate old chunks/citations**
  (soft-delete), so citations always point to live fragments. Costs/behavior to be detailed.

### D4 — Production quality & cost metrics
- No scope cut planned for now (decision #9). Production answer-quality and per-query cost
  measurement approach to be written; anything deferred near the deadline gets logged here.

## How we use generative AI (and how we verify)
- _To be completed throughout the project_: which parts were AI-assisted, and the checks
  applied (tests passing, manual code review, running the eval, inspecting traces).

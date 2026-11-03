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
- Chunk size/overlap: starting at 800–1000 tokens / 15–20% overlap (decision #5).
- Retrieval: **hybrid** (vector similarity via pgvector HNSW `vector_cosine_ops` +
  PostgreSQL full-text via a generated `content_tsv` + GIN index). Reranking: TBD.
- **Evidence:** to be filled from the recall@k evaluation report.

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

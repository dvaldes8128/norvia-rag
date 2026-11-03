"""Run recall@k evaluation over the synthetic corpus (R7 / E5).

Requires a migrated Compose Postgres reachable via DATABASE_URL /
ADMIN_DATABASE_URL (same stack as integration tests).

Usage:
    uv run python -m eval.run
    uv run python -m eval.run --k 5 --fail-under 0.8
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Host-side defaults before importing app settings/engine (Compose publishes :5432).
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://norvia_app:norvia_app@localhost:5432/norvia",
)
os.environ.setdefault(
    "ADMIN_DATABASE_URL",
    "postgresql+psycopg://norvia:norvia@localhost:5432/norvia",
)
os.environ.setdefault("APP_DB_PASSWORD", "norvia_app")

from sqlalchemy import select, text

from app.core.auth import ensure_tenant
from app.db.models import Chunk, Document
from app.db.session import admin_session, tenant_session
from app.ingestion.pipeline import ingest_file
from app.providers.fake import FakeEmbeddings
from app.retrieval.hybrid import retrieve
from corpus import PDFS_DIR, load_questions
from corpus.build_pdfs import build_all
from eval.metrics import QuestionResult, mean_reciprocal_rank, recall_at_k

REPORTS_DIR = Path(__file__).resolve().parent / "reports"
EVAL_TENANT = "eval-corpus"
DEFAULT_K = 5
DEFAULT_FAIL_UNDER = 0.8


def _stem_from_filename(filename: str) -> str:
    return Path(filename).stem


def _prepare_corpus(tenant_id: str) -> dict[str, str]:
    """Build PDFs, wipe prior eval tenant data, ingest. Returns doc_id -> document UUID."""
    from sqlalchemy import delete

    from app.db.models import IngestionJob

    built = build_all()
    ensure_tenant(tenant_id, name="Eval corpus tenant")

    # Delete tenant-owned rows under RLS, then the tenant row itself.
    with tenant_session(tenant_id) as session:
        session.execute(delete(Chunk))
        session.execute(delete(IngestionJob))
        session.execute(delete(Document))
    with admin_session() as session:
        session.execute(text("DELETE FROM tenants WHERE id = :tid"), {"tid": tenant_id})
    ensure_tenant(tenant_id, name="Eval corpus tenant")

    mapping: dict[str, str] = {}
    with tenant_session(tenant_id) as session:
        for doc_id, pdf_path in built:
            result = ingest_file(
                session,
                tenant_id=tenant_id,
                file_path=pdf_path,
                filename=f"{doc_id}.pdf",
                embeddings=FakeEmbeddings(),
            )
            mapping[doc_id] = str(result.document_id)
    return mapping


def _evaluate(tenant_id: str, *, k: int) -> list[QuestionResult]:
    from sqlalchemy import func

    questions = load_questions()
    embeddings = FakeEmbeddings()
    results: list[QuestionResult] = []

    with tenant_session(tenant_id) as session:
        docs = {
            str(row.id): _stem_from_filename(row.filename)
            for row in session.scalars(
                select(Document).where(Document.deleted_at.is_(None))
            ).all()
        }
        chunk_count = session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.deleted_at.is_(None))
        )
        if not chunk_count:
            raise RuntimeError("No chunks indexed for eval tenant")

        for item in questions:
            retrieved = retrieve(
                session,
                question=item["question"],
                top_k=k,
                embeddings=embeddings,
            )
            retrieved_doc_ids: list[str] = []
            for chunk in retrieved:
                stem = docs.get(str(chunk.document_id), _stem_from_filename(chunk.filename))
                if stem not in retrieved_doc_ids:
                    retrieved_doc_ids.append(stem)

            expected = list(item["expected_doc_ids"])
            markers = [m.lower() for m in item.get("expected_markers", [])]
            hit = any(doc in retrieved_doc_ids for doc in expected)
            rank: int | None = None
            for idx, doc_id in enumerate(retrieved_doc_ids, start=1):
                if doc_id in expected:
                    rank = idx
                    break

            joined = " ".join(c.content.lower() for c in retrieved)
            marker_hit = all(m in joined for m in markers) if markers else hit

            results.append(
                QuestionResult(
                    question_id=item["id"],
                    question=item["question"],
                    expected_doc_ids=expected,
                    retrieved_doc_ids=retrieved_doc_ids,
                    hit=hit,
                    marker_hit=marker_hit,
                    rank=rank,
                )
            )
    return results


def _render_report(
    results: list[QuestionResult],
    *,
    k: int,
    tenant_id: str,
) -> str:
    hits = [r.hit for r in results]
    marker_hits = [r.marker_hit for r in results]
    recall = recall_at_k(hits)
    marker_recall = recall_at_k(marker_hits)
    mrr = mean_reciprocal_rank([r.rank for r in results])
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")

    lines = [
        "# Retrieval evaluation report",
        "",
        f"- Generated: `{now}`",
        f"- Tenant: `{tenant_id}`",
        f"- Corpus PDFs: `{PDFS_DIR}`",
        f"- Questions: {len(results)}",
        f"- Metric: **recall@{k}** (document-level) + marker check + MRR",
        "- Embeddings: fake feature-hashing (dim=768)",
        f"- Retrieval: hybrid (vector 0.6 / text 0.4), top_k={k}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| recall@{k} (expected doc in top-{k}) | **{recall:.3f}** |",
        f"| marker recall@{k} (all markers in retrieved text) | **{marker_recall:.3f}** |",
        f"| MRR | **{mrr:.3f}** |",
        "",
        "## Per-question",
        "",
        "| ID | Hit | Markers | Rank | Expected | Retrieved | Question |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.question_id} | {'yes' if r.hit else 'no'} | "
            f"{'yes' if r.marker_hit else 'no'} | {r.rank or '-'} | "
            f"{', '.join(r.expected_doc_ids)} | "
            f"{', '.join(r.retrieved_doc_ids) or '-'} | "
            f"{r.question} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Document-level hit: any retrieved chunk belongs to an expected `doc_id`.",
            "- Marker hit: every `expected_markers` substring appears in the retrieved chunk text.",
            "- This report is reproducible offline with the fake providers and Compose Postgres.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Norvia RAG recall@k evaluation")
    parser.add_argument("--k", type=int, default=DEFAULT_K)
    parser.add_argument("--fail-under", type=float, default=DEFAULT_FAIL_UNDER)
    parser.add_argument("--tenant", default=EVAL_TENANT)
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORTS_DIR / "latest.md",
        help="Path to write the markdown report",
    )
    args = parser.parse_args(argv)

    print(f"Preparing corpus into tenant={args.tenant!r} …", flush=True)
    mapping = _prepare_corpus(args.tenant)
    print(f"Ingested {len(mapping)} documents.", flush=True)

    results = _evaluate(args.tenant, k=args.k)
    report = _render_report(results, k=args.k, tenant_id=args.tenant)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nWrote report → {args.report}", flush=True)

    recall = recall_at_k([r.hit for r in results])
    if recall < args.fail_under:
        print(
            f"FAIL: recall@{args.k}={recall:.3f} < fail-under={args.fail_under}",
            file=sys.stderr,
        )
        return 1
    print(f"OK: recall@{args.k}={recall:.3f} >= {args.fail_under}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Celery tasks for asynchronous document ingestion (R1 / R2)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from celery.exceptions import MaxRetriesExceededError

from app.db.models import IngestionJob, JobStatus
from app.db.session import tenant_session
from app.ingestion.errors import PermanentIngestionError, TransientIngestionError
from app.ingestion.pipeline import ingest_file
from app.workers.celery_app import celery

logger = logging.getLogger(__name__)

# Soft time limit leaves room for the worker to mark the job failed cleanly.
_SOFT_TIME_LIMIT = 10 * 60
_HARD_TIME_LIMIT = 12 * 60


def _set_job_status(
    *,
    tenant_id: str,
    job_id: str,
    status: JobStatus,
    error: str | None = None,
    document_id: UUID | None = None,
) -> None:
    with tenant_session(tenant_id) as session:
        job = session.get(IngestionJob, UUID(job_id))
        if job is None:
            logger.error(
                "ingestion.job_missing",
                extra={"tenant_id": tenant_id, "job_id": job_id},
            )
            return
        job.status = status.value
        job.error = error
        if document_id is not None:
            job.document_id = document_id
        job.updated_at = datetime.now(UTC)


@celery.task(
    bind=True,
    name="app.workers.tasks.process_ingestion",
    max_retries=3,
    default_retry_delay=15,
    soft_time_limit=_SOFT_TIME_LIMIT,
    time_limit=_HARD_TIME_LIMIT,
    acks_late=True,
)
def process_ingestion(
    self,
    job_id: str,
    tenant_id: str,
    file_path: str,
    filename: str,
) -> dict[str, str | int | bool]:
    """Extract → chunk → embed → upsert; drive job status through the lifecycle."""
    logger.info(
        "ingestion.task_start",
        extra={"tenant_id": tenant_id, "job_id": job_id, "filename": filename},
    )
    _set_job_status(tenant_id=tenant_id, job_id=job_id, status=JobStatus.processing)

    try:
        with tenant_session(tenant_id) as session:
            result = ingest_file(
                session,
                tenant_id=tenant_id,
                file_path=file_path,
                filename=filename,
            )
            job = session.get(IngestionJob, UUID(job_id))
            if job is not None:
                job.status = JobStatus.completed.value
                job.document_id = result.document_id
                job.error = None
                job.updated_at = datetime.now(UTC)

        return {
            "job_id": job_id,
            "document_id": str(result.document_id),
            "chunk_count": result.chunk_count,
            "page_count": result.page_count,
            "reused": result.reused,
            "status": JobStatus.completed.value,
        }

    except PermanentIngestionError as exc:
        logger.warning(
            "ingestion.permanent_failure",
            extra={"tenant_id": tenant_id, "job_id": job_id, "error": str(exc)},
        )
        _set_job_status(
            tenant_id=tenant_id,
            job_id=job_id,
            status=JobStatus.failed,
            error=str(exc),
        )
        return {"job_id": job_id, "status": JobStatus.failed.value, "error": str(exc)}

    except TransientIngestionError as exc:
        logger.warning(
            "ingestion.transient_failure",
            extra={
                "tenant_id": tenant_id,
                "job_id": job_id,
                "error": str(exc),
                "retries": self.request.retries,
            },
        )
        try:
            raise self.retry(exc=exc) from exc
        except MaxRetriesExceededError:
            _set_job_status(
                tenant_id=tenant_id,
                job_id=job_id,
                status=JobStatus.failed,
                error=f"Retries exhausted: {exc}",
            )
            return {
                "job_id": job_id,
                "status": JobStatus.failed.value,
                "error": str(exc),
            }

    except Exception as exc:
        logger.exception(
            "ingestion.unexpected_failure",
            extra={"tenant_id": tenant_id, "job_id": job_id},
        )
        try:
            raise self.retry(exc=exc) from exc
        except MaxRetriesExceededError:
            _set_job_status(
                tenant_id=tenant_id,
                job_id=job_id,
                status=JobStatus.failed,
                error=f"Retries exhausted: {exc}",
            )
            raise

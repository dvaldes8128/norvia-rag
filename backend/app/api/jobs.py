"""GET /jobs/{job_id} — poll ingestion status (F1.2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentTenant
from app.api.schemas import JobStatusResponse
from app.db.models import Document, IngestionJob
from app.db.session import tenant_session

router = APIRouter(tags=["ingestion"])


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: UUID, principal: CurrentTenant) -> JobStatusResponse:
    with tenant_session(principal.tenant_id) as session:
        job = session.get(IngestionJob, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Job not found",
            )
        filename: str | None = None
        if job.document_id is not None:
            doc = session.get(Document, job.document_id)
            if doc is not None:
                filename = doc.filename
        return JobStatusResponse(
            job_id=job.id,
            status=job.status,
            filename=filename,
            document_id=job.document_id,
            error=job.error,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


@router.get("/jobs", response_model=list[JobStatusResponse])
def list_jobs(principal: CurrentTenant, limit: int = 50) -> list[JobStatusResponse]:
    """List recent jobs for the authenticated tenant (supports the frontend status list)."""
    limit = max(1, min(limit, 200))
    with tenant_session(principal.tenant_id) as session:
        jobs = session.scalars(
            select(IngestionJob)
            .where(IngestionJob.tenant_id == principal.tenant_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(limit)
        ).all()
        doc_ids = [j.document_id for j in jobs if j.document_id is not None]
        filenames: dict[UUID, str] = {}
        if doc_ids:
            docs = session.scalars(select(Document).where(Document.id.in_(doc_ids))).all()
            filenames = {d.id: d.filename for d in docs}
        return [
            JobStatusResponse(
                job_id=j.id,
                status=j.status,
                filename=filenames.get(j.document_id) if j.document_id else None,
                document_id=j.document_id,
                error=j.error,
                created_at=j.created_at,
                updated_at=j.updated_at,
            )
            for j in jobs
        ]

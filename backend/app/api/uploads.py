"""POST /upload — accept a PDF, create a pending job, enqueue Celery (F1.1)."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from opentelemetry import trace

from app.api.deps import CurrentTenant
from app.api.schemas import UploadAccepted
from app.config import settings
from app.core.logging import get_correlation_id, get_logger
from app.db.models import IngestionJob, JobStatus
from app.db.session import tenant_session
from app.workers.tasks import process_ingestion

logger = get_logger(__name__)

router = APIRouter(tags=["ingestion"])

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_PDF_MAGIC = b"%PDF"

PdfUpload = Annotated[UploadFile, File(description="PDF document to ingest")]


def _safe_filename(name: str | None) -> str:
    raw = (name or "upload.pdf").strip() or "upload.pdf"
    base = Path(raw).name
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "upload.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned}.pdf"
    return cleaned[:200]


def _validate_pdf(content_type: str | None, filename: str, head: bytes) -> None:
    ct = (content_type or "").lower()
    if ct and ct not in {
        "application/pdf",
        "application/x-pdf",
        "binary/octet-stream",
        "application/octet-stream",
    }:
        if "pdf" not in ct:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Unsupported content type: {content_type}",
            )
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF uploads are accepted",
        )
    if not head.startswith(_PDF_MAGIC):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is not a valid PDF (missing %PDF header)",
        )


@router.post(
    "/upload",
    response_model=UploadAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_pdf(
    file: PdfUpload,
    principal: CurrentTenant,
) -> UploadAccepted:
    """Validate & store a PDF, create a pending job, enqueue ingestion."""
    trace.get_current_span().set_attribute("tenant_id", principal.tenant_id)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    filename = _safe_filename(file.filename)
    job_id = uuid.uuid4()

    dest_dir = Path(settings.upload_dir) / principal.tenant_id / str(job_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename

    written = 0
    head = b""
    try:
        with dest_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                if written == 0:
                    head = chunk[:8]
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds {settings.max_upload_mb} MB limit",
                    )
                out.write(chunk)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        try:
            dest_dir.rmdir()
        except OSError:
            pass
        raise
    finally:
        await file.close()

    if written == 0:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty upload",
        )

    try:
        _validate_pdf(file.content_type, filename, head)
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        try:
            dest_dir.rmdir()
        except OSError:
            pass
        raise

    with tenant_session(principal.tenant_id) as session:
        job = IngestionJob(
            id=job_id,
            tenant_id=principal.tenant_id,
            status=JobStatus.pending.value,
        )
        session.add(job)

    trace.get_current_span().set_attribute("job_id", str(job_id))
    # Propagate the correlation id into the worker so API + worker logs share one id (Q6).
    correlation_id = get_correlation_id()
    process_ingestion.delay(
        str(job_id),
        principal.tenant_id,
        str(dest_path),
        filename,
        correlation_id=correlation_id,
    )
    logger.info(
        "upload.accepted",
        tenant_id=principal.tenant_id,
        job_id=str(job_id),
        filename=filename,
        bytes=written,
    )
    return UploadAccepted(job_id=job_id, status=JobStatus.pending.value, filename=filename)

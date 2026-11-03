"""Document soft-delete API (D3)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from opentelemetry import trace

from app.api.deps import CurrentTenant
from app.api.schemas import DocumentDeleted
from app.core.logging import get_logger
from app.db.session import tenant_session
from app.ingestion.pipeline import soft_delete_document

logger = get_logger(__name__)

router = APIRouter(tags=["documents"])


@router.delete(
    "/documents/{document_id}",
    response_model=DocumentDeleted,
    status_code=status.HTTP_200_OK,
)
def delete_document(document_id: UUID, principal: CurrentTenant) -> DocumentDeleted:
    """Soft-delete a document and its live chunks (retrieval ignores them)."""
    trace.get_current_span().set_attribute("tenant_id", principal.tenant_id)
    with tenant_session(principal.tenant_id) as session:
        document = soft_delete_document(session, document_id=document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found or already deleted",
            )
        logger.info(
            "document.soft_deleted",
            tenant_id=principal.tenant_id,
            document_id=str(document_id),
        )
        return DocumentDeleted(
            document_id=document.id,
            filename=document.filename,
            deleted=True,
        )

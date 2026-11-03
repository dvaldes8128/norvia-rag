"""Shared request/response schemas for the HTTP API."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class UploadAccepted(BaseModel):
    job_id: UUID
    status: str = "pending"
    filename: str


class DocumentDeleted(BaseModel):
    document_id: UUID
    filename: str
    deleted: bool = True


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: str
    filename: str | None = None
    document_id: UUID | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class TokenRequest(BaseModel):
    """Exchange a tenant API key for a short-lived JWT."""

    api_key: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant_id: str


class CitationOut(BaseModel):
    document_id: UUID
    filename: str
    page_number: int
    chunk_id: UUID
    excerpt: str


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    # A: cite top-N by retrieval score. B: also require lexical overlap with the answer.
    citation_top_n: int = Field(default=3, ge=1, le=20)
    lexical_grounding: bool = False


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    confidence: float = Field(ge=0.0, le=1.0)

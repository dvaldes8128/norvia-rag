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
    # Retrieval near-copy gate (token_set_ratio 0–100). 0 = off (default, open QA).
    near_copy_min_ratio: float = Field(default=0.0, ge=0.0, le=100.0)


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    confidence: float = Field(ge=0.0, le=1.0)


# ---- Admin (platform ops) ----


class CreateTenantRequest(BaseModel):
    id: str = Field(min_length=2, max_length=64)
    name: str | None = Field(default=None, max_length=255)
    key_label: str = Field(default="default", max_length=128)


class IssueTenantKeyRequest(BaseModel):
    label: str = Field(default="default", max_length=128)


class AdminTenantOut(BaseModel):
    id: str
    name: str
    created_at: datetime
    document_count: int
    job_count: int
    api_key_prefixes: list[str]
    env_backed: bool = False


class AdminTenantCreated(BaseModel):
    id: str
    name: str
    api_key: str
    api_key_id: UUID
    api_key_prefix: str


class AdminTenantKeyIssued(BaseModel):
    tenant_id: str
    api_key: str
    api_key_id: UUID
    api_key_prefix: str
    label: str


class AdminQueueSnapshot(BaseModel):
    workers: list[str]
    worker_count: int
    broker_queue_depth: int | None
    active_tasks: list[dict]
    reserved_tasks: list[dict]
    scheduled_tasks: list[dict]
    jobs_by_status: dict[str, int]


class AdminTelemetrySnapshot(BaseModel):
    service_name: str
    traces_exporter: str
    otlp_endpoint_configured: bool
    llm_provider: str
    embeddings_provider: str
    tenant_count: int
    document_count: int
    chunk_count: int
    jobs_by_status: dict[str, int]
    worker_count: int
    recent_failed_jobs: list[dict]
    note: str

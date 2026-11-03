"""Platform admin API: tenants, Celery queues, operational telemetry.

Protected by ``X-Admin-Key`` (``ADMIN_API_KEY``). This is an ops overview — not a
live dollar-cost dashboard (still out of scope per D4).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from redis import Redis
from sqlalchemy import func, select

from app.api.schemas import (
    AdminQueueSnapshot,
    AdminTelemetrySnapshot,
    AdminTenantCreated,
    AdminTenantKeyIssued,
    AdminTenantOut,
    CreateTenantRequest,
    IssueTenantKeyRequest,
)
from app.config import settings
from app.core.auth import (
    issue_tenant_api_key,
    key_prefix,
    require_admin_key,
)
from app.db.models import Chunk, Document, IngestionJob, Tenant, TenantApiKey
from app.db.session import admin_session
from app.workers.celery_app import celery

router = APIRouter(prefix="/admin", tags=["admin"])

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")


def _admin_auth(
    x_admin_key: Annotated[str | None, Header(alias="X-Admin-Key")] = None,
) -> None:
    require_admin_key(x_admin_key)


AdminAuth = Annotated[None, Depends(_admin_auth)]


def _validate_tenant_id(tenant_id: str) -> str:
    tid = tenant_id.strip().lower()
    if not _TENANT_ID_RE.match(tid):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="tenant_id must be 2–63 chars: lowercase alphanumeric, _ or -",
        )
    return tid


@router.get("/tenants", response_model=list[AdminTenantOut])
def list_tenants(_: AdminAuth) -> list[AdminTenantOut]:
    with admin_session() as session:
        tenants = session.scalars(select(Tenant).order_by(Tenant.created_at.asc())).all()
        out: list[AdminTenantOut] = []
        for t in tenants:
            doc_count = session.scalar(
                select(func.count())
                .select_from(Document)
                .where(Document.tenant_id == t.id, Document.deleted_at.is_(None))
            )
            job_count = session.scalar(
                select(func.count()).select_from(IngestionJob).where(IngestionJob.tenant_id == t.id)
            )
            live_keys = session.scalars(
                select(TenantApiKey).where(
                    TenantApiKey.tenant_id == t.id,
                    TenantApiKey.revoked_at.is_(None),
                )
            ).all()
            env_keys = [key_prefix(k) for k, tid in settings.api_key_map().items() if tid == t.id]
            out.append(
                AdminTenantOut(
                    id=t.id,
                    name=t.name,
                    created_at=t.created_at,
                    document_count=int(doc_count or 0),
                    job_count=int(job_count or 0),
                    api_key_prefixes=[*env_keys, *(k.key_prefix for k in live_keys)],
                    env_backed=bool(env_keys),
                )
            )
        return out


@router.post(
    "/tenants",
    response_model=AdminTenantCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_tenant(body: CreateTenantRequest, _: AdminAuth) -> AdminTenantCreated:
    tenant_id = _validate_tenant_id(body.id)
    name = (body.name or tenant_id).strip() or tenant_id

    with admin_session() as session:
        if session.get(Tenant, tenant_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Tenant '{tenant_id}' already exists",
            )
        session.add(Tenant(id=tenant_id, name=name))

    key_id, raw_key = issue_tenant_api_key(tenant_id, label=body.key_label or "default")
    return AdminTenantCreated(
        id=tenant_id,
        name=name,
        api_key=raw_key,
        api_key_id=key_id,
        api_key_prefix=key_prefix(raw_key),
    )


@router.post(
    "/tenants/{tenant_id}/keys",
    response_model=AdminTenantKeyIssued,
    status_code=status.HTTP_201_CREATED,
)
def issue_key(
    tenant_id: str,
    body: IssueTenantKeyRequest,
    _: AdminAuth,
) -> AdminTenantKeyIssued:
    tid = _validate_tenant_id(tenant_id)
    with admin_session() as session:
        if session.get(Tenant, tid) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tenant '{tid}' not found",
            )
    key_id, raw_key = issue_tenant_api_key(tid, label=body.label or "default")
    return AdminTenantKeyIssued(
        tenant_id=tid,
        api_key=raw_key,
        api_key_id=key_id,
        api_key_prefix=key_prefix(raw_key),
        label=body.label or "default",
    )


@router.post("/tenants/{tenant_id}/keys/{key_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_key(tenant_id: str, key_id: UUID, _: AdminAuth) -> None:
    tid = _validate_tenant_id(tenant_id)
    with admin_session() as session:
        row = session.scalar(
            select(TenantApiKey).where(
                TenantApiKey.id == key_id,
                TenantApiKey.tenant_id == tid,
            )
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Key not found")
        if row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)


def _queue_depth() -> int | None:
    """Best-effort Redis LLEN of the default Celery queue."""
    try:
        client = Redis.from_url(settings.celery_broker_url, socket_connect_timeout=1.0)
        try:
            return int(client.llen("celery"))
        finally:
            client.close()
    except Exception:
        return None


def _flatten_inspect(payload: dict | None) -> list[dict]:
    if not payload:
        return []
    rows: list[dict] = []
    for worker, items in payload.items():
        for item in items or []:
            rows.append(
                {
                    "worker": worker,
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "args": item.get("args"),
                    "kwargs": item.get("kwargs"),
                }
            )
    return rows


@router.get("/queues", response_model=AdminQueueSnapshot)
def queue_snapshot(_: AdminAuth) -> AdminQueueSnapshot:
    inspect = celery.control.inspect(timeout=1.0)
    try:
        stats = inspect.stats() or {}
        active = inspect.active() or {}
        reserved = inspect.reserved() or {}
        scheduled = inspect.scheduled() or {}
    except Exception:
        stats, active, reserved, scheduled = {}, {}, {}, {}

    with admin_session() as session:
        by_status_rows = session.execute(
            select(IngestionJob.status, func.count())
            .group_by(IngestionJob.status)
            .order_by(IngestionJob.status)
        ).all()
        jobs_by_status = {str(status_): int(count) for status_, count in by_status_rows}

    return AdminQueueSnapshot(
        workers=sorted(stats.keys()),
        worker_count=len(stats),
        broker_queue_depth=_queue_depth(),
        active_tasks=_flatten_inspect(active),
        reserved_tasks=_flatten_inspect(reserved),
        scheduled_tasks=_flatten_inspect(scheduled),
        jobs_by_status=jobs_by_status,
    )


@router.get("/telemetry", response_model=AdminTelemetrySnapshot)
def telemetry_snapshot(_: AdminAuth) -> AdminTelemetrySnapshot:
    """Operational telemetry overview (not a live $ cost dashboard — see D4)."""
    with admin_session() as session:
        tenant_count = session.scalar(select(func.count()).select_from(Tenant)) or 0
        document_count = (
            session.scalar(
                select(func.count()).select_from(Document).where(Document.deleted_at.is_(None))
            )
            or 0
        )
        chunk_count = (
            session.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.deleted_at.is_(None))
            )
            or 0
        )
        by_status_rows = session.execute(
            select(IngestionJob.status, func.count()).group_by(IngestionJob.status)
        ).all()
        jobs_by_status = {str(s): int(c) for s, c in by_status_rows}
        recent_failed = session.scalars(
            select(IngestionJob)
            .where(IngestionJob.status == "failed")
            .order_by(IngestionJob.updated_at.desc())
            .limit(10)
        ).all()
        failed_out = [
            {
                "job_id": str(j.id),
                "tenant_id": j.tenant_id,
                "error": (j.error or "")[:240] or None,
                "updated_at": j.updated_at.isoformat() if j.updated_at else None,
            }
            for j in recent_failed
        ]

    inspect = celery.control.inspect(timeout=1.0)
    try:
        worker_stats = inspect.stats() or {}
    except Exception:
        worker_stats = {}

    otlp = bool(settings.otel_exporter_otlp_endpoint.strip())
    exporter = "otlp" if otlp else settings.otel_traces_exporter

    return AdminTelemetrySnapshot(
        service_name=settings.otel_service_name,
        traces_exporter=exporter,
        otlp_endpoint_configured=otlp,
        llm_provider=settings.llm_provider,
        embeddings_provider=settings.embeddings_provider,
        tenant_count=int(tenant_count),
        document_count=int(document_count),
        chunk_count=int(chunk_count),
        jobs_by_status=jobs_by_status,
        worker_count=len(worker_stats),
        recent_failed_jobs=failed_out,
        note=(
            "Token/cost attributes live on OTel spans (llm.prompt_tokens / "
            "completion_tokens). No in-app dollar dashboard (D4)."
        ),
    )

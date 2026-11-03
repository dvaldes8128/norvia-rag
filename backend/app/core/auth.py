"""Tenant authentication: API key and JWT (decision #3).

Both schemes resolve to a :class:`TenantPrincipal`. API keys come from the
``X-API-Key`` header (or ``Authorization: ApiKey <key>``). JWTs use
``Authorization: Bearer <token>`` with a ``tenant_id`` claim.

Keys may come from ``TENANT_API_KEYS`` (env demo map) or from hashed rows in
``tenant_api_keys`` (issued by the admin panel).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, settings
from app.db.models import Tenant, TenantApiKey
from app.db.session import admin_session

_KEY_PREFIX = "nvk_"


@dataclass(frozen=True)
class TenantPrincipal:
    tenant_id: str
    auth_method: str  # "api_key" | "jwt"


def hash_api_key(raw_key: str, *, cfg: Settings | None = None) -> str:
    """Peppered SHA-256 so a DB leak alone is not enough to forge keys."""
    cfg = cfg or settings
    material = f"{cfg.jwt_secret}:{raw_key}".encode()
    return hashlib.sha256(material).hexdigest()


def generate_api_key() -> str:
    """Return a new opaque tenant API key (shown once to the operator)."""
    return f"{_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def key_prefix(raw_key: str) -> str:
    """Short display prefix for lists (never the full secret)."""
    return raw_key[:12] if len(raw_key) >= 12 else raw_key


def create_access_token(
    tenant_id: str,
    *,
    cfg: Settings | None = None,
    expires_minutes: int | None = None,
) -> str:
    cfg = cfg or settings
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes if expires_minutes is not None else cfg.jwt_expire_minutes
    )
    payload = {"sub": tenant_id, "tenant_id": tenant_id, "exp": expire}
    return jwt.encode(payload, cfg.jwt_secret, algorithm=cfg.jwt_algorithm)


def decode_access_token(token: str, *, cfg: Settings | None = None) -> str:
    """Return ``tenant_id`` from a valid JWT, or raise HTTP 401."""
    cfg = cfg or settings
    try:
        payload = jwt.decode(token, cfg.jwt_secret, algorithms=[cfg.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc
    tenant_id = payload.get("tenant_id") or payload.get("sub")
    if not tenant_id or not isinstance(tenant_id, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing tenant_id claim",
        )
    return tenant_id


def ensure_tenant(tenant_id: str, *, name: str | None = None) -> None:
    """Upsert a tenant row so FK constraints succeed on first authenticated request."""
    with admin_session() as session:
        existing = session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if existing is None:
            session.add(Tenant(id=tenant_id, name=name or tenant_id))


def lookup_tenant_for_api_key(raw_key: str, *, cfg: Settings | None = None) -> str | None:
    """Resolve ``tenant_id`` for a raw API key (env map first, then DB hash).

    If Postgres is unreachable, only the env map is consulted (unit tests / degraded
    mode). DB-issued keys require a live database.
    """
    cfg = cfg or settings
    key = raw_key.strip()
    if not key:
        return None

    env_tenant = cfg.api_key_map().get(key)
    if env_tenant:
        return env_tenant

    digest = hash_api_key(key, cfg=cfg)
    try:
        with admin_session() as session:
            row = session.scalar(
                select(TenantApiKey).where(
                    TenantApiKey.key_hash == digest,
                    TenantApiKey.revoked_at.is_(None),
                )
            )
            return row.tenant_id if row else None
    except SQLAlchemyError:
        # Keep env-key auth working offline; treat DB miss/outage as "unknown key".
        return None


def issue_tenant_api_key(
    tenant_id: str,
    *,
    label: str = "default",
    cfg: Settings | None = None,
) -> tuple[UUID, str]:
    """Persist a hashed key for ``tenant_id``; return ``(key_id, raw_key)``."""
    cfg = cfg or settings
    raw = generate_api_key()
    row = TenantApiKey(
        tenant_id=tenant_id,
        key_hash=hash_api_key(raw, cfg=cfg),
        key_prefix=key_prefix(raw),
        label=label,
    )
    with admin_session() as session:
        session.add(row)
        session.flush()
        return row.id, raw


def resolve_principal(
    *,
    authorization: str | None,
    x_api_key: str | None,
    cfg: Settings | None = None,
) -> TenantPrincipal:
    """Resolve tenant identity from headers. Prefer Bearer JWT, then API key."""
    cfg = cfg or settings

    if authorization:
        scheme, _, credential = authorization.partition(" ")
        scheme_l = scheme.lower()
        credential = credential.strip()
        if scheme_l == "bearer" and credential:
            tenant_id = decode_access_token(credential, cfg=cfg)
            return TenantPrincipal(tenant_id=tenant_id, auth_method="jwt")
        if scheme_l == "apikey" and credential:
            tenant_id = lookup_tenant_for_api_key(credential, cfg=cfg)
            if tenant_id:
                return TenantPrincipal(tenant_id=tenant_id, auth_method="api_key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    if x_api_key:
        tenant_id = lookup_tenant_for_api_key(x_api_key, cfg=cfg)
        if tenant_id:
            return TenantPrincipal(tenant_id=tenant_id, auth_method="api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required (X-API-Key or Bearer JWT)",
    )


async def get_current_tenant(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> TenantPrincipal:
    principal = resolve_principal(authorization=authorization, x_api_key=x_api_key)
    ensure_tenant(principal.tenant_id)
    return principal


def require_admin_key(x_admin_key: str | None, *, cfg: Settings | None = None) -> None:
    """Validate platform admin key (constant-time). Raises 401/503 as needed."""
    cfg = cfg or settings
    expected = (cfg.admin_api_key or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API disabled (set ADMIN_API_KEY)",
        )
    provided = (x_admin_key or "").strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin API key",
        )

"""Tenant authentication: API key and JWT (decision #3).

Both schemes resolve to a :class:`TenantPrincipal`. API keys come from the
``X-API-Key`` header (or ``Authorization: ApiKey <key>``). JWTs use
``Authorization: Bearer <token>`` with a ``tenant_id`` claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select

from app.config import Settings, settings
from app.db.models import Tenant
from app.db.session import admin_session


@dataclass(frozen=True)
class TenantPrincipal:
    tenant_id: str
    auth_method: str  # "api_key" | "jwt"


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
            tenant_id = cfg.api_key_map().get(credential)
            if tenant_id:
                return TenantPrincipal(tenant_id=tenant_id, auth_method="api_key")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

    if x_api_key:
        tenant_id = cfg.api_key_map().get(x_api_key.strip())
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

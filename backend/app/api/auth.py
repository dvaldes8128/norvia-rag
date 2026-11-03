"""Auth helpers: exchange API key for JWT."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.schemas import TokenRequest, TokenResponse
from app.config import settings
from app.core.auth import create_access_token, ensure_tenant

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
def issue_token(body: TokenRequest) -> TokenResponse:
    tenant_id = settings.api_key_map().get(body.api_key.strip())
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    ensure_tenant(tenant_id)
    token = create_access_token(tenant_id)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_minutes * 60,
        tenant_id=tenant_id,
    )

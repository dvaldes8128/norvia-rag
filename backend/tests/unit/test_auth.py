"""Unit tests for API key + JWT tenant resolution."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.core.auth import create_access_token, decode_access_token, resolve_principal


@pytest.fixture
def cfg() -> Settings:
    return Settings(
        tenant_api_keys="acme:devkey-acme,globex:devkey-globex",
        jwt_secret="test-secret",
        jwt_algorithm="HS256",
        jwt_expire_minutes=30,
    )


def test_api_key_header_resolves_tenant(cfg: Settings) -> None:
    principal = resolve_principal(authorization=None, x_api_key="devkey-acme", cfg=cfg)
    assert principal.tenant_id == "acme"
    assert principal.auth_method == "api_key"


def test_api_key_authorization_scheme(cfg: Settings) -> None:
    principal = resolve_principal(
        authorization="ApiKey devkey-globex",
        x_api_key=None,
        cfg=cfg,
    )
    assert principal.tenant_id == "globex"


def test_jwt_bearer_resolves_tenant(cfg: Settings) -> None:
    token = create_access_token("acme", cfg=cfg)
    principal = resolve_principal(
        authorization=f"Bearer {token}",
        x_api_key=None,
        cfg=cfg,
    )
    assert principal.tenant_id == "acme"
    assert principal.auth_method == "jwt"


def test_invalid_api_key_rejected(cfg: Settings) -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_principal(authorization=None, x_api_key="nope", cfg=cfg)
    assert exc.value.status_code == 401


def test_missing_auth_rejected(cfg: Settings) -> None:
    with pytest.raises(HTTPException) as exc:
        resolve_principal(authorization=None, x_api_key=None, cfg=cfg)
    assert exc.value.status_code == 401


def test_expired_or_bad_jwt_rejected(cfg: Settings) -> None:
    with pytest.raises(HTTPException):
        decode_access_token("not.a.jwt", cfg=cfg)

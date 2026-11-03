"""Unit tests for POST /ask error envelope (Q2.2 / Q2.4)."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.providers.base import ProviderError


def test_ask_requires_auth() -> None:
    client = TestClient(app)
    response = client.post("/ask", json={"question": "What is the deductible?"})
    assert response.status_code == 401


def test_ask_provider_error_returns_envelope(monkeypatch) -> None:
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield MagicMock()

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.ask.tenant_session", fake_tenant_session),
        patch(
            "app.api.ask.answer_question",
            side_effect=ProviderError("LLM HTTP 503: upstream down"),
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/ask",
            headers={"X-API-Key": "devkey-acme"},
            json={"question": "What is the deductible?"},
        )

    assert response.status_code == 503
    body = response.json()
    assert body["error"] == "Upstream AI provider failed"
    assert body["code"] == "provider_error"
    assert "upstream down" in body["detail"]

"""Unit tests for DELETE /documents soft-delete (D3)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db.models import Document
from app.main import app


def test_delete_document_requires_auth() -> None:
    client = TestClient(app)
    response = client.delete(f"/documents/{uuid4()}")
    assert response.status_code == 401


def test_delete_document_soft_deletes(monkeypatch) -> None:
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")

    doc_id = uuid4()
    doc = Document(
        id=doc_id,
        tenant_id="acme",
        filename="policy.pdf",
        content_hash="b" * 64,
        page_count=1,
        version=1,
        deleted_at=datetime.now(UTC),
    )

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield MagicMock()

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.documents.tenant_session", fake_tenant_session),
        patch("app.api.documents.soft_delete_document", return_value=doc),
    ):
        client = TestClient(app)
        response = client.delete(
            f"/documents/{doc_id}",
            headers={"X-API-Key": "devkey-acme"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is True
    assert body["document_id"] == str(doc_id)
    assert body["filename"] == "policy.pdf"


def test_delete_document_404_when_missing(monkeypatch) -> None:
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    from app.config import settings

    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield MagicMock()

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.documents.tenant_session", fake_tenant_session),
        patch("app.api.documents.soft_delete_document", return_value=None),
    ):
        client = TestClient(app)
        response = client.delete(
            f"/documents/{uuid4()}",
            headers={"X-API-Key": "devkey-acme"},
        )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"

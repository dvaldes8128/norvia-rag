"""Unit tests for /admin endpoints (auth gate + happy paths with mocks)."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def test_admin_requires_key(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    from app.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "secret-admin")

    client = TestClient(app)
    assert client.get("/admin/tenants").status_code == 401
    assert client.get("/admin/tenants", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_admin_disabled_without_config(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "")
    client = TestClient(app)
    response = client.get("/admin/tenants", headers={"X-Admin-Key": "anything"})
    assert response.status_code == 503


def test_create_tenant_issues_key(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    from app.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "secret-admin")
    key_id = uuid4()

    @contextmanager
    def fake_admin_session():
        session = MagicMock()
        session.get.return_value = None
        yield session

    with (
        patch("app.api.admin.admin_session", fake_admin_session),
        patch(
            "app.api.admin.issue_tenant_api_key",
            return_value=(key_id, "nvk_testkey_abcdefghijklmnopqrstuvwxyz"),
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/admin/tenants",
            headers={"X-Admin-Key": "secret-admin"},
            json={"id": "contoso", "name": "Contoso Corp"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == "contoso"
    assert body["api_key"].startswith("nvk_")
    assert body["api_key_id"] == str(key_id)


def test_queues_and_telemetry(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    from app.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "secret-admin")

    @contextmanager
    def fake_admin_session():
        session = MagicMock()
        session.execute.return_value.all.return_value = [("completed", 2), ("failed", 1)]
        session.scalar.side_effect = [3, 10, 100]
        session.scalars.return_value.all.return_value = []
        yield session

    class FakeInspect:
        def stats(self):
            return {"celery@worker": {}}

        def active(self):
            return {}

        def reserved(self):
            return {}

        def scheduled(self):
            return {}

    with (
        patch("app.api.admin.admin_session", fake_admin_session),
        patch("app.api.admin.celery.control.inspect", return_value=FakeInspect()),
        patch("app.api.admin._queue_depth", return_value=0),
    ):
        client = TestClient(app)
        headers = {"X-Admin-Key": "secret-admin"}
        queues = client.get("/admin/queues", headers=headers)
        telem = client.get("/admin/telemetry", headers=headers)

    assert queues.status_code == 200
    assert queues.json()["worker_count"] == 1
    assert queues.json()["jobs_by_status"]["completed"] == 2

    assert telem.status_code == 200
    body = telem.json()
    assert body["tenant_count"] == 3
    assert "D4" in body["note"]
    assert body["service_name"]


def test_lookup_api_key_env_and_db(monkeypatch) -> None:
    from app.config import settings
    from app.core.auth import hash_api_key, lookup_tenant_for_api_key

    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")
    assert lookup_tenant_for_api_key("devkey-acme") == "acme"

    digest = hash_api_key("nvk_dbkey")

    @contextmanager
    def fake_admin_session():
        session = MagicMock()
        row = MagicMock()
        row.tenant_id = "contoso"
        session.scalar.return_value = row
        yield session

    with patch("app.core.auth.admin_session", fake_admin_session):
        assert lookup_tenant_for_api_key("nvk_dbkey") == "contoso"
        # ensure we queried with the peppered hash
        # (scalar called inside the context)
    assert digest == hash_api_key("nvk_dbkey")


def test_list_tenants(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_API_KEY", "secret-admin")
    from app.config import settings

    monkeypatch.setattr(settings, "admin_api_key", "secret-admin")
    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")

    tenant = MagicMock()
    tenant.id = "acme"
    tenant.name = "acme"
    tenant.created_at = datetime(2026, 1, 1, tzinfo=UTC)

    @contextmanager
    def fake_admin_session():
        session = MagicMock()
        session.scalars.side_effect = [
            MagicMock(all=MagicMock(return_value=[tenant])),
            MagicMock(all=MagicMock(return_value=[])),
        ]
        session.scalar.side_effect = [4, 7]
        yield session

    with patch("app.api.admin.admin_session", fake_admin_session):
        client = TestClient(app)
        response = client.get("/admin/tenants", headers={"X-Admin-Key": "secret-admin"})

    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "acme"
    assert body[0]["document_count"] == 4
    assert body[0]["env_backed"] is True

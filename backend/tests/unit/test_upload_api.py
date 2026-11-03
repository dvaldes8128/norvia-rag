"""Unit tests for upload validation and the /upload endpoint (mocked I/O)."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.uploads import _safe_filename, _validate_pdf
from app.main import app


def test_safe_filename_strips_path_and_forces_pdf() -> None:
    assert _safe_filename("../../evil.exe") == "evil.exe.pdf"
    assert _safe_filename("My Policy (v2).PDF") == "My_Policy_v2_.PDF"


def test_validate_pdf_rejects_bad_magic() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_pdf("application/pdf", "a.pdf", b"NOTPDF")
    assert exc.value.status_code == 400


def test_validate_pdf_rejects_non_pdf_extension() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_pdf("application/pdf", "a.txt", b"%PDF-1.4")
    assert exc.value.status_code == 415


def test_upload_requires_auth() -> None:
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("doc.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "unauthorized"


def _patch_upload_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import uploads as uploads_mod
    from app.config import settings

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tenant_api_keys", "acme:devkey-acme")
    monkeypatch.setattr(uploads_mod.settings, "upload_dir", str(tmp_path))


def test_upload_accepts_pdf_and_enqueues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    _patch_upload_settings(tmp_path, monkeypatch)

    mock_session = MagicMock()

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield mock_session

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.uploads.tenant_session", fake_tenant_session),
        patch("app.api.uploads.detect_filename_conflict", return_value=None),
        patch("app.api.uploads.process_ingestion") as task,
    ):
        task.delay = MagicMock()
        client = TestClient(app)
        response = client.post(
            "/upload",
            headers={"X-API-Key": "devkey-acme"},
            files={"file": ("policy.pdf", b"%PDF-1.4\ncontent", "application/pdf")},
        )

    assert response.status_code == 202
    data = response.json()
    assert data["status"] == "pending"
    assert data["filename"] == "policy.pdf"
    assert "job_id" in data
    task.delay.assert_called_once()
    mock_session.add.assert_called_once()


def test_upload_filename_conflict_returns_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from app.ingestion.pipeline import FilenameConflict

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    _patch_upload_settings(tmp_path, monkeypatch)

    conflict = FilenameConflict(
        document_id=uuid4(),
        filename="policy.pdf",
        version=1,
        content_hash="a" * 64,
    )
    mock_session = MagicMock()

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield mock_session

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.uploads.tenant_session", fake_tenant_session),
        patch("app.api.uploads.detect_filename_conflict", return_value=conflict),
        patch("app.api.uploads.process_ingestion") as task,
    ):
        task.delay = MagicMock()
        client = TestClient(app)
        response = client.post(
            "/upload",
            headers={"X-API-Key": "devkey-acme"},
            files={"file": ("policy.pdf", b"%PDF-1.4\ncontent-v2", "application/pdf")},
        )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "filename_conflict"
    assert body["detail"]["existing_document_id"] == str(conflict.document_id)
    task.delay.assert_not_called()


def test_upload_confirm_replace_enqueues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from app.ingestion.pipeline import FilenameConflict

    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("TENANT_API_KEYS", "acme:devkey-acme")
    _patch_upload_settings(tmp_path, monkeypatch)

    doc_id = uuid4()
    conflict = FilenameConflict(
        document_id=doc_id,
        filename="policy.pdf",
        version=1,
        content_hash="a" * 64,
    )
    mock_session = MagicMock()

    @contextmanager
    def fake_tenant_session(_tenant_id: str):
        yield mock_session

    with (
        patch("app.core.auth.ensure_tenant"),
        patch("app.api.uploads.tenant_session", fake_tenant_session),
        patch("app.api.uploads.detect_filename_conflict", return_value=conflict),
        patch("app.api.uploads.process_ingestion") as task,
    ):
        task.delay = MagicMock()
        client = TestClient(app)
        response = client.post(
            f"/upload?confirm=replace&replace_document_id={doc_id}",
            headers={"X-API-Key": "devkey-acme"},
            files={"file": ("policy.pdf", b"%PDF-1.4\ncontent-v2", "application/pdf")},
        )

    assert response.status_code == 202
    kwargs = task.delay.call_args.kwargs
    assert kwargs["replace_mode"] == "replace"
    assert kwargs["replace_document_id"] == str(doc_id)

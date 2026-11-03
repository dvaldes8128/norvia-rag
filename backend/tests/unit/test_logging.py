"""Unit tests for structured logging + correlation id + redaction (Q6). DB-free."""

from __future__ import annotations

import json

import pytest

from app.core import logging as applog


def _last_json_line(raw: str) -> dict:
    lines = [line for line in raw.strip().splitlines() if line.strip().startswith("{")]
    assert lines, f"no JSON log line found in output: {raw!r}"
    return json.loads(lines[-1])


def test_log_line_carries_bound_correlation_id(capsys: pytest.CaptureFixture[str]) -> None:
    applog.setup_logging("INFO")
    applog.clear_correlation()
    applog.bind_correlation_id("corr-123")

    log = applog.get_logger("test")
    log.info("ask.completed", tenant_id="acme", citation_count=2)

    record = _last_json_line(capsys.readouterr().out)
    assert record["correlation_id"] == "corr-123"
    assert record["tenant_id"] == "acme"
    assert record["event"] == "ask.completed"


def test_redacted_text_omits_full_content(capsys: pytest.CaptureFixture[str]) -> None:
    applog.setup_logging("INFO")
    applog.clear_correlation()
    applog.bind_correlation_id("corr-xyz")

    secret = "TOPSECRET " * 50  # a long user question / document body
    log = applog.get_logger("test")
    log.info("ask.received", tenant_id="acme", **applog.redacted_text("question", secret))

    raw = capsys.readouterr().out
    record = _last_json_line(raw)
    # Only safe metadata is logged, never the full text.
    assert record["question_len"] == len(secret)
    assert len(record["question_sha256"]) == 8
    assert len(record["question_preview"]) <= 32
    assert secret not in raw


def test_redacted_text_shapes() -> None:
    fields = applog.redacted_text("doc", "hello world", preview_chars=4)
    assert fields["doc_len"] == 11
    assert fields["doc_preview"] == "hell"
    assert isinstance(fields["doc_sha256"], str)

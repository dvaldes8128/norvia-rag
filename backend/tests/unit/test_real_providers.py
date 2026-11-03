"""Unit tests for real provider retries and ProviderError mapping (F5.3 / Q2.2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.config import settings
from app.providers.base import ProviderError
from app.providers.real import RealEmbeddings, RealLLM


@pytest.fixture
def fast_retries(monkeypatch):
    monkeypatch.setattr(settings, "provider_max_retries", 3)
    monkeypatch.setattr(settings, "provider_backoff_base_seconds", 0.01)
    monkeypatch.setattr(settings, "provider_timeout_seconds", 1.0)
    monkeypatch.setattr(settings, "real_llm_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "real_llm_model", "test-model")
    monkeypatch.setattr(settings, "real_llm_api_key", "test-key")
    monkeypatch.setattr(settings, "real_embeddings_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "real_embeddings_model", "test-emb")
    monkeypatch.setattr(settings, "real_embeddings_api_key", "test-key")
    monkeypatch.setattr(settings, "embeddings_dim", 8)


def _response(status: int, *, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.text = text or f"status {status}"
    resp.json.return_value = json_body or {}
    return resp


def test_exhausted_429_becomes_provider_error(fast_retries) -> None:
    llm = RealLLM()
    with patch("app.providers.real.httpx.post", return_value=_response(429, text="slow")) as post:
        with pytest.raises(ProviderError, match="rate limited"):
            llm.generate("hello")
    assert post.call_count == 3


def test_timeout_is_retried_then_provider_error(fast_retries) -> None:
    llm = RealLLM()
    with patch(
        "app.providers.real.httpx.post",
        side_effect=httpx.TimeoutException("deadline"),
    ) as post:
        with pytest.raises(ProviderError, match="timed out"):
            llm.generate("hello")
    assert post.call_count == 3


def test_transport_error_maps_to_provider_error(fast_retries) -> None:
    llm = RealLLM()
    with patch(
        "app.providers.real.httpx.post",
        side_effect=httpx.ConnectError("refused"),
    ) as post:
        with pytest.raises(ProviderError, match="transport error"):
            llm.generate("hello")
    assert post.call_count == 3


def test_client_4xx_is_not_retried(fast_retries) -> None:
    llm = RealLLM()
    with patch(
        "app.providers.real.httpx.post",
        return_value=_response(400, text="bad request"),
    ) as post:
        with pytest.raises(ProviderError, match="HTTP 400"):
            llm.generate("hello")
    assert post.call_count == 1


def test_5xx_is_retried_then_provider_error(fast_retries) -> None:
    llm = RealLLM()
    with patch(
        "app.providers.real.httpx.post",
        return_value=_response(503, text="unavailable"),
    ) as post:
        with pytest.raises(ProviderError, match="HTTP 503"):
            llm.generate("hello")
    assert post.call_count == 3


def test_success_after_transient_429(fast_retries) -> None:
    llm = RealLLM()
    ok = _response(
        200,
        json_body={
            "choices": [{"message": {"content": "ok answer"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        },
    )
    with patch(
        "app.providers.real.httpx.post",
        side_effect=[_response(429, text="slow"), ok],
    ) as post:
        result = llm.generate("hello")
    assert result.text == "ok answer"
    assert post.call_count == 2


def test_embeddings_exhausted_429_becomes_provider_error(fast_retries) -> None:
    emb = RealEmbeddings()
    with patch("app.providers.real.httpx.post", return_value=_response(429)) as post:
        with pytest.raises(ProviderError, match="rate limited"):
            emb.embed(["hola"])
    assert post.call_count == 3


def test_stream_surfaces_provider_error(fast_retries) -> None:
    llm = RealLLM()
    with patch("app.providers.real.httpx.post", return_value=_response(429)):
        with pytest.raises(ProviderError, match="rate limited"):
            next(llm.stream("hello"))

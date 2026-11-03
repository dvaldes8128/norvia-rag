"""Real provider adapter (custom, no LiteLLM).

Talks to any OpenAI-compatible HTTP endpoint (chat/completions + embeddings),
configured entirely via environment variables. Wraps calls with:

* a request **timeout**,
* **retries with exponential backoff** (tenacity) for timeouts, transport errors,
  HTTP 429, and HTTP 5xx,
* final failures always raised as :class:`ProviderError` (API → 503 envelope).

This keeps a single code path whether you point it at Gemini behind an
OpenAI-compatible gateway, a self-hosted model, or any other vendor.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.providers.base import LLMResult, ProviderError


class _Transient(Exception):
    """Retriable upstream failure; mapped to ProviderError after retries exhaust."""


def _retrying():
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.provider_max_retries),
        wait=wait_exponential(multiplier=settings.provider_backoff_base_seconds, max=30),
        retry=retry_if_exception_type(_Transient),
    )


def _as_provider_error(exc: BaseException) -> ProviderError:
    if isinstance(exc, ProviderError):
        return exc
    return ProviderError(str(exc))


def _post_json(url: str, *, api_key: str, payload: dict) -> httpx.Response:
    try:
        return httpx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=settings.provider_timeout_seconds,
        )
    except httpx.TimeoutException as exc:
        raise _Transient("request timed out") from exc
    except httpx.TransportError as exc:
        raise _Transient(f"transport error: {exc}") from exc


def _raise_for_status(resp: httpx.Response, *, what: str) -> None:
    if resp.status_code == 429:
        raise _Transient(f"{what} rate limited (HTTP 429)")
    if resp.status_code >= 500:
        raise _Transient(f"{what} HTTP {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400:
        raise ProviderError(f"{what} HTTP {resp.status_code}: {resp.text[:200]}")


class RealEmbeddings:
    def __init__(self) -> None:
        self.dim = settings.embeddings_dim
        self._base = settings.real_embeddings_base_url.rstrip("/")
        self._model = settings.real_embeddings_model
        self._key = settings.real_embeddings_api_key
        if not (self._base and self._model and self._key):
            raise ProviderError("Real embeddings provider is not fully configured")

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            return self._call(texts)
        except _Transient as exc:
            raise _as_provider_error(exc) from exc

    @_retrying()
    def _call(self, texts: list[str]) -> list[list[float]]:
        resp = _post_json(
            f"{self._base}/embeddings",
            api_key=self._key,
            payload={"model": self._model, "input": texts},
        )
        _raise_for_status(resp, what="Embeddings")
        data = resp.json()["data"]
        return [item["embedding"] for item in data]


class RealLLM:
    def __init__(self) -> None:
        self._base = settings.real_llm_base_url.rstrip("/")
        self.model = settings.real_llm_model
        self._key = settings.real_llm_api_key
        if not (self._base and self.model and self._key):
            raise ProviderError("Real LLM provider is not fully configured")

    def generate(self, prompt: str) -> LLMResult:
        try:
            return self._call(prompt)
        except _Transient as exc:
            raise _as_provider_error(exc) from exc

    def stream(self, prompt: str) -> Iterator[str]:
        # Non-incremental fallback until a real SSE client is wired; errors still
        # surface as ProviderError via generate().
        yield self.generate(prompt).text

    @_retrying()
    def _call(self, prompt: str) -> LLMResult:
        resp = _post_json(
            f"{self._base}/chat/completions",
            api_key=self._key,
            payload={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
        )
        _raise_for_status(resp, what="LLM")
        body = resp.json()
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=self.model,
        )

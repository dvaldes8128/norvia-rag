"""Real provider adapter (custom, no LiteLLM).

Talks to any OpenAI-compatible HTTP endpoint (chat/completions + embeddings),
configured entirely via environment variables. Wraps calls with:

* a request **timeout**,
* **retries with exponential backoff** (tenacity),
* explicit **rate-limit handling** (HTTP 429 -> retried).

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


class _RateLimited(Exception):
    pass


def _retrying():
    return retry(
        reraise=True,
        stop=stop_after_attempt(settings.provider_max_retries),
        wait=wait_exponential(multiplier=settings.provider_backoff_base_seconds, max=30),
        retry=retry_if_exception_type((_RateLimited, httpx.TransportError)),
    )


class RealEmbeddings:
    def __init__(self) -> None:
        self.dim = settings.embeddings_dim
        self._base = settings.real_embeddings_base_url.rstrip("/")
        self._model = settings.real_embeddings_model
        self._key = settings.real_embeddings_api_key
        if not (self._base and self._model and self._key):
            raise ProviderError("Real embeddings provider is not fully configured")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._call(texts)

    @_retrying()
    def _call(self, texts: list[str]) -> list[list[float]]:
        try:
            resp = httpx.post(
                f"{self._base}/embeddings",
                headers={"Authorization": f"Bearer {self._key}"},
                json={"model": self._model, "input": texts},
                timeout=settings.provider_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("Embeddings request timed out") from exc
        if resp.status_code == 429:
            raise _RateLimited()
        if resp.status_code >= 400:
            raise ProviderError(f"Embeddings HTTP {resp.status_code}: {resp.text[:200]}")
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
        return self._call(prompt, stream=False)

    def stream(self, prompt: str) -> Iterator[str]:
        # Minimal non-incremental fallback; true SSE streaming can be added later.
        yield self.generate(prompt).text

    @_retrying()
    def _call(self, prompt: str, *, stream: bool) -> LLMResult:
        try:
            resp = httpx.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=settings.provider_timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("LLM request timed out") from exc
        if resp.status_code == 429:
            raise _RateLimited()
        if resp.status_code >= 400:
            raise ProviderError(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        usage = body.get("usage", {})
        return LLMResult(
            text=body["choices"][0]["message"]["content"],
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            model=self.model,
        )

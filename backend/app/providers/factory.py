"""Select providers from settings. Defaults to the deterministic fakes."""

from __future__ import annotations

from functools import lru_cache

from app.config import settings
from app.providers.base import EmbeddingsProvider, LLMProvider
from app.providers.fake import FakeEmbeddings, FakeLLM


@lru_cache(maxsize=1)
def get_embeddings_provider() -> EmbeddingsProvider:
    if settings.embeddings_provider == "real":
        from app.providers.real import RealEmbeddings

        return RealEmbeddings()
    return FakeEmbeddings(settings.embeddings_dim)


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    if settings.llm_provider == "real":
        from app.providers.real import RealLLM

        return RealLLM()
    return FakeLLM()

"""Provider abstractions for embeddings and LLM generation.

Two interchangeable implementations exist:

* :mod:`app.providers.fake` — deterministic, offline, no API keys (default).
* :mod:`app.providers.real` — configurable real backend (custom adapter) with
  timeouts, retries with backoff and rate-limit handling.

Selected via :mod:`app.providers.factory` from environment settings.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    model: str


@runtime_checkable
class EmbeddingsProvider(Protocol):
    """Maps texts to fixed-dimension vectors."""

    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding per input text."""
        ...


@runtime_checkable
class LLMProvider(Protocol):
    """Generates an answer from a fully-built prompt."""

    def generate(self, prompt: str) -> LLMResult:
        ...

    def stream(self, prompt: str) -> Iterator[str]:
        """Yield answer text incrementally (for streaming responses)."""
        ...


class ProviderError(RuntimeError):
    """Raised when a provider call ultimately fails (after retries)."""

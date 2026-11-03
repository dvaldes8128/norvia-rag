"""Deterministic, offline providers used by default (no external API keys).

Design choice: the fake embeddings are a **feature-hashing bag-of-words** encoder,
not random noise. Each token is hashed into a bucket with a signed contribution and
the vector is L2-normalised. This makes embeddings:

* deterministic — the same text always yields the same vector (idempotent ingestion,
  reproducible eval);
* lexically meaningful — texts that share words get higher cosine similarity, so
  retrieval and ``recall@k`` are actually exercised rather than being pure chance.

The fake LLM is likewise deterministic: it grounds its answer in the context block of
the prompt, so demos and tests are stable without a real model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator

from app.providers.base import LLMResult

# Unicode letters + digits (keeps ``póliza``); separate from tiktoken chunk sizing.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokenize(text: str) -> list[str]:
    return [m.group(0).casefold() for m in _TOKEN_RE.finditer(text)]


class FakeEmbeddings:
    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            # Empty/stopword-only text: stable non-zero unit vector.
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


class FakeLLM:
    """Deterministic LLM that answers strictly from the prompt's context.

    The QA layer builds a prompt with a ``Context:`` section (the retrieved chunks)
    and a ``Question:`` line. This fake picks the context sentence with the highest
    lexical overlap with the question — a grounded, reproducible stand-in for a model.
    """

    model = "fake-deterministic-1"

    def _answer(self, prompt: str) -> str:
        context, question = self._split_prompt(prompt)
        if not context.strip():
            return "I don't know based on the provided documents."
        sentences = re.split(r"(?<=[.!?])\s+", context)
        q_tokens = set(_tokenize(question))
        if not q_tokens:
            return sentences[0].strip()
        best = max(
            sentences,
            key=lambda s: len(q_tokens & set(_tokenize(s))),
            default="",
        )
        overlap = len(q_tokens & set(_tokenize(best)))
        if overlap == 0:
            return "I don't know based on the provided documents."
        return best.strip()

    @staticmethod
    def _split_prompt(prompt: str) -> tuple[str, str]:
        context, question = prompt, ""
        if "Question:" in prompt:
            context, _, question = prompt.rpartition("Question:")
        if "Context:" in context:
            context = context.partition("Context:")[2]
        return context, question

    def generate(self, prompt: str) -> LLMResult:
        text = self._answer(prompt)
        return LLMResult(
            text=text,
            prompt_tokens=len(_tokenize(prompt)),
            completion_tokens=len(_tokenize(text)),
            model=self.model,
        )

    def stream(self, prompt: str) -> Iterator[str]:
        for word in self._answer(prompt).split(" "):
            yield word + " "

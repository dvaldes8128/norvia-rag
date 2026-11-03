"""Synthetic corpus helpers (R8) used by eval and integration tests."""

from __future__ import annotations

import json
from pathlib import Path

CORPUS_DIR = Path(__file__).resolve().parent
DOCUMENTS_DIR = CORPUS_DIR / "documents"
PDFS_DIR = CORPUS_DIR / "pdfs"
QUESTIONS_PATH = CORPUS_DIR / "questions.json"


def load_questions() -> list[dict]:
    return json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))


def document_sources() -> list[tuple[str, Path]]:
    """Return (doc_id, txt_path) pairs sorted by doc_id."""
    return sorted((p.stem, p) for p in DOCUMENTS_DIR.glob("*.txt"))

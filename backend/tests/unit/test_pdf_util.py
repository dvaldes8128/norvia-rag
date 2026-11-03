"""Unit tests for the synthetic-corpus PDF writer."""

from __future__ import annotations

from pathlib import Path

from app.ingestion.pdf import extract_pages
from corpus.pdf_util import write_text_pdf


def test_write_text_pdf_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "policy.pdf"
    write_text_pdf(
        path,
        [
            "Flood damage is covered up to fifty thousand EUR under section A.",
            "Vehicle theft excess is five percent of market value.",
        ],
    )
    pages = extract_pages(path)
    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert "flood" in pages[0].text.lower()
    assert "theft" in pages[1].text.lower()

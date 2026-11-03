"""Unit tests for PDF extraction with page numbers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.errors import PermanentIngestionError
from app.ingestion.pdf import extract_pages

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "sample_policy.pdf"


def test_extract_pages_from_fixture() -> None:
    pages = extract_pages(FIXTURE)
    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2
    joined = " ".join(p.text for p in pages).lower()
    assert "flood" in joined
    assert "theft" in joined


def test_extract_pages_from_bytes() -> None:
    pages = extract_pages(FIXTURE.read_bytes())
    assert len(pages) == 2


def test_corrupt_pdf_is_permanent_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not a real pdf content")
    with pytest.raises(PermanentIngestionError, match="Corrupt|unreadable|Cannot"):
        extract_pages(bad)


def test_empty_text_pdf_is_permanent_error(tmp_path: Path) -> None:
    # Valid PDF structure with a blank page (no text operators).
    blank = (
        b"%PDF-1.4\n"
        b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n"
        b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n"
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<< /Size 4 /Root 1 0 R >>\nstartxref\n178\n%%EOF\n"
    )
    path = tmp_path / "blank.pdf"
    path.write_bytes(blank)
    with pytest.raises(PermanentIngestionError, match="no extractable text|no pages"):
        extract_pages(path)


def test_missing_file_is_permanent_error(tmp_path: Path) -> None:
    with pytest.raises(PermanentIngestionError):
        extract_pages(tmp_path / "missing.pdf")

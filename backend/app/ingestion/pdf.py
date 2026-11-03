"""PDF text extraction with page numbers (F2.1)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingestion.errors import PermanentIngestionError


@dataclass(frozen=True)
class PageText:
    """One page of extracted text. ``page_number`` is 1-indexed."""

    page_number: int
    text: str


def extract_pages(source: str | Path | bytes) -> list[PageText]:
    """Extract plain text per page from a PDF file path or raw bytes.

    Raises:
        PermanentIngestionError: corrupt PDF, unreadable, or no extractable text.
    """
    try:
        reader = _open_reader(source)
    except PdfReadError as exc:
        raise PermanentIngestionError(f"Corrupt or unreadable PDF: {exc}") from exc
    except OSError as exc:
        raise PermanentIngestionError(f"Cannot open PDF: {exc}") from exc

    if reader.is_encrypted:
        # Try empty password; otherwise treat as permanent failure.
        try:
            unlocked = reader.decrypt("")
        except Exception as exc:  # noqa: BLE001 — pypdf raises varied types
            raise PermanentIngestionError(f"Encrypted PDF cannot be opened: {exc}") from exc
        if unlocked == 0:
            raise PermanentIngestionError("Encrypted PDF requires a password")

    pages: list[PageText] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            raise PermanentIngestionError(
                f"Failed extracting text from page {index + 1}: {exc}"
            ) from exc
        pages.append(PageText(page_number=index + 1, text=text))

    if not pages:
        raise PermanentIngestionError("PDF has no pages")

    if not any(p.text.strip() for p in pages):
        raise PermanentIngestionError("PDF has no extractable text")

    return pages


def _open_reader(source: str | Path | bytes) -> PdfReader:
    if isinstance(source, bytes):
        from io import BytesIO

        return PdfReader(BytesIO(source))
    return PdfReader(str(source))

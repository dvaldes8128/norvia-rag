"""Build corpus PDFs from the plain-text sources (R8).

Usage:
    uv run python -m corpus.build_pdfs
"""

from __future__ import annotations

from pathlib import Path

from corpus import PDFS_DIR, document_sources
from corpus.pdf_util import write_text_pdf


def build_all() -> list[tuple[str, Path]]:
    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    built: list[tuple[str, Path]] = []
    for doc_id, txt_path in document_sources():
        text = txt_path.read_text(encoding="utf-8").strip()
        pdf_path = PDFS_DIR / f"{doc_id}.pdf"
        write_text_pdf(pdf_path, [text])
        built.append((doc_id, pdf_path))
    return built


def main() -> None:
    built = build_all()
    for doc_id, path in built:
        print(f"wrote {doc_id} -> {path}")


if __name__ == "__main__":
    main()

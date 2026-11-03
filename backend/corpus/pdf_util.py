"""Minimal PDF writer for synthetic corpus (no extra deps)."""

from __future__ import annotations

from pathlib import Path


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_lines(text: str, width: int = 90) -> list[str]:
    words = text.replace("\n", " ").split()
    lines: list[str] = []
    current: list[str] = []
    length = 0
    for word in words:
        extra = len(word) + (1 if current else 0)
        if current and length + extra > width:
            lines.append(" ".join(current))
            current = [word]
            length = len(word)
        else:
            current.append(word)
            length += extra
    if current:
        lines.append(" ".join(current))
    return lines or [""]


def write_text_pdf(path: str | Path, pages: list[str]) -> Path:
    """Write a multi-page PDF with Helvetica text (one content block per page)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not pages:
        raise ValueError("pages must be non-empty")

    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []

    for page_text in pages:
        lines = _wrap_lines(page_text)
        parts = ["BT /F1 11 Tf 50 750 Td 14 TL"]
        first = True
        for line in lines:
            escaped = _escape_pdf_text(line)
            if first:
                parts.append(f"({escaped}) Tj")
                first = False
            else:
                parts.append(f"T* ({escaped}) Tj")
        parts.append("ET")
        stream = "\n".join(parts).encode("latin-1", errors="replace")
        content_id = add(
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
        page_id = add(
            (
                f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>"
            ).encode()
        )
        page_ids.append(page_id)

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode()
    )
    for pid in page_ids:
        objects[pid - 1] = objects[pid - 1].replace(
            b"/Parent 0 0 R", f"/Parent {pages_id} 0 R".encode()
        )

    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode())

    with out.open("wb") as fh:
        fh.write(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(fh.tell())
            fh.write(f"{index} 0 obj\n".encode())
            fh.write(obj)
            fh.write(b"\nendobj\n")
        xref_pos = fh.tell()
        fh.write(f"xref\n0 {len(objects) + 1}\n".encode())
        fh.write(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            fh.write(f"{off:010d} 00000 n \n".encode())
        fh.write(
            (
                f"trailer<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
                f"startxref\n{xref_pos}\n%%EOF\n"
            ).encode()
        )
    return out

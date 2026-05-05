from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # type: ignore[import-untyped]


@dataclass
class ExtractedPdf:
    full_text: str
    pages: list[str]
    page_count: int
    has_text_layer: bool


def extract_text(pdf_path: Path) -> ExtractedPdf:
    pages: list[str] = []
    parts: list[str] = []
    with fitz.open(pdf_path) as doc:
        page_count = doc.page_count
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append(text)
            parts.append(f"\n\n--- page {i} ---\n\n{text}")
    full_text = "".join(parts).strip()

    if page_count > 1 and len(full_text) < 100 * page_count:
        has_text_layer = False
    else:
        has_text_layer = bool(full_text.strip())

    return ExtractedPdf(
        full_text=full_text,
        pages=pages,
        page_count=page_count,
        has_text_layer=has_text_layer,
    )


def looks_like_pdf(blob: bytes) -> bool:
    return blob[:5] == b"%PDF-"

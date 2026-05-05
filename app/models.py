from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Paper:
    id: int
    title: str | None
    authors: list[str]
    first_author: str | None
    publication_date: str | None
    source_url: str | None
    memo: str | None
    pdf_filename: str
    pdf_path: str
    abstract: str | None
    page_count: int | None
    has_text_layer: bool
    metadata_status: str
    metadata_error: str | None
    created_at: datetime | str | None


@dataclass
class Translation:
    id: int
    paper_id: int
    language: str
    provider: str | None
    model: str | None
    status: str
    progress: int
    content_path: str | None
    error_message: str | None
    started_at: datetime | str | None
    completed_at: datetime | str | None

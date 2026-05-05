from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import config
from .util import last_name_of

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT,
    authors_json    TEXT,
    first_author    TEXT,
    display_authors TEXT,                 -- list-page label, user-editable; auto-seeded from first_author
    publication_date TEXT,
    source_url      TEXT,
    memo            TEXT,
    pdf_filename    TEXT NOT NULL,
    pdf_path        TEXT NOT NULL,
    abstract        TEXT,
    extracted_text  TEXT,
    page_count      INTEGER,
    has_text_layer  INTEGER DEFAULT 1,
    metadata_status TEXT DEFAULT 'pending',
    metadata_error  TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS translations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL,
    language        TEXT NOT NULL DEFAULT 'ja',
    provider        TEXT,
    model           TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    progress        INTEGER DEFAULT 0,
    content_path    TEXT,
    error_message   TEXT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    UNIQUE (paper_id, language)
);

CREATE INDEX IF NOT EXISTS idx_papers_created ON papers(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_translations_paper ON translations(paper_id);
"""


def init(db_path: Path | None = None) -> None:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        # Migrations: ALTER TABLE for columns added after the initial release.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
        if "display_authors" not in cols:
            conn.execute("ALTER TABLE papers ADD COLUMN display_authors TEXT")
            # Backfill the new column from first_author on existing rows.
            rows = conn.execute(
                "SELECT id, first_author FROM papers "
                "WHERE display_authors IS NULL AND first_author IS NOT NULL"
            ).fetchall()
            for row_id, first_author in rows:
                seed = last_name_of(first_author) or None
                conn.execute(
                    "UPDATE papers SET display_authors = ? WHERE id = ?",
                    (seed, row_id),
                )
        conn.commit()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

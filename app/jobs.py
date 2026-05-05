from __future__ import annotations

import asyncio
import json
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from . import config, db, pdf_utils
from .translator import build_metadata_provider, build_provider

_QUEUE: asyncio.Queue["Job"] | None = None
_WORKER_TASK: asyncio.Task | None = None


def _log(event: str, **fields: object) -> None:
    parts = [f"event={event}"]
    for k, v in fields.items():
        s = str(v).replace("\n", " ").replace("\r", " ")
        if " " in s or "=" in s:
            s = '"' + s.replace('"', "'") + '"'
        parts.append(f"{k}={s}")
    print(" ".join(parts), file=sys.stderr, flush=True)


@dataclass
class Job:
    kind: str  # 'metadata' | 'translate'
    paper_id: int
    force: bool = False


def get_queue() -> asyncio.Queue["Job"]:
    if _QUEUE is None:
        raise RuntimeError("Job queue not initialized")
    return _QUEUE


async def start_worker() -> None:
    global _QUEUE, _WORKER_TASK
    _QUEUE = asyncio.Queue()
    _WORKER_TASK = asyncio.create_task(_worker_loop(), name="rpp-worker")
    _log("worker_started")


async def stop_worker() -> None:
    global _WORKER_TASK
    if _WORKER_TASK is not None:
        _WORKER_TASK.cancel()
        try:
            await _WORKER_TASK
        except (asyncio.CancelledError, Exception):
            pass
        _WORKER_TASK = None


async def schedule(job: Job) -> None:
    await get_queue().put(job)


async def _worker_loop() -> None:
    queue = get_queue()
    while True:
        job = await queue.get()
        try:
            if job.kind == "metadata":
                await run_metadata(job.paper_id)
            elif job.kind == "translate":
                await run_translation(job.paper_id, force=job.force)
            else:
                _log("worker_unknown_job", kind=job.kind)
        except Exception as exc:
            _log("worker_job_failed", kind=job.kind, paper_id=job.paper_id, err=repr(exc))
            traceback.print_exc(file=sys.stderr)
        finally:
            queue.task_done()


# ---------------------------------------------------------------- metadata


async def run_metadata(paper_id: int) -> None:
    _log("metadata_start", paper_id=paper_id)
    cfg = config.load()

    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, pdf_path FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    if row is None:
        _log("metadata_missing_paper", paper_id=paper_id)
        return

    pdf_full_path = config.PDF_DIR / row["pdf_path"]
    try:
        extracted = await asyncio.to_thread(pdf_utils.extract_text, pdf_full_path)
    except Exception as exc:
        _set_metadata_failed(paper_id, f"PDF extraction failed: {exc}")
        return

    with db.connect() as conn:
        conn.execute(
            "UPDATE papers SET extracted_text = ?, page_count = ?, has_text_layer = ? WHERE id = ?",
            (
                extracted.full_text,
                extracted.page_count,
                1 if extracted.has_text_layer else 0,
                paper_id,
            ),
        )

    if not extracted.has_text_layer:
        _set_metadata_failed(paper_id, "No text layer (likely scanned)")
        return

    provider = build_metadata_provider()
    snippet = extracted.full_text[:6000]

    from .translator.base import METADATA_SYSTEM_PROMPT

    raw = ""
    parsed: dict | None = None
    last_error: str | None = None

    for attempt in range(2):
        sys_prompt = METADATA_SYSTEM_PROMPT
        if attempt == 1:
            sys_prompt += "\n\nIMPORTANT: respond with ONLY a valid JSON object. No code fences, no commentary."
        try:
            raw = await asyncio.wait_for(
                provider.complete_json(sys_prompt, snippet), timeout=70.0
            )
        except Exception as exc:
            last_error = f"LLM call failed: {exc}"
            continue

        try:
            parsed = _parse_json_response(raw)
            break
        except Exception as exc:
            last_error = f"JSON parse failed: {exc}; raw={raw[:200]}"
            parsed = None

    if parsed is None:
        _set_metadata_failed(paper_id, last_error or "metadata extraction failed")
        return

    title = _str_or_none(parsed.get("title"))
    authors_raw = parsed.get("authors") or []
    authors = [str(a) for a in authors_raw if a] if isinstance(authors_raw, list) else []
    pub_date = _str_or_none(parsed.get("publication_date"))
    abstract = _str_or_none(parsed.get("abstract")) or ""

    with db.connect() as conn:
        conn.execute(
            """
            UPDATE papers
            SET title = ?, authors_json = ?, first_author = ?,
                publication_date = ?, abstract = ?,
                metadata_status = 'done', metadata_error = NULL
            WHERE id = ?
            """,
            (
                title,
                json.dumps(authors, ensure_ascii=False),
                authors[0] if authors else None,
                pub_date,
                abstract,
                paper_id,
            ),
        )
    _log("metadata_done", paper_id=paper_id, title=title or "")


def _set_metadata_failed(paper_id: int, error: str) -> None:
    _log("metadata_failed", paper_id=paper_id, err=error)
    with db.connect() as conn:
        conn.execute(
            "UPDATE papers SET metadata_status = 'failed', metadata_error = ? WHERE id = ?",
            (error, paper_id),
        )


def _str_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _parse_json_response(raw: str) -> dict:
    text = raw.strip()
    # strip ```json fences if present
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # try direct parse, else find first {...} block
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise ValueError("metadata response was not a JSON object")
    return obj


# ---------------------------------------------------------------- translation


async def run_translation(paper_id: int, *, force: bool = False) -> None:
    _log("translate_start", paper_id=paper_id, force=force)
    cfg = config.load()

    with db.connect() as conn:
        paper = conn.execute(
            "SELECT id, extracted_text, has_text_layer FROM papers WHERE id = ?",
            (paper_id,),
        ).fetchone()
        trans = conn.execute(
            "SELECT * FROM translations WHERE paper_id = ? AND language = 'ja'",
            (paper_id,),
        ).fetchone()

    if paper is None:
        _log("translate_missing_paper", paper_id=paper_id)
        return
    if not paper["has_text_layer"]:
        _set_translation_failed(paper_id, "Cannot translate: no text layer in PDF")
        return
    if trans is None:
        _set_translation_failed(paper_id, "Translation row missing — internal error")
        return

    text = paper["extracted_text"] or ""
    if not text.strip():
        _set_translation_failed(paper_id, "Extracted text is empty")
        return

    with db.connect() as conn:
        conn.execute(
            "UPDATE translations SET status = 'running', progress = 0, error_message = NULL WHERE paper_id = ? AND language = 'ja'",
            (paper_id,),
        )

    chunks = chunk_text(text, max_chars=cfg.translation_chunk_chars)
    total = len(chunks)
    _log("translate_chunked", paper_id=paper_id, chunks=total)

    provider = build_provider()
    pieces: list[str] = []
    last_tail = ""

    for i, chunk in enumerate(chunks):
        try:
            translated = await _translate_with_retry(provider, chunk, last_tail)
        except Exception as exc:
            _set_translation_failed(
                paper_id,
                f"Chunk {i+1}/{total} failed: {exc}",
            )
            return
        pieces.append(translated)
        last_tail = translated[-300:]
        progress = int(round((i + 1) / total * 100))
        with db.connect() as conn:
            conn.execute(
                "UPDATE translations SET progress = ? WHERE paper_id = ? AND language = 'ja'",
                (progress, paper_id),
            )
        _log("translate_chunk_done", paper_id=paper_id, chunk=i + 1, total=total)

    output = "\n\n".join(pieces).strip() + "\n"
    out_path = config.TRANSLATION_DIR / f"{paper_id}.ja.md"
    out_path.write_text(output, encoding="utf-8")

    completed = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE translations
            SET status = 'done', progress = 100,
                content_path = ?, completed_at = ?,
                provider = ?, model = ?
            WHERE paper_id = ? AND language = 'ja'
            """,
            (
                f"{paper_id}.ja.md",
                completed,
                provider.name,
                provider.model,
                paper_id,
            ),
        )
    _log("translate_done", paper_id=paper_id, chars=len(output))


async def _translate_with_retry(provider, chunk: str, context: str) -> str:  # type: ignore[no-untyped-def]
    try:
        return await asyncio.wait_for(
            provider.translate_chunk(chunk, context=context), timeout=120.0
        )
    except Exception:
        await asyncio.sleep(2.0)
        return await asyncio.wait_for(
            provider.translate_chunk(chunk, context=context), timeout=120.0
        )


def _set_translation_failed(paper_id: int, error: str) -> None:
    _log("translate_failed", paper_id=paper_id, err=error)
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE translations
            SET status = 'failed', error_message = ?
            WHERE paper_id = ? AND language = 'ja'
            """,
            (error, paper_id),
        )


# ---------------------------------------------------------------- chunking

_PAGE_SEP = re.compile(r"\n\n--- page \d+ ---\n\n")


def chunk_text(text: str, *, max_chars: int) -> list[str]:
    """Split into chunks of <= max_chars, preferring page breaks, then blank lines, then sentences."""
    if len(text) <= max_chars:
        return [text]

    # Split by page boundaries first, keeping the separator markers.
    pieces = _split_keep(text, _PAGE_SEP)
    units: list[str] = pieces

    # If any single unit still exceeds max_chars, split it on blank lines.
    refined: list[str] = []
    for u in units:
        if len(u) <= max_chars:
            refined.append(u)
        else:
            refined.extend(_split_blank_lines(u, max_chars))
    units = refined

    # If any single unit still exceeds max_chars, split on sentence boundaries.
    refined = []
    for u in units:
        if len(u) <= max_chars:
            refined.append(u)
        else:
            refined.extend(_split_sentences(u, max_chars))
    units = refined

    # Greedily pack units into chunks.
    chunks: list[str] = []
    current = ""
    for u in units:
        if not current:
            current = u
        elif len(current) + len(u) <= max_chars:
            current += u
        else:
            chunks.append(current)
            current = u
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


def _split_keep(text: str, pattern: re.Pattern[str]) -> list[str]:
    out: list[str] = []
    last = 0
    for m in pattern.finditer(text):
        if m.start() > last:
            out.append(text[last : m.start()])
        out.append(m.group(0))
        last = m.end()
    if last < len(text):
        out.append(text[last:])
    return out


def _split_blank_lines(text: str, max_chars: int) -> list[str]:
    parts = re.split(r"(\n\s*\n)", text)
    out: list[str] = []
    for p in parts:
        if not p:
            continue
        if len(p) <= max_chars:
            out.append(p)
        else:
            # fall back to sentence split
            out.extend(_split_sentences(p, max_chars))
    return out


def _split_sentences(text: str, max_chars: int) -> list[str]:
    # Naive sentence split; safe — equations are still kept as runs
    sentences = re.split(r"(?<=[.!?。!?])\s+", text)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if len(s) > max_chars:
            # hard split as last resort
            for i in range(0, len(s), max_chars):
                out.append(s[i : i + max_chars])
            buf = ""
            continue
        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf = buf + " " + s
        else:
            out.append(buf)
            buf = s
    if buf:
        out.append(buf)
    return out

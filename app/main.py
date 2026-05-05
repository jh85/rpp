from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import config, db, jobs, pdf_utils
from .translator import build_provider

cfg = config.load()
db.init()

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _parse_authors(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        out = json.loads(raw)
        return [str(a) for a in out] if isinstance(out, list) else []
    except json.JSONDecodeError:
        return []


def _truncate(s: str | None, n: int = 80) -> str:
    if not s:
        return ""
    s = s.strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


templates.env.filters["truncate_text"] = _truncate
templates.env.filters["authors_list"] = _parse_authors


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    await jobs.start_worker()
    try:
        yield
    finally:
        await jobs.stop_worker()


app = FastAPI(title="rpp - Research Paper Manager", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def list_papers(request: Request) -> HTMLResponse:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, t.status AS translation_status, t.progress AS translation_progress
            FROM papers p
            LEFT JOIN translations t ON t.paper_id = p.id AND t.language = 'ja'
            ORDER BY p.created_at DESC
            """
        ).fetchall()
    papers = [dict(r) for r in rows]
    return templates.TemplateResponse(
        request, "list.html", {"papers": papers, "title": "rpp - Papers"}
    )


@app.get("/papers/new", response_class=HTMLResponse)
async def upload_form(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "upload.html", {"title": "Upload paper"}
    )


@app.post("/papers")
async def upload_paper(
    pdf: UploadFile,
    source_url: str = Form(...),
    memo: str = Form(""),
) -> RedirectResponse:
    blob = await pdf.read()
    if not pdf_utils.looks_like_pdf(blob):
        raise HTTPException(status_code=400, detail="Uploaded file is not a PDF")

    filename = pdf.filename or "uploaded.pdf"

    with db.connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO papers (pdf_filename, pdf_path, source_url, memo, metadata_status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (filename, "__pending__", source_url, memo),
        )
        paper_id = cur.lastrowid

    pdf_path = f"{paper_id}.pdf"
    (config.PDF_DIR / pdf_path).write_bytes(blob)

    with db.connect() as conn:
        conn.execute(
            "UPDATE papers SET pdf_path = ? WHERE id = ?", (pdf_path, paper_id)
        )

    await jobs.schedule(jobs.Job(kind="metadata", paper_id=paper_id))
    return RedirectResponse(url=f"/papers/{paper_id}", status_code=303)


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
async def paper_detail(request: Request, paper_id: int) -> HTMLResponse:
    paper = _get_paper(paper_id)
    trans = _get_translation(paper_id)
    cfg_obj = config.load()
    return templates.TemplateResponse(
        request,
        "paper.html",
        {
            "title": paper["title"] or paper["pdf_filename"],
            "paper": paper,
            "translation": trans,
            "translation_provider": cfg_obj.translation_provider,
            "translation_model": cfg_obj.model_for(cfg_obj.translation_provider),
        },
    )


@app.get("/papers/{paper_id}/pdf")
async def paper_pdf(paper_id: int) -> FileResponse:
    paper = _get_paper(paper_id)
    path = config.PDF_DIR / paper["pdf_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF file missing")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=paper["pdf_filename"],
        headers={"Content-Disposition": f'inline; filename="{paper["pdf_filename"]}"'},
    )


@app.get("/papers/{paper_id}/translation", response_class=HTMLResponse)
async def translation_page(request: Request, paper_id: int) -> HTMLResponse:
    paper = _get_paper(paper_id)
    trans = _get_translation(paper_id)
    rendered = ""
    if trans and trans["status"] == "done" and trans["content_path"]:
        md_text = (config.TRANSLATION_DIR / trans["content_path"]).read_text(
            encoding="utf-8"
        )
        rendered = md.markdown(
            md_text,
            extensions=[
                "fenced_code",
                "tables",
                "pymdownx.arithmatex",
            ],
            extension_configs={"pymdownx.arithmatex": {"generic": True}},
        )
    cfg_obj = config.load()
    return templates.TemplateResponse(
        request,
        "translation.html",
        {
            "title": f"Translation – {paper['title'] or paper['pdf_filename']}",
            "paper": paper,
            "translation": trans,
            "rendered": rendered,
            "translation_provider": cfg_obj.translation_provider,
            "translation_model": cfg_obj.model_for(cfg_obj.translation_provider),
        },
    )


@app.post("/papers/{paper_id}/translate")
async def trigger_translation(paper_id: int, force: int = 0) -> RedirectResponse:
    paper = _get_paper(paper_id)
    if not paper["has_text_layer"]:
        raise HTTPException(status_code=400, detail="No text layer in PDF")

    trans = _get_translation(paper_id)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cfg_obj = config.load()

    schedule = False
    with db.connect() as conn:
        if trans is None:
            conn.execute(
                """
                INSERT INTO translations
                (paper_id, language, provider, model, status, progress, started_at)
                VALUES (?, 'ja', ?, ?, 'pending', 0, ?)
                """,
                (
                    paper_id,
                    cfg_obj.translation_provider,
                    cfg_obj.model_for(cfg_obj.translation_provider),
                    started,
                ),
            )
            schedule = True
        elif trans["status"] == "running":
            schedule = False
        elif trans["status"] == "done" and not force:
            schedule = False
        else:
            conn.execute(
                """
                UPDATE translations
                SET status = 'pending', progress = 0, error_message = NULL,
                    started_at = ?, completed_at = NULL,
                    provider = ?, model = ?
                WHERE paper_id = ? AND language = 'ja'
                """,
                (
                    started,
                    cfg_obj.translation_provider,
                    cfg_obj.model_for(cfg_obj.translation_provider),
                    paper_id,
                ),
            )
            schedule = True

    if schedule:
        await jobs.schedule(jobs.Job(kind="translate", paper_id=paper_id, force=bool(force)))

    return RedirectResponse(url=f"/papers/{paper_id}/translation", status_code=303)


@app.get("/papers/{paper_id}/translation/status", response_class=HTMLResponse)
async def translation_status(request: Request, paper_id: int) -> HTMLResponse:
    paper = _get_paper(paper_id)
    trans = _get_translation(paper_id)
    rendered = ""
    if trans and trans["status"] == "done" and trans["content_path"]:
        md_text = (config.TRANSLATION_DIR / trans["content_path"]).read_text(
            encoding="utf-8"
        )
        rendered = md.markdown(
            md_text,
            extensions=[
                "fenced_code",
                "tables",
                "pymdownx.arithmatex",
            ],
            extension_configs={"pymdownx.arithmatex": {"generic": True}},
        )
    return templates.TemplateResponse(
        request,
        "partials/translation_status.html",
        {"paper": paper, "translation": trans, "rendered": rendered},
    )


@app.post("/papers/{paper_id}/delete")
async def delete_paper(paper_id: int) -> RedirectResponse:
    paper = _get_paper(paper_id)
    pdf_path = config.PDF_DIR / paper["pdf_path"]
    trans = _get_translation(paper_id)
    if trans and trans["content_path"]:
        tpath = config.TRANSLATION_DIR / trans["content_path"]
        if tpath.exists():
            tpath.unlink()
    if pdf_path.exists():
        pdf_path.unlink()
    with db.connect() as conn:
        conn.execute("DELETE FROM translations WHERE paper_id = ?", (paper_id,))
        conn.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
    return RedirectResponse(url="/", status_code=303)


@app.put("/papers/{paper_id}/memo", response_class=HTMLResponse)
async def update_memo(request: Request, paper_id: int, memo: str = Form("")) -> HTMLResponse:
    _get_paper(paper_id)
    with db.connect() as conn:
        conn.execute("UPDATE papers SET memo = ? WHERE id = ?", (memo, paper_id))
    safe = (memo or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = (
        '<div id="memo-block">'
        f'<blockquote>{safe or "<em>(no memo)</em>"}</blockquote>'
        '<button hx-get="/papers/' + str(paper_id) + '/memo/edit" '
        'hx-target="#memo-block" hx-swap="outerHTML">Edit memo</button>'
        "</div>"
    )
    return HTMLResponse(body)


@app.get("/papers/{paper_id}/memo/edit", response_class=HTMLResponse)
async def edit_memo(paper_id: int) -> HTMLResponse:
    paper = _get_paper(paper_id)
    memo = (paper["memo"] or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    body = (
        '<form id="memo-block" hx-put="/papers/' + str(paper_id) + '/memo" '
        'hx-target="#memo-block" hx-swap="outerHTML">'
        f'<textarea name="memo" rows="4" style="width:100%">{memo}</textarea>'
        '<button type="submit">Save</button>'
        "</form>"
    )
    return HTMLResponse(body)


# ---------------------------------------------------------------- helpers


def _get_paper(paper_id: int) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return dict(row)


def _get_translation(paper_id: int) -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM translations WHERE paper_id = ? AND language = 'ja'",
            (paper_id,),
        ).fetchone()
    return dict(row) if row else None

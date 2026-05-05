# rpp — Personal Research Paper Manager

A single-user, locally-hosted, fully-portable web app for managing research
papers. Upload a PDF, attach a source URL and a personal memo; an LLM agent
extracts metadata and produces a Japanese translation on demand. Everything —
code, config, database, PDFs, translations — lives under this one project
directory, so backing up = copying the folder.

Built per `paper_manager_spec.md`.

---

## Quick start

```bash
git clone https://github.com/<your-user>/rpp.git
cd rpp
cp .env.example .env
# edit .env and add at least one provider API key
./run.sh
# open http://127.0.0.1:8765
```

The first `./run.sh` creates `.venv/`, installs dependencies, and starts
`uvicorn` on `127.0.0.1:8765` (override via `HOST`/`PORT`).

---

## Switching translation provider

Three providers are supported out of the box: **Anthropic Claude**,
**OpenAI**, and **ZhipuAI GLM**. To switch, edit `.env`:

```dotenv
TRANSLATION_PROVIDER=anthropic    # or "openai" | "glm"
```

Make sure the corresponding `*_API_KEY` is set. Optionally, set
`METADATA_PROVIDER` to use a cheaper model for the (much shorter) metadata
extraction step. If unset, metadata uses the same provider as translation.

Adding a new provider only requires a new class implementing
`TranslationProvider` in `app/translator/` and a branch in
`app/translator/__init__.py:build_provider`.

---

## Backup

Stop the server, then either:

```bash
tar czf rpp-backup-$(date +%F).tgz rpp/
# or
rsync -a rpp/ /path/to/backup/rpp/
```

Restore by un-taring (or rsyncing back) and running `./run.sh`.

All mutable state lives under `rpp/data/`:

```
data/
├── papers.db            # SQLite database
├── pdfs/                # original PDFs, named <paper_id>.pdf
└── translations/        # translation Markdown, <paper_id>.ja.md
```

The `.venv/` is regenerated on first run from `requirements.txt`, so it's safe
to omit from backups.

## Moving to a new machine

Copy the entire `rpp/` directory (with `data/`) to the new machine, run
`./run.sh`, and your papers, PDFs, and translations are at the same URLs.

## Exposing remotely

There is **no authentication**. Bind stays on `127.0.0.1`. To use it from
another machine, tunnel over SSH:

```bash
ssh -L 8765:127.0.0.1:8765 user@host
# then open http://127.0.0.1:8765 locally
```

Do **not** set `HOST=0.0.0.0` unless you put it behind your own auth /
reverse proxy.

---

## Implementation notes / deviations from spec

- **Pico.css** is loaded from CDN; htmx is vendored under `app/static/` per
  spec. MathJax is loaded from CDN on the translation page only.
- The memo edit endpoint is `PUT /papers/{id}/memo` (the small extra route the
  spec explicitly allows), with a companion `GET /papers/{id}/memo/edit` for
  the edit form.
- The background runner is a single in-process `asyncio.Queue` worker started
  in the FastAPI lifespan. Concurrency is intentionally 1: a single user
  doesn't need parallel LLM calls and this avoids runaway costs.
- LLM SDK calls have a 60s SDK-level timeout and one in-process retry on
  transient errors; chunk translations have an additional 120s wait_for.
- The metadata response parser strips ```json fences and falls back to
  finding the first `{...}` block, so common LLM formatting quirks don't
  break extraction.

## Stretch goals (not built)

Full-text search (SQLite FTS5), tagging, BibTeX export, side-by-side view, and
annotations are designed-for but deliberately out of scope for v1. The schema
and file layout already support adding them.

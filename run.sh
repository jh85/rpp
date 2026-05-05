#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt
mkdir -p data/pdfs data/translations
if [ -f .env ]; then
  set -a; source .env; set +a
fi
exec uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8765}"

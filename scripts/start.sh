#!/usr/bin/env bash
set -euo pipefail
exec .venv/bin/uvicorn app.main:app --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"

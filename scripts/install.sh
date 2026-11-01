#!/usr/bin/env bash
set -euo pipefail
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip ffmpeg
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
if ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  .venv/bin/playwright install --with-deps chromium
fi
mkdir -p data/exports
[ -f .env ] || cp .env.example .env
echo "Installation terminee. Configure GOOGLE_PLACES_API_KEY dans .env puis lance scripts/start.sh"

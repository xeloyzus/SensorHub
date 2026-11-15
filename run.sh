#!/usr/bin/env bash
# Start (or update) the campus monitoring stack.
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "First-time setup needs python3. Install it, then run bash run.sh again." >&2
    exit 1
  fi
  python3 scripts/setup_env.py "$@"
elif [ "$#" -gt 0 ]; then
  echo ".env already exists. Edit its DOMAIN directly; existing secrets are preserved." >&2
  exit 1
fi

docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build

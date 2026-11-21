#!/usr/bin/env bash
# Start (or update) the campus monitoring stack.
set -euo pipefail

cd "$(dirname "$0")"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Required command '$1' was not found." >&2
    echo "Install Docker Engine and the Compose plugin, then run bash run.sh again." >&2
    exit 1
  fi
}

require_command docker
require_command python3

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is not available." >&2
  echo "Install the Docker Compose plugin, then run bash run.sh again." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "The Docker daemon is unavailable or this user cannot access it." >&2
  echo "Start Docker and ensure this user belongs to the docker group, then try again." >&2
  exit 1
fi

if [ ! -f .env ]; then
  python3 scripts/setup_env.py "$@"
elif [ "$#" -gt 0 ]; then
  echo ".env already exists. Edit its DOMAIN directly; existing secrets are preserved." >&2
  exit 1
fi

# Add the Semtech Gateway Bridge credential when upgrading an older .env.
# The helper preserves every existing setting and generates only this missing
# secret, so database passwords and existing service credentials stay intact.
if ! grep -q '^MQTT_BRIDGE_PASSWORD=[^[:space:]]' .env; then
  python3 scripts/ensure_env.py .env
fi

# Collect and validate the shared AM103 OTAA credential before starting
# services. It is stored only in the private, git-ignored .env file.
python3 scripts/provision_chirpstack.py --prepare .env

docker compose --env-file .env config --quiet
docker compose --env-file .env up -d --build
python3 scripts/provision_chirpstack.py .env

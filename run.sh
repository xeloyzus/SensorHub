#!/usr/bin/env bash
# Start (or update) the campus monitoring stack.
set -euo pipefail

cd "$(dirname "$0")"

reset_database=false
setup_args=()
for argument in "$@"; do
  if [ "$argument" = "--reset-database" ]; then
    reset_database=true
  else
    setup_args+=("$argument")
  fi
done

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

# Make the selected daemon explicit. Mixing `docker` and `sudo docker` can
# operate on different daemons (rootless vs. rootful), leaving an old database
# volume running even after a cleanup on the other daemon.
echo "Docker context: $(docker context show 2>/dev/null || echo default)"
docker_data_root="$(docker info --format '{{.DockerRootDir}}')"
echo "Docker data root: $docker_data_root"
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  sudo_data_root="$(sudo -n docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  if [ -n "$sudo_data_root" ] && [ "$sudo_data_root" != "$docker_data_root" ]; then
    sudo_stack="$(sudo -n docker ps -aq --filter label=com.docker.compose.project=sensorhub 2>/dev/null || true)"
    if [ -n "$sudo_stack" ]; then
      echo "A SensorHub stack exists on the separate sudo Docker daemon ($sudo_data_root)." >&2
      echo "This run uses $docker_data_root and would create or clean a different stack." >&2
      echo "Use one Docker daemon consistently; do not mix 'docker' and 'sudo docker'." >&2
      exit 1
    fi
  fi
fi

if [ ! -f .env ]; then
  python3 scripts/setup_env.py "${setup_args[@]}"
elif [ "${#setup_args[@]}" -gt 0 ]; then
  echo ".env already exists. Edit its DOMAIN directly; existing secrets are preserved." >&2
  exit 1
fi

# Add newly introduced runtime-only credentials when upgrading an older .env.
# The helper preserves existing settings and creates only missing secrets.
python3 scripts/ensure_env.py .env

# Collect and validate the shared AM103 OTAA credential before starting
# services. It is stored only in the private, git-ignored .env file.
python3 scripts/provision_chirpstack.py --prepare .env

docker compose --env-file .env config --quiet
# Stop application clients before changing their schema. ChirpStack is separate.
docker compose --env-file .env stop api ingest grafana
# Keep the private .env authoritative even when persistent database volumes
# were initialized with older passwords. This changes the DB role secrets but
# preserves both databases and their contents.
docker compose --env-file .env up -d timescaledb chirpstack-postgres
python3 scripts/sync_database_password.py .env

# Ensure ChirpStack's required extension exists before its schema migrations.
# PostgreSQL only runs /docker-entrypoint-initdb.d scripts on an empty volume;
# this idempotent check also repairs a previously initialized volume safely.
chirpstack_pg_id="$(docker compose --env-file .env ps -q chirpstack-postgres)"
if [ -z "$chirpstack_pg_id" ]; then
  echo "ChirpStack PostgreSQL container was not created." >&2
  exit 1
fi
for attempt in $(seq 1 120); do
  pg_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$chirpstack_pg_id" 2>/dev/null || true)"
  if [ "$pg_health" = healthy ]; then
    break
  fi
  if [ "$pg_health" = unhealthy ] || [ "$pg_health" = exited ] || [ "$pg_health" = dead ]; then
    echo "ChirpStack PostgreSQL is $pg_health; recent logs:" >&2
    docker compose --env-file .env logs --no-color --tail=80 chirpstack-postgres >&2 || true
    exit 1
  fi
  if [ "$attempt" -eq 120 ]; then
    echo "Timed out waiting for ChirpStack PostgreSQL to become healthy; recent logs:" >&2
    docker compose --env-file .env logs --no-color --tail=80 chirpstack-postgres >&2 || true
    exit 1
  fi
  sleep 1
done
docker compose --env-file .env exec -T chirpstack-postgres \
  psql -U chirpstack -d chirpstack -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS pg_trgm;'
echo "ChirpStack PostgreSQL is healthy and pg_trgm is installed."

docker compose --env-file .env build migrate
if [ "$reset_database" = true ]; then
  echo "Rebuilding the application database from its complete baseline; application readings and registry edits will be discarded."
  docker compose --env-file .env run --rm --no-deps migrate python -m app.db.migrate --reset
else
  docker compose --env-file .env run --rm --no-deps migrate
fi
docker compose --env-file .env up -d --build
python3 scripts/provision_chirpstack.py .env

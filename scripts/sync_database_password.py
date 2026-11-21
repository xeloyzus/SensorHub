"""Synchronize the existing TimescaleDB role password with the private .env."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import time


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def compose(env_path: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose", "--env-file", str(env_path), *args]
    return subprocess.run(command, cwd=Path(__file__).resolve().parents[1], text=True, **kwargs)


def synchronize(env_path: Path) -> None:
    env = read_env(env_path)
    username = env.get("POSTGRES_USER", "sensorhub")
    database = env.get("POSTGRES_DB", "sensorhub")
    password = env.get("POSTGRES_PASSWORD", "")
    if not username or not database or not password:
        raise RuntimeError("POSTGRES_USER, POSTGRES_DB, and POSTGRES_PASSWORD must be set in .env.")

    last_error = ""
    for _ in range(120):
        ready = compose(
            env_path,
            "exec", "-T", "timescaledb", "pg_isready", "-U", username, "-d", database,
            capture_output=True,
        )
        if ready.returncode == 0:
            break
        last_error = (ready.stderr or ready.stdout).strip()[-400:]
        time.sleep(1)
    else:
        raise RuntimeError(f"TimescaleDB did not become ready for local password synchronization: {last_error}")

    sql = f"ALTER ROLE {quote_identifier(username)} WITH PASSWORD {quote_literal(password)};\n"
    result = compose(
        env_path,
        "exec", "-T", "timescaledb", "psql", "-X", "-q", "-U", username,
        "-d", "postgres", "-v", "ON_ERROR_STOP=1",
        input=sql,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-500:]
        raise RuntimeError(f"Could not synchronize the TimescaleDB role password: {detail}")


if __name__ == "__main__":
    env_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    try:
        synchronize(env_file)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Database password setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print("TimescaleDB role password synchronized with .env; existing database data preserved.")

"""Build, test and clean up an isolated Compose project (Windows or Linux)."""

import os
from pathlib import Path
import subprocess
import uuid


def main():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    # Override inherited production variables with this committed synthetic
    # fixture. The generated project name gives this run its own volumes.
    for line in (root / "tests/integration.env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key] = value
    env["MQTT_PORT"] = "0"
    env["INTEGRATION_API_PORT"] = "0"
    env["POSTGRES_PORT"] = "0"
    project = "sensorhub-integration-" + uuid.uuid4().hex[:12]
    compose = [
        "docker", "compose", "--progress", "plain", "-p", project,
        "--env-file", "tests/integration.env",
        "-f", "docker-compose.yml", "-f", "tests/compose.integration.yml",
    ]

    def run(*args, check=True):
        return subprocess.run(compose + list(args), cwd=root, env=env, check=check)

    try:
        run("up", "-d", "--build", "--quiet-pull", "--wait", "--wait-timeout", "120", "mosquitto", "timescaledb", "ingest", "api")
        run("exec", "-T", "ingest", "python", "/tests/database_check.py")
        run("exec", "-T", "ingest", "python", "/tests/integration_check.py")
        run("restart", "mosquitto")
        # A broker restart recreates credentials on an existing volume and
        # must allow ingestion to reconnect before the second smoke check.
        run("up", "-d", "--wait", "--wait-timeout", "60", "mosquitto", "timescaledb", "ingest", "api")
        run("exec", "-T", "ingest", "python", "/tests/integration_check.py")
    except subprocess.CalledProcessError:
        run("logs", "--tail", "40", "migrate", "ingest", "api", check=False)
        raise
    finally:
        # This name was generated above for this run, never a user deployment.
        run("down", "--volumes", "--remove-orphans", "--rmi", "local", check=False)


if __name__ == "__main__":
    main()

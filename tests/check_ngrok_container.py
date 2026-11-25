"""Check the real ngrok entrypoint offline with a synthetic agent token.

Run explicitly after pulling ngrok/ngrok:3:
    python tests/check_ngrok_container.py

No tunnel is opened and no application services or volumes are changed.
"""

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    environment = {
        **os.environ,
        "COMPOSE_PROFILES": "ngrok",
        "NGROK_AUTHTOKEN": "synthetic-offline-test-token",
        "PUBLIC_BASE_URL": "https://offline-test.ngrok-free.app",
    }
    resolved = subprocess.check_output(
        ["docker", "compose", "-f", str(ROOT / "docker-compose.yml"),
         "--env-file", str(ROOT / "tests/integration.env"),
         "config", "--format", "json"],
        env=environment, text=True,
    )
    service = json.loads(resolved)["services"]["ngrok"]
    command = ["docker", "run", "--rm", "--pull=never", "--network", "none"]
    if service.get("read_only"):
        command.append("--read-only")
    for mount in service.get("tmpfs", []):
        command += ["--tmpfs", mount]
    for capability in service.get("cap_drop", []):
        command += ["--cap-drop", capability]
    for option in service.get("security_opt", []):
        command += ["--security-opt", option]
    command += ["--env", "NGROK_AUTHTOKEN=" + environment["NGROK_AUTHTOKEN"],
                service["image"], "config", "check",
                "--config=/var/lib/ngrok/ngrok.yml",
                "--config=/var/lib/ngrok/auth-config.yml"]
    # Config checking runs the image's real entrypoint, which must create the
    # auth file from the environment before ngrok can parse it. --network none
    # prevents even an accidental attempt to reach the public ngrok service.
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode or "Valid configuration file" not in result.stdout:
        raise RuntimeError("Offline ngrok bootstrap failed:\n" + result.stdout + result.stderr)
    print("PASS: official ngrok entrypoint creates and reads auth-config.yml from an environment token offline")


if __name__ == "__main__":
    main()

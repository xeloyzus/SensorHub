"""Add newly introduced runtime secrets without replacing existing credentials."""

import os
from pathlib import Path
import re
import secrets
import sys
import tempfile


RUNTIME_SECRETS = ("MQTT_BRIDGE_PASSWORD", "GRAFANA_DB_PASSWORD")


def ensure_runtime_secrets(target: Path) -> list[str]:
    text = target.read_text(encoding="utf-8")
    added = []
    for key in RUNTIME_SECRETS:
        match = re.search(rf"(?m)^{key}=(.*)$", text)
        if match and match.group(1).strip():
            continue
        line = f"{key}={secrets.token_hex(32)}"
        if match:
            text = text[:match.start()] + line + text[match.end():]
        else:
            text = text.rstrip("\r\n") + "\n" + line + "\n"
        added.append(key)

    if not added:
        return []

    descriptor, temporary_name = tempfile.mkstemp(prefix=".env.", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise
    return added


def ensure_bridge_password(target: Path) -> bool:
    """Backward-compatible name; ensure all required runtime secrets."""
    return "MQTT_BRIDGE_PASSWORD" in ensure_runtime_secrets(target)


if __name__ == "__main__":
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    added = ensure_runtime_secrets(env_path)
    if added:
        print(f"Added generated runtime secret(s) to .env: {', '.join(added)}.")

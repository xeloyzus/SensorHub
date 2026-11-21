"""Add newly introduced runtime secrets without replacing existing credentials."""

import os
from pathlib import Path
import re
import secrets
import sys
import tempfile


def ensure_bridge_password(target: Path) -> bool:
    text = target.read_text(encoding="utf-8")
    match = re.search(r"(?m)^MQTT_BRIDGE_PASSWORD=(.*)$", text)
    if match and match.group(1).strip():
        return False

    line = f"MQTT_BRIDGE_PASSWORD={secrets.token_hex(32)}"
    if match:
        text = text[:match.start()] + line + text[match.end():]
    else:
        text = text.rstrip("\r\n") + "\n" + line + "\n"

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
    return True


if __name__ == "__main__":
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env")
    if ensure_bridge_password(env_path):
        print("Added a unique MQTT bridge password to .env.")

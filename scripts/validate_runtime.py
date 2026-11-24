"""Check resolved Compose settings before the launcher changes running services."""

import json
import sys
from urllib.parse import urlsplit


def validate_runtime(config: dict) -> None:
    tunnel = config.get("services", {}).get("ngrok")
    if tunnel is None:
        return

    if not tunnel.get("environment", {}).get("NGROK_AUTHTOKEN", "").strip():
        raise ValueError("The ngrok profile requires NGROK_AUTHTOKEN in .env.")

    url = next((arg.removeprefix("--url=") for arg in tunnel["command"]
                if arg.startswith("--url=")), "")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.port in {None, 443}
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
            and not any(character.isspace() for character in url)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(
            "The ngrok profile requires PUBLIC_BASE_URL set to your assigned "
            "HTTPS origin, without a trailing slash, path, or query."
        )


def main() -> int:
    try:
        validate_runtime(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError):
        # Never echo the input, which contains resolved deployment credentials.
        # Known validation errors are safe, fixed messages.
        print("Invalid tunnel configuration. Set NGROK_AUTHTOKEN and an HTTPS "
              "PUBLIC_BASE_URL in .env when COMPOSE_PROFILES includes ngrok.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

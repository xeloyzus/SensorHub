"""Create first-run Compose configuration without overwriting existing secrets."""

import argparse
import ipaddress
import os
from pathlib import Path
import re
import secrets
import sys
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = (
    "POSTGRES_PASSWORD", "GRAFANA_ADMIN_PASSWORD",
    "MQTT_GATEWAY_PASSWORD", "MQTT_INGEST_PASSWORD",
    "MQTT_CHIRPSTACK_PASSWORD", "MQTT_FORWARDER_PASSWORD",
    "CHIRPSTACK_POSTGRES_PASSWORD", "CHIRPSTACK_API_SECRET",
)


def site_address(value: str) -> str:
    value = value.strip()
    if value == "http://":
        return value  # Caddy's HTTP catch-all; independent of the host's IP.
    if not value or any(character.isspace() for character in value):
        raise ValueError("Enter a hostname or http://SERVER_IP, without spaces.")
    explicit_scheme = "://" in value
    parsed = urlsplit(value if explicit_scheme else "https://" + value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a hostname for HTTPS, or http://SERVER_IP for local HTTP.")
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Enter only the server address, without credentials, paths, or query strings.")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("The server address has an invalid port.") from exc
    if port is not None:
        raise ValueError("Use the server address without a port; Compose publishes ports 80/443.")
    host = parsed.hostname
    try:
        ipaddress.ip_address(host)
        local_address = True
    except ValueError:
        local_address = host == "localhost"
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", host):
            raise ValueError("The hostname contains invalid characters.")
        if any(not label or label.startswith('-') or label.endswith('-') for label in host.split('.')):
            raise ValueError("The hostname has an invalid label.")
    if host in {"dashboard.example.com", "example.com"}:
        raise ValueError("Replace the example hostname with your server's hostname or IP.")
    authority = f"[{host}]" if ":" in host else host
    if parsed.scheme == "http" or (local_address and not explicit_scheme):
        return "http://" + authority
    return authority if not explicit_scheme else "https://" + authority


def create_env(
    address: str, target: Path, template: Path = ROOT / ".env.example", *, http_port: int = 80
) -> str:
    address = site_address(address)
    if not 1 <= http_port <= 65535:
        raise ValueError("The HTTP port must be between 1 and 65535.")
    source = template.read_text(encoding="utf-8-sig")
    defaults = dict(line.split("=", 1) for line in source.splitlines() if line and not line.startswith("#") and "=" in line)
    values = {key: secrets.token_hex(32) for key in SECRET_KEYS}
    values["DOMAIN"] = address
    values["HTTP_PORT"] = str(http_port)
    if address != "http://":
        origin = address if "://" in address else "https://" + address
        if origin.startswith("http://") and http_port != 80:
            origin += f":{http_port}"
        values["PUBLIC_BASE_URL"] = origin
    values["DATABASE_URL"] = (
        f"postgresql://{quote(defaults['POSTGRES_USER'], safe='')}:{values['POSTGRES_PASSWORD']}"
        f"@timescaledb:5432/{quote(defaults['POSTGRES_DB'], safe='')}"
    )
    for key, value in values.items():
        source, count = re.subn(rf"(?m)^{key}=.*$", f"{key}={value}", source)
        if count != 1:
            raise ValueError(f"The environment template must define {key} exactly once.")
    # Exclusive creation protects an existing database's password on reruns.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source)
    return address


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    address_options = parser.add_mutually_exclusive_group()
    address_options.add_argument("--domain", help="Your hostname, or http://SERVER_IP for local HTTP")
    address_options.add_argument("--local", action="store_true", help="Local HTTP on port 8080, without a fixed IP or hostname")
    parser.add_argument("--output", type=Path, default=ROOT / ".env", help="New environment file (default: project .env)")
    args = parser.parse_args(argv)
    if args.output.exists():
        print(f"{args.output} already exists and was left unchanged. Edit missing values in that file; keep the existing database password.", file=sys.stderr)
        return 1
    address = "http://" if args.local else args.domain
    http_port = 8080 if args.local else 80
    if address is None:
        if not sys.stdin.isatty():
            parser.error("Provide --domain YOUR_HOSTNAME or --domain http://SERVER_IP.")
        address = input("Dashboard hostname for HTTPS, or http://SERVER_IP for local HTTP: ")
    try:
        address = create_env(address, args.output, http_port=http_port)
    except (ValueError, OSError) as exc:
        print(f"Configuration was not created: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.output} with generated credentials and API secrets. Keep this file private.")
    display_url = f"http://localhost:{http_port}" if address == "http://" else address if '://' in address else 'https://' + address
    print(f"Dashboard address: {display_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

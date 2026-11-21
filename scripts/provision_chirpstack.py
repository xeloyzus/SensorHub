"""Idempotently provision the NanitesLab ChirpStack v4 resources."""

from __future__ import annotations

import getpass
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TENANT_NAME = "NanitesLab"
APPLICATION_NAME = "AM103 Sensors"
PROFILE_NAME = "Milesight AM103 EU868"
DEFAULT_JOIN_EUI = "24e124c0002a0001"
GATEWAYS = (
    ("24e124fffef3e837", "ARH_Gateway"),
    ("24e124fffef3e679", "KEH_Gateway"),
    ("24e124fffef3f713", "UiS_Gateway"),
)
DEVICES = (
    ("24e124725f514441", "AM103-KEH-A101", "kjolv-egelands-hus", "A101"),
    ("24e124725f519422", "AM103-KEH-E101", "kjolv-egelands-hus", "E101"),
    ("24e124725f514020", "AM103-KEH-C106", "kjolv-egelands-hus", "C106"),
    ("24e124725f517900", "AM103-SiS-Styrkesal", "sis", "Styrkesal"),
    ("24e124725f517844", "AM103-SiS-Functional Fitness", "sis", "Functional Fitness"),
    ("24e124725f512512", "AM103-KEH-Biblioteket", "kjolv-egelands-hus", "Biblioteket"),
    ("24e124725f517383", "AM103-ARH-Q120", "arne-rettedals-hus", "Q120"),
    ("24e124725f518499", "AM103-ARH-G001", "arne-rettedals-hus", "G001"),
    ("24e124725f512668", "AM103-EOJ-101", "eoj", "101"),
    ("24e124725f518129", "AM103-EOJ-110", "eoj", "110"),
    ("24e124725f516684", "AM103-KEH-C101", "kjolv-egelands-hus", "C101"),
    ("24e124725f515337", "AM103-KEH-Utenfor", "kjolv-egelands-hus", "Utenfor"),
)


def read_env(path: Path) -> tuple[str, dict[str, str]]:
    raw = path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in raw.splitlines():
        if line and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return raw, values


def write_env(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".env.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def set_env_value(path: Path, key: str, value: str) -> None:
    text, _ = read_env(path)
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    replacement = f"{key}={value}"
    if pattern.search(text):
        text = pattern.sub(lambda _: replacement, text, count=1)
    else:
        text = text.rstrip("\r\n") + "\n" + replacement + "\n"
    write_env(path, text)


def ensure_app_key(env_path: Path) -> str:
    _, env = read_env(env_path)
    app_key = os.environ.get("CHIRPSTACK_AM103_APP_KEY", env.get("CHIRPSTACK_AM103_APP_KEY", "")).strip()
    if not app_key:
        if not sys.stdin.isatty():
            raise RuntimeError("Set CHIRPSTACK_AM103_APP_KEY in .env (32 hex characters) before running non-interactively.")
        while True:
            app_key = getpass.getpass("Shared AM103 AppKey (32 hex characters; applied to all 12 sensors): ").strip()
            if re.fullmatch(r"[0-9a-fA-F]{32}", app_key):
                break
            print("The AppKey must be exactly 32 hexadecimal characters.", file=sys.stderr)
        set_env_value(env_path, "CHIRPSTACK_AM103_APP_KEY", app_key.upper())
    if not re.fullmatch(r"[0-9a-fA-F]{32}", app_key):
        raise RuntimeError("CHIRPSTACK_AM103_APP_KEY must be exactly 32 hexadecimal characters.")
    app_key = app_key.upper()
    set_env_value(env_path, "CHIRPSTACK_AM103_APP_KEY", app_key)
    return app_key


def ensure_join_eui(env_path: Path) -> str:
    _, env = read_env(env_path)
    join_eui = os.environ.get("CHIRPSTACK_AM103_JOIN_EUI", env.get("CHIRPSTACK_AM103_JOIN_EUI", DEFAULT_JOIN_EUI)).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{16}", join_eui):
        raise RuntimeError("CHIRPSTACK_AM103_JOIN_EUI must be exactly 16 hexadecimal characters.")
    join_eui = join_eui.lower()
    set_env_value(env_path, "CHIRPSTACK_AM103_JOIN_EUI", join_eui.upper())
    return join_eui


def create_api_token(env_path: Path) -> str:
    _, env = read_env(env_path)
    token = env.get("CHIRPSTACK_BOOTSTRAP_API_TOKEN", "")
    if token:
        return token
    command = [
        "docker", "compose", "--env-file", str(env_path), "exec", "-T", "chirpstack",
        "chirpstack", "--config", "/etc/chirpstack", "create-api-key", "--name", "naniteslab-bootstrap",
    ]
    last_error = ""
    for _ in range(30):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        output = result.stdout + "\n" + result.stderr
        match = re.search(r"(?m)^token:\s*(\S+)\s*$", output)
        if result.returncode == 0 and match:
            token = match.group(1)
            set_env_value(env_path, "CHIRPSTACK_BOOTSTRAP_API_TOKEN", token)
            return token
        last_error = output[-500:]
        time.sleep(2)
    raise RuntimeError("Could not create the ChirpStack bootstrap API key after 60 seconds: " + last_error)


class ChirpStackHTTPError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, detail: str):
        super().__init__(f"ChirpStack API {method} {path} returned HTTP {status}: {detail}")
        self.status = status


class ChirpStackAPI:
    def __init__(self, port: str, token: str):
        self.base = f"http://127.0.0.1:{port}/api"
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None, *, allow_missing: bool = False) -> dict:
        data = None if body is None else json.dumps(body).encode()
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except HTTPError as exc:
            if allow_missing and exc.code == 404:
                return {}
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ChirpStackHTTPError(method, path, exc.code, detail) from exc
        except (URLError, TimeoutError) as exc:
            raise RuntimeError(f"ChirpStack REST API is not ready at {self.base}: {exc}") from exc

    def wait_ready(self) -> None:
        last_error = None
        for _ in range(60):
            try:
                self.request("GET", "/tenants?limit=1")
                return
            except ChirpStackHTTPError as exc:
                # Authentication errors cannot become healthy by waiting.
                if exc.status in {401, 403}:
                    raise
                last_error = exc
                time.sleep(2)
            except RuntimeError as exc:
                last_error = exc
                time.sleep(2)
        raise RuntimeError(f"ChirpStack REST API did not become ready: {last_error}")


def find_by_name(api: ChirpStackAPI, path: str, query: dict[str, str], name: str) -> dict | None:
    response = api.request("GET", path + "?" + urlencode({"limit": "100", "search": name, **query}))
    return next((item for item in response.get("result", []) if item.get("name") == name), None)


def provision(api: ChirpStackAPI, app_key: str, join_eui: str) -> None:
    tenant = find_by_name(api, "/tenants", {}, TENANT_NAME)
    if tenant is None:
        created = api.request("POST", "/tenants", {"tenant": {
            "name": TENANT_NAME,
            "description": "NanitesLab AM103 deployment",
            "canHaveGateways": True,
        }})
        tenant_id = created.get("id") or created.get("tenantId")
    else:
        tenant_id = tenant["id"]
    if not tenant_id:
        raise RuntimeError("ChirpStack did not return a tenant ID.")
    tenant_details = api.request("GET", f"/tenants/{tenant_id}").get("tenant", {})
    if not tenant_details.get("canHaveGateways", False):
        tenant_details["canHaveGateways"] = True
        tenant_details.pop("id", None)  # the tenant ID is carried in the URL
        api.request("PUT", f"/tenants/{tenant_id}", {"tenant": tenant_details})

    profile = find_by_name(api, "/device-profiles", {"tenantId": tenant_id}, PROFILE_NAME)
    profile_data = {
        "tenantId": tenant_id,
        "name": PROFILE_NAME,
        "description": "Milesight AM103; EU868; LoRaWAN 1.0.3; Regional Parameters revision B; OTAA.",
        "region": "EU868",
        "regionConfigId": "eu868",
        "macVersion": "LORAWAN_1_0_3",
        "regParamsRevision": "B",
        "supportsOtaa": True,
        "supportsClassB": False,
        "supportsClassC": False,
        "payloadCodecRuntime": "JS",
        "payloadCodecScript": (ROOT / "chirpstack" / "codec" / "am103.js").read_text(encoding="utf-8"),
        "autoDetectMeasurements": True,
    }
    if profile is None:
        created = api.request("POST", "/device-profiles", {"deviceProfile": profile_data})
        profile_id = created.get("id")
    else:
        profile_id = profile["id"]
        # ChirpStack takes the profile ID from the path for updates.
        api.request("PUT", f"/device-profiles/{profile_id}", {"deviceProfile": profile_data})
    if not profile_id:
        raise RuntimeError("ChirpStack did not return a device profile ID.")

    application = find_by_name(api, "/applications", {"tenantId": tenant_id}, APPLICATION_NAME)
    if application is None:
        created = api.request("POST", "/applications", {"application": {"tenantId": tenant_id, "name": APPLICATION_NAME, "description": "Milesight AM103 sensors for NanitesLab"}})
        application_id = created.get("id")
    else:
        application_id = application["id"]
    if not application_id:
        raise RuntimeError("ChirpStack did not return an application ID.")

    for gateway_id, name in GATEWAYS:
        existing_gateway = api.request("GET", f"/gateways/{gateway_id}", allow_missing=True)
        existing_gateway_data = existing_gateway.get("gateway", {})
        # ChirpStack validates this field as strictly positive. Preserve an
        # existing positive priority; older/default records may report zero.
        downlink_priority = max(1, int(existing_gateway_data.get("downlinkPriority") or 1))
        gateway = {
            "gatewayId": gateway_id,
            "tenantId": tenant_id,
            "name": name,
            "description": name,
            "downlinkPriority": downlink_priority,
        }
        if existing_gateway_data:
            # The gateway ID is supplied by the URL path on updates.
            update = {key: value for key, value in gateway.items() if key != "gatewayId"}
            api.request("PUT", f"/gateways/{gateway_id}", {"gateway": update})
        else:
            api.request("POST", "/gateways", {"gateway": gateway})

    for dev_eui, name, building, room in DEVICES:
        device_fields = {
            "joinEui": join_eui,
            "name": name,
            "applicationId": application_id,
            "deviceProfileId": profile_id,
            "isDisabled": False,
            "skipFcntCheck": False,
            "tags": {"building": building, "room": room, "model": "AM103"},
        }
        existing = api.request("GET", f"/devices/{dev_eui}", allow_missing=True)
        if existing.get("device"):
            # The DevEUI is supplied by the URL path on updates.
            api.request("PUT", f"/devices/{dev_eui}", {"device": device_fields})
        else:
            api.request("POST", "/devices", {"device": {"devEui": dev_eui, **device_fields}})
        key_path = f"/devices/{dev_eui}/keys"
        # ChirpStack's REST schema carries the DevEUI in the URL for key
        # create/update; the request body only accepts the key fields.
        keys = {"deviceKeys": {"nwkKey": app_key}}
        current_keys = api.request("GET", key_path, allow_missing=True)
        if current_keys:
            api.request("PUT", key_path, keys)
        else:
            api.request("POST", key_path, keys)

    print(f"ChirpStack provisioned: 1 tenant, 1 AM103 profile (EU868 / LoRaWAN 1.0.3 / revision B), 1 application, {len(GATEWAYS)} gateways, {len(DEVICES)} OTAA devices using the same AppKey.")


def main() -> int:
    prepare_only = "--prepare" in sys.argv[1:]
    args = [arg for arg in sys.argv[1:] if arg != "--prepare"]
    env_path = Path(args[0]) if args else ROOT / ".env"
    try:
        app_key = ensure_app_key(env_path)
        join_eui = ensure_join_eui(env_path)
        if prepare_only:
            return 0
        token = create_api_token(env_path)
        _, env = read_env(env_path)
        api = ChirpStackAPI(env.get("CHIRPSTACK_REST_API_PORT", "18090"), token)
        try:
            api.wait_ready()
        except ChirpStackHTTPError as exc:
            if exc.status not in {401, 403}:
                raise
            # A token copied from an older ChirpStack database may no longer
            # exist. Create a fresh global key and retry once automatically.
            print("The saved ChirpStack API token was rejected; generating a fresh bootstrap token.", file=sys.stderr)
            set_env_value(env_path, "CHIRPSTACK_BOOTSTRAP_API_TOKEN", "")
            token = create_api_token(env_path)
            api = ChirpStackAPI(env.get("CHIRPSTACK_REST_API_PORT", "18090"), token)
            api.wait_ready()
        provision(api, app_key, join_eui)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"ChirpStack setup failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

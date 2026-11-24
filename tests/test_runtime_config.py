"""Tunnel settings fail before startup without disclosing credentials."""

import json
from io import StringIO

import pytest

from scripts.validate_runtime import main, validate_runtime


def config(url="https://campus.ngrok-free.app", token="private-agent-token"):
    return {"services": {"ngrok": {
        "environment": {"NGROK_AUTHTOKEN": token},
        "command": ["http", "http://api:8000", f"--url={url}"],
    }}}


def test_ordinary_stack_requires_no_tunnel_credentials():
    validate_runtime({"services": {"api": {}}})


def test_valid_tunnel_configuration():
    validate_runtime(config())


@pytest.mark.parametrize("url", [
    "", "http://campus.ngrok-free.app", "https://host/path", "https://host/",
    "https://host?query=1", "https://host#fragment", "https://user:secret@host",
    "https://host:8080", "https://host:invalid", "https://bad host",
])
def test_invalid_endpoint_is_rejected(url):
    with pytest.raises(ValueError):
        validate_runtime(config(url=url))


def test_missing_token_is_rejected():
    with pytest.raises(ValueError, match="NGROK_AUTHTOKEN"):
        validate_runtime(config(token=""))


def test_validation_does_not_disclose_credentials(monkeypatch, capsys):
    value = config(url="https://user:secret-value@host")
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(value)))
    assert main() == 1
    output = capsys.readouterr()
    assert "PUBLIC_BASE_URL" in output.err
    assert "private-agent-token" not in output.err + output.out
    assert "secret-value" not in output.err + output.out

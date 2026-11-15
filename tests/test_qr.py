"""Decode the exact QR response with an independent barcode reader."""

from io import BytesIO

from fastapi.testclient import TestClient
from PIL import Image
import pytest
import zxingcpp

from app.core.config import settings, Settings
from app.main import app


@pytest.mark.parametrize("origin", ["https://dashboard.uis.no", "http://192.0.2.10:8080"])
def test_qr_decodes_to_the_same_url_as_runtime_info(monkeypatch, origin):
    monkeypatch.setattr(settings, "public_base_url", origin)
    client = TestClient(app)
    response = client.get("/qr/dashboard.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(response.content)))
    assert decoded is not None
    assert decoded.text == client.get("/api/system/status").json()["dashboard_url"] == origin + "/overview"
    assert 'href="' + origin + '/overview"' in client.get("/").text


def test_qr_uses_request_origin_when_canonical_origin_is_unset(monkeypatch):
    monkeypatch.setattr(settings, "public_base_url", "")
    client = TestClient(app, base_url="https://campus.uis.no")
    image = Image.open(BytesIO(client.get("/qr/dashboard.png").content))
    assert zxingcpp.read_barcode(image).text == "https://campus.uis.no/overview"


@pytest.mark.parametrize("value", ["javascript:alert(1)", "https://user:pass@campus.uis.no", "https://campus.uis.no/path", "https://campus.uis.no/?x=1", "https://campus.uis.no/#x", "https://campus.uis.no:bad"])
def test_qr_origin_rejects_non_origins(value):
    with pytest.raises(ValueError):
        Settings(_env_file=None, public_base_url=value)


def test_runtime_has_no_generated_data_mode():
    assert "demo_mode" not in Settings.model_fields
    from pathlib import Path
    assert not (Path(__file__).resolve().parents[1] / "app/demo.py").exists()


@pytest.mark.parametrize("seconds", [0, 9, 3601])
def test_refresh_interval_has_safe_bounds(seconds):
    with pytest.raises(ValueError):
        Settings(_env_file=None, display_refresh_seconds=seconds)

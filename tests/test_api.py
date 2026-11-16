"""Smoke tests for the API wiring (no database connection required)."""

from app.main import app


def test_openapi_paths():
    paths = sorted(app.openapi()["paths"])
    assert paths == sorted(
        [
            "/api/buildings",
            "/api/buildings/{building_id}/current",
            "/api/buildings/{building_id}/history",
            "/api/buildings/{building_id}/insights",
            "/api/buildings/{building_id}/recommendations",
            "/api/buildings/{building_id}/summary",
            "/api/campus/summary",
            "/api/methodology",
            "/api/system/status",
            "/api/sensor-models",
            "/health",
        ]
    )


def test_app_title():
    assert app.title == "Campus dashboard API"


def test_frontend_wiring():
    from app.routers import pages

    # Display, web overview, and mobile HTML pages are registered on the pages router.
    assert {r.path for r in pages.router.routes} == {"/", "/display", "/mobile", "/overview"}

    # Static assets are mounted at /static.
    assert any(getattr(r, "path", None) == "/static" for r in app.routes)

    # HTML pages are excluded from the JSON API schema.
    api_paths = app.openapi()["paths"]
    assert "/" not in api_paths
    assert "/display" not in api_paths
    assert "/mobile" not in api_paths
    assert "/overview" not in api_paths


def test_runtime_status_contract(monkeypatch):
    import asyncio

    from app.core.config import settings
    from app.routers import system

    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@db:5432/sensorhub")
    monkeypatch.setattr(settings, "display_refresh_seconds", 45)

    from starlette.requests import Request
    request = Request({"type": "http", "scheme": "https", "server": ("dashboard.uis.no", 443), "headers": [], "path": "/api/system/status", "root_path": ""})
    status = asyncio.run(system.status(request))

    assert status.app == "Campus dashboard"
    assert status.dashboard_url == "https://dashboard.uis.no/overview"
    assert status.mode == "live"
    assert status.data_source == "timescaledb"
    assert status.database_configured is True
    assert status.gateway_ingest_expected is True
    assert status.display_refresh_seconds == 45

"""Shared test configuration.

Set ``DATABASE_URL`` before any test imports the app so ``Settings`` can load
without a real database (tests only inspect the app; they never connect).
"""

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql://user:pass@localhost:5432/sensorhub"
)


@pytest.fixture
def telemetry_services(monkeypatch):
    """Inject fixture responses into analytics without a runtime data switch."""
    from tests import telemetry_fixture
    from app.services import buildings_service, history_service

    async def list_buildings(db):
        return telemetry_fixture.list_buildings()

    async def get_current(db, building_id):
        return telemetry_fixture.get_current(building_id)

    async def get_history(db, building_id, range_):
        return telemetry_fixture.get_history(building_id, range_)

    monkeypatch.setattr(buildings_service, "list_buildings", list_buildings)
    monkeypatch.setattr(buildings_service, "get_current", get_current)
    monkeypatch.setattr(history_service, "get_history", get_history)

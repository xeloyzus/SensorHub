"""The hardware plan, preview fleet and sensor inventory endpoint agree."""

import asyncio
from collections import Counter
import csv
from pathlib import Path

from tests import telemetry_fixture
from app.core.sensors import SENSOR_MODELS
from unittest.mock import AsyncMock
from app.services.sensors_service import list_sensor_models


def test_inventory_quantities_match_supplied_csv():
    cursor = AsyncMock()
    cursor.__aenter__.return_value = cursor
    cursor.fetchall.return_value = [(m['type'], m['name'], m['planned_quantity'], m['metrics'], 0) for m in SENSOR_MODELS]

    class DB:
        def cursor(self):
            return cursor

    models = asyncio.run(list_sensor_models(DB()))
    with (Path(__file__).resolve().parents[1] / "hardware/hardware.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for model in models:
        source = next(row for row in rows if row["Item / Equipment"].startswith(model.name))
        assert model.planned_quantity == int(source["Qty"])
    assert {model.type for model in models} == {"am103", "am107", "ct305"}


def test_fixture_uses_current_buildings_and_all_active_sensor_models():
    buildings = telemetry_fixture.list_buildings()
    assert {building.slug for building in buildings} == {"kjolv-egelands-hus", "eoj", "arne-rettedals-hus", "sis"}
    counts = Counter(sensor.type for building in buildings for sensor in telemetry_fixture.get_current(building.id).sensors)
    assert counts == {"am103": 10, "am107": 4, "ct305": 3}
    assert counts == telemetry_fixture.registered_sensor_counts()
    for building in buildings:
        history = telemetry_fixture.get_history(building.id, "24h")
        assert any(series.type == "am107" and series.metric == "activity" for series in history.series)

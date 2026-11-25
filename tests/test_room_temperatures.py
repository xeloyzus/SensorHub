"""Room means must not be distorted by sensor density, missing values or rounding."""

from datetime import timedelta

import pytest

from app.schemas.analytics import MetricStatistics
from app.services import analytics_service as analytics
from tests.test_reading_quality import NOW, sensor, summary


def temperature(device_id, room, value):
    item = sensor(device_id=device_id)
    item.room = room
    if value is None:
        item.readings.pop("temperature")
        item.metric_updated.pop("temperature")
    else:
        item.readings["temperature"] = value
    return item


def test_each_room_has_equal_weight_even_with_multiple_sensors(monkeypatch):
    sensors = [
        temperature(1, "Room A", 20), temperature(2, " room   a ", 24),
        temperature(3, "Room B", 30), temperature(4, "Room C", None),
        temperature(5, None, 99), sensor(device_id=6, type_="ct305"),
    ]
    result = summary(monkeypatch, sensors, [])
    assert result.temperature.current == 26  # ((20+24)/2 + 30)/2
    assert result.temperature.aggregation == "room_mean"
    assert result.temperature.aggregation_count == 2
    assert result.temperature.aggregation_sum == 52
    assert result.temperature.source_count == 3
    rooms = {room.room: room for room in result.room_temperatures}
    assert rooms["Room A"].current == 22
    assert rooms["Room A"].device_ids == [1, 2]
    assert rooms["Room A"].source_count == 2
    assert rooms["Room C"].current is None
    assert rooms[None].current == 99
    assert len(rooms) == 4  # CT305 panel temperature is not a room measurement.


def test_zero_is_included_and_missing_temperature_is_not_zero(monkeypatch):
    result = summary(monkeypatch, [temperature(1, "A", 0), temperature(2, "B", 20), temperature(3, "C", None)], [])
    assert result.temperature.current == 10
    assert result.temperature.aggregation_count == 2


def test_no_room_average_is_invented_for_unassigned_sensors(monkeypatch):
    result = summary(monkeypatch, [temperature(1, None, 20)], [])
    assert result.temperature.current is None
    assert result.temperature.aggregation_count == 0
    assert result.room_temperatures[0].current == 20
    assert "Room unassigned" in result.room_temperatures[0].label


def test_future_temperature_is_not_used(monkeypatch):
    item = temperature(1, "A", 30)
    item.metric_updated["temperature"] = NOW + timedelta(minutes=1)
    result = summary(monkeypatch, [item], [])
    assert result.temperature.current is None
    assert result.room_temperatures[0].current is None


def test_campus_uses_room_counts_and_unrounded_sums():
    common = dict(label="Temperature", unit="°C", sample_count=0, coverage_24h=0, aggregation="room_mean")
    values = [
        MetricStatistics(**common, current=22, source_count=10, aggregation_count=2, aggregation_sum=44.08),
        MetricStatistics(**common, current=23, source_count=1, aggregation_count=1, aggregation_sum=23.04),
    ]
    result = analytics._combine_metric("Temperature", "°C", values)
    assert result.current == 22.4
    assert result.aggregation_sum == pytest.approx(67.12)
    assert result.aggregation_count == 3


def test_room_average_keeps_original_measurement_precision(monkeypatch):
    result = summary(monkeypatch, [temperature(1, "A", 20.04), temperature(2, "A", 20.08)], [])
    assert result.room_temperatures[0].current == pytest.approx(20.06)
    assert result.temperature.aggregation_sum == pytest.approx(20.06)

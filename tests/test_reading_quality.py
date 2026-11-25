"""Regression tests for partial outages, time-based trends and CO2 evidence."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.schemas import Building, CurrentResponse, HistoryPoint, HistoryResponse, Sensor, Series
from app.schemas.analytics import MetricStatistics
from app.services import analytics_service as analytics, buildings_service, history_service
from app.core.config import settings

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
BUILDING = Building(id=1, name="Test", slug="test")


def sensor(device_id=1, co2=1100, age=0, type_="am103"):
    timestamp = NOW - timedelta(minutes=age)
    readings = {"co2": co2, "temperature": 21, "humidity": 40} if type_ in {"am103", "am107"} else {"temperature": 80, "current_1": 0, "current_2": 0, "current_3": 0}
    return Sensor(device_id=device_id, label="Test", type=type_, room=f"Room {device_id}", readings=readings, updated=timestamp, metric_updated={metric: timestamp for metric in readings})


def series(values, ages, device_id=1, metric="co2", type_="am103"):
    return Series(device_id=device_id, label="Test", type=type_, metric=metric, points=[HistoryPoint(time=NOW-timedelta(minutes=age), value=value) for value, age in zip(values, ages)])


def summary(monkeypatch, sensors, history):
    monkeypatch.setattr(analytics, "_now", lambda: NOW)
    monkeypatch.setattr(buildings_service, "get_current", AsyncMock(return_value=CurrentResponse(building=BUILDING, updated=NOW, sensors=sensors)))
    monkeypatch.setattr(history_service, "get_history", AsyncMock(return_value=HistoryResponse(building=BUILDING, range="24h", series=history)))
    return asyncio.run(analytics.get_building_summary(None, 1))


def test_latest_values_include_every_sensor_with_measurements(monkeypatch):
    reporting = sensor(co2=600)
    earlier = sensor(device_id=2, co2=2400, age=120)
    missing = Sensor(device_id=3, label="Never reported", type="am103", readings={})
    panel = sensor(device_id=4, type_="ct305")
    result = summary(monkeypatch, [reporting, earlier, missing, panel], [])
    assert result.co2.current == 1500
    assert result.temperature.current == 21
    assert result.co2.source_count == 2
    assert result.data_quality.registered_sensors == 4
    assert result.data_quality.sensors_with_readings == 3
    assert result.data_quality.missing_sensors == 1
    assert result.data_quality.latest_reading == NOW
    assert result.recommendations == []


def test_metrics_are_available_independently_of_their_timestamp(monkeypatch):
    partial = sensor()
    partial.metric_updated["co2"] = NOW - timedelta(hours=2)
    result = summary(monkeypatch, [partial], [])
    assert result.co2.current == 1100
    assert result.co2.source_count == 1
    assert result.temperature.current == 21
    assert result.data_quality.sensors_with_readings == 1


@pytest.mark.parametrize("minutes", [0, 20, 45, 120, 1884])
def test_measurement_age_does_not_hide_latest_values(monkeypatch, minutes):
    result = summary(monkeypatch, [sensor(age=minutes)], [])
    assert result.co2.current == 1100
    assert result.data_quality.sensors_with_readings == 1
    assert result.data_quality.missing_sensors == 0
    assert result.data_quality.latest_reading == NOW - timedelta(minutes=minutes)
    assert set(result.data_quality.model_dump()) == {
        "registered_sensors", "sensors_with_readings", "missing_sensors",
        "coverage_24h", "latest_reading",
    }


def test_storage_time_does_not_replace_measurement_time(monkeypatch):
    old = sensor(age=1880)
    old.metric_received_at = {metric: NOW for metric in old.readings}
    result = summary(monkeypatch, [old], [])
    assert result.data_quality.latest_reading == NOW - timedelta(minutes=1880)
    assert result.co2.current == 1100


def test_coverage_includes_registered_silent_air_sensors(monkeypatch):
    history = series([600] * 96, list(reversed(range(0, 1440, 15))))
    missing = Sensor(device_id=2, label="Silent", type="am103", readings={})
    result = summary(monkeypatch, [sensor(co2=600), missing], [history])
    assert result.co2.coverage_24h == 0.5
    assert result.co2.registered_source_count == 2


@pytest.mark.parametrize("ages, expected", [([60, 45, 30, 15, 0], 400), ([720, 540, 360, 180, 0], None), ([60, 30, 15, 0], None), ([150, 135, 120, 105, 90], None)])
def test_hour_change_checks_timestamps_gaps_and_recency(ages, expected):
    history = series([600 + i * 100 for i in range(len(ages))], ages)
    assert analytics._change_over_last_hour([history], 1000, NOW) == expected


@pytest.mark.parametrize("values, ages, should_recommend", [
    ([1100]*4, [45, 30, 15, 0], True),
    ([600, 700, 800, 1100], [45, 30, 15, 0], False),
    ([1100]*4, [80, 60, 40, 0], False),
    ([1100]*4, [30, 20, 10, 0], False),
    ([1100]*4, [150, 135, 120, 105], False),
])
def test_recommendation_requires_recent_sustained_evidence(monkeypatch, values, ages, should_recommend):
    result = summary(monkeypatch, [sensor()], [series(values, ages)])
    assert bool(result.recommendations) is should_recommend
    if should_recommend:
        evidence = result.recommendations[0].evidence
        assert evidence["sustained_minutes"] == 45
        assert evidence["device_ids"] == [1]
        assert result.recommendations[0].methodology_id == "co2-v2"


def test_evidence_is_not_combined_between_sensors(monkeypatch):
    result = summary(monkeypatch, [sensor(), sensor(device_id=2)], [series([1100]*2, [45, 30]), series([1100]*2, [15, 0], device_id=2)])
    assert result.recommendations == []


def test_panel_history_is_excluded_from_indoor_temperature(monkeypatch):
    result = summary(monkeypatch, [sensor(), sensor(device_id=2, type_="ct305")], [series([21], [0], metric="temperature"), series([80], [0], device_id=2, metric="temperature", type_="ct305")])
    assert result.temperature.mean_24h == 21


def test_campus_current_average_is_weighted_by_reporting_sensors():
    metrics = [MetricStatistics(label="CO2", unit="ppm", current=600, source_count=3, sample_count=30, mean_24h=600, registered_source_count=3, coverage_24h=1), MetricStatistics(label="CO2", unit="ppm", current=1200, source_count=1, sample_count=10, mean_24h=1200, registered_source_count=1, coverage_24h=0)]
    result = analytics._combine_metric("CO2", "ppm", metrics)
    assert result.current == 750
    assert result.mean_24h == 750
    assert result.coverage_24h == 0.75


def test_zero_current_and_earlier_current_are_measurements():
    assert analytics._energy_summary([sensor(type_="ct305")], NOW).current_kw == 0
    assert analytics._energy_summary([sensor(type_="ct305", age=120)], NOW).current_kw == 0


def test_future_timestamps_do_not_enter_latest_aggregates(monkeypatch):
    result = summary(monkeypatch, [sensor(age=-1)], [])
    assert result.co2.current is None
    assert result.data_quality.sensors_with_readings == 0
    assert result.data_quality.latest_reading is None


def test_empty_campus_quality_has_no_measurements():
    result = analytics._combine_quality([])
    assert result.sensors_with_readings == result.registered_sensors == 0
    assert result.latest_reading is None


def test_campus_quality_combines_counts_and_latest_timestamp():
    from app.schemas.analytics import DataQuality
    result = analytics._combine_quality([
        DataQuality(sensors_with_readings=1, registered_sensors=2, missing_sensors=1,
                    coverage_24h=0.5, latest_reading=NOW-timedelta(hours=2)),
        DataQuality(sensors_with_readings=3, registered_sensors=3, missing_sensors=0,
                    coverage_24h=1, latest_reading=NOW),
    ])
    assert result.sensors_with_readings == 4
    assert result.registered_sensors == 5
    assert result.missing_sensors == 1
    assert result.latest_reading == NOW
    assert result.coverage_24h == 0.8


def test_current_query_keeps_silent_devices_and_metric_timestamps(monkeypatch):
    cursor = AsyncMock()
    cursor.fetchone.return_value = (1, "Test", "test")
    cursor.fetchall.return_value = [(1, "Room", "am103", "co2", 700, NOW, NOW, "A101"), (1, "Room", "am103", "temperature", 21, NOW-timedelta(hours=2), NOW, "A101"), (2, "Silent", "am103", None, None, None, None, "A102")]

    class DB:
        def cursor(self):
            return cursor

    cursor.__aenter__.return_value = cursor
    result = asyncio.run(buildings_service.get_current(DB(), 1))
    assert len(result.sensors) == 2
    assert result.sensors[0].metric_updated["temperature"] == NOW-timedelta(hours=2)
    assert result.sensors[0].metric_received_at["temperature"] == NOW
    assert result.sensors[1].updated is None
    assert result.sensors[1].readings == {}
    assert "LEFT JOIN LATERAL" in cursor.execute.call_args_list[1].args[0]


def test_am107_contributes_to_climate_coverage_and_sustained_evidence(monkeypatch):
    result = summary(monkeypatch, [sensor(co2=900), sensor(device_id=2, type_="am107")], [
        series([900] * 4, [45, 30, 15, 0]),
        series([1100] * 4, [45, 30, 15, 0], device_id=2, type_="am107"),
    ])
    assert result.co2.current == 1000
    assert result.co2.registered_source_count == 2
    assert result.co2.sample_count == 8
    assert result.co2.mean_24h == 1000
    assert result.data_quality.sensors_with_readings == 2
    assert result.recommendations[0].evidence["device_ids"] == [2]


def test_am107_activity_keeps_climate_timestamps_independent(monkeypatch):
    air = sensor(type_="am107", age=120)
    air.readings.update(activity=10, illumination=350)
    air.metric_updated.update(activity=NOW, illumination=NOW)
    result = summary(monkeypatch, [air], [])
    assert result.data_quality.sensors_with_readings == 1
    assert result.co2.current == 1100
    assert result.temperature.current == 21
    assert air.metric_updated["co2"] == NOW-timedelta(minutes=120)
    assert result.recommendations == []

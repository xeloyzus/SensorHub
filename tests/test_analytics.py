"""Tests for the first deterministic analytics slice."""

import asyncio

from app.services import analytics_service


def test_building_summary_has_evidence(telemetry_services):

    summary = asyncio.run(analytics_service.get_building_summary(None, 4))

    assert summary is not None
    assert summary.building.name == "EOJ"
    assert summary.co2.current is not None
    assert summary.co2.sample_count > 0
    assert summary.data_quality.sensors_with_readings > 0
    assert summary.insights


def test_campus_summary_and_methodology(telemetry_services):

    campus = asyncio.run(analytics_service.get_campus_summary(None))
    methodology = analytics_service.get_methodology()

    assert campus.buildings
    assert methodology.id == "co2-v2"

"""Deterministic analytics for summaries, insights, and recommendations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Iterable

from psycopg import AsyncConnection

from ..core.sensors import AIR_SENSOR_TYPES

from ..schemas import Building
from ..schemas.analytics import (
    BuildingSummary,
    CampusSummary,
    DataQuality,
    EnergySummary,
    Insight,
    Methodology,
    MetricStatistics,
    Recommendation,
)
from . import buildings_service, history_service

EVIDENCE_WINDOW_MINUTES = 20
CO2_REFERENCE_PPM = 1000
CO2_RAPID_CHANGE_PPM = 150
SUSTAINED_MINUTES = 45
MINIMUM_SAMPLES = 4
EXPECTED_24H_SAMPLES_PER_SERIES = 96
MAX_SAMPLE_GAP_MINUTES = 20
HISTORY_BUCKET_MINUTES = 15
METHODOLOGY_ID = "co2-v2"

METHODOLOGY = Methodology(
    id=METHODOLOGY_ID,
    title="CO2 rules with sustained measurement evidence",
    co2_reference_ppm=CO2_REFERENCE_PPM,
    co2_bands=[
        {"label": "typical", "from": 0, "to": 800, "color": "#24734d"},
        {"label": "watch", "from": 800, "to": CO2_REFERENCE_PPM, "color": "#8a5700"},
        {"label": "elevated", "from": CO2_REFERENCE_PPM, "to": None, "color": "#b13e35"},
    ],
    sustained_minutes=SUSTAINED_MINUTES,
    minimum_samples=MINIMUM_SAMPLES,
    notes=[
        "CO2 reference bands help interpret readings; they are not a diagnosis of indoor air quality.",
        "Recommendations are deterministic suggestions, not automated diagnoses.",
        "Correlation between metrics is not treated as evidence of causation.",
        "Summary values use the latest stored measurement per sensor and metric, excluding future timestamps.",
        "CO2 actions require four consecutive elevated 15-minute averages from one sensor spanning 45 minutes, with no gap over 20 minutes. The latest raw measurement must be within 20 minutes and the latest bucket within 35 minutes, allowing for bucket alignment.",
        "Coverage is populated 15-minute buckets divided by 96 per registered air sensor.",
    ],
)


async def get_campus_summary(db: AsyncConnection) -> CampusSummary:
    buildings = await buildings_service.list_buildings(db)
    summaries = [
        summary
        for summary in [await get_building_summary(db, building.id) for building in buildings]
        if summary is not None
    ]

    generated_at = _now()
    co2 = _combine_metric("CO2", "ppm", [summary.co2 for summary in summaries])
    temperature = _combine_metric("Temperature", "°C", [summary.temperature for summary in summaries])
    energy = _combine_energy([summary.energy for summary in summaries])
    quality = _combine_quality([summary.data_quality for summary in summaries])
    insights = _campus_insights(summaries)

    return CampusSummary(
        generated_at=generated_at,
        data_quality=quality,
        co2=co2,
        temperature=temperature,
        energy=energy,
        buildings=summaries,
        insights=insights,
    )


async def get_building_summary(
    db: AsyncConnection, building_id: int
) -> BuildingSummary | None:
    current = await buildings_service.get_current(db, building_id)
    if current is None:
        return None

    history = await history_service.get_history(db, building_id, "24h")
    if history is None:
        return None

    generated_at = _now()
    measured = [
        sensor for sensor in current.sensors
        if any(_has_measurement(sensor, metric, generated_at) for metric in sensor.readings)
    ]
    timestamps = [
        _aware_utc(sensor.metric_updated[metric])
        for sensor in measured for metric in sensor.readings
        if _has_measurement(sensor, metric, generated_at)
    ]
    air_sensors = [sensor for sensor in current.sensors if sensor.type in AIR_SENSOR_TYPES]

    co2 = _metric_stats(
        label="CO2",
        unit="ppm",
        metric="co2",
        current_values=[
            sensor.readings["co2"]
            for sensor in air_sensors
            if _has_measurement(sensor, "co2", generated_at)
        ],
        history_series=history.series,
        sensors=air_sensors,
        now=generated_at,
    )
    temperature = _metric_stats(
        label="Temperature",
        unit="°C",
        metric="temperature",
        current_values=[
            sensor.readings["temperature"]
            for sensor in air_sensors
            if _has_measurement(sensor, "temperature", generated_at)
        ],
        history_series=history.series,
        sensors=air_sensors,
        now=generated_at,
    )
    energy = _energy_summary(current.sensors, generated_at)

    quality = DataQuality(
        sensors_with_readings=len(measured),
        registered_sensors=len(current.sensors),
        missing_sensors=len(current.sensors) - len(measured),
        coverage_24h=max(co2.coverage_24h, temperature.coverage_24h),
        latest_reading=max(timestamps, default=None),
    )
    insights = _building_insights(current.building, co2, temperature, energy)
    recommendations = _building_recommendations(current.building, co2)

    return BuildingSummary(
        building=current.building,
        generated_at=generated_at,
        data_quality=quality,
        co2=co2,
        temperature=temperature,
        energy=energy,
        insights=insights,
        recommendations=recommendations,
    )


async def get_building_insights(db: AsyncConnection, building_id: int) -> list[Insight] | None:
    summary = await get_building_summary(db, building_id)
    return None if summary is None else summary.insights


async def get_building_recommendations(
    db: AsyncConnection, building_id: int
) -> list[Recommendation] | None:
    summary = await get_building_summary(db, building_id)
    return None if summary is None else summary.recommendations


def get_methodology() -> Methodology:
    return METHODOLOGY


def _metric_stats(
    *,
    label: str,
    unit: str,
    metric: str,
    current_values: Iterable[float],
    history_series,
    sensors,
    now: datetime,
) -> MetricStatistics:
    sensor_ids = {sensor.device_id for sensor in sensors}
    matching_series = [
        series for series in history_series
        if series.metric == metric
        and series.type in AIR_SENSOR_TYPES
        and series.device_id in sensor_ids
    ]
    points = [
        float(point.value)
        for series in matching_series
        for point in _ordered_points(series, now)
    ]
    current_values = list(current_values)
    current = _rounded_mean(current_values)
    source_count = len(current_values)
    precision = 1 if metric == "temperature" else 0
    registered_count = len(sensors)
    expected = registered_count * EXPECTED_24H_SAMPLES_PER_SERIES
    coverage = min(1.0, round(len(points) / expected, 2)) if expected else 0.0

    if not points:
        return MetricStatistics(
            label=label,
            unit=unit,
            current=_round_optional(current, precision),
            sample_count=0,
            source_count=source_count,
            registered_source_count=registered_count,
            coverage_24h=coverage,
        )

    changes = _hour_changes(matching_series, now)
    change_1h = mean(changes) if changes else None
    sustained = _sustained_evidence(matching_series, sensors, now) if metric == "co2" else {}

    return MetricStatistics(
        label=label,
        unit=unit,
        current=_round_optional(current, precision),
        mean_24h=round(mean(points), precision),
        median_24h=round(median(points), precision),
        min_24h=round(min(points), precision),
        max_24h=round(max(points), precision),
        p95_24h=round(_percentile(points, 95), precision),
        change_1h=_round_optional(change_1h, precision),
        sample_count=len(points),
        source_count=source_count,
        registered_source_count=registered_count,
        trend_source_count=len(changes),
        sustained_minutes=max(sustained.values(), default=0),
        sustained_device_ids=sorted(sustained),
        coverage_24h=coverage,
    )


def _energy_summary(sensors, now: datetime | None = None) -> EnergySummary:
    now = now or _now()
    total_amps = 0.0
    has_readings = False
    for sensor in sensors:
        if sensor.type != "ct305":
            continue
        phase_values = [
            float(sensor.readings[metric])
            for metric in ("current_1", "current_2", "current_3")
            if _has_measurement(sensor, metric, now)
        ]
        if phase_values:
            total_amps += sum(phase_values)
            has_readings = True

    current_kw = round(total_amps * 230 / 1000, 1) if has_readings else None
    return EnergySummary(
        current_kw=current_kw,
        method=(
            "Estimated from available CT305 phase-current readings at 230 V. "
            "Energy totals require calibrated kWh data."
        ),
    )


def _building_insights(
    building: Building,
    co2: MetricStatistics,
    temperature: MetricStatistics,
    energy: EnergySummary,
) -> list[Insight]:
    insights: list[Insight] = []

    if co2.current is not None and co2.change_1h is not None:
        if co2.current >= CO2_REFERENCE_PPM and co2.change_1h >= CO2_RAPID_CHANGE_PPM:
            insights.append(
                Insight(
                    id="rapid_co2_rise",
                    title=f"CO2 is elevated and rising in {building.name}",
                    body=(
                        f"Average CO2 is {co2.current:.0f} ppm and has increased "
                        f"by about {co2.change_1h:.0f} ppm over the last hour."
                    ),
                    severity="attention",
                    metric="co2",
                    evidence={"current": co2.current, "change_1h": co2.change_1h},
                )
            )
        elif co2.max_24h is not None:
            insights.append(
                Insight(
                    id="daily_co2_peak",
                    title=f"{building.name} CO2 peaked at {co2.max_24h:.0f} ppm",
                    body="This is the highest measured CO2 value in the selected 24-hour window.",
                    severity="info",
                    metric="co2",
                    evidence={"max_24h": co2.max_24h, "samples": co2.sample_count},
                )
            )

    if energy.current_kw is not None:
        insights.append(
            Insight(
                id="estimated_energy_now",
                title=f"{building.name} electricity demand is about {energy.current_kw:.1f} kW",
                body="This is an estimate from available current readings and should be treated as directional.",
                severity="info",
                metric="energy",
                evidence={"current_kw": energy.current_kw},
            )
        )

    if not insights and temperature.current is not None:
        insights.append(
            Insight(
                id="temperature_context",
                title=f"{building.name} temperature is {temperature.current:.1f} °C",
                body="No notable CO2 or electricity pattern was detected in the recent readings.",
                severity="info",
                metric="temperature",
                evidence={"current": temperature.current},
            )
        )

    return insights[:3]


def _building_recommendations(
    building: Building, co2: MetricStatistics
) -> list[Recommendation]:
    if (
        co2.current is None
        or co2.current < CO2_REFERENCE_PPM
        or co2.sample_count < MINIMUM_SAMPLES
        or co2.sustained_minutes < SUSTAINED_MINUTES
        or not co2.sustained_device_ids
    ):
        return []

    confidence = "medium"
    if co2.coverage_24h >= 0.8 and co2.change_1h is not None and co2.change_1h > 0:
        confidence = "high"
    elif co2.coverage_24h < 0.5:
        confidence = "low"

    return [
        Recommendation(
            id="co2_sustained_elevation",
            title=f"CO2 may need attention in {building.name}",
            evidence={
                "current": co2.current,
                "reference": CO2_REFERENCE_PPM,
                "change_1h": co2.change_1h,
                "samples": co2.sample_count,
                "coverage_24h": co2.coverage_24h,
                "sustained_minutes": co2.sustained_minutes,
                "device_ids": co2.sustained_device_ids,
            },
            interpretation=(
                "The pattern is consistent with ventilation not keeping pace with "
                "room activity, but sensor data alone does not prove the cause."
            ),
            actions=[
                "Students can consider another study area if the room feels crowded or uncomfortable.",
                "Facilities can review ventilation operation or scheduling if the pattern recurs.",
            ],
            audience=["student", "facilities"],
            confidence=confidence,
            verification="Watch whether CO2 trends downward over the next 30-60 minutes.",
            methodology_id=METHODOLOGY_ID,
        )
    ]


def _campus_insights(summaries: list[BuildingSummary]) -> list[Insight]:
    insights: list[Insight] = []
    if not summaries:
        return insights

    with_co2 = [summary for summary in summaries if summary.co2.current is not None]
    if with_co2:
        highest = max(with_co2, key=lambda item: item.co2.current or 0)
        insights.append(
            Insight(
                id="campus_highest_co2",
                title=f"{highest.building.name} has the highest CO2 average in the latest readings",
                body=(
                    f"Latest average is {highest.co2.current:.0f} ppm across "
                    f"{highest.co2.source_count} air sensors with readings."
                ),
                severity="info",
                metric="co2",
                evidence={
                    "building_id": highest.building.id,
                    "current": highest.co2.current,
                    "source_count": highest.co2.source_count,
                },
            )
        )

    return insights[:4]


def _combine_metric(
    label: str, unit: str, metrics: Iterable[MetricStatistics]
) -> MetricStatistics:
    metric_list = list(metrics)
    sample_count = sum(metric.sample_count for metric in metric_list)
    source_count = sum(metric.source_count for metric in metric_list)
    registered_count = sum(metric.registered_source_count for metric in metric_list)

    precision = 1 if unit == "°C" else 0
    return MetricStatistics(
        label=label,
        unit=unit,
        current=_round_optional(
            _weighted_metric(metric_list, "current", "source_count"), precision
        ),
        mean_24h=_round_optional(
            _weighted_metric(metric_list, "mean_24h", "sample_count"), precision
        ),
        median_24h=None,
        min_24h=min(
            [metric.min_24h for metric in metric_list if metric.min_24h is not None],
            default=None,
        ),
        max_24h=max(
            [metric.max_24h for metric in metric_list if metric.max_24h is not None],
            default=None,
        ),
        p95_24h=None,
        change_1h=_round_optional(
            _weighted_metric(metric_list, "change_1h", "trend_source_count"), precision
        ),
        sample_count=sample_count,
        source_count=source_count,
        registered_source_count=registered_count,
        trend_source_count=sum(metric.trend_source_count for metric in metric_list),
        coverage_24h=round(
            _weighted_metric(metric_list, "coverage_24h", "registered_source_count") or 0.0,
            2,
        ),
    )


def _combine_energy(energies: Iterable[EnergySummary]) -> EnergySummary:
    values = [energy.current_kw for energy in energies if energy.current_kw is not None]
    return EnergySummary(
        current_kw=round(sum(values), 1) if values else None,
        method="Campus estimate sums building-level CT305 phase-current estimates.",
    )


def _combine_quality(qualities: list[DataQuality]) -> DataQuality:
    registered = sum(quality.registered_sensors for quality in qualities)
    covered = sum(quality.coverage_24h * quality.registered_sensors for quality in qualities)
    return DataQuality(
        sensors_with_readings=sum(quality.sensors_with_readings for quality in qualities),
        registered_sensors=registered,
        missing_sensors=sum(quality.missing_sensors for quality in qualities),
        coverage_24h=round(covered / registered, 2) if registered else 0.0,
        latest_reading=max(
            (quality.latest_reading for quality in qualities if quality.latest_reading is not None),
            default=None,
        ),
    )


def _change_over_last_hour(
    series_list, current: float | None, now: datetime | None = None
) -> float | None:
    if current is None:
        return None

    changes = _hour_changes(series_list, now or _now())

    if not changes:
        return None
    return mean(changes)


def _has_measurement(sensor, metric: str, now: datetime) -> bool:
    timestamp = sensor.metric_updated.get(metric)
    return (
        metric in sensor.readings
        and timestamp is not None
        and _aware_utc(timestamp) <= _aware_utc(now)
    )


def _weighted_metric(metrics, field: str, weight_field: str) -> float | None:
    pairs = [
        (getattr(item, field), getattr(item, weight_field)) for item in metrics
        if getattr(item, field) is not None and getattr(item, weight_field) > 0
    ]
    if not pairs:
        return None
    return sum(value * weight for value, weight in pairs) / sum(weight for _, weight in pairs)


def _ordered_points(series, now: datetime):
    # Deduplicate timestamps and ignore points outside the selected window.
    cutoff = now - timedelta(hours=24, minutes=HISTORY_BUCKET_MINUTES)
    points = {
        _aware_utc(point.time): point for point in series.points
        if cutoff < _aware_utc(point.time) <= now
    }
    return [points[timestamp] for timestamp in sorted(points)]


def _history_is_recent(points, now: datetime) -> bool:
    maximum_age = (EVIDENCE_WINDOW_MINUTES + HISTORY_BUCKET_MINUTES) * 60
    return bool(points) and (now - _aware_utc(points[-1].time)).total_seconds() <= maximum_age


def _has_history_gap(points) -> bool:
    return any(
        (_aware_utc(right.time) - _aware_utc(left.time)).total_seconds()
        > MAX_SAMPLE_GAP_MINUTES * 60
        for left, right in zip(points, points[1:])
    )


def _hour_changes(series_list, now: datetime) -> list[float]:
    changes = []
    for series in series_list:
        points = _ordered_points(series, now)
        if len(points) < 2 or not _history_is_recent(points, now):
            continue
        target = _aware_utc(points[-1].time) - timedelta(hours=1)
        index = min(
            range(len(points)),
            key=lambda i: abs((_aware_utc(points[i].time) - target).total_seconds()),
        )
        if abs((_aware_utc(points[index].time) - target).total_seconds()) > 5 * 60:
            continue
        window = points[index:]
        if _has_history_gap(window):
            continue
        changes.append(float(points[-1].value) - float(points[index].value))
    return changes


def _sustained_evidence(series_list, sensors, now: datetime) -> dict[int, float]:
    eligible = {
        sensor.device_id for sensor in sensors
        if _has_measurement(sensor, "co2", now)
        and now - _aware_utc(sensor.metric_updated["co2"]) < timedelta(minutes=EVIDENCE_WINDOW_MINUTES)
        and sensor.readings["co2"] >= CO2_REFERENCE_PPM
    }
    evidence = {}
    for series in series_list:
        if series.device_id not in eligible:
            continue
        points = _ordered_points(series, now)
        if not _history_is_recent(points, now):
            continue
        elevated = []
        for point in reversed(points):
            if point.value < CO2_REFERENCE_PPM:
                break
            if elevated and _has_history_gap([point, elevated[-1]]):
                break
            elevated.append(point)
        if len(elevated) < MINIMUM_SAMPLES:
            continue
        duration = (_aware_utc(elevated[0].time) - _aware_utc(elevated[-1].time)).total_seconds() / 60
        if duration >= SUSTAINED_MINUTES:
            evidence[series.device_id] = round(duration, 1)
    return evidence


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((percentile / 100) * (len(ordered) - 1))
    return ordered[index]


def _rounded_mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    if not clean:
        return None
    return mean(clean)


def _round_optional(value: float | None, precision: int = 1) -> float | None:
    return None if value is None else round(value, precision)


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)

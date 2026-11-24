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
    Freshness,
    Insight,
    Methodology,
    MetricStatistics,
    Recommendation,
)
from . import buildings_service, history_service

CURRENT_MINUTES = 20
DELAYED_MINUTES = 45
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
    title="CO2 rules with sensor freshness and sustained evidence",
    freshness_minutes={"current": CURRENT_MINUTES, "delayed": DELAYED_MINUTES},
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
        "Current aggregates exclude readings over 45 minutes old and future timestamps.",
        "CO2 actions require at least four consecutive elevated 15-minute averages from one current sensor spanning 45 minutes, with no gap over 20 minutes.",
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
    quality = _combine_quality([summary.data_quality for summary in summaries], generated_at)
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
    sensor_freshness = [_sensor_freshness(sensor, generated_at) for sensor in current.sensors]
    freshness = _worst_freshness(sensor_freshness)
    active_sensors = sum(item.status in {"current", "delayed"} for item in sensor_freshness)
    stale_sensors = sum(item.status == "stale" for item in sensor_freshness)
    air_sensors = [sensor for sensor in current.sensors if sensor.type in AIR_SENSOR_TYPES]

    co2 = _metric_stats(
        label="CO2",
        unit="ppm",
        metric="co2",
        current_values=[
            sensor.readings["co2"]
            for sensor in air_sensors
            if _metric_is_fresh(sensor, "co2", generated_at)
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
            if _metric_is_fresh(sensor, "temperature", generated_at)
        ],
        history_series=history.series,
        sensors=air_sensors,
        now=generated_at,
    )
    energy = _energy_summary(current.sensors, generated_at)

    quality = DataQuality(
        active_sensors=active_sensors,
        stale_sensors=stale_sensors,
        registered_sensors=len(current.sensors),
        missing_sensors=sum(item.status == "unknown" for item in sensor_freshness),
        coverage_24h=max(co2.coverage_24h, temperature.coverage_24h),
        freshness=freshness,
    )
    insights = _building_insights(current.building, quality, co2, temperature, energy)
    recommendations = _building_recommendations(current.building, quality, co2)

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


def classify_freshness(latest: datetime | None, now: datetime | None = None) -> Freshness:
    if latest is None:
        return Freshness(
            status="unknown",
            latest_reading=None,
            age_minutes=None,
            description="No reading timestamp is available.",
        )

    now = _aware_utc(now or _now())
    latest = _aware_utc(latest)
    if latest > now:
        return Freshness(status="unknown", latest_reading=latest, description="Reading timestamp is in the future.")
    elapsed_minutes = (now - latest).total_seconds() / 60
    age = round(elapsed_minutes)
    if elapsed_minutes < CURRENT_MINUTES:
        status = "current"
        description = f"Latest reading is {age} min old."
    elif elapsed_minutes <= DELAYED_MINUTES:
        status = "delayed"
        description = f"Latest reading is delayed at {age} min old."
    else:
        status = "stale"
        description = f"Latest reading is stale at {age} min old."

    return Freshness(
        status=status,
        latest_reading=latest,
        age_minutes=age,
        description=description,
    )


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
    last_known_samples = [
        (float(sensor.readings[metric]), _aware_utc(sensor.metric_updated[metric]))
        for sensor in sensors
        if metric in sensor.readings and sensor.metric_updated.get(metric) is not None
        and _aware_utc(sensor.metric_updated[metric]) <= _aware_utc(now)
    ]
    last_known = _rounded_mean([value for value, _ in last_known_samples])
    last_known_age = (
        max(round((now - timestamp).total_seconds() / 60) for _, timestamp in last_known_samples)
        if last_known_samples
        else None
    )
    registered_count = len(sensors)
    expected = registered_count * EXPECTED_24H_SAMPLES_PER_SERIES
    coverage = min(1.0, round(len(points) / expected, 2)) if expected else 0.0

    if not points:
        return MetricStatistics(
            label=label,
            unit=unit,
            current=current,
            last_known=last_known,
            last_known_source_count=len(last_known_samples),
            last_known_age_minutes=last_known_age,
            sample_count=0,
            source_count=source_count,
            registered_source_count=registered_count,
            coverage_24h=coverage,
        )

    fresh_ids = {
        sensor.device_id for sensor in sensors
        if _metric_is_fresh(sensor, metric, now)
    }
    fresh_series = [series for series in matching_series if series.device_id in fresh_ids]
    changes = _hour_changes(fresh_series, now)
    change_1h = mean(changes) if changes else None
    sustained = _sustained_evidence(fresh_series, sensors, now) if metric == "co2" else {}
    precision = 1 if metric == "temperature" else 0

    return MetricStatistics(
        label=label,
        unit=unit,
        current=_round_optional(current, precision),
        last_known=_round_optional(last_known, precision),
        last_known_source_count=len(last_known_samples),
        last_known_age_minutes=last_known_age,
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
            if _metric_is_fresh(sensor, metric, now)
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
    quality: DataQuality,
    co2: MetricStatistics,
    temperature: MetricStatistics,
    energy: EnergySummary,
) -> list[Insight]:
    insights: list[Insight] = []

    if quality.freshness.status in {"delayed", "stale", "unknown"}:
        insights.append(
            Insight(
                id="sensor_stale",
                title=f"{building.name} data is {quality.freshness.status}",
                body=quality.freshness.description + " Current conditions may differ.",
                severity="warning",
                evidence={"age_minutes": quality.freshness.age_minutes},
            )
        )

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
    building: Building, quality: DataQuality, co2: MetricStatistics
) -> list[Recommendation]:
    if (
        co2.current is None
        or co2.current < CO2_REFERENCE_PPM
        or co2.sample_count < MINIMUM_SAMPLES
        or quality.freshness.status != "current"
        or co2.sustained_minutes < SUSTAINED_MINUTES
        or not co2.sustained_device_ids
    ):
        return []

    confidence = "medium"
    if co2.coverage_24h >= 0.8 and co2.change_1h is not None and co2.change_1h > 0:
        confidence = "high"
    elif co2.coverage_24h < 0.5 or quality.freshness.status == "delayed":
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
                title=f"{highest.building.name} has the highest current CO2 average",
                body=(
                    f"Current average is {highest.co2.current:.0f} ppm across "
                    f"{highest.co2.source_count} reporting air sensors."
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

    stale_count = sum(summary.data_quality.stale_sensors for summary in summaries)
    if stale_count:
        insights.append(
            Insight(
                id="campus_stale_sensors",
                title=f"{stale_count} sensors have stale measurements",
                body="Stale readings are excluded from claims about current conditions.",
                severity="warning",
                evidence={"stale_sensors": stale_count},
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
        last_known=_round_optional(
            _weighted_metric(metric_list, "last_known", "last_known_source_count"), precision
        ),
        last_known_source_count=sum(metric.last_known_source_count for metric in metric_list),
        last_known_age_minutes=max(
            [metric.last_known_age_minutes for metric in metric_list if metric.last_known_age_minutes is not None],
            default=None,
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


def _combine_quality(qualities: list[DataQuality], generated_at: datetime) -> DataQuality:
    registered = sum(quality.registered_sensors for quality in qualities)
    covered = sum(quality.coverage_24h * quality.registered_sensors for quality in qualities)
    return DataQuality(
        active_sensors=sum(quality.active_sensors for quality in qualities),
        stale_sensors=sum(quality.stale_sensors for quality in qualities),
        registered_sensors=registered,
        missing_sensors=sum(quality.missing_sensors for quality in qualities),
        coverage_24h=round(covered / registered, 2) if registered else 0.0,
        freshness=_worst_freshness([quality.freshness for quality in qualities]),
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


def _metric_is_fresh(sensor, metric: str, now: datetime) -> bool:
    timestamp = sensor.metric_updated.get(metric)
    if metric not in sensor.readings or timestamp is None:
        return False
    age = (_aware_utc(now) - _aware_utc(timestamp)).total_seconds() / 60
    return 0 <= age <= DELAYED_MINUTES


def _sensor_freshness(sensor, now: datetime) -> Freshness:
    expected = (
        ("co2", "temperature", "humidity") if sensor.type in AIR_SENSOR_TYPES
        else ("current_1", "current_2", "current_3")
    )
    missing = [metric for metric in expected if sensor.metric_updated.get(metric) is None]
    if missing:
        return classify_freshness(None, now).model_copy(update={
            "device_id": sensor.device_id, "device_label": sensor.label,
            "metric": missing[0], "checked_at": _aware_utc(now),
            "description": f"{sensor.label}: no timestamp for {', '.join(missing)}.",
        })
    # A fresh battery or panel-temperature report cannot mask old telemetry.
    timestamps = [(metric, _aware_utc(sensor.metric_updated[metric])) for metric in expected]
    metric, timestamp = next(
        ((metric, timestamp) for metric, timestamp in timestamps if timestamp > _aware_utc(now)),
        min(timestamps, key=lambda item: item[1]),
    )
    result = classify_freshness(timestamp, now)
    received_at = sensor.metric_received_at.get(metric)
    receipt_text = (
        f" First stored: {_aware_utc(received_at).isoformat()}."
        if received_at is not None and result.status != "current" else ""
    )
    return result.model_copy(update={
        "device_id": sensor.device_id, "device_label": sensor.label,
        "metric": metric, "checked_at": _aware_utc(now),
        "received_at": received_at,
        "description": (
            f"{sensor.label} / {metric}: {result.description} "
            f"Measurement timestamp: {timestamp.isoformat()}." + receipt_text
        ),
    })


def _worst_freshness(items: list[Freshness]) -> Freshness:
    if not items:
        return classify_freshness(None)
    rank = {"current": 0, "delayed": 1, "unknown": 2, "stale": 3}
    worst = max(items, key=lambda item: (rank[item.status], item.age_minutes or 0))
    description = worst.description
    if not description.startswith("Least fresh sensor:"):
        description = "Least fresh sensor: " + description
    return worst.model_copy(update={"description": description})


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
    maximum_age = (CURRENT_MINUTES + HISTORY_BUCKET_MINUTES) * 60
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
        if _metric_is_fresh(sensor, "co2", now)
        and classify_freshness(sensor.metric_updated["co2"], now).status == "current"
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

"""Generated telemetry for isolated tests; never imported by the application."""

import math
import random
from datetime import datetime, timedelta, timezone

from app.schemas import (
    Building,
    CurrentResponse,
    HistoryPoint,
    HistoryResponse,
    Sensor,
    Series,
)

_BUILDINGS = [
    {"id": 1, "name": "Kjølv Egelands hus", "slug": "kjolv-egelands-hus", "co2": 650, "temp": 21.5, "am103": 3, "panel": True},
    {"id": 3, "name": "Arne Rettedals hus", "slug": "arne-rettedals-hus", "co2": 1150, "temp": 22.8, "am103": 2, "panel": True},
    {"id": 4, "name": "EOJ", "slug": "eoj", "co2": 900, "temp": 22.0, "am103": 3, "panel": True},
    {"id": 5, "name": "SiS", "slug": "sis", "co2": 750, "temp": 21.8, "am103": 2, "panel": False},
]

_rng = random.Random(42)


def list_buildings() -> list[Building]:
    return [Building(id=b["id"], name=b["name"], slug=b["slug"]) for b in _BUILDINGS]


def _air_devices(building):
    return enumerate(["am103"] * building["am103"] + ["am107"], 1)


def registered_sensor_counts() -> dict[str, int]:
    return {
        "am103": sum(building["am103"] for building in _BUILDINGS),
        "am107": len(_BUILDINGS),
        "ct305": sum(building["panel"] for building in _BUILDINGS),
    }


def get_current(building_id: int) -> CurrentResponse | None:
    b = _find(building_id)
    if b is None:
        return None

    sensors = []
    for i, kind in _air_devices(b):
        sensor = Sensor(
            device_id=building_id * 10 + i,
            label=f"{b['name']} — Room {i}",
            room=f"Room {i}",
            type=kind,
            readings={
                "co2": round(b["co2"] + _rng.uniform(-80, 80)),
                "temperature": round(b["temp"] + _rng.uniform(-1, 1), 1),
                "humidity": round(38 + _rng.uniform(-8, 8), 1),
            },
        )
        if kind == "am107":
            sensor.label = f"{b['name']} — Auditorium"
            sensor.readings.update({
                "battery": 100, "activity": _rng.randint(0, 10),
                "illumination": 350, "infrared_and_visible": 400,
                "infrared": 50, "tvoc": 120, "pressure": 1013.2,
            })
        sensors.append(sensor)
    if b["panel"]:
        sensors.append(Sensor(
            device_id=building_id * 10 + 9,
            label=f"{b['name']} — Main panel",
            type="ct305",
            readings={
                "current_1": round(_rng.uniform(4, 16), 1),
                "current_2": round(_rng.uniform(3, 13), 1),
                "current_3": round(_rng.uniform(4, 15), 1),
                "total_1": round(_rng.uniform(50, 300)),
                "total_2": round(_rng.uniform(40, 260)),
                "total_3": round(_rng.uniform(50, 290)),
            },
        ))

    # Exercise earlier readings for one building.
    updated = datetime.now(timezone.utc)
    if building_id == 3:
        updated -= timedelta(minutes=60)

    for sensor in sensors:
        sensor.updated = updated
        sensor.metric_updated = {metric: updated for metric in sensor.readings}

    return CurrentResponse(
        building=Building(id=b["id"], name=b["name"], slug=b["slug"]),
        updated=updated,
        sensors=sensors,
    )


def get_history(building_id: int, range_: str) -> HistoryResponse | None:
    b = _find(building_id)
    if b is None:
        return None

    series = []
    for i, kind in _air_devices(b):
        label = f"{b['name']} — Auditorium" if kind == "am107" else f"{b['name']} — Room {i}"
        device_id = building_id * 10 + i
        metrics = [("co2", b["co2"], 90, 0), ("temperature", b["temp"], 1.2, 1), ("humidity", 40, 5, 1)]
        if kind == "am107":
            metrics += [("activity", 2, 1, 0), ("illumination", 350, 100, 0),
                        ("infrared_and_visible", 400, 100, 0), ("infrared", 50, 10, 0),
                        ("tvoc", 120, 30, 0), ("pressure", 1013.2, 2, 1)]
        for metric, base, amplitude, decimals in metrics:
            series.append(Series(
                device_id=device_id, label=label, type=kind, metric=metric,
                points=_series(base, amplitude, decimals),
            ))

    return HistoryResponse(
        building=Building(id=b["id"], name=b["name"], slug=b["slug"]),
        range=range_,
        series=series,
    )


def _find(building_id: int):
    return next((x for x in _BUILDINGS if x["id"] == building_id), None)


def _series(base: float, amplitude: float, decimals: int = 0) -> list[HistoryPoint]:
    """96 points (24h at 15-min steps) with a daily cycle + noise."""
    now = datetime.now(timezone.utc)
    points = []
    for i in range(96):
        t = now - timedelta(minutes=(95 - i) * 15)
        hour = t.hour + t.minute / 60
        value = base + amplitude * math.sin((hour - 9) * math.pi / 12) + _rng.uniform(-amplitude * 0.3, amplitude * 0.3)
        points.append(HistoryPoint(time=t, value=round(value, decimals)))
    return points

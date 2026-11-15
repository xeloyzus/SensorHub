"""Business logic for building and current-readings queries."""

from datetime import datetime

from psycopg import AsyncConnection

from ..schemas import Building, CurrentResponse, Sensor


async def list_buildings(db: AsyncConnection) -> list[Building]:
    """Return every building (id, name, slug)."""
    async with db.cursor() as cur:
        await cur.execute("SELECT id, name, slug FROM buildings WHERE is_active ORDER BY id")
        rows = await cur.fetchall()
    return [Building(id=r[0], name=r[1], slug=r[2]) for r in rows]


async def get_current(db: AsyncConnection, building_id: int) -> CurrentResponse | None:
    """Latest value of every metric for every device in a building.

    Returns ``None`` when the building does not exist.
    """
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT id, name, slug FROM buildings WHERE id = %s", (building_id,)
        )
        row = await cur.fetchone()
        if row is None:
            return None
        building = Building(id=row[0], name=row[1], slug=row[2])

        await cur.execute(
            """
            SELECT DISTINCT ON (d.id, r.metric)
                   d.id, d.label, d.type, r.metric, r.value, r.time
            FROM devices d
            LEFT JOIN readings r ON d.id = r.device_id
              AND r.value > '-Infinity'::double precision
              AND r.value < 'Infinity'::double precision
              AND r.time <= now()
            WHERE d.building_id = %s
            ORDER BY d.id, r.metric, r.time DESC
            """,
            (building_id,),
        )
        rows = await cur.fetchall()

    # Group the flat rows into one Sensor per device.
    sensors: dict[int, Sensor] = {}
    latest: datetime | None = None
    for device_id, label, device_type, metric, value, ts in rows:
        sensor = sensors.setdefault(
            device_id,
            Sensor(device_id=device_id, label=label, type=device_type, readings={}),
        )
        if metric is None:
            continue  # Keep registered sensors that have never reported.
        sensor.readings[metric] = value
        sensor.metric_updated[metric] = ts
        if sensor.updated is None or ts > sensor.updated:
            sensor.updated = ts
        if latest is None or ts > latest:
            latest = ts

    return CurrentResponse(building=building, updated=latest, sensors=list(sensors.values()))

"""Business logic for history queries."""

from psycopg import AsyncConnection

from ..schemas import Building, HistoryPoint, HistoryResponse, Series

# Supported range presets -> the ``time_bucket`` used to downsample the series.
RANGES = {
    "1h": "5 minutes",
    "24h": "15 minutes",
    "48h": "30 minutes",
    "7d": "1 hour",
    "30d": "6 hours",
}

# Lookback window per preset, in hours. Passing a plain number (instead of the
# raw preset string cast to an interval) keeps Postgres's forgiving interval
# syntax out of the query path entirely.
RANGE_HOURS = {"1h": 1, "24h": 24, "48h": 48, "7d": 168, "30d": 720}


async def get_history(
    db: AsyncConnection, building_id: int, range_: str
) -> HistoryResponse | None:
    """Return downsampled history for a building over ``range_``.

    Returns ``None`` when the building does not exist; raises ``ValueError``
    for an unsupported range.
    """
    bucket = RANGES.get(range_)
    if bucket is None:
        raise ValueError(f"unsupported range {range_!r}; choose one of {sorted(RANGES)}")


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
            SELECT d.id, d.label, d.type, r.metric,
                   time_bucket(%s::interval, r.time) AS t,
                   avg(r.value) AS value
            FROM readings r
            JOIN devices d ON d.id = r.device_id
            WHERE d.building_id = %s
              AND r.time > now() - (%s || ' hours')::interval
              AND r.time <= now()
              AND r.value > '-Infinity'::double precision
              AND r.value < 'Infinity'::double precision
            GROUP BY d.id, d.label, d.type, r.metric, t
            ORDER BY d.id, r.metric, t
            """,
            (bucket, building_id, RANGE_HOURS[range_]),
        )
        rows = await cur.fetchall()

    # Group flat rows into one Series per (device, metric).
    series_map: dict[tuple[int, str], Series] = {}
    for device_id, label, device_type, metric, ts, value in rows:
        key = (device_id, metric)
        item = series_map.setdefault(
            key,
            Series(device_id=device_id, label=label, type=device_type, metric=metric, points=[]),
        )
        item.points.append(HistoryPoint(time=ts, value=value))

    return HistoryResponse(building=building, range=range_, series=list(series_map.values()))

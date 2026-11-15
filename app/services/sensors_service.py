"""Expose the hardware plan alongside actual device registration counts."""

from psycopg import AsyncConnection

from ..schemas.inventory import SensorModel


async def list_sensor_models(db: AsyncConnection) -> list[SensorModel]:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT m.type, m.name, m.planned_quantity, m.metrics, count(d.id) "
            "FROM sensor_models m LEFT JOIN devices d ON d.type = m.type "
            "GROUP BY m.type, m.name, m.planned_quantity, m.metrics ORDER BY m.type"
        )
        rows = await cur.fetchall()
    return [SensorModel(type=kind, name=name, planned_quantity=planned,
                        metrics=metrics, registered_quantity=registered)
            for kind, name, planned, metrics, registered in rows]

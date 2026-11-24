"""Expose the hardware plan alongside actual device registration counts."""

from psycopg import AsyncConnection

from ..schemas.inventory import SensorModel


async def list_sensor_models(db: AsyncConnection) -> list[SensorModel]:
    async with db.cursor() as cur:
        await cur.execute(
            "SELECT m.type, m.name, m.planned_quantity, "
            "ARRAY(SELECT sm.metric FROM sensor_model_metrics sm "
            "WHERE sm.model_type = m.type ORDER BY sm.display_order), "
            "(SELECT count(*) FROM devices d WHERE d.type = m.type AND d.is_active) "
            "FROM sensor_models m ORDER BY m.type"
        )
        rows = await cur.fetchall()
    return [SensorModel(type=kind, name=name, planned_quantity=planned,
                        metrics=metrics, registered_quantity=registered)
            for kind, name, planned, metrics, registered in rows]

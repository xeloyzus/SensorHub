"""Read-only sensor model inventory endpoint."""

from fastapi import APIRouter

from ..dependencies import DbConn
from ..schemas.inventory import SensorModel
from ..services import sensors_service

router = APIRouter(prefix="/api/sensor-models", tags=["sensors"])


@router.get("", response_model=list[SensorModel])
async def list_sensor_models(db: DbConn):
    return await sensors_service.list_sensor_models(db)

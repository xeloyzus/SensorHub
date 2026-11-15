"""Sensor model inventory; planned hardware is distinct from registered devices."""

from pydantic import BaseModel, Field


class SensorModel(BaseModel):
    type: str
    name: str
    planned_quantity: int = Field(ge=0)
    registered_quantity: int = Field(ge=0)
    metrics: list[str]

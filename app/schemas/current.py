"""Schemas for the "current readings" endpoint."""

from datetime import datetime

from pydantic import BaseModel, Field

from .building import Building


class Sensor(BaseModel):
    device_id: int
    label: str
    type: str
    readings: dict[str, float]
    updated: datetime | None = None
    metric_updated: dict[str, datetime] = Field(default_factory=dict)
    metric_received_at: dict[str, datetime] = Field(default_factory=dict)


class CurrentResponse(BaseModel):
    building: Building
    updated: datetime | None = None
    sensors: list[Sensor]

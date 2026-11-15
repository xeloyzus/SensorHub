"""Schemas for deployment/runtime status endpoints."""

from pydantic import BaseModel


class RuntimeStatus(BaseModel):
    app: str
    mode: str
    data_source: str
    dashboard_url: str
    database_configured: bool
    gateway_ingest_expected: bool
    display_refresh_seconds: int

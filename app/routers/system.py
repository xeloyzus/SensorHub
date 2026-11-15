"""Runtime status endpoints shared by the frontend and deployment checks."""

from fastapi import APIRouter, Request

from ..core.config import settings
from ..schemas import RuntimeStatus

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/status", response_model=RuntimeStatus)
async def status(request: Request):
    return RuntimeStatus(
        app="Campus dashboard",
        mode=settings.runtime_mode,
        data_source=settings.data_source,
        dashboard_url=dashboard_url(request),
        database_configured=bool(settings.database_url),
        gateway_ingest_expected=True,
        display_refresh_seconds=settings.display_refresh_seconds,
    )


def dashboard_url(request: Request) -> str:
    origin = settings.public_base_url or str(request.base_url).rstrip("/")
    return f"{origin}/overview"

"""Internal ops endpoints (health checks used by orchestration/monitoring)."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from psycopg import Error
from psycopg_pool import PoolTimeout

from ..core.config import settings
from ..db.database import pool

router = APIRouter(tags=["internal"])


@router.get("/health")
async def health():
    if pool is None:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    try:
        async with pool.connection(timeout=3) as db:
            await db.execute("SELECT 1")
    except (Error, PoolTimeout):
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {
        "status": "ok",
        "mode": settings.runtime_mode,
        "data_source": settings.data_source,
        "database_configured": bool(settings.database_url),
    }

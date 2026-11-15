"""Campus dashboard API — FastAPI application.

Serves the JSON API and the dashboard frontend (Jinja2 templates + static
assets). Run with::

    uvicorn app.main:app
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db.database import pool
from .core.config import settings
from .internal import health
from .routers import analytics, buildings, history, pages, qr, sensors, system

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.require_database_url()
    if pool is None:
        raise RuntimeError("Database pool is not configured.")
    try:
        await pool.open(wait=True)
        yield
    finally:
        await pool.close()


app = FastAPI(title="Campus dashboard API", version="1.0.0", lifespan=lifespan)

# Frontend assets (CSS / JS / images).
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(analytics.router)
app.include_router(buildings.router)
app.include_router(history.router)
app.include_router(health.router)
app.include_router(system.router)
app.include_router(sensors.router)
app.include_router(qr.router)
app.include_router(pages.router)


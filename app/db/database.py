"""Database connection pool (async psycopg).

TimescaleDB is queried through plain Postgres SQL — the time-series extension
is transparent for these queries.
"""

from psycopg_pool import AsyncConnectionPool

from ..core.config import settings

# Created with ``open=False``; opened in ``main.py``'s lifespan handler.
# A missing URL is rejected by the application lifespan before serving traffic.
pool = (
    AsyncConnectionPool(
        settings.database_url, min_size=1, max_size=10, open=False,
        kwargs={"options": "-c default_transaction_read_only=on -c statement_timeout=15000"},
    )
    if settings.database_url
    else None
)

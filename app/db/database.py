"""Database connection pool (async psycopg).

TimescaleDB is queried through plain Postgres SQL — the time-series extension
is transparent for these queries.
"""

from psycopg_pool import AsyncConnectionPool

from ..core.config import settings

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 10


def create_pool() -> AsyncConnectionPool:
    """Build the shared pool. Raises when ``DATABASE_URL`` is missing.

    Constructing the pool lazily (instead of at import time) means a missing
    configuration surfaces as a clear error in the application lifespan —
    where tests and tooling can handle it — rather than an obscure failure
    while importing any module that touches the database.
    """
    return AsyncConnectionPool(
        settings.require_database_url(),
        min_size=POOL_MIN_SIZE,
        max_size=POOL_MAX_SIZE,
        open=False,
        timeout=10.0,
        kwargs={
            "options": "-c default_transaction_read_only=on -c statement_timeout=15000",
        },
    )


# Created with ``open=False``; opened in ``main.py``'s lifespan handler.
pool = create_pool() if settings.database_url else None

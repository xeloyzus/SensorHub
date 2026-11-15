"""Readiness must reflect the database connection, not just configuration."""

import asyncio
from contextlib import asynccontextmanager

import psycopg
from psycopg_pool import PoolTimeout
import pytest

from app.internal import health


@pytest.mark.parametrize("failure", [psycopg.OperationalError("offline"), PoolTimeout("busy")])
def test_database_outage_returns_503_without_exposing_details(monkeypatch, failure):
    class Pool:
        @asynccontextmanager
        async def connection(self, timeout):
            raise failure
            yield

    monkeypatch.setattr(health, "pool", Pool())
    response = asyncio.run(health.health())
    assert response.status_code == 503
    assert b"offline" not in response.body
    assert b"busy" not in response.body


def test_readiness_executes_a_real_database_probe(monkeypatch):
    queries = []

    class DB:
        async def execute(self, query):
            queries.append(query)

    class Pool:
        @asynccontextmanager
        async def connection(self, timeout):
            yield DB()

    monkeypatch.setattr(health, "pool", Pool())
    assert asyncio.run(health.health())["status"] == "ok"
    assert queries == ["SELECT 1"]

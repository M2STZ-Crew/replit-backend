"""asyncpg connection pool and database access wrapper.

A single process-wide asyncpg pool against the Supabase Postgres (transaction
pooler). The backend connects as the privileged Postgres role, so queries bypass
RLS — application-layer RBAC plus the DB authority triggers are the enforcement
(see project memory: service_role/RLS model). Statement caching is disabled for
compatibility with the Supabase transaction pooler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import get_logger

log = get_logger(__name__)


class DatabaseNotConfiguredError(AppError):
    """Raised when a DB operation runs without an initialized pool (HTTP 503)."""

    status_code = 503
    error_code = "database_unavailable"


class Database:
    """Thin async wrapper around an asyncpg connection pool."""

    def __init__(self) -> None:
        self._pool: asyncpg.Pool | None = None

    @property
    def pool(self) -> asyncpg.Pool:
        """Return the live pool or raise if the DB has not connected."""
        if self._pool is None:
            raise DatabaseNotConfiguredError(
                "Database pool is not initialized (DATABASE_URL missing or unreachable)."
            )
        return self._pool

    @property
    def is_connected(self) -> bool:
        """True once a pool has been created."""
        return self._pool is not None

    async def connect(self) -> None:
        """Create the asyncpg pool. No-op if DATABASE_URL is unset; resilient to errors."""
        if self._pool is not None:
            return
        settings = get_settings()
        if not settings.database_configured:
            log.warning("database_not_configured", 
                        detail="DATABASE_URL is empty; DB features disabled",
                        )
            return
        try:
            self._pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
                command_timeout=settings.db_command_timeout,
                statement_cache_size=0,  # required for the Supabase transaction pooler
                ssl="require",
                server_settings={
                    "search_path": "public,extensions",
                    "application_name": "replit_backend",
                },
            )
            log.info(
                "database_pool_connected",
                min_size=settings.db_pool_min_size,
                max_size=settings.db_pool_max_size,
            )
        except Exception:
            self._pool = None
            log.error("database_pool_connect_failed", exc_info=True)

    async def disconnect(self) -> None:
        """Close the pool if open."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            log.info("database_pool_closed")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquire a pooled connection as an async context manager."""
        async with self.pool.acquire() as connection:
            yield connection

    async def fetch(self, query: str, *args: Any) -> list[asyncpg.Record]:
        """Run a query and return all rows."""
        async with self.pool.acquire() as connection:
            rows: list[asyncpg.Record] = await connection.fetch(query, *args)
            return rows

    async def fetchrow(self, query: str, *args: Any) -> asyncpg.Record | None:
        """Run a query and return the first row, or None."""
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        """Run a query and return the first column of the first row."""
        async with self.pool.acquire() as connection:
            return await connection.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> str:
        """Execute a statement and return its status tag."""
        async with self.pool.acquire() as connection:
            status_tag: str = await connection.execute(query, *args)
            return status_tag

    async def healthcheck(self) -> bool:
        """Return True if a trivial `select 1` succeeds."""
        try:
            return bool(await self.fetchval("select 1") == 1)
        except Exception:
            log.warning("database_healthcheck_failed", exc_info=True)
            return False


# Process-wide singleton, connected/disconnected by the app lifespan.
database = Database()
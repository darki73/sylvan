"""PostgreSQL backend — asyncpg + tsvector/GIN + pgvector."""

from sylvan.database.backends.postgres.backend import PostgresBackend
from sylvan.database.backends.postgres.dialect import PostgresDialect

__all__ = ["PostgresBackend", "PostgresDialect"]

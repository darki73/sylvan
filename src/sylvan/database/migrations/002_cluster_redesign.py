"""Migration 002: Cluster redesign.

Drops and recreates instances + coding_sessions tables with new schema.
Adds cluster_lock (single-row election) and cluster_nodes tables.
Preserves coding_sessions cumulative stats across the migration.
"""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Apply this migration.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)

    # Preserve coding session stats
    existing_sessions = await backend.fetch_all("SELECT * FROM coding_sessions")

    # Drop old tables (instances first due to FK)
    await schema.drop("instances")
    await schema.drop("coding_sessions")

    # Create cluster_lock (single-row, seeded with NULLs)
    await schema.create(
        "cluster_lock",
        lambda t: (
            t.text("holder_id").nullable(),
            t.integer("pid").nullable(),
            t.text("claimed_at").nullable(),
            t.text("heartbeat_at").nullable(),
        ),
    )
    await backend.execute("INSERT INTO cluster_lock VALUES (NULL, NULL, NULL, NULL)")

    # Recreate coding_sessions first (referenced by cluster_nodes and instances)
    await schema.create(
        "coding_sessions",
        lambda t: (
            t.text("id").primary_key(),
            t.text("started_at"),
            t.text("ended_at").nullable(),
            t.integer("total_tool_calls").default(0),
            t.integer("total_tokens_returned").default(0),
            t.integer("total_tokens_avoided").default(0),
            t.integer("total_efficiency_returned").default(0),
            t.integer("total_efficiency_equivalent").default(0),
            t.integer("total_symbols_retrieved").default(0),
            t.integer("total_sections_retrieved").default(0),
            t.integer("total_queries").default(0),
            t.integer("instances_spawned").default(0),
            t.text("category_data").default("{}").nullable(),
        ),
    )

    # Create cluster_nodes (references coding_sessions)
    await schema.create(
        "cluster_nodes",
        lambda t: (
            t.text("node_id").primary_key(),
            t.integer("pid"),
            t.text("role").default("follower"),
            t.integer("ws_port").nullable(),
            t.text("connected_at"),
            t.text("last_seen"),
            t.text("coding_session_id").references("coding_sessions", "id"),
        ),
    )

    # Recreate instances (stats-only, references cluster_nodes and coding_sessions)
    await schema.create(
        "instances",
        lambda t: (
            t.text("instance_id").primary_key(),
            t.text("node_id").references("cluster_nodes", "node_id"),
            t.text("coding_session_id").references("coding_sessions", "id"),
            t.text("started_at"),
            t.text("ended_at").nullable(),
            t.integer("tool_calls").default(0),
            t.integer("tokens_returned").default(0),
            t.integer("tokens_avoided").default(0),
            t.integer("efficiency_returned").default(0),
            t.integer("efficiency_equivalent").default(0),
            t.integer("symbols_retrieved").default(0),
            t.integer("sections_retrieved").default(0),
            t.integer("queries").default(0),
            t.integer("cache_hits").default(0),
            t.integer("cache_misses").default(0),
            t.text("category_data").default("{}").nullable(),
        ),
    )

    # Re-insert preserved coding session data
    for row in existing_sessions:
        r = dict(row)
        await backend.execute(
            "INSERT INTO coding_sessions "
            "(id, started_at, ended_at, total_tool_calls, total_tokens_returned, "
            "total_tokens_avoided, total_efficiency_returned, total_efficiency_equivalent, "
            "total_symbols_retrieved, total_sections_retrieved, total_queries, "
            "instances_spawned, category_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                r.get("id"),
                r.get("started_at"),
                r.get("ended_at"),
                r.get("total_tool_calls", 0),
                r.get("total_tokens_returned", 0),
                r.get("total_tokens_avoided", 0),
                r.get("total_efficiency_returned", 0),
                r.get("total_efficiency_equivalent", 0),
                r.get("total_symbols_retrieved", 0),
                r.get("total_sections_retrieved", 0),
                r.get("total_queries", 0),
                r.get("instances_spawned", 0),
                r.get("category_data", "{}"),
            ],
        )

    await backend.commit()


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Reverse this migration.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)

    # Preserve coding session stats
    existing_sessions = await backend.fetch_all("SELECT * FROM coding_sessions")

    # Drop new tables
    await schema.drop("instances")
    await schema.drop("cluster_nodes")
    await schema.drop("coding_sessions")
    await schema.drop("cluster_lock")

    # Recreate original coding_sessions (exact schema from 001)
    await schema.create(
        "coding_sessions",
        lambda t: (
            t.text("id").primary_key(),
            t.text("started_at"),
            t.text("ended_at").nullable(),
            t.integer("total_tool_calls").default(0),
            t.integer("total_tokens_returned").default(0),
            t.integer("total_tokens_avoided").default(0),
            t.integer("total_efficiency_returned").default(0),
            t.integer("total_efficiency_equivalent").default(0),
            t.integer("total_symbols_retrieved").default(0),
            t.integer("total_sections_retrieved").default(0),
            t.integer("total_queries").default(0),
            t.integer("instances_spawned").default(0),
            t.text("category_data").default("{}").nullable(),
        ),
    )

    # Recreate original instances (exact schema from 001)
    await schema.create(
        "instances",
        lambda t: (
            t.text("instance_id").primary_key(),
            t.text("coding_session_id").references("coding_sessions", "id"),
            t.integer("pid"),
            t.text("role").default("leader"),
            t.text("started_at"),
            t.text("ended_at").nullable(),
            t.text("last_heartbeat"),
            t.integer("tool_calls").default(0),
            t.integer("tokens_returned").default(0),
            t.integer("tokens_avoided").default(0),
            t.integer("efficiency_returned").default(0),
            t.integer("efficiency_equivalent").default(0),
            t.integer("symbols_retrieved").default(0),
            t.integer("sections_retrieved").default(0),
            t.integer("queries").default(0),
            t.integer("cache_hits").default(0),
            t.integer("cache_misses").default(0),
            t.text("category_data").default("{}").nullable(),
        ),
    )

    # Re-insert preserved coding session data
    for row in existing_sessions:
        r = dict(row)
        await backend.execute(
            "INSERT INTO coding_sessions "
            "(id, started_at, ended_at, total_tool_calls, total_tokens_returned, "
            "total_tokens_avoided, total_efficiency_returned, total_efficiency_equivalent, "
            "total_symbols_retrieved, total_sections_retrieved, total_queries, "
            "instances_spawned, category_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                r.get("id"),
                r.get("started_at"),
                r.get("ended_at"),
                r.get("total_tool_calls", 0),
                r.get("total_tokens_returned", 0),
                r.get("total_tokens_avoided", 0),
                r.get("total_efficiency_returned", 0),
                r.get("total_efficiency_equivalent", 0),
                r.get("total_symbols_retrieved", 0),
                r.get("total_sections_retrieved", 0),
                r.get("total_queries", 0),
                r.get("instances_spawned", 0),
                r.get("category_data", "{}"),
            ],
        )

    await backend.commit()

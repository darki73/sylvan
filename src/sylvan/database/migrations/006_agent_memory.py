"""Migration 006: Agent memory and preferences tables."""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Create memories, memories_vec, and preferences tables."""
    schema = Schema(backend)

    await schema.create(
        "memories",
        lambda t: (
            t.id(),
            t.foreign_id("repo_id"),
            t.text("content"),
            t.text("tags").nullable(),
            t.text("created_at").default("(datetime('now'))"),
            t.text("updated_at").default("(datetime('now'))"),
            t.index("repo_id"),
        ),
    )

    await schema.vec(
        "memories_vec",
        id_column="memory_id",
        id_type="INTEGER",
        distance_metric="cosine",
    )

    await schema.create(
        "preferences",
        lambda t: (
            t.id(),
            t.text("scope"),
            t.integer("scope_id").nullable(),
            t.text("key"),
            t.text("instruction"),
            t.text("created_at").default("(datetime('now'))"),
            t.text("updated_at").default("(datetime('now'))"),
            t.unique(["scope", "scope_id", "key"]),
            t.index("scope"),
        ),
    )

    await backend.commit()


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Drop agent memory tables."""
    schema = Schema(backend)
    await schema.drop("memories_vec")
    await schema.drop("preferences")
    await schema.drop("memories")
    await backend.commit()

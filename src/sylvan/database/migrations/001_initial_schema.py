"""Migration 001: Initial schema — all tables, indexes, FTS5, sqlite-vec."""

from sylvan.database.backends.base import Dialect, StorageBackend
from sylvan.database.builder import Schema


async def up(backend: StorageBackend, dialect: Dialect) -> None:
    """Create all tables, indexes, FTS5 virtual tables, and sqlite-vec tables.

    This migration is the single source of truth for sylvan's database schema.
    It produces the complete current schema in one step.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)

    await schema.create(
        "schema_version",
        lambda t: (
            t.integer("version").primary_key(),
            t.text("applied_at").default("(datetime('now'))"),
        ),
    )

    await schema.create(
        "repos",
        lambda t: (
            t.id(),
            t.text("name"),
            t.text("source_path").nullable().unique(),
            t.text("github_url").nullable(),
            t.text("indexed_at"),
            t.text("git_head").nullable(),
            t.text("repo_type").default("local").nullable(),
            t.text("package_manager").nullable(),
            t.text("package_name").nullable(),
            t.text("version").nullable(),
        ),
    )

    await schema.create(
        "files",
        lambda t: (
            t.id(),
            t.foreign_id("repo_id"),
            t.text("path"),
            t.text("language").nullable(),
            t.text("content_hash"),
            t.integer("byte_size"),
            t.real("mtime").nullable(),
            t.unique(["repo_id", "path"]),
            t.index("repo_id"),
            t.index("content_hash"),
        ),
    )

    await schema.create(
        "blobs",
        lambda t: (
            t.text("content_hash").primary_key(),
            t.blob("content"),
        ),
    )

    await schema.create(
        "symbols",
        lambda t: (
            t.id(),
            t.foreign_id("file_id", table="files"),
            t.text("symbol_id").unique(),
            t.text("name"),
            t.text("qualified_name"),
            t.text("kind"),
            t.text("language"),
            t.text("signature").nullable(),
            t.text("docstring").nullable(),
            t.text("summary").nullable(),
            t.text("decorators").nullable(),
            t.text("keywords").nullable(),
            t.text("parent_symbol_id").nullable(),
            t.integer("line_start").nullable(),
            t.integer("line_end").nullable(),
            t.integer("byte_offset"),
            t.integer("byte_length"),
            t.text("content_hash").nullable(),
            t.index("file_id"),
            t.index("kind"),
            t.index("name"),
            t.index("parent_symbol_id"),
        ),
    )

    await schema.create(
        "sections",
        lambda t: (
            t.id(),
            t.foreign_id("file_id", table="files"),
            t.text("section_id").unique(),
            t.text("title"),
            t.integer("level"),
            t.text("parent_section_id").nullable(),
            t.integer("byte_start"),
            t.integer("byte_end"),
            t.text("summary").nullable(),
            t.text("tags").nullable(),
            t.text("refs").nullable(),
            t.text("content_hash").nullable(),
            t.text("body_text").default("").nullable(),
            t.index("file_id"),
            t.index("level"),
        ),
    )

    await schema.create(
        "file_imports",
        lambda t: (
            t.id(),
            t.foreign_id("file_id", table="files"),
            t.text("specifier"),
            t.text("names").nullable(),
            t.integer("resolved_file_id").nullable(),
            t.index("file_id"),
            t.index("resolved_file_id"),
        ),
    )

    await schema.create(
        "usage_stats",
        lambda t: (
            t.foreign_id("repo_id"),
            t.text("date"),
            t.integer("sessions").default(0),
            t.integer("tool_calls").default(0),
            t.integer("tokens_returned").default(0),
            t.integer("tokens_avoided").default(0),
            t.integer("symbols_retrieved").default(0),
            t.integer("sections_retrieved").default(0),
            t.integer("tokens_returned_search").default(0),
            t.integer("tokens_equivalent_search").default(0),
            t.integer("tokens_returned_retrieval").default(0),
            t.integer("tokens_equivalent_retrieval").default(0),
            t.primary(["repo_id", "date"]),
        ),
    )

    await schema.create_quoted(
        "references",
        lambda t: (
            t.id(),
            t.text("source_symbol_id"),
            t.text("target_symbol_id").nullable(),
            t.text("target_specifier"),
            t.text("target_names").nullable(),
        ),
    )

    await schema.create_index_quoted("references", ["source_symbol_id"], name="idx_refs_source")
    await schema.create_index_quoted("references", ["target_symbol_id"], name="idx_refs_target")

    await schema.create(
        "quality",
        lambda t: (
            t.text("symbol_id").primary_key(),
            t.boolean("has_tests").default(False),
            t.boolean("has_docs").default(False),
            t.boolean("has_types").default(False),
            t.integer("complexity").default(0),
            t.integer("change_frequency").default(0),
            t.text("last_changed").nullable(),
        ),
    )

    await schema.create(
        "blame_cache",
        lambda t: (
            t.integer("file_id"),
            t.integer("line_start"),
            t.integer("line_end"),
            t.text("author").nullable(),
            t.text("commit_hash").nullable(),
            t.text("commit_date").nullable(),
            t.primary(["file_id", "line_start"]),
        ),
    )

    await schema.create(
        "workspaces",
        lambda t: (
            t.id(),
            t.text("name").unique(),
            t.text("created_at").default("(datetime('now'))"),
            t.text("description").nullable(),
        ),
    )

    await schema.create(
        "workspace_repos",
        lambda t: (
            t.foreign_id("workspace_id", table="workspaces"),
            t.foreign_id("repo_id"),
            t.primary(["workspace_id", "repo_id"]),
        ),
    )

    await schema.fts(
        "symbols_fts",
        columns=["symbol_id", "name", "qualified_name", "signature", "docstring", "summary", "keywords"],
        content_table="symbols",
    )

    await schema.fts(
        "sections_fts",
        columns=["section_id", "title", "summary", "tags", "body_text"],
        content_table="sections",
    )

    await schema.vec("symbols_vec", id_column="symbol_id")
    await schema.vec("sections_vec", id_column="section_id")

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


async def down(backend: StorageBackend, dialect: Dialect) -> None:
    """Drop all tables in reverse dependency order.

    Args:
        backend: The async storage backend.
        dialect: The SQL dialect for database-specific SQL generation.
    """
    schema = Schema(backend)

    await schema.drop_vec("sections_vec")
    await schema.drop_vec("symbols_vec")
    await schema.drop_fts("sections_fts", content_table="sections")
    await schema.drop_fts("symbols_fts", content_table="symbols")

    for table in [
        "instances",
        "coding_sessions",
        "workspace_repos",
        "workspaces",
        "usage_stats",
        "blame_cache",
        "quality",
        "file_imports",
        "sections",
        "symbols",
        "blobs",
        "files",
        "repos",
        "schema_version",
    ]:
        await schema.drop(table)

    await schema.drop_quoted("references")

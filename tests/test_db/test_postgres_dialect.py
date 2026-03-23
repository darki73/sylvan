"""Tests for sylvan.database.backends.postgres.dialect — pure SQL generation."""

from __future__ import annotations

from sylvan.database.backends.postgres.dialect import PostgresDialect


class TestPlaceholder:
    """Tests for placeholder generation."""

    def test_placeholder_property(self):
        """The placeholder property returns '$'."""
        d = PostgresDialect()
        assert d.placeholder == "$"

    def test_placeholder_for_zero(self):
        """Zero-based index produces $1."""
        d = PostgresDialect()
        assert d.placeholder_for(0) == "$1"

    def test_placeholder_for_indices(self):
        """Various indices produce correct numbered placeholders."""
        d = PostgresDialect()
        assert d.placeholder_for(0) == "$1"
        assert d.placeholder_for(1) == "$2"
        assert d.placeholder_for(4) == "$5"
        assert d.placeholder_for(99) == "$100"

    def test_placeholders_single(self):
        """Generating 1 placeholder."""
        d = PostgresDialect()
        assert d.placeholders(1) == "$1"

    def test_placeholders_multiple(self):
        """Generating multiple placeholders."""
        d = PostgresDialect()
        assert d.placeholders(3) == "$1, $2, $3"
        assert d.placeholders(5) == "$1, $2, $3, $4, $5"


class TestBuildUpsert:
    """Tests for PostgreSQL upsert SQL generation."""

    def test_upsert_with_update(self):
        """Generates INSERT ... ON CONFLICT ... DO UPDATE."""
        d = PostgresDialect()
        sql = d.build_upsert(
            table="repos",
            columns=["id", "name", "path"],
            conflict_columns=["id"],
            update_columns=["name", "path"],
        )
        assert "INSERT INTO repos" in sql
        assert "VALUES ($1, $2, $3)" in sql
        assert "ON CONFLICT (id)" in sql
        assert "DO UPDATE SET" in sql
        assert "name=EXCLUDED.name" in sql
        assert "path=EXCLUDED.path" in sql

    def test_upsert_without_update(self):
        """Generates INSERT ... ON CONFLICT ... DO NOTHING when no update cols."""
        d = PostgresDialect()
        sql = d.build_upsert(
            table="repos",
            columns=["id", "name"],
            conflict_columns=["id"],
            update_columns=[],
        )
        assert "DO NOTHING" in sql
        assert "DO UPDATE" not in sql

    def test_upsert_multi_conflict(self):
        """Handles composite conflict keys."""
        d = PostgresDialect()
        sql = d.build_upsert(
            table="symbols",
            columns=["file_id", "name", "kind"],
            conflict_columns=["file_id", "name"],
            update_columns=["kind"],
        )
        assert "ON CONFLICT (file_id, name)" in sql


class TestBuildInsertOrIgnore:
    """Tests for INSERT ... ON CONFLICT DO NOTHING."""

    def test_basic_insert_or_ignore(self):
        """Generates correct INSERT ... ON CONFLICT DO NOTHING SQL."""
        d = PostgresDialect()
        sql = d.build_insert_or_ignore("repos", ["id", "name", "path"])
        assert "INSERT INTO repos (id, name, path)" in sql
        assert "VALUES ($1, $2, $3)" in sql
        assert "ON CONFLICT DO NOTHING" in sql

    def test_single_column(self):
        """Handles single-column insert."""
        d = PostgresDialect()
        sql = d.build_insert_or_ignore("tags", ["name"])
        assert "VALUES ($1)" in sql


class TestBuildFtsSearch:
    """Tests for PostgreSQL full-text search SQL generation."""

    def test_fts_search_sql(self):
        """Generates tsvector/tsquery-based FTS SQL."""
        d = PostgresDialect()
        sql, params = d.build_fts_search(
            table="symbols",
            fts_table="symbols_fts",  # Ignored for Postgres
            query="hello world",
            select_columns=["id", "name", "kind"],
        )
        assert "ts_rank" in sql
        assert "to_tsquery" in sql
        assert "search_vector" in sql
        assert "ORDER BY _rank DESC" in sql
        # Query terms are joined with &
        assert params == ["hello & world"]

    def test_fts_search_single_term(self):
        """Single-term query produces correct tsquery."""
        d = PostgresDialect()
        _, params = d.build_fts_search(
            table="symbols",
            fts_table="symbols_fts",
            query="function",
            select_columns=["id"],
        )
        assert params == ["function"]

    def test_fts_search_selects_correct_columns(self):
        """Selected columns are qualified with the table name."""
        d = PostgresDialect()
        sql, _ = d.build_fts_search(
            table="symbols",
            fts_table="symbols_fts",
            query="test",
            select_columns=["id", "name"],
        )
        assert "symbols.id" in sql
        assert "symbols.name" in sql


class TestBuildVectorSearch:
    """Tests for pgvector similarity search SQL generation."""

    def test_vector_search_sql(self):
        """Generates pgvector distance-based search SQL."""
        d = PostgresDialect()
        sql, params = d.build_vector_search(
            table="symbols",
            vec_table="symbol_embeddings",
            vec_column="symbol_id",
            vector=[0.1, 0.2, 0.3],
            k=10,
            select_columns=["id", "name"],
        )
        assert "embedding <-> $1::vector" in sql
        assert "LIMIT $2" in sql
        assert "JOIN symbols ON symbols.symbol_id = symbol_embeddings.symbol_id" in sql
        assert params[0] == "[0.1,0.2,0.3]"
        assert params[1] == 10

    def test_vector_search_k_value(self):
        """k parameter is correctly passed as LIMIT."""
        d = PostgresDialect()
        _, params = d.build_vector_search(
            table="symbols",
            vec_table="embeddings",
            vec_column="id",
            vector=[1.0, 2.0],
            k=5,
            select_columns=["id"],
        )
        assert params[1] == 5


class TestDialectName:
    """Tests for dialect metadata."""

    def test_name_is_postgres(self):
        """Dialect name is 'postgres'."""
        d = PostgresDialect()
        assert d.name == "postgres"

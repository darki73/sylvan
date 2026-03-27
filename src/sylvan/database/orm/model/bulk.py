"""Class-level CRUD and bulk write operations.

Model inherits from _BulkMixin, so all classmethods remain available
on Model itself.  All methods here hit the database and are async.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.database.orm.exceptions import QueryError
from sylvan.database.orm.query.builder import QueryBuilder

if TYPE_CHECKING:
    from sylvan.database.orm.model.base import Model

from sylvan.database.orm.model.persistence import _translate_sql


class _BulkMixin:
    """Class-level CRUD and bulk write operations.

    Mixed into Model to keep finders.py focused on query construction.
    """

    @classmethod
    async def create(cls, **kwargs: Any) -> Model:
        """Insert a new record and return the instance.

        Args:
            **kwargs: Field values for the new record.

        Returns:
            The persisted model instance with its primary key set.
        """
        instance = cls(**kwargs)
        await instance.save()
        return instance

    @classmethod
    async def first_or_create(cls, search_by: dict, **defaults: Any) -> Model:
        """Find the first matching record, or create one if not found.

        Args:
            search_by: Dict of column=value conditions to search for.
            **defaults: Additional field values used only when creating.

        Returns:
            The found or newly created model instance.
        """
        instance = await cls.where(search_by).first()
        if instance is not None:
            return instance
        return await cls.create(**search_by, **defaults)

    @classmethod
    async def update_or_create(cls, search_by: dict, **values: Any) -> Model:
        """Find and update, or create if not found.

        Args:
            search_by: Dict of column=value conditions to search for.
            **values: Field values to update (or use for creation).

        Returns:
            The updated or newly created model instance.
        """
        instance = await cls.where(search_by).first()
        if instance is not None:
            await instance.update(**values)
            return instance
        return await cls.create(**search_by, **values)

    @classmethod
    async def upsert(cls, conflict_columns: list[str], update_columns: list[str] | None = None, **kwargs: Any) -> Model:
        """INSERT or UPDATE on conflict (ON CONFLICT DO UPDATE).

        Uses SQLite's ON CONFLICT clause. After execution, fetches the actual PK
        by querying the conflict columns rather than trusting cursor.lastrowid.

        Args:
            conflict_columns: Columns forming the uniqueness constraint.
            update_columns: Columns to update on conflict; defaults to all non-conflict columns.
            **kwargs: Field values for the record.

        Returns:
            The upserted model instance with its primary key set.

        Raises:
            QueryError: If a conflict column is not a valid field.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()

        fields = cls._get_fields()
        valid_db_cols = {f.db_name for f in fields.values()}
        valid_attr_cols = set(fields.keys())
        valid_cols = valid_db_cols | valid_attr_cols
        for col in conflict_columns:
            if col not in valid_cols:
                raise QueryError(f"Invalid conflict column: {col!r}")

        prep = cls._prepare_insert_data(**kwargs)
        cols, vals, placeholders = prep.cols, prep.vals, prep.placeholders

        conflict_str = ", ".join(conflict_columns)
        if update_columns is None:
            update_columns = [c for c in cols if c not in conflict_columns]

        if update_columns:
            update_str = ", ".join(f"{c}=excluded.{c}" for c in update_columns)
            sql = (
                f"INSERT INTO {cls.__table__} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict_str}) DO UPDATE SET {update_str}"
            )
        else:
            sql = (
                f"INSERT INTO {cls.__table__} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT({conflict_str}) DO NOTHING"
            )

        await backend.execute(_translate_sql(backend, sql), vals)

        fields = cls._get_fields()
        pk_field = fields.get(cls._pk_column)
        if pk_field and pk_field.primary_key:
            where_parts = [f"{c} = ?" for c in conflict_columns]
            where_vals = [prep.data[c] for c in conflict_columns]
            pk_sql = f"SELECT {pk_field.db_name} FROM {cls.__table__} WHERE {' AND '.join(where_parts)}"
            row = await backend.fetch_one(
                _translate_sql(backend, pk_sql),
                where_vals,
            )
            if row:
                object.__setattr__(prep.instance, cls._pk_column, next(iter(row.values())))

        prep.instance._persisted = True
        return prep.instance

    @classmethod
    async def insert_or_ignore(cls, **kwargs: Any) -> Model:
        """INSERT OR IGNORE -- skip if row already exists.

        Args:
            **kwargs: Field values for the new record.

        Returns:
            The model instance (may not be persisted if ignored).
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        prep = cls._prepare_insert_data(**kwargs)

        sql = f"INSERT OR IGNORE INTO {cls.__table__} ({', '.join(prep.cols)}) VALUES ({prep.placeholders})"
        row_id = await backend.execute_returning_id(_translate_sql(backend, sql), prep.vals)

        if row_id:
            fields = cls._get_fields()
            pk_field = fields.get(cls._pk_column)
            if pk_field and pk_field.primary_key:
                object.__setattr__(prep.instance, cls._pk_column, row_id)
            prep.instance._persisted = True

        return prep.instance

    @classmethod
    async def insert_or_replace(cls, **kwargs: Any) -> Model:
        """INSERT OR REPLACE -- replace if row exists.

        Args:
            **kwargs: Field values for the record.

        Returns:
            The persisted model instance.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        prep = cls._prepare_insert_data(**kwargs)

        sql = f"INSERT OR REPLACE INTO {cls.__table__} ({', '.join(prep.cols)}) VALUES ({prep.placeholders})"
        row_id = await backend.execute_returning_id(_translate_sql(backend, sql), prep.vals)

        fields = cls._get_fields()
        pk_field = fields.get(cls._pk_column)
        if pk_field and pk_field.primary_key and row_id:
            object.__setattr__(prep.instance, cls._pk_column, row_id)
        prep.instance._persisted = True
        return prep.instance

    @classmethod
    async def raw(cls, sql: str, params: list | None = None) -> list[Model]:
        """Execute raw SQL and return model instances.

        Args:
            sql: Raw SQL SELECT statement.
            params: Optional list of query parameters.

        Returns:
            List of model instances created from the result rows.
        """
        return await QueryBuilder.raw(cls, sql, params)

    @classmethod
    async def bulk_create(cls, records: list[dict]) -> int:
        """Insert multiple records in batches.

        Respects SQLite's 999-parameter limit by automatically splitting
        into multiple INSERT statements when necessary.

        Args:
            records: List of dicts mapping column names to values.

        Returns:
            Total number of records inserted.
        """
        if not records:
            return 0

        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        fields = cls._get_fields()
        pk_field = fields.get(cls._pk_column)

        first = cls(**records[0])
        data = first._to_dict()
        if pk_field and pk_field.primary_key and data.get(pk_field.db_name) is None:
            data = {k: v for k, v in data.items() if k != pk_field.db_name}
        cols = list(data.keys())
        row_placeholder = "(" + ", ".join("?" for _ in cols) + ")"
        batch_size = max(1, 999 // len(cols)) if cols else len(records)

        total = 0
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            all_values: list = []
            value_rows: list[str] = []
            for record in batch:
                instance = cls(**record)
                row_data = instance._to_dict()
                if pk_field and pk_field.primary_key and row_data.get(pk_field.db_name) is None:
                    row_data = {k: v for k, v in row_data.items() if k != pk_field.db_name}
                all_values.extend(row_data.get(col) for col in cols)
                value_rows.append(row_placeholder)

            sql = f"INSERT INTO {cls.__table__} ({', '.join(cols)}) VALUES {', '.join(value_rows)}"
            total += await backend.execute(_translate_sql(backend, sql), all_values)

        return total

    @classmethod
    async def bulk_upsert(
        cls,
        records: list[dict],
        conflict_columns: list[str],
        update_columns: list[str] | None = None,
    ) -> int:
        """Upsert multiple records in a single SQL statement.

        Args:
            records: List of dicts mapping column names to values.
            conflict_columns: Columns that trigger the conflict.
            update_columns: Columns to update on conflict (None = all non-conflict).

        Returns:
            Number of records processed.
        """
        if not records:
            return 0

        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        fields = cls._get_fields()
        pk_field = fields.get(cls._pk_column)

        first = cls(**records[0])
        data = first._to_dict()
        if pk_field and pk_field.primary_key and data.get(pk_field.db_name) is None:
            data = {k: v for k, v in data.items() if k != pk_field.db_name}
        cols = list(data.keys())
        row_placeholder = "(" + ", ".join("?" for _ in cols) + ")"
        conflict_str = ", ".join(conflict_columns)

        if update_columns is None:
            update_columns = [c for c in cols if c not in conflict_columns]

        if update_columns:
            update_str = ", ".join(f"{c}=excluded.{c}" for c in update_columns)
            suffix = f"ON CONFLICT({conflict_str}) DO UPDATE SET {update_str}"
        else:
            suffix = f"ON CONFLICT({conflict_str}) DO NOTHING"

        batch_size = max(1, 999 // len(cols))
        total = 0

        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            all_values: list = []
            value_rows: list[str] = []
            for record in batch:
                instance = cls(**record)
                row_data = instance._to_dict()
                if pk_field and pk_field.primary_key and row_data.get(pk_field.db_name) is None:
                    row_data = {k: v for k, v in row_data.items() if k != pk_field.db_name}
                all_values.extend(row_data.get(col) for col in cols)
                value_rows.append(row_placeholder)

            sql = f"INSERT INTO {cls.__table__} ({', '.join(cols)}) VALUES {', '.join(value_rows)} {suffix}"
            total += await backend.execute(_translate_sql(backend, sql), all_values)

        return total

"""Instance-level async CRUD operations (save, update, delete).

Model inherits from both _CrudMixin and _QueryMixin so that instances
gain save/update/delete while the class gains query shortcuts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sylvan.database.orm.exceptions import QueryError

if TYPE_CHECKING:
    from sylvan.database.orm.model.base import Model


def _translate_sql(backend: Any, sql: str) -> str:
    """Replace '?' placeholders with dialect-specific ones.

    Args:
        backend: The storage backend with a dialect attribute.
        sql: SQL string with '?' placeholders.

    Returns:
        SQL with dialect-appropriate placeholders.
    """
    dialect = backend.dialect
    if dialect.placeholder == "?":
        return sql
    parts = sql.split("?")
    if len(parts) == 1:
        return sql
    result = parts[0]
    for i, part in enumerate(parts[1:]):
        result += dialect.placeholder_for(i) + part
    return result


class _CrudMixin:
    """Instance-level async save / update / delete, mixed into Model."""

    async def save(self) -> Model:
        """INSERT or UPDATE this instance depending on persistence state.

        On UPDATE, only writes columns that have changed (dirty tracking).
        Snapshots the original state after a successful persist.

        Returns:
            This instance after persisting.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        fields = self._get_fields()
        data = self._to_dict()

        if self._persisted:
            await self._save_update(backend, fields, data)
        else:
            await self._save_insert(backend, fields, data)

        self._snapshot_original()
        return self

    async def _save_update(self, backend: Any, fields: dict, data: dict) -> None:
        """Handle the UPDATE branch of save().

        Only writes columns that have changed since loading. Skips the
        UPDATE entirely if nothing is dirty.

        Args:
            backend: The active storage backend.
            fields: Field descriptors for this model.
            data: Serialized column-to-value mapping.
        """
        pk_field = fields.get(self._pk_column)
        pk_db = pk_field.db_name if pk_field else self._pk_column
        pk_val = data.pop(pk_db, None)
        if pk_val is None:
            raise QueryError("Cannot update: no primary key value")

        if self._original:
            dirty = self.get_dirty()
            if not dirty:
                return
            dirty_data = {}
            for attr_name in dirty:
                field = fields.get(attr_name)
                if field:
                    dirty_data[field.db_name] = field.to_db(getattr(self, attr_name, None))
            if not dirty_data:
                return
            data = dirty_data

        set_parts = [f"{col} = ?" for col in data]
        params = [*data.values(), pk_val]
        sql = f"UPDATE {self.__table__} SET {', '.join(set_parts)} WHERE {pk_db} = ?"
        await backend.execute(
            _translate_sql(backend, sql),
            params,
        )

    async def _save_insert(self, backend: Any, fields: dict, data: dict) -> None:
        """Handle the INSERT branch of save().

        Args:
            backend: The active storage backend.
            fields: Field descriptors for this model.
            data: Serialized column-to-value mapping.
        """
        pk_field = fields.get(self._pk_column)
        if pk_field and pk_field.primary_key and data.get(pk_field.db_name) is None:
            data = {k: v for k, v in data.items() if k != pk_field.db_name}
        cols = list(data.keys())
        vals = list(data.values())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO {self.__table__} ({', '.join(cols)}) VALUES ({placeholders})"
        row_id = await backend.execute_returning_id(
            _translate_sql(backend, sql),
            vals,
        )
        current_pk = getattr(self, self._pk_column, None)
        if pk_field and pk_field.primary_key and row_id is not None and current_pk is None:
            object.__setattr__(self, self._pk_column, row_id)
        self._persisted = True

    async def update(self, **kwargs: Any) -> Model:
        """Update specific fields on this instance and persist to the database.

        Executes the UPDATE query first, then sets attributes on success.

        Args:
            **kwargs: Field name to new value mappings.

        Returns:
            This instance with the updated fields.
        """
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        fields = self._get_fields()

        pk_field = fields.get(self._pk_column)
        pk_db = pk_field.db_name if pk_field else self._pk_column
        pk_val = getattr(self, self._pk_column)

        set_parts: list[str] = []
        params: list[Any] = []
        for k, v in kwargs.items():
            field = fields.get(k)
            set_parts.append(f"{(field.db_name if field else k)} = ?")
            params.append(field.to_db(v) if field else v)

        params.append(pk_val)
        sql = f"UPDATE {self.__table__} SET {', '.join(set_parts)} WHERE {pk_db} = ?"
        await backend.execute(_translate_sql(backend, sql), params)

        for k, v in kwargs.items():
            object.__setattr__(self, k, v)
        return self

    async def delete(self) -> None:
        """Delete this instance and cascade to relations with on_delete set.

        Walks all relation descriptors on the model class. For HasMany/HasOne
        with ``on_delete="cascade"``, deletes all children (recursively).
        For BelongsToMany with ``on_delete="detach"``, removes pivot rows.
        """
        await self._cascade_relations()

        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        fields = self._get_fields()
        pk_field = fields.get(self._pk_column)
        pk_db = pk_field.db_name if pk_field else self._pk_column
        pk_val = getattr(self, self._pk_column)
        sql = f"DELETE FROM {self.__table__} WHERE {pk_db} = ?"
        await backend.execute(_translate_sql(backend, sql), [pk_val])
        self._persisted = False

        try:
            from sylvan.context import get_context

            ctx = get_context()
            if ctx.identity_map is not None:
                ctx.identity_map.remove(type(self), pk_val)
        except Exception:  # noqa: S110 -- identity map cleanup is best-effort
            pass

    async def _cascade_relations(self) -> None:
        """Process on_delete for all relation descriptors on this model."""
        from sylvan.database.orm.primitives.relations import BelongsToMany, HasMany, HasOne

        for attr_name in dir(type(self)):
            rel = getattr(type(self), attr_name, None)
            if rel is None or not hasattr(rel, "on_delete") or rel.on_delete is None:
                continue

            if isinstance(rel, BelongsToMany) and rel.on_delete == "detach":
                await self.detach(attr_name)

            elif isinstance(rel, (HasMany, HasOne)) and rel.on_delete == "cascade":
                related_model = rel.related_model
                local_value = getattr(self, rel.local_key)

                if _has_cascade_children(related_model):
                    children = await related_model.where(**{rel.foreign_key: local_value}).get()
                    for child in children:
                        await child.delete()
                else:
                    await related_model.where(**{rel.foreign_key: local_value}).delete()


def _has_cascade_children(model_class: type) -> bool:
    """Check if a model has any relations with on_delete set.

    If it does, its children need individual delete() calls to trigger
    their own cascades. If not, a bulk delete is safe and faster.

    Args:
        model_class: The ORM model class to inspect.

    Returns:
        True if the model has cascading relations.
    """
    from sylvan.database.orm.primitives.relations import RelationDescriptor

    for attr_name in dir(model_class):
        rel = getattr(model_class, attr_name, None)
        if isinstance(rel, RelationDescriptor) and getattr(rel, "on_delete", None):
            return True
    return False

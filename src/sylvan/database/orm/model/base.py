"""Base Model class -- Active Record with metaclass magic.

Instance construction and identity are synchronous.  Database operations
(save, refresh, find) are async.
"""

from dataclasses import dataclass
from typing import Any

from sylvan.database.orm.exceptions import ModelNotFoundError
from sylvan.database.orm.model.bulk import _BulkMixin
from sylvan.database.orm.model.finders import _QueryMixin
from sylvan.database.orm.model.metaclass import ModelMeta
from sylvan.database.orm.model.persistence import _CrudMixin
from sylvan.database.orm.primitives.fields import Column
from sylvan.database.orm.primitives.relations import RelationDescriptor


@dataclass(slots=True, frozen=True)
class _InsertData:
    """Holds the prepared column/value/placeholder tuple for INSERT statements.

    Attributes:
        instance: The model instance being inserted.
        cols: Column names for the INSERT.
        vals: Parameter values for the INSERT.
        placeholders: Comma-separated '?' placeholders string.
        data: Full column-to-value mapping.
    """

    instance: Any
    cols: list[str]
    vals: list[Any]
    placeholders: str
    data: dict[str, Any]


class Model(_CrudMixin, _QueryMixin, _BulkMixin, metaclass=ModelMeta):
    """Base Active Record model.

    Subclass this and declare Column/JsonColumn fields and relations::

        class Symbol(Model):
            __table__ = "symbols"
            id = AutoPrimaryKey()
            name = Column(str)
            kind = Column(str)
            decorators = JsonColumn(list)
            file = BelongsTo(FileRecord, foreign_key="file_id")

    Filter methods (where, query, all, search, etc.) are synchronous and
    return QueryBuilder instances.  Terminal methods (get, first, find,
    count, save, delete, etc.) are async and must be awaited.

    Attributes:
        __table__: Database table name. Auto-derived from class name if not set.
        __fts_table__: FTS5 virtual table name for full-text search.
        __fts_weights__: BM25 weight string for FTS5 ranking columns.
        __vec_table__: sqlite-vec virtual table name for vector similarity search.
        __vec_column__: Column name used to join with the vector table.
    """

    __table__: str = None  # type: ignore
    __fts_table__: str | None = None
    __fts_weights__: str | None = None
    __vec_table__: str | None = None
    __vec_column__: str | None = None

    _fields_cache: dict[str, Column] = {}
    """Collected Column descriptors, populated by ModelMeta."""

    _relations_cache: dict[str, RelationDescriptor] = {}
    """Collected RelationDescriptor instances, populated by ModelMeta."""

    _pk_column: str = "id"
    """Primary key attribute name."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize a model instance from keyword arguments.

        Args:
            **kwargs: Field values keyed by attribute name or database column name.
        """
        fields = self._get_fields()
        for attr_name, field in fields.items():
            value = kwargs.get(attr_name, kwargs.get(field.db_name))
            if value is not None:
                value = field.from_db(value) if isinstance(value, (str, int, float, bytes, bool)) or value is None else value
            elif field.default is not None:
                value = field.default
            object.__setattr__(self, attr_name, value)

        for k, v in kwargs.items():
            if k not in fields and not k.startswith("_rel_"):
                object.__setattr__(self, k, v)

        self._persisted = kwargs.get("_persisted", False)

    @classmethod
    def _get_fields(cls) -> dict[str, Column]:
        """Return the cached field descriptors for this model class."""
        return cls._fields_cache

    @classmethod
    def _from_row(cls, row: dict) -> "Model":
        """Create an instance from a database row dict.

        Checks the identity map first -- if this (class, pk) was already
        loaded in this request, returns the existing instance.

        Args:
            row: A dict mapping column names to values.

        Returns:
            A model instance populated from the row, reusing a cached
            instance from the identity map when available.
        """
        from sylvan.context import get_context

        identity_map = None
        try:
            ctx = get_context()
            identity_map = ctx.identity_map
        except Exception:  # noqa: S110 -- identity map is optional optimization
            pass

        if identity_map is not None:
            pk_field = cls._fields_cache.get(cls._pk_column)
            pk_db = pk_field.db_name if pk_field else cls._pk_column
            pk_val = row.get(pk_db) or row.get(cls._pk_column)
            if pk_val is not None:
                existing = identity_map.get(cls, pk_val)
                if existing is not None:
                    return existing

        fields = cls._get_fields()
        kwargs: dict[str, Any] = {}
        for attr_name, field in fields.items():
            db_name = field.db_name
            if db_name in row:
                kwargs[attr_name] = field.from_db(row[db_name])
            elif attr_name in row:
                kwargs[attr_name] = field.from_db(row[attr_name])

        for k, v in row.items():
            if k not in kwargs and k not in fields:
                kwargs[k] = v

        kwargs["_persisted"] = True
        instance = cls.__new__(cls)
        Model.__init__(instance, **kwargs)

        if identity_map is not None:
            pk_val = getattr(instance, cls._pk_column, None)
            identity_map.put(cls, pk_val, instance)

        return instance

    def _to_dict(self) -> dict[str, Any]:
        """Convert to dict of {db_column: db_value}.

        Returns:
            A dict mapping database column names to serialized values.
        """
        fields = self._get_fields()
        return {field.db_name: field.to_db(getattr(self, attr_name, None))
                for attr_name, field in fields.items()}

    @classmethod
    def _prepare_insert_data(cls, **kwargs: Any) -> _InsertData:
        """Build instance and column/value/placeholder tuple, filtering out None PKs.

        Centralises the repeated pattern of: construct instance, serialise to dict,
        strip auto-increment PK when None, and split into parallel col/val lists.

        Args:
            **kwargs: Field values for the new instance.

        Returns:
            An _InsertData holding the prepared INSERT components.
        """
        fields = cls._get_fields()
        instance = cls(**kwargs)
        data = instance._to_dict()

        pk_field = fields.get(cls._pk_column)
        if pk_field and pk_field.primary_key and data.get(pk_field.db_name) is None:
            data = {k: v for k, v in data.items() if k != pk_field.db_name}

        cols = list(data.keys())
        vals = list(data.values())
        placeholders = ", ".join("?" for _ in cols)

        return _InsertData(instance, cols, vals, placeholders, data)

    async def load(self, *relation_names: str) -> "Model":
        """Explicitly load one or more relations asynchronously.

        Since Python descriptors cannot be async, this method provides the
        async path for loading relations that are not yet cached.

        Args:
            *relation_names: Names of relations to load.

        Returns:
            This instance with the requested relations populated.
        """
        from sylvan.database.orm.primitives.relations import BelongsTo, BelongsToMany, HasMany, HasOne
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()

        for rel_name in relation_names:
            cache_key = f"_rel_{rel_name}"
            if getattr(self, cache_key, None) is not None:
                continue

            rel_desc = None
            for cls in type(self).__mro__:
                if rel_name in cls.__dict__:
                    attr = cls.__dict__[rel_name]
                    if isinstance(attr, (BelongsTo, HasMany, HasOne, BelongsToMany)):
                        rel_desc = attr
                        break

            if rel_desc is None:
                continue

            if isinstance(rel_desc, BelongsTo):
                fk_value = getattr(self, rel_desc.foreign_key, None)
                if fk_value is None:
                    object.__setattr__(self, cache_key, None)
                    continue
                related = rel_desc.related_model
                result = await related.where(**{rel_desc.local_key: fk_value}).first()
                object.__setattr__(self, cache_key, result)

            elif isinstance(rel_desc, HasMany):
                local_value = getattr(self, rel_desc.local_key, None)
                if local_value is None:
                    object.__setattr__(self, cache_key, [])
                    continue
                related = rel_desc.related_model
                result = await related.where(**{rel_desc.foreign_key: local_value}).get()
                object.__setattr__(self, cache_key, result)

            elif isinstance(rel_desc, HasOne):
                local_value = getattr(self, rel_desc.local_key, None)
                if local_value is None:
                    object.__setattr__(self, cache_key, None)
                    continue
                related = rel_desc.related_model
                result = await related.where(**{rel_desc.foreign_key: local_value}).first()
                object.__setattr__(self, cache_key, result)

            elif isinstance(rel_desc, BelongsToMany):
                local_value = getattr(self, rel_desc.local_key, None)
                if local_value is None:
                    object.__setattr__(self, cache_key, [])
                    continue
                rows = await backend.fetch_all(
                    f"SELECT {rel_desc.related_key} FROM {rel_desc.pivot_table} "
                    f"WHERE {rel_desc.foreign_key} = ?",
                    [local_value],
                )
                if not rows:
                    object.__setattr__(self, cache_key, [])
                    continue
                related_ids = [next(iter(r.values())) for r in rows]
                related = rel_desc.related_model
                result = await related.where_in(related._pk_column, related_ids).get()
                object.__setattr__(self, cache_key, result)

        return self

    async def refresh(self) -> "Model":
        """Re-fetch this instance from the database.

        Returns:
            This instance, updated with fresh database values.

        Raises:
            ModelNotFoundError: If the record no longer exists.
        """
        pk_val = getattr(self, self._pk_column)
        fresh = await self.__class__.find(pk_val)
        if fresh is None:
            raise ModelNotFoundError(f"{self.__class__.__name__} no longer exists: {pk_val}")
        for attr_name in self._get_fields():
            object.__setattr__(self, attr_name, getattr(fresh, attr_name))
        return self

    async def fresh(self) -> "Model":
        """Alias for refresh() -- re-fetch from database.

        Returns:
            This instance, updated with fresh database values.
        """
        return await self.refresh()

    def replicate(self, **overrides: Any) -> "Model":
        """Clone this instance without the primary key (ready to save as new).

        Args:
            **overrides: Field values to override on the clone.

        Returns:
            A new unsaved model instance with the same field values.
        """
        fields = self._get_fields()
        kwargs: dict[str, Any] = {
            attr_name: getattr(self, attr_name, None)
            for attr_name, field in fields.items()
            if not field.primary_key
        }
        kwargs.update(overrides)
        return self.__class__(**kwargs)

    def __eq__(self, other: object) -> bool:
        """Compare by primary key if both instances are persisted.

        Args:
            other: The object to compare against.

        Returns:
            True if both are the same class with equal primary keys, NotImplemented otherwise.
        """
        if not isinstance(other, self.__class__):
            return NotImplemented
        pk_self = getattr(self, self._pk_column, None)
        pk_other = getattr(other, other._pk_column, None)
        if pk_self is None or pk_other is None:
            return self is other
        return pk_self == pk_other

    def __hash__(self) -> int:
        """Hash by class name and primary key, falling back to object identity."""
        pk = getattr(self, self._pk_column, None)
        if pk is None:
            return id(self)
        return hash((self.__class__.__name__, pk))

    def __repr__(self) -> str:
        """Show class name and primary key value."""
        pk = getattr(self, self._pk_column, None)
        return f"<{self.__class__.__name__} {self._pk_column}={pk}>"

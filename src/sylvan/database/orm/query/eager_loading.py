"""Eager loading mixin for QueryBuilder.

Prevents N+1 queries by batch-loading relations and relation counts.
All methods are async and use the storage backend from context.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class QueryEagerMixin:
    """Mixin providing async eager loading for QueryBuilder."""

    self: QueryBuilder

    async def _load_eager(self, instances: list) -> None:
        """Batch-load relations for a list of instances to prevent N+1 queries.

        Args:
            instances: List of model instances to load relations for.
        """
        if not instances:
            return

        for rel_name in self._eager_loads:
            rel_desc = getattr(type(instances[0]), rel_name, None)
            if rel_desc is None:
                continue

            from sylvan.database.orm.primitives.relations import BelongsTo, HasMany, HasOne

            if isinstance(rel_desc, BelongsTo):
                await self._eager_load_belongs_to(instances, rel_name, rel_desc)
            elif isinstance(rel_desc, (HasMany, HasOne)):
                await self._eager_load_has(instances, rel_name, rel_desc)

    async def _eager_load_belongs_to(self, instances: list, rel_name: str, rel_desc: Any) -> None:
        """Eager-load a BelongsTo relation for all instances.

        Args:
            instances: List of model instances.
            rel_name: Name of the relation being loaded.
            rel_desc: The BelongsTo descriptor.
        """
        fk_values = [
            getattr(inst, rel_desc.foreign_key) for inst in instances if getattr(inst, rel_desc.foreign_key) is not None
        ]
        if not fk_values:
            return
        related = rel_desc.related_model
        related_instances = await related.where_in(rel_desc.local_key, fk_values).get()
        lookup = {getattr(r, rel_desc.local_key): r for r in related_instances}
        for inst in instances:
            fk = getattr(inst, rel_desc.foreign_key)
            object.__setattr__(inst, f"_rel_{rel_name}", lookup.get(fk))

    async def _eager_load_has(self, instances: list, rel_name: str, rel_desc: Any) -> None:
        """Eager-load a HasMany or HasOne relation for all instances.

        Args:
            instances: List of model instances.
            rel_name: Name of the relation being loaded.
            rel_desc: The HasMany or HasOne descriptor.
        """
        from sylvan.database.orm.primitives.relations import HasMany

        local_values = [
            getattr(inst, rel_desc.local_key) for inst in instances if getattr(inst, rel_desc.local_key) is not None
        ]
        if not local_values:
            return

        related = rel_desc.related_model
        related_instances = await related.where_in(rel_desc.foreign_key, local_values).get()

        if isinstance(rel_desc, HasMany):
            lookup_many: dict[Any, list] = {}
            for r in related_instances:
                key = getattr(r, rel_desc.foreign_key)
                lookup_many.setdefault(key, []).append(r)
            for inst in instances:
                lv = getattr(inst, rel_desc.local_key)
                object.__setattr__(inst, f"_rel_{rel_name}", lookup_many.get(lv, []))
        else:
            lookup_one = {getattr(r, rel_desc.foreign_key): r for r in related_instances}
            for inst in instances:
                lv = getattr(inst, rel_desc.local_key)
                object.__setattr__(inst, f"_rel_{rel_name}", lookup_one.get(lv))

    async def _load_eager_counts(self, instances: list) -> None:
        """Batch-load relation counts for a list of instances.

        Args:
            instances: List of model instances to load counts for.
        """
        if not instances:
            return

        for rel_name in self._eager_counts:
            rel_desc = getattr(type(instances[0]), rel_name, None)
            if rel_desc is None:
                continue

            from sylvan.database.orm.primitives.relations import BelongsToMany, HasMany

            if isinstance(rel_desc, HasMany):
                await self._eager_count_has_many(instances, rel_name, rel_desc)
            elif isinstance(rel_desc, BelongsToMany):
                await self._eager_count_belongs_to_many(instances, rel_name, rel_desc)

    async def _eager_count_has_many(self, instances: list, rel_name: str, rel_desc: Any) -> None:
        """Count related records for a HasMany relation across all instances.

        Args:
            instances: List of model instances.
            rel_name: Name of the relation to count.
            rel_desc: The HasMany descriptor.
        """
        local_values = [
            getattr(inst, rel_desc.local_key) for inst in instances if getattr(inst, rel_desc.local_key) is not None
        ]
        if not local_values:
            return
        related = rel_desc.related_model
        ph = ", ".join("?" for _ in local_values)
        sql = (
            f"SELECT {rel_desc.foreign_key}, COUNT(*) as cnt "
            f"FROM {related.__table__} "
            f"WHERE {rel_desc.foreign_key} IN ({ph}) "
            f"GROUP BY {rel_desc.foreign_key}"
        )
        rows = await self.backend.fetch_all(sql, local_values)
        lookup = {(v := list(r.values()))[0]: v[1] for r in rows}
        for inst in instances:
            lv = getattr(inst, rel_desc.local_key)
            object.__setattr__(inst, f"{rel_name}_count", lookup.get(lv, 0))

    async def _eager_count_belongs_to_many(self, instances: list, rel_name: str, rel_desc: Any) -> None:
        """Count related records for a BelongsToMany relation across all instances.

        Args:
            instances: List of model instances.
            rel_name: Name of the relation to count.
            rel_desc: The BelongsToMany descriptor.
        """
        local_values = [
            getattr(inst, rel_desc.local_key) for inst in instances if getattr(inst, rel_desc.local_key) is not None
        ]
        if not local_values:
            return
        ph = ", ".join("?" for _ in local_values)
        sql = (
            f"SELECT {rel_desc.foreign_key}, COUNT(*) as cnt "
            f"FROM {rel_desc.pivot_table} "
            f"WHERE {rel_desc.foreign_key} IN ({ph}) "
            f"GROUP BY {rel_desc.foreign_key}"
        )
        rows = await self.backend.fetch_all(sql, local_values)
        lookup = {(v := list(r.values()))[0]: v[1] for r in rows}
        for inst in instances:
            lv = getattr(inst, rel_desc.local_key)
            object.__setattr__(inst, f"{rel_name}_count", lookup.get(lv, 0))

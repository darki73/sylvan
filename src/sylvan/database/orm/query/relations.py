"""Relation subquery mixin for QueryBuilder.

Provides has/doesnt_have filtering and the internal helpers that build
correlated EXISTS subqueries for each relation type.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sylvan.database.orm.query.builder import QueryBuilder


class QueryRelationMixin:
    """Mixin providing relation-based filtering for QueryBuilder."""

    self: QueryBuilder

    def has(self, relation: str) -> QueryBuilder[Any]:
        """Filter to records that have at least one related record.

        Uses WHERE EXISTS with a correlated subquery.

        Args:
            relation: Relation name to check existence of.

        Returns:
            This builder for chaining.
        """
        subquery, sub_params = self._build_relation_subquery(relation)
        self._wheres.append((f"EXISTS ({subquery})", sub_params, "AND"))
        return self

    def doesnt_have(self, relation: str) -> QueryBuilder[Any]:
        """Filter to records that have no related records.

        Uses WHERE NOT EXISTS with a correlated subquery.

        Args:
            relation: Relation name to check absence of.

        Returns:
            This builder for chaining.
        """
        subquery, sub_params = self._build_relation_subquery(relation)
        self._wheres.append((f"NOT EXISTS ({subquery})", sub_params, "AND"))
        return self

    def _build_relation_subquery(self, relation: str) -> tuple[str, list]:
        """Build a correlated EXISTS subquery for a relation descriptor.

        Args:
            relation: Relation name on the model.

        Returns:
            Tuple of (subquery SQL, parameter list).

        Raises:
            QueryError: If the relation is not found on the model.
        """
        from sylvan.database.orm.exceptions import QueryError
        from sylvan.database.orm.primitives.relations import BelongsTo, BelongsToMany

        rel_desc = self._find_relation_descriptor(relation)
        if rel_desc is None:
            raise QueryError(f"Relation '{relation}' not found on {self._model.__name__}")

        table = self._model.__table__

        if isinstance(rel_desc, BelongsToMany):
            return self._build_belongs_to_many_subquery(rel_desc, table)
        elif isinstance(rel_desc, BelongsTo):
            return self._build_belongs_to_subquery(rel_desc, table)
        else:
            return self._build_has_relation_subquery(rel_desc, table)

    def _find_relation_descriptor(self, relation: str) -> Any:
        """Look up a relation descriptor by name on the model's MRO.

        Args:
            relation: Relation name to find.

        Returns:
            The relation descriptor, or None if not found.
        """
        from sylvan.database.orm.primitives.relations import BelongsTo, BelongsToMany, HasMany, HasOne

        for cls in self._model.__mro__:
            if relation in cls.__dict__:
                attr = cls.__dict__[relation]
                if isinstance(attr, (BelongsTo, HasMany, HasOne, BelongsToMany)):
                    return attr
        return None

    def _build_belongs_to_many_subquery(self, rel_desc: Any, table: str) -> tuple[str, list]:
        """Build an EXISTS subquery for a BelongsToMany relation.

        Args:
            rel_desc: The BelongsToMany descriptor.
            table: The owning model's table name.

        Returns:
            Tuple of (subquery SQL, parameter list).
        """
        subq = (
            f"SELECT 1 FROM {rel_desc.pivot_table} "
            f"WHERE {rel_desc.pivot_table}.{rel_desc.foreign_key} = {table}.{rel_desc.local_key}"
        )
        return subq, []

    def _build_belongs_to_subquery(self, rel_desc: Any, table: str) -> tuple[str, list]:
        """Build an EXISTS subquery for a BelongsTo relation.

        Args:
            rel_desc: The BelongsTo descriptor.
            table: The owning model's table name.

        Returns:
            Tuple of (subquery SQL, parameter list).
        """
        related_model = rel_desc.related_model
        related_table = related_model.__table__
        subq = (
            f"SELECT 1 FROM {related_table} "
            f"WHERE {related_table}.{rel_desc.local_key} = {table}.{rel_desc.foreign_key}"
        )
        if getattr(related_model, "__soft_deletes__", False):
            subq += f" AND {related_table}.deleted_at IS NULL"
        return subq, []

    def _build_has_relation_subquery(self, rel_desc: Any, table: str) -> tuple[str, list]:
        """Build an EXISTS subquery for a HasMany or HasOne relation.

        Args:
            rel_desc: The HasMany or HasOne descriptor.
            table: The owning model's table name.

        Returns:
            Tuple of (subquery SQL, parameter list).
        """
        related_model = rel_desc.related_model
        related_table = related_model.__table__
        subq = (
            f"SELECT 1 FROM {related_table} "
            f"WHERE {related_table}.{rel_desc.foreign_key} = {table}.{rel_desc.local_key}"
        )
        if getattr(related_model, "__soft_deletes__", False):
            subq += f" AND {related_table}.deleted_at IS NULL"
        return subq, []

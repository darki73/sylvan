"""ModelMeta metaclass -- collects Column/Relation descriptors and registers models."""

import re

from sylvan.database.orm.primitives.fields import Column
from sylvan.database.orm.primitives.relations import RelationDescriptor
from sylvan.database.orm.runtime.model_registry import register_model


def _to_snake_case(name: str) -> str:
    """Convert CamelCase to snake_case for auto-generating table names.

    Args:
        name: A CamelCase class name.

    Returns:
        The snake_case equivalent.
    """
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", name)
    return s.lower()


class ModelMeta(type):
    """Metaclass that collects Column/Relation descriptors and registers models.

    When a Model subclass is defined, this metaclass scans the namespace for
    Column and RelationDescriptor instances, inherits descriptors from base
    classes, sets sensible defaults for FTS5/vector config, and registers the
    model in the global registry for string-based lookups.
    """

    def __new__(mcs, name: str, bases: tuple, namespace: dict) -> "ModelMeta":
        """Create a new Model subclass, collecting fields and relations.

        Args:
            name: The class name.
            bases: Base classes tuple.
            namespace: Class namespace dict.

        Returns:
            The newly created model class.
        """
        cls = super().__new__(mcs, name, bases, namespace)

        if name == "Model":
            return cls

        fields: dict[str, Column] = {}
        relations: dict[str, RelationDescriptor] = {}
        pk_column: str | None = None

        for attr_name, attr_val in namespace.items():
            if isinstance(attr_val, Column):
                attr_val._attr_name = attr_name
                fields[attr_name] = attr_val
                if attr_val.primary_key:
                    if pk_column is not None:
                        raise TypeError(
                            f"Model {name} has multiple primary keys: "
                            f"{pk_column!r} and {attr_name!r}. "
                            f"Only one Column(primary_key=True) is allowed."
                        )
                    pk_column = attr_name
            elif isinstance(attr_val, RelationDescriptor):
                attr_val._attr_name = attr_name
                relations[attr_name] = attr_val

        for base in bases:
            for attr_name in dir(base):
                if attr_name.startswith("_"):
                    continue
                attr_val = getattr(base, attr_name, None)
                if isinstance(attr_val, Column) and attr_name not in fields:
                    fields[attr_name] = attr_val
                elif isinstance(attr_val, RelationDescriptor) and attr_name not in relations:
                    relations[attr_name] = attr_val

        cls._fields_cache = fields
        cls._relations_cache = relations
        cls._pk_column = pk_column or "id"

        if not hasattr(cls, "__table__") or cls.__table__ is None:
            cls.__table__ = _to_snake_case(name) + "s"

        if not hasattr(cls, "__fts_table__"):
            cls.__fts_table__ = None
        if not hasattr(cls, "__fts_weights__"):
            cls.__fts_weights__ = None
        if not hasattr(cls, "__vec_table__"):
            cls.__vec_table__ = None
        if not hasattr(cls, "__vec_column__"):
            cls.__vec_column__ = None

        register_model(cls)
        return cls

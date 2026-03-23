"""Reference model -- symbol-level reference graph edges."""

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn


class Reference(Model):
    """Represents a reference edge between two symbols in the reference graph.

    Attributes:
        __table__: Database table name (quoted because 'references' is a SQL reserved word).
    """

    __table__ = '"references"'  # quoted -- reserved word in SQL

    id = AutoPrimaryKey()
    """Auto-incrementing primary key."""

    source_symbol_id = Column(str)
    """Symbol ID of the referencing symbol."""

    target_symbol_id = Column(str, nullable=True)
    """Symbol ID of the referenced symbol, if resolved."""

    target_specifier = Column(str)
    """Import specifier or name used to reference the target."""

    target_names = JsonColumn(list)
    """List of specific names referenced from the target."""

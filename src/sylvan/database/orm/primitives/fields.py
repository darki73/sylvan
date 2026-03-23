"""Field descriptors -- Column, JsonColumn, AutoPrimaryKey."""

import json
from typing import Any, override


class Column:
    """Declares a database column on a Model.

    Attributes:
        type: Python type for this column's values.
        nullable: Whether this column allows NULL values.
        primary_key: Whether this column is the primary key.
        default: Default value when the column is not provided.
    """

    def __init__(
        self,
        type: type = str,
        nullable: bool = False,
        primary_key: bool = False,
        column_name: str | None = None,
        default: Any = None,
    ):
        """Define a column with type, constraints, and optional default.

        Args:
            type: Python type for this column's values.
            nullable: Whether this column allows NULL values.
            primary_key: Whether this column is the primary key.
            column_name: Explicit database column name (defaults to attribute name).
            default: Default value when the column is not provided.
        """
        self.type = type
        self.nullable = nullable
        self.primary_key = primary_key
        self._column_name = column_name
        self.default = default
        self._attr_name: str = ""

    @property
    def db_name(self) -> str:
        """Return the actual column name in the database."""
        return self._column_name or self._attr_name

    def to_db(self, value: Any) -> Any:
        """Convert a Python value to a SQLite-compatible value.

        Args:
            value: The Python value to convert.

        Returns:
            The SQLite-compatible value, or None if the input is None.
        """
        if value is None:
            return None
        return value

    def from_db(self, value: Any) -> Any:
        """Convert a SQLite value to a Python value.

        Args:
            value: The raw value from the database.

        Returns:
            The converted Python value, using the column's type constructor.
        """
        if value is None:
            return self.default
        if self.type is bool:
            return bool(value)
        return self.type(value)

    def __repr__(self) -> str:
        """Show the column type, nullability, and database name."""
        return f"Column({self.type.__name__}, nullable={self.nullable}, db={self.db_name!r})"


class JsonColumn(Column):
    """Column that auto-serializes list/dict to JSON in the database.

    Attributes:
        _default_factory: Callable that produces fresh default values.
    """

    def __init__(
        self,
        inner_type: type = list,
        nullable: bool = True,
        column_name: str | None = None,
        default_factory: Any = None,
    ):
        """Define a JSON column with a factory for default values.

        Args:
            inner_type: Python type for deserialized values (list or dict).
            nullable: Whether this column allows NULL values.
            column_name: Explicit database column name.
            default_factory: Callable returning a fresh default; inferred from inner_type if omitted.
        """
        self._default_factory = default_factory or (list if inner_type is list else dict)
        super().__init__(
            type=inner_type, nullable=nullable, column_name=column_name,
            default=None,
        )

    @property
    def default(self) -> Any:
        """Return a fresh default by calling the factory."""
        return self._default_factory()

    @default.setter
    def default(self, value: Any) -> None:
        """Ignore attempts to set default directly; the factory is always used.

        Args:
            value: The value to set (ignored).
        """

    @override
    def to_db(self, value: Any) -> Any:
        """Serialize a list or dict to a JSON string for storage.

        Args:
            value: The Python collection to serialize.

        Returns:
            A JSON string, or None for empty or None values.
        """
        if value is None or (isinstance(value, (list, dict)) and not value):
            return None
        return json.dumps(value)

    @override
    def from_db(self, value: Any) -> Any:
        """Deserialize a JSON string back to a Python list or dict.

        Args:
            value: The raw database value (string or already-parsed).

        Returns:
            The deserialized Python collection, or a fresh default for None.
        """
        if value is None:
            return self._default_factory()
        if isinstance(value, str):
            return json.loads(value)
        return value


class AutoPrimaryKey(Column):
    """INTEGER PRIMARY KEY with auto-increment."""

    def __init__(self):
        """Define an auto-incrementing integer primary key.
        """
        super().__init__(type=int, nullable=True, primary_key=True)

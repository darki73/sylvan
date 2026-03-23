"""ORM-specific exceptions."""


class ORMError(Exception):
    """Base exception for all ORM errors."""


class ModelNotFoundError(ORMError):
    """Raised when find_or_fail() cannot find a record."""


class QueryError(ORMError):
    """Raised when a query fails to execute."""


class ValidationError(ORMError):
    """Raised when model data fails validation."""

"""Scope decorator -- reusable query filters on models.

Usage on a Model subclass::

    class Symbol(Model):
        @scope
        def functions(query):
            return query.where(kind="function")

        @scope
        def in_repo(query, name):
            return query.join("files", "files.id = symbols.file_id") \\
                        .join("repos", "repos.id = files.repo_id") \\
                        .where("repos.name", name)

    # Then call as:
    Symbol.functions().in_repo("sylvan").get()
"""

from collections.abc import Callable
from typing import Any


class ScopeDescriptor:
    """Descriptor that creates a QueryBuilder and applies the scope function.

    When accessed on a model class, returns a callable that creates a fresh
    QueryBuilder and passes it through the scope function.

    Attributes:
        func: The underlying scope function.
        name: Name of the scope, taken from the wrapped function.
    """

    def __init__(self, func: Callable):
        """Wrap a scope function in a descriptor.

        Args:
            func: The scope function to wrap.
        """
        self.func = func
        self.name = func.__name__

    def __set_name__(self, owner: type, name: str) -> None:
        """Record the attribute name when assigned to a class.

        Args:
            owner: The class that owns this descriptor.
            name: The attribute name assigned to this descriptor.
        """
        self.name = name

    def __get__(self, obj: Any, objtype: type | None = None) -> Callable:
        """Return a callable that applies the scope to a new QueryBuilder.

        Args:
            obj: The instance, or None when accessed on the class.
            objtype: The class owning the descriptor.

        Returns:
            A callable that creates a QueryBuilder and applies the scope function.
        """
        if objtype is None:
            objtype = type(obj)

        model_class = objtype

        def scope_caller(*args: Any, **kwargs: Any) -> Any:
            """Create a QueryBuilder and apply the scope function."""
            from sylvan.database.orm.query.builder import QueryBuilder

            builder = QueryBuilder(model_class)
            return self.func(builder, *args, **kwargs)

        return scope_caller


def scope(func: Callable) -> ScopeDescriptor:
    """Decorator to define a reusable query scope on a Model.

    Args:
        func: The scope function, which receives a QueryBuilder as its first argument.

    Returns:
        A ScopeDescriptor wrapping the function.
    """
    return ScopeDescriptor(func)

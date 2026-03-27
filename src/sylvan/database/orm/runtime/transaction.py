"""Transaction helper for the ORM.

Provides a convenience function to start a transaction using the
current backend from context.

Usage::

    from sylvan.database.orm import transaction

    async with transaction():
        await Model.where(id=1).update(status="active")
        await OtherModel.create(name="foo")
        # commits on exit, rolls back on exception
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


@asynccontextmanager
async def transaction() -> AsyncIterator[None]:
    """Start a database transaction using the current backend.

    Issues BEGIN, commits on success, rolls back on error.

    Yields:
        None.
    """
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()
    async with backend.transaction():
        yield

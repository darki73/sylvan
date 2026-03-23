"""Tests for sylvan.database.orm.runtime.connection_manager — get_backend()."""

from __future__ import annotations

import pytest

from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.orm.runtime.connection_manager import get_backend


class TestGetBackend:
    async def test_returns_backend_from_context(self, orm_ctx):
        backend = get_backend()
        assert backend is orm_ctx.backend

    async def test_raises_when_no_backend(self, orm_ctx):
        # Create a context without a backend
        ctx = SylvanContext(backend=None)
        token = set_context(ctx)
        try:
            with pytest.raises(RuntimeError, match="No storage backend"):
                get_backend()
        finally:
            reset_context(token)

    async def test_backend_is_connected(self, orm_ctx):
        backend = get_backend()
        # Should be able to execute a query
        result = await backend.fetch_value("SELECT 1")
        assert result == 1

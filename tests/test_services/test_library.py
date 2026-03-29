"""Tests for sylvan.services.library - list_libraries."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from sylvan.services.library import list_libraries


class TestListLibraries:
    async def test_list_libraries_empty(self, ctx):
        with patch(
            "sylvan.libraries.manager.async_list_libraries",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await list_libraries()
            assert result == []

    async def test_list_libraries(self, ctx):
        mock_libs = [
            {"name": "django", "version": "4.2", "symbols": 100},
            {"name": "flask", "version": "3.0", "symbols": 50},
        ]
        with patch(
            "sylvan.libraries.manager.async_list_libraries",
            new_callable=AsyncMock,
            return_value=mock_libs,
        ):
            result = await list_libraries()
            assert len(result) == 2
            assert result[0]["name"] == "django"
            assert result[1]["name"] == "flask"

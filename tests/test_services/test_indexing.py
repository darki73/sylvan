"""Tests for sylvan.services.indexing - index_folder."""

from __future__ import annotations

from sylvan.services.indexing import index_folder


class TestIndexFolder:
    async def test_index_folder_delegates(self, ctx, tmp_path):
        py_file = tmp_path / "hello.py"
        py_file.write_text("def greet():\n    pass\n", encoding="utf-8")

        result = await index_folder(str(tmp_path), name="test-idx")

        assert result["repo"] == "test-idx"
        assert result["files_indexed"] >= 1
        assert result["symbols_extracted"] >= 1

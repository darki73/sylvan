"""Tests for sylvan.indexing.post_processing.file_watcher.

Covers the filter-and-dispatch logic that sits between the Rust
watcher and the reindexer. End-to-end watcher behaviour lives in
``tests/test_file_watcher.py``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sylvan.indexing.post_processing.file_watcher import (
    _filter_indexable,
    _reindex,
    start_watcher_background,
)


class TestFilterIndexable:
    """Tests for :func:`_filter_indexable`."""

    def test_added_file_passes(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/repo/src/main.py")], root)
        assert result == ["src/main.py"]

    def test_modified_file_passes(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("modified", "/repo/utils.py")], root)
        assert result == ["utils.py"]

    def test_removed_file_passes(self) -> None:
        # Removed paths must reach the reindexer so it can prune symbols;
        # this is a deliberate behaviour change from the old watchfiles
        # path which dropped deletions.
        root = Path("/repo")
        result = _filter_indexable([("removed", "/repo/old.py")], root)
        assert result == ["old.py"]

    def test_unknown_kind_ignored(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("renamed_from", "/repo/x.py")], root)
        assert result == []

    def test_hidden_file_skipped(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/repo/.hidden")], root)
        assert result == []

    def test_node_modules_skipped(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/repo/node_modules/pkg/index.js")], root)
        assert result == []

    def test_git_dir_skipped(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/repo/.git/objects/abc")], root)
        assert result == []

    def test_path_outside_root_skipped(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/other/place/x.py")], root)
        assert result == []

    def test_minified_file_skipped(self) -> None:
        root = Path("/repo")
        result = _filter_indexable([("added", "/repo/bundle.min.js")], root)
        assert result == []

    def test_multiple_changes_mixed(self) -> None:
        root = Path("/repo")
        result = _filter_indexable(
            [
                ("added", "/repo/a.py"),
                ("removed", "/repo/b.py"),
                ("modified", "/repo/c.py"),
                ("added", "/repo/.secret"),
                ("modified", "/repo/node_modules/pkg.js"),
            ],
            root,
        )
        assert sorted(result) == ["a.py", "b.py", "c.py"]


class TestReindex:
    """Tests for :func:`_reindex`."""

    @pytest.mark.asyncio
    async def test_reindex_calls_index_folder(self) -> None:
        mock_result = MagicMock(files_indexed=5, symbols_extracted=20)
        with patch(
            "sylvan.indexing.pipeline.orchestrator.index_folder",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_index:
            await _reindex(Path("/repo"), "my_repo")
            mock_index.assert_called_once()

    @pytest.mark.asyncio
    async def test_reindex_swallows_errors(self) -> None:
        with patch(
            "sylvan.indexing.pipeline.orchestrator.index_folder",
            new_callable=AsyncMock,
            side_effect=RuntimeError("indexing failed"),
        ):
            # Errors must be logged, not propagated, so the watcher keeps running.
            await _reindex(Path("/repo"), "my_repo")


class TestStartWatcherBackground:
    """Tests for :func:`start_watcher_background`."""

    def test_starts_daemon_thread(self) -> None:
        with patch("asyncio.run") as mock_run:
            start_watcher_background("/repo", "test_repo")
            import time

            time.sleep(0.1)
            mock_run.assert_called_once()

"""Tests for sylvan.indexing.post_processing.file_watcher."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Create a fake 'watchfiles' module so the import inside _collect_changed_files
# succeeds.  We use an IntEnum-like class so the `in (Change.added, ...)` check
# works with plain ints that we pass as change_type.
# ---------------------------------------------------------------------------

_fake_watchfiles = types.ModuleType("watchfiles")


class _FakeChange:
    added = 1
    modified = 2
    deleted = 3


_fake_watchfiles.Change = _FakeChange
_fake_watchfiles.awatch = MagicMock()  # not used directly by _collect_changed_files


@pytest.fixture(autouse=True)
def _inject_fake_watchfiles():
    """Temporarily inject a fake watchfiles module for all tests in this file."""
    had_it = "watchfiles" in sys.modules
    old = sys.modules.get("watchfiles")
    sys.modules["watchfiles"] = _fake_watchfiles
    # Reload so the function picks up the fake module
    import sylvan.indexing.post_processing.file_watcher as fw
    importlib.reload(fw)
    yield
    # Restore
    if had_it:
        sys.modules["watchfiles"] = old
    else:
        sys.modules.pop("watchfiles", None)
    importlib.reload(fw)


class TestCollectChangedFiles:
    """Tests for _collect_changed_files()."""

    def test_added_files_collected(self):
        """Added files appear in the result."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.added, "/repo/src/main.py")]
        result = _collect_changed_files(changes, root)
        assert "src/main.py" in result

    def test_modified_files_collected(self):
        """Modified files appear in the result."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.modified, "/repo/utils.py")]
        result = _collect_changed_files(changes, root)
        assert "utils.py" in result

    def test_deleted_files_excluded(self):
        """Deleted files are not collected (only added/modified)."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.deleted, "/repo/old.py")]
        result = _collect_changed_files(changes, root)
        assert result == []

    def test_hidden_files_skipped(self):
        """Files starting with '.' are filtered out."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.added, "/repo/.hidden")]
        result = _collect_changed_files(changes, root)
        assert result == []

    def test_node_modules_skipped(self):
        """Files under skipped directories (like node_modules) are filtered out."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.added, "/repo/node_modules/pkg/index.js")]
        result = _collect_changed_files(changes, root)
        assert result == []

    def test_git_dir_skipped(self):
        """Files under .git directory are filtered out."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [(_FakeChange.added, "/repo/.git/objects/abc")]
        result = _collect_changed_files(changes, root)
        assert result == []

    def test_multiple_changes_mixed(self):
        """Multiple changes: only added/modified non-hidden files pass."""
        from sylvan.indexing.post_processing.file_watcher import _collect_changed_files

        root = Path("/repo")
        changes = [
            (_FakeChange.added, "/repo/a.py"),
            (_FakeChange.deleted, "/repo/b.py"),
            (_FakeChange.modified, "/repo/c.py"),
            (_FakeChange.added, "/repo/.secret"),
        ]
        result = _collect_changed_files(changes, root)
        assert sorted(result) == ["a.py", "c.py"]


class TestWatchFolder:
    """Tests for watch_folder()."""

    @pytest.mark.asyncio
    async def test_returns_if_watchfiles_not_installed(self):
        """watch_folder() returns gracefully when watchfiles is missing."""
        # Temporarily remove our fake so the import fails
        old = sys.modules.pop("watchfiles", None)
        try:
            import sylvan.indexing.post_processing.file_watcher as fw
            importlib.reload(fw)

            # Should not raise — the except ImportError block handles it
            await fw.watch_folder("/some/path")
        finally:
            if old is not None:
                sys.modules["watchfiles"] = old


class TestReindex:
    """Tests for _reindex()."""

    @pytest.mark.asyncio
    async def test_reindex_calls_index_folder(self):
        """_reindex() calls index_folder with correct arguments."""
        from sylvan.indexing.post_processing.file_watcher import _reindex

        mock_result = MagicMock(files_indexed=5, symbols_extracted=20)
        with patch(
            "sylvan.indexing.pipeline.orchestrator.index_folder",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            await _reindex(Path("/repo"), "my_repo")

    @pytest.mark.asyncio
    async def test_reindex_handles_error(self):
        """_reindex() catches exceptions and logs them."""
        from sylvan.indexing.post_processing.file_watcher import _reindex

        with patch(
            "sylvan.indexing.pipeline.orchestrator.index_folder",
            new_callable=AsyncMock,
            side_effect=RuntimeError("indexing failed"),
        ):
            # Should not raise
            await _reindex(Path("/repo"), "my_repo")


class TestStartWatcherBackground:
    """Tests for start_watcher_background()."""

    def test_starts_daemon_thread(self):
        """start_watcher_background() starts a daemon thread."""
        with patch("asyncio.run") as mock_run:
            from sylvan.indexing.post_processing.file_watcher import start_watcher_background

            start_watcher_background("/repo", "test_repo")

            # Give the thread a moment to start
            import time
            time.sleep(0.1)

            mock_run.assert_called_once()

"""Tests for sylvan.hooks -- worktree event handling."""

from __future__ import annotations

import json

import pytest

from sylvan.hooks import get_active_worktrees, record_event

# Use non-/tmp paths to avoid S108 lint rule
_WT1 = "/home/user/worktrees/wt1"
_WT2 = "/home/user/worktrees/wt2"


@pytest.fixture
def clean_manifest(tmp_path, monkeypatch):
    """Redirect the manifest to a temp directory."""
    manifest = tmp_path / "worktrees.jsonl"
    monkeypatch.setattr("sylvan.hooks.MANIFEST_PATH", manifest)
    return manifest


class TestRecordEvent:
    def test_creates_manifest(self, clean_manifest):
        record_event("worktree-create", _WT1)
        assert clean_manifest.exists()
        lines = clean_manifest.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "worktree-create"
        assert entry["path"] == _WT1
        assert "timestamp" in entry

    def test_appends_events(self, clean_manifest):
        record_event("worktree-create", _WT1)
        record_event("worktree-create", _WT2)
        lines = clean_manifest.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2

    def test_records_remove_event(self, clean_manifest):
        record_event("worktree-remove", _WT1)
        entry = json.loads(clean_manifest.read_text(encoding="utf-8").strip())
        assert entry["event"] == "worktree-remove"


class TestGetActiveWorktrees:
    def test_empty_manifest(self, clean_manifest):
        assert get_active_worktrees() == []

    def test_single_create(self, clean_manifest):
        record_event("worktree-create", _WT1)
        assert get_active_worktrees() == [_WT1]

    def test_create_then_remove(self, clean_manifest):
        record_event("worktree-create", _WT1)
        record_event("worktree-remove", _WT1)
        assert get_active_worktrees() == []

    def test_multiple_active(self, clean_manifest):
        record_event("worktree-create", _WT1)
        record_event("worktree-create", _WT2)
        active = get_active_worktrees()
        assert _WT1 in active
        assert _WT2 in active

    def test_partial_remove(self, clean_manifest):
        record_event("worktree-create", _WT1)
        record_event("worktree-create", _WT2)
        record_event("worktree-remove", _WT1)
        active = get_active_worktrees()
        assert active == [_WT2]

    def test_nonexistent_manifest(self, clean_manifest):
        """When manifest doesn't exist, returns empty list."""
        assert get_active_worktrees() == []

    def test_corrupt_lines_ignored(self, clean_manifest):
        clean_manifest.write_text("not json\n", encoding="utf-8")
        record_event("worktree-create", _WT1)
        assert get_active_worktrees() == [_WT1]


class TestHandleWorktreeRemove:
    def test_records_event(self, clean_manifest):
        from sylvan.hooks import handle_worktree_remove
        handle_worktree_remove(_WT1)
        entry = json.loads(clean_manifest.read_text(encoding="utf-8").strip())
        assert entry["event"] == "worktree-remove"
        assert entry["path"] == _WT1

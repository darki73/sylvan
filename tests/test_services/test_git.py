"""Tests for sylvan.services.git - GitService."""

from __future__ import annotations

import pytest

from sylvan.database.orm import Repo
from sylvan.error_codes import RepoNotFoundError
from sylvan.services.git import GitService


class TestGitServiceContext:
    async def test_context_repo_not_found(self, ctx):
        svc = GitService()
        with pytest.raises(RepoNotFoundError):
            await svc.context("nonexistent-repo")

    async def test_context_no_source_path(self, ctx):
        await Repo.create(name="no-src", source_path=None, indexed_at="2025-01-01T00:00:00")
        svc = GitService()
        # source_path is None, so repo_obj.source_path is falsy - raises RepoNotFoundError
        with pytest.raises(RepoNotFoundError):
            await svc.context("no-src")

    async def test_context_no_file_or_symbol(self, ctx, tmp_path):
        await Repo.create(name="with-src", source_path=str(tmp_path), indexed_at="2025-01-01T00:00:00")
        svc = GitService()
        result = await svc.context("with-src")
        assert result == {"error": "provide file_path or symbol_id"}


class TestGitServiceRecentChanges:
    async def test_recent_changes_repo_not_found(self, ctx):
        svc = GitService()
        with pytest.raises(RepoNotFoundError):
            await svc.recent_changes("nonexistent-repo")

    async def test_recent_changes_no_source_path(self, ctx):
        await Repo.create(name="lib-repo", source_path=None, indexed_at="2025-01-01T00:00:00")
        svc = GitService()
        result = await svc.recent_changes("lib-repo")
        assert result["error"] == "source_unavailable"

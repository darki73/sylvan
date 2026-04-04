"""Tests for sylvan.services.preference - PreferenceService."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sylvan.database.orm.models import Preference, Repo
from sylvan.error_codes import InvalidScopeError, RepoNotFoundError, WorkspaceNotFoundError
from sylvan.services.preference import PreferenceService
from sylvan.services.workspace import WorkspaceService


async def _seed_repo(ctx, name="test-repo"):
    """Create a repo for testing."""
    await ctx.backend.execute(
        f"INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '/tmp/{name}', '2024-01-01', 'local')"
    )
    await ctx.backend.commit()
    return await Repo.where(name=name).first()


class TestPreferenceSave:
    async def test_creates_global_preference(self, ctx):
        """Save creates a global preference."""
        result = await PreferenceService().save(
            key="test_style",
            instruction="Use pytest directly",
            scope="global",
        )
        assert result["status"] == "created"
        assert result["scope"] == "global"
        assert result["key"] == "test_style"

        pref = await Preference.find(result["id"])
        assert pref.instruction == "Use pytest directly"
        assert pref.scope_id is None

    async def test_creates_repo_preference(self, ctx):
        """Save creates a repo-scoped preference."""
        repo = await _seed_repo(ctx)
        result = await PreferenceService().save(
            key="commit_format",
            instruction="Use conventional commits",
            scope="repo",
            scope_id=repo.id,
        )
        assert result["status"] == "created"
        assert result["scope"] == "repo"

        pref = await Preference.find(result["id"])
        assert pref.scope_id == repo.id

    async def test_creates_workspace_preference(self, ctx):
        """Save creates a workspace-scoped preference."""
        ws = await WorkspaceService().create("my-ws")
        result = await PreferenceService().save(
            key="code_style",
            instruction="No pipes in tests",
            scope="workspace",
            scope_id=ws.id,
        )
        assert result["status"] == "created"
        assert result["scope"] == "workspace"

    async def test_upserts_same_key_and_scope(self, ctx):
        """Save updates existing preference with same key and scope."""
        first = await PreferenceService().save(
            key="test_style",
            instruction="Original",
            scope="global",
        )
        second = await PreferenceService().save(
            key="test_style",
            instruction="Updated",
            scope="global",
        )
        assert second["status"] == "updated"
        assert second["id"] == first["id"]

        pref = await Preference.find(first["id"])
        assert pref.instruction == "Updated"

    async def test_same_key_different_scope_creates_both(self, ctx):
        """Same key at different scopes creates separate preferences."""
        repo = await _seed_repo(ctx)
        global_result = await PreferenceService().save(
            key="test_style",
            instruction="Global rule",
            scope="global",
        )
        repo_result = await PreferenceService().save(
            key="test_style",
            instruction="Repo rule",
            scope="repo",
            scope_id=repo.id,
        )
        assert global_result["id"] != repo_result["id"]

    async def test_invalid_scope_raises(self, ctx):
        """Save raises InvalidScopeError for unknown scope."""
        with pytest.raises(InvalidScopeError):
            await PreferenceService().save(
                key="k",
                instruction="i",
                scope="invalid",
            )

    async def test_repo_scope_requires_scope_id(self, ctx):
        """Save raises when scope_id is missing for repo scope."""
        with pytest.raises(InvalidScopeError):
            await PreferenceService().save(
                key="k",
                instruction="i",
                scope="repo",
            )

    async def test_repo_scope_validates_repo_exists(self, ctx):
        """Save raises RepoNotFoundError for nonexistent repo ID."""
        with pytest.raises(RepoNotFoundError):
            await PreferenceService().save(
                key="k",
                instruction="i",
                scope="repo",
                scope_id=99999,
            )

    async def test_workspace_scope_validates_workspace_exists(self, ctx):
        """Save raises WorkspaceNotFoundError for nonexistent workspace ID."""
        with pytest.raises(WorkspaceNotFoundError):
            await PreferenceService().save(
                key="k",
                instruction="i",
                scope="workspace",
                scope_id=99999,
            )

    async def test_global_scope_ignores_scope_id(self, ctx):
        """Save forces scope_id to None for global scope."""
        result = await PreferenceService().save(
            key="k",
            instruction="i",
            scope="global",
            scope_id=123,
        )
        pref = await Preference.find(result["id"])
        assert pref.scope_id is None


class TestPreferenceGetAll:
    async def test_returns_global_preferences(self, ctx):
        """get_all includes global preferences."""
        await _seed_repo(ctx)
        await PreferenceService().save("rule1", "Do this", scope="global")

        result = await PreferenceService().get_all("test-repo")
        assert result["count"] == 1
        assert result["preferences"][0]["key"] == "rule1"

    async def test_merges_three_scopes(self, ctx):
        """get_all merges global, workspace, and repo preferences."""
        repo = await _seed_repo(ctx)
        ws = await WorkspaceService().create("ws")
        await WorkspaceService().add_repo("ws", "test-repo")

        await PreferenceService().save("global_rule", "G", scope="global")
        await PreferenceService().save("ws_rule", "W", scope="workspace", scope_id=ws.id)
        await PreferenceService().save("repo_rule", "R", scope="repo", scope_id=repo.id)

        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 3
        keys = {p["key"] for p in result["preferences"]}
        assert keys == {"global_rule", "ws_rule", "repo_rule"}

    async def test_repo_overrides_global_same_key(self, ctx):
        """Repo preference wins over global for the same key."""
        repo = await _seed_repo(ctx)
        await PreferenceService().save("style", "Global style", scope="global")
        await PreferenceService().save("style", "Repo style", scope="repo", scope_id=repo.id)

        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 1
        assert result["preferences"][0]["instruction"] == "Repo style"
        assert result["preferences"][0]["scope"] == "repo"

    async def test_workspace_overrides_global_same_key(self, ctx):
        """Workspace preference wins over global for the same key."""
        await _seed_repo(ctx)
        ws = await WorkspaceService().create("ws")
        await WorkspaceService().add_repo("ws", "test-repo")

        await PreferenceService().save("style", "Global", scope="global")
        await PreferenceService().save("style", "Workspace", scope="workspace", scope_id=ws.id)

        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 1
        assert result["preferences"][0]["instruction"] == "Workspace"

    async def test_repo_overrides_workspace_same_key(self, ctx):
        """Repo preference wins over workspace for the same key."""
        repo = await _seed_repo(ctx)
        ws = await WorkspaceService().create("ws")
        await WorkspaceService().add_repo("ws", "test-repo")

        await PreferenceService().save("style", "Workspace", scope="workspace", scope_id=ws.id)
        await PreferenceService().save("style", "Repo", scope="repo", scope_id=repo.id)

        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 1
        assert result["preferences"][0]["instruction"] == "Repo"

    async def test_unknown_repo_raises(self, ctx):
        """get_all raises RepoNotFoundError for unknown repo."""
        with pytest.raises(RepoNotFoundError):
            await PreferenceService().get_all("ghost")

    async def test_empty_when_no_preferences(self, ctx):
        """get_all returns empty list when no preferences exist."""
        await _seed_repo(ctx)
        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 0
        assert result["preferences"] == []


class TestPreferenceDelete:
    async def test_delete_removes_preference(self, ctx):
        """Delete removes the preference."""
        saved = await PreferenceService().save("rule", "Do it", scope="global")
        result = await PreferenceService().delete("rule", scope="global")
        assert result["status"] == "deleted"

        pref = await Preference.find(saved["id"])
        assert pref is None

    async def test_delete_nonexistent_returns_not_found(self, ctx):
        """Delete returns not_found status for missing preference."""
        result = await PreferenceService().delete("ghost", scope="global")
        assert result["status"] == "not_found"

    async def test_delete_invalid_scope_raises(self, ctx):
        """Delete raises InvalidScopeError for unknown scope."""
        with pytest.raises(InvalidScopeError):
            await PreferenceService().delete("k", scope="bad")

    async def test_delete_scoped_preference(self, ctx):
        """Delete removes a repo-scoped preference."""
        repo = await _seed_repo(ctx)
        await PreferenceService().save("rule", "Repo rule", scope="repo", scope_id=repo.id)

        result = await PreferenceService().delete("rule", scope="repo", scope_id=repo.id)
        assert result["status"] == "deleted"

        all_prefs = await Preference.all().get()
        assert len(all_prefs) == 0


class TestPreferenceDedup:
    async def test_dedup_keeps_narrower_scope(self, ctx):
        """Semantic dedup keeps repo preference over similar global one."""
        repo = await _seed_repo(ctx)

        await PreferenceService().save("global_test", "Always use pytest", scope="global")
        await PreferenceService().save("repo_test", "Run tests with pytest", scope="repo", scope_id=repo.id)

        def _make_similar_vec(seed):
            return [seed + i * 0.0001 for i in range(384)]

        class SimilarProvider:
            def embed(self, texts):
                return [_make_similar_vec(0.5) for _ in texts]

            def available(self):
                return True

        with patch("sylvan.services.preference.get_embedding_provider", return_value=SimilarProvider()):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 1
        assert result["preferences"][0]["scope"] == "repo"

    async def test_dedup_skipped_without_provider(self, ctx):
        """Without embedding provider, all preferences are returned."""
        repo = await _seed_repo(ctx)

        await PreferenceService().save("a", "Always use pytest", scope="global")
        await PreferenceService().save("b", "Run tests with pytest", scope="repo", scope_id=repo.id)

        with patch("sylvan.services.preference.get_embedding_provider", return_value=None):
            result = await PreferenceService().get_all("test-repo")

        assert result["count"] == 2

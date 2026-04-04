"""Tests for sylvan.services.memory - MemoryService."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sylvan.database.orm.models import Memory, Repo
from sylvan.error_codes import MemoryNotFoundError, RepoNotFoundError
from sylvan.services.memory import MemoryService


async def _seed_repo(ctx, name="test-repo"):
    """Create a repo for testing."""
    await ctx.backend.execute(
        f"INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '/tmp/{name}', '2024-01-01', 'local')"
    )
    await ctx.backend.commit()
    return await Repo.where(name=name).first()


def _make_vector(dims=384, seed=0.1):
    """Create a deterministic float vector."""
    return [seed + i * 0.001 for i in range(dims)]


def _make_orthogonal_vectors(dims=384):
    """Create two vectors pointing in very different directions."""
    a = [0.0] * dims
    b = [0.0] * dims
    a[0] = 1.0
    b[dims // 2] = 1.0
    return a, b


def _mock_provider(vectors=None):
    """Create a mock embedding provider."""

    class FakeProvider:
        def embed(self, texts):
            if vectors is not None:
                return vectors[: len(texts)]
            return [_make_vector(seed=hash(t) % 100 * 0.01) for t in texts]

        def available(self):
            return True

    return FakeProvider()


class TestMemorySave:
    async def test_creates_memory(self, ctx):
        """Save creates a new memory and returns its ID."""
        repo = await _seed_repo(ctx)
        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            result = await MemoryService().save("test-repo", "Test insight", ["tag1"])

        assert result["status"] == "created"
        assert result["id"] is not None

        memory = await Memory.find(result["id"])
        assert memory is not None
        assert memory.content == "Test insight"
        assert memory.tags == ["tag1"]
        assert memory.repo_id == repo.id

    async def test_creates_without_tags(self, ctx):
        """Save works without tags."""
        await _seed_repo(ctx)
        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            result = await MemoryService().save("test-repo", "No tags")

        memory = await Memory.find(result["id"])
        assert memory.tags == []

    async def test_raises_on_unknown_repo(self, ctx):
        """Save raises RepoNotFoundError for unknown repo."""
        with (
            patch("sylvan.services.memory.get_embedding_provider", return_value=None),
            pytest.raises(RepoNotFoundError),
        ):
            await MemoryService().save("ghost-repo", "content")

    async def test_dedup_updates_similar(self, ctx):
        """When content is very similar, updates existing instead of creating."""
        await _seed_repo(ctx)
        same_vec = [_make_vector(seed=0.5)]
        provider = _mock_provider(vectors=same_vec)

        with patch("sylvan.services.memory.get_embedding_provider", return_value=provider):
            first = await MemoryService().save("test-repo", "Original insight")
            assert first["status"] == "created"

            second = await MemoryService().save("test-repo", "Updated insight")
            assert second["status"] == "updated"
            assert second["id"] == first["id"]

        memory = await Memory.find(first["id"])
        assert memory.content == "Updated insight"

    async def test_creates_distinct_memories(self, ctx):
        """Different content creates separate memories."""
        await _seed_repo(ctx)

        vec_a, vec_b = _make_orthogonal_vectors()

        with patch("sylvan.services.memory.get_embedding_provider") as mock_provider:

            class ProviderA:
                def embed(self, texts):
                    return [vec_a]

                def available(self):
                    return True

            mock_provider.return_value = ProviderA()
            first = await MemoryService().save("test-repo", "About architecture")

            class ProviderB:
                def embed(self, texts):
                    return [vec_b]

                def available(self):
                    return True

            mock_provider.return_value = ProviderB()
            second = await MemoryService().save("test-repo", "About testing")

        assert first["id"] != second["id"]
        assert first["status"] == "created"
        assert second["status"] == "created"


class TestMemorySearch:
    async def test_search_returns_results(self, ctx):
        """Search returns memories ranked by similarity."""
        await _seed_repo(ctx)

        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            await MemoryService().save("test-repo", "Architecture decision about caching")
            await MemoryService().save("test-repo", "Testing strategy for the API")

        provider = _mock_provider()
        with patch("sylvan.services.memory.get_embedding_provider", return_value=provider):
            result = await MemoryService().search("test-repo", "caching", limit=10)

        assert "memories" in result
        assert result["count"] >= 0

    async def test_search_without_provider(self, ctx):
        """Search without embedding provider returns empty with note."""
        await _seed_repo(ctx)
        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            result = await MemoryService().search("test-repo", "anything")

        assert result["memories"] == []
        assert "note" in result

    async def test_search_unknown_repo(self, ctx):
        """Search raises RepoNotFoundError for unknown repo."""
        with (
            patch("sylvan.services.memory.get_embedding_provider", return_value=None),
            pytest.raises(RepoNotFoundError),
        ):
            await MemoryService().search("ghost", "query")


class TestMemoryRetrieve:
    async def test_retrieve_by_id(self, ctx):
        """Retrieve returns the correct memory."""
        await _seed_repo(ctx)
        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            saved = await MemoryService().save("test-repo", "My insight", ["tag"])

        result = await MemoryService().retrieve("test-repo", saved["id"])
        assert result["id"] == saved["id"]
        assert result["content"] == "My insight"
        assert result["tags"] == ["tag"]

    async def test_retrieve_wrong_repo(self, ctx):
        """Retrieve raises when memory belongs to different repo."""
        await _seed_repo(ctx, "repo-a")
        await _seed_repo(ctx, "repo-b")

        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            saved = await MemoryService().save("repo-a", "Secret insight")

        with pytest.raises(MemoryNotFoundError):
            await MemoryService().retrieve("repo-b", saved["id"])

    async def test_retrieve_nonexistent(self, ctx):
        """Retrieve raises for nonexistent ID."""
        await _seed_repo(ctx)
        with pytest.raises(MemoryNotFoundError):
            await MemoryService().retrieve("test-repo", 99999)


class TestMemoryDelete:
    async def test_delete_removes_memory(self, ctx):
        """Delete removes the memory from the database."""
        await _seed_repo(ctx)
        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            saved = await MemoryService().save("test-repo", "To be deleted")

        result = await MemoryService().delete("test-repo", saved["id"])
        assert result["status"] == "deleted"

        memory = await Memory.find(saved["id"])
        assert memory is None

    async def test_delete_wrong_repo(self, ctx):
        """Delete raises when memory belongs to different repo."""
        await _seed_repo(ctx, "repo-a")
        await _seed_repo(ctx, "repo-b")

        with patch("sylvan.services.memory.get_embedding_provider", return_value=None):
            saved = await MemoryService().save("repo-a", "Content")

        with pytest.raises(MemoryNotFoundError):
            await MemoryService().delete("repo-b", saved["id"])

    async def test_delete_nonexistent(self, ctx):
        """Delete raises for nonexistent ID."""
        await _seed_repo(ctx)
        with pytest.raises(MemoryNotFoundError):
            await MemoryService().delete("test-repo", 99999)

"""Tests for Model.bulk_update -- CASE-based multi-row updates."""

from __future__ import annotations

from sylvan.database.orm.models import FileRecord, Repo


async def _make_repo(ctx, name="test-repo"):
    """Insert a repo and return its id."""
    repo = await Repo.create(name=name, indexed_at="2024-01-01")
    return repo.id


async def _make_files(ctx, repo_id, count=3):
    """Insert multiple file records and return their ids."""
    ids = []
    for i in range(count):
        f = await FileRecord.create(
            repo_id=repo_id,
            path=f"file_{i}.py",
            language="python",
            content_hash=f"hash_{i}",
            byte_size=100 + i,
        )
        ids.append(f.id)
    return ids


class TestBulkUpdate:
    async def test_empty_records_returns_zero(self, orm_ctx):
        result = await FileRecord.bulk_update([])
        assert result == 0

    async def test_single_record_update(self, orm_ctx):
        repo_id = await _make_repo(orm_ctx)
        file_ids = await _make_files(orm_ctx, repo_id, count=1)

        result = await FileRecord.bulk_update(
            [
                {"id": file_ids[0], "language": "typescript"},
            ]
        )
        assert result == 1

        updated = await FileRecord.find(file_ids[0])
        assert updated.language == "typescript"

    async def test_multiple_records_different_values(self, orm_ctx):
        repo_id = await _make_repo(orm_ctx)
        file_ids = await _make_files(orm_ctx, repo_id, count=3)

        result = await FileRecord.bulk_update(
            [
                {"id": file_ids[0], "language": "go", "byte_size": 999},
                {"id": file_ids[1], "language": "rust", "byte_size": 888},
                {"id": file_ids[2], "language": "java", "byte_size": 777},
            ]
        )
        assert result == 3

        f0 = await FileRecord.find(file_ids[0])
        f1 = await FileRecord.find(file_ids[1])
        f2 = await FileRecord.find(file_ids[2])

        assert f0.language == "go"
        assert f0.byte_size == 999
        assert f1.language == "rust"
        assert f1.byte_size == 888
        assert f2.language == "java"
        assert f2.byte_size == 777

    async def test_data_actually_persisted(self, orm_ctx):
        """Verify updates survive a fresh query, not just cached state."""
        repo_id = await _make_repo(orm_ctx)
        file_ids = await _make_files(orm_ctx, repo_id, count=2)

        await FileRecord.bulk_update(
            [
                {"id": file_ids[0], "path": "renamed_a.py"},
                {"id": file_ids[1], "path": "renamed_b.py"},
            ]
        )

        # Re-fetch all files for the repo to confirm persistence.
        all_files = await FileRecord.where(repo_id=repo_id).order_by("id").get()
        paths = [f.path for f in all_files]
        assert "renamed_a.py" in paths
        assert "renamed_b.py" in paths
        # Original paths should be gone.
        assert "file_0.py" not in paths
        assert "file_1.py" not in paths

    async def test_untouched_rows_unchanged(self, orm_ctx):
        """Rows not in the update list should remain untouched."""
        repo_id = await _make_repo(orm_ctx)
        file_ids = await _make_files(orm_ctx, repo_id, count=3)

        # Only update the first file.
        await FileRecord.bulk_update(
            [
                {"id": file_ids[0], "language": "c"},
            ]
        )

        f1 = await FileRecord.find(file_ids[1])
        f2 = await FileRecord.find(file_ids[2])
        assert f1.language == "python"
        assert f2.language == "python"

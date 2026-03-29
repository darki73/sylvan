"""Tests for sylvan.analysis.structure.reference_graph.build_reference_graph."""

from __future__ import annotations

import zlib
from datetime import UTC, datetime

from sylvan.database.orm import FileImport, FileRecord, Reference, Repo, Symbol


class TestBuildReferenceGraph:
    async def _setup_repo_with_imports(self, ctx):
        """Create a repo with two files, symbols, and an import between them."""
        backend = ctx.backend
        now = datetime.now(UTC).isoformat()
        repo = await Repo.create(name="ref-repo", source_path="/ref", repo_type="local", indexed_at=now)

        # File A imports from File B
        file_a = await FileRecord.create(
            repo_id=repo.id,
            path="src/a.py",
            language="python",
            content_hash="hash_a",
            byte_size=100,
        )
        file_b = await FileRecord.create(
            repo_id=repo.id,
            path="src/b.py",
            language="python",
            content_hash="hash_b",
            byte_size=100,
        )

        # Store blob content for file A (it references "helper_func")
        content_a = b"from b import helper_func\n\ndef main():\n    helper_func()\n"
        await backend.execute(
            "INSERT INTO blobs (content_hash, content) VALUES (?, ?)",
            ["hash_a", zlib.compress(content_a)],
        )
        await backend.commit()

        # Symbol in file A
        await Symbol.create(
            symbol_id="sym-a-main",
            file_id=file_a.id,
            name="main",
            qualified_name="a.main",
            kind="function",
            language="python",
            line_start=3,
            line_end=4,
            byte_offset=26,
            byte_length=30,
        )
        # Symbol in file B (target)
        await Symbol.create(
            symbol_id="sym-b-helper",
            file_id=file_b.id,
            name="helper_func",
            qualified_name="b.helper_func",
            kind="function",
            language="python",
            line_start=1,
            line_end=5,
            byte_offset=0,
            byte_length=50,
        )

        # Import from A -> B
        await FileImport.create(
            file_id=file_a.id,
            specifier="b",
            resolved_file_id=file_b.id,
            names='["helper_func"]',
        )

        return repo

    async def test_builds_edges(self, ctx):
        from sylvan.analysis.structure.reference_graph import build_reference_graph

        repo = await self._setup_repo_with_imports(ctx)
        edges = await build_reference_graph(repo.id)
        assert edges >= 1

    async def test_creates_reference_records(self, ctx):
        from sylvan.analysis.structure.reference_graph import build_reference_graph

        repo = await self._setup_repo_with_imports(ctx)
        await build_reference_graph(repo.id)

        refs = await Reference.all().get()
        assert len(refs) >= 1
        ref = refs[0]
        assert ref.target_symbol_id == "sym-b-helper"

    async def test_empty_repo(self, ctx):
        from sylvan.analysis.structure.reference_graph import build_reference_graph

        now = datetime.now(UTC).isoformat()
        repo = await Repo.create(name="empty-ref", source_path="/er", repo_type="local", indexed_at=now)
        edges = await build_reference_graph(repo.id)
        assert edges == 0

    async def test_unresolved_import_uses_path_matching(self, ctx):
        """Imports without resolved_file_id fall back to path matching."""
        from sylvan.analysis.structure.reference_graph import build_reference_graph

        backend = ctx.backend
        now = datetime.now(UTC).isoformat()
        repo = await Repo.create(name="unresolved-ref", source_path="/ur", repo_type="local", indexed_at=now)

        file_a = await FileRecord.create(
            repo_id=repo.id,
            path="src/caller.py",
            language="python",
            content_hash="hash_caller",
            byte_size=80,
        )
        file_b = await FileRecord.create(
            repo_id=repo.id,
            path="src/utils.py",
            language="python",
            content_hash="hash_utils",
            byte_size=80,
        )

        content = b"import utils\n\ndef go():\n    utils.do_work()\n"
        await backend.execute(
            "INSERT INTO blobs (content_hash, content) VALUES (?, ?)",
            ["hash_caller", zlib.compress(content)],
        )
        await backend.commit()

        await Symbol.create(
            symbol_id="sym-caller-go",
            file_id=file_a.id,
            name="go",
            qualified_name="caller.go",
            kind="function",
            language="python",
            line_start=3,
            line_end=4,
            byte_offset=13,
            byte_length=30,
        )
        await Symbol.create(
            symbol_id="sym-utils-do",
            file_id=file_b.id,
            name="do_work",
            qualified_name="utils.do_work",
            kind="function",
            language="python",
            line_start=1,
            line_end=3,
            byte_offset=0,
            byte_length=40,
        )

        # Import without resolved_file_id - will try path matching
        await FileImport.create(
            file_id=file_a.id,
            specifier="utils",
        )

        edges = await build_reference_graph(repo.id)
        # Should resolve "utils" to "utils.py" via stem matching
        assert edges >= 1

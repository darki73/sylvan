"""Tests for sylvan.tools.analysis.get_dependency_graph."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def indexed_repo(tmp_path):
    """Index a project with imports for dependency graph tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()
    reset_session()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "base.py").write_text(
        'class Animal:\n    """Base animal class."""\n    pass\n',
        encoding="utf-8",
    )
    (proj / "dog.py").write_text(
        "from base import Animal\n\nclass Dog(Animal):\n    pass\n",
        encoding="utf-8",
    )
    (proj / "app.py").write_text(
        "from dog import Dog\n\ndef main():\n    d = Dog()\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="graph-repo")
    await backend.commit()
    assert result.symbols_extracted >= 3

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestGetDependencyGraph:
    async def test_returns_nodes_and_edges(self, indexed_repo):
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        resp = await get_dependency_graph(repo="graph-repo", file_path="dog.py")

        assert "_meta" in resp
        assert "nodes" in resp
        assert "edges" in resp
        assert "target" in resp
        assert resp["target"] == "dog.py"

        meta = resp["_meta"]
        assert "node_count" in meta
        assert "edge_count" in meta
        assert "direction" in meta

    async def test_target_is_marked(self, indexed_repo):
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        resp = await get_dependency_graph(repo="graph-repo", file_path="dog.py")

        if "dog.py" in resp["nodes"]:
            assert resp["nodes"]["dog.py"]["is_target"] is True

    async def test_direction_imports(self, indexed_repo):
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        resp = await get_dependency_graph(
            repo="graph-repo",
            file_path="dog.py",
            direction="imports",
        )

        assert "_meta" in resp
        assert resp["_meta"]["direction"] == "imports"

    async def test_direction_importers(self, indexed_repo):
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        resp = await get_dependency_graph(
            repo="graph-repo",
            file_path="dog.py",
            direction="importers",
        )

        assert "_meta" in resp
        assert resp["_meta"]["direction"] == "importers"

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        with pytest.raises(RepoNotFoundError):
            await get_dependency_graph(repo="nonexistent", file_path="dog.py")

    async def test_file_not_found(self, indexed_repo):
        from sylvan.error_codes import IndexFileNotFoundError
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        with pytest.raises(IndexFileNotFoundError):
            await get_dependency_graph(repo="graph-repo", file_path="nonexistent.py")

    async def test_depth_clamped(self, indexed_repo):
        from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

        resp = await get_dependency_graph(
            repo="graph-repo",
            file_path="dog.py",
            depth=10,
        )

        assert resp["_meta"]["depth"] == 3


class TestBfsHelpers:
    async def test_bfs_forward_empty(self, indexed_repo):
        from sylvan.services.analysis import _bfs_forward

        nodes: set[int] = set()
        edges: list[tuple[int, int]] = []
        await _bfs_forward(999999, 1, nodes, edges)
        assert 999999 in nodes
        assert len(edges) == 0

    async def test_bfs_reverse_empty(self, indexed_repo):
        from sylvan.services.analysis import _bfs_reverse

        nodes: set[int] = set()
        edges: list[tuple[int, int]] = []
        await _bfs_reverse(999999, 1, nodes, edges)
        assert 999999 in nodes
        assert len(edges) == 0

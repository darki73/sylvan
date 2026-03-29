"""Tests for ORM cascade delete behavior across the model graph."""

from __future__ import annotations

from sylvan.database.orm import FileRecord, Quality, Reference, Repo, Section, Symbol
from sylvan.database.orm.models.workspace import Workspace


async def _seed_full_graph(ctx):
    """Seed a repo with files, symbols, quality, references, and sections."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (id, name, source_path, indexed_at, repo_type) "
        "VALUES (1, 'cascade-repo', '/tmp/cascade', '2024-01-01', 'local')"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (1, 1, 'src/main.py', 'python', 'h1', 100)"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (2, 1, 'docs/README.md', 'markdown', 'h2', 200)"
    )
    # Symbols
    await backend.execute(
        "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        "VALUES (1, 1, 'src/main.py::main#function', 'main', 'main', 'function', "
        "'python', 0, 50)"
    )
    await backend.execute(
        "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        "VALUES (2, 1, 'src/main.py::helper#function', 'helper', 'helper', 'function', "
        "'python', 50, 40)"
    )
    # Quality
    await backend.execute(
        "INSERT INTO quality (symbol_id, has_tests, has_docs) VALUES ('src/main.py::main#function', 1, 1)"
    )
    # References
    await backend.execute(
        'INSERT INTO "references" (source_symbol_id, target_symbol_id, target_specifier) '
        "VALUES ('src/main.py::main#function', 'src/main.py::helper#function', 'helper')"
    )
    # Sections
    await backend.execute(
        "INSERT INTO sections (id, file_id, section_id, title, level, byte_start, byte_end) "
        "VALUES (1, 2, 'cascade-repo::docs/README.md::intro#section', 'Intro', 1, 0, 50)"
    )
    await backend.commit()


class TestFileDeleteCascades:
    async def test_file_delete_cascades_symbols(self, ctx):
        await _seed_full_graph(ctx)
        file_rec = await FileRecord.where(id=1).first()
        assert file_rec is not None

        await file_rec.delete()

        syms = await Symbol.where(file_id=1).get()
        assert len(syms) == 0

    async def test_file_delete_cascades_sections(self, ctx):
        await _seed_full_graph(ctx)
        file_rec = await FileRecord.where(id=2).first()
        assert file_rec is not None

        await file_rec.delete()

        secs = await Section.where(file_id=2).get()
        assert len(secs) == 0


class TestSymbolDeleteCascades:
    async def test_symbol_delete_cascades_quality(self, ctx):
        await _seed_full_graph(ctx)
        sym = await Symbol.where(symbol_id="src/main.py::main#function").first()
        assert sym is not None

        await sym.delete()

        quality = await Quality.where(symbol_id="src/main.py::main#function").first()
        assert quality is None

    async def test_symbol_delete_cascades_references(self, ctx):
        await _seed_full_graph(ctx)
        sym = await Symbol.where(symbol_id="src/main.py::main#function").first()
        assert sym is not None

        await sym.delete()

        refs = await Reference.where(source_symbol_id="src/main.py::main#function").get()
        assert len(refs) == 0


class TestRepoDeleteCascades:
    async def test_repo_delete_cascades_files(self, ctx):
        await _seed_full_graph(ctx)
        repo = await Repo.where(name="cascade-repo").first()
        assert repo is not None

        await repo.delete()

        files = await FileRecord.where(repo_id=1).get()
        assert len(files) == 0

    async def test_repo_delete_cascades_full_chain(self, ctx):
        await _seed_full_graph(ctx)
        repo = await Repo.where(name="cascade-repo").first()
        assert repo is not None

        await repo.delete()

        # Files gone
        assert await FileRecord.where(repo_id=1).count() == 0
        # Symbols gone
        assert await Symbol.where(symbol_id="src/main.py::main#function").first() is None
        assert await Symbol.where(symbol_id="src/main.py::helper#function").first() is None
        # Quality gone
        assert await Quality.where(symbol_id="src/main.py::main#function").first() is None
        # References gone
        assert await Reference.where(source_symbol_id="src/main.py::main#function").count() == 0
        # Sections gone
        assert await Section.where(section_id="cascade-repo::docs/README.md::intro#section").first() is None


class TestWorkspacePivotCleanup:
    async def test_workspace_delete_detaches_repos(self, ctx):
        await _seed_full_graph(ctx)
        # Create workspace and attach repo
        ws = await Workspace.create(name="ws-cascade", created_at="2024-01-01")
        await ws.attach("repos", 1)

        # Verify repo is attached
        ws = await Workspace.where(name="ws-cascade").with_("repos").first()
        assert len(ws.repos) == 1

        # Delete workspace
        await ws.detach("repos")
        await ws.delete()

        # Workspace gone, repo still exists
        assert await Workspace.where(name="ws-cascade").first() is None
        assert await Repo.where(name="cascade-repo").first() is not None

    async def test_repo_delete_detaches_from_workspaces(self, ctx):
        await _seed_full_graph(ctx)
        ws = await Workspace.create(name="ws-detach", created_at="2024-01-01")
        await ws.attach("repos", 1)

        # Delete the repo
        repo = await Repo.where(name="cascade-repo").first()
        await repo.delete()

        # Workspace still exists, but repo is gone from pivot
        ws = await Workspace.where(name="ws-detach").with_("repos").first()
        assert ws is not None
        assert len(ws.repos) == 0

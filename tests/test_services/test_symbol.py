"""Tests for sylvan.services.symbol - SymbolService fluent builder."""

from __future__ import annotations

import hashlib

import pytest

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.error_codes import SymbolNotFoundError
from sylvan.services.symbol import SymbolResult, SymbolService


async def _seed_repo(ctx, name="test-repo"):
    """Create a repo."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '/tmp/{name}', '2024-01-01', 'local')"
    )
    await backend.commit()
    return await Repo.where(name=name).first()


async def _seed_file_with_blob(ctx, repo_id, path="src/main.py", language="python", content=b"def main(): pass"):
    """Create a file record with a stored blob."""
    content_hash = hashlib.sha256(content).hexdigest()
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO files (repo_id, path, language, content_hash, byte_size) "
        f"VALUES ({repo_id}, '{path}', '{language}', '{content_hash}', {len(content)})"
    )
    await Blob.store(content_hash, content)
    await backend.commit()
    return await FileRecord.where(path=path).first()


async def _seed_symbol(
    ctx,
    file_id,
    name="main",
    kind="function",
    byte_offset=0,
    byte_length=16,
    content_hash=None,
    line_start=1,
    line_end=1,
    parent_symbol_id=None,
    path="src/main.py",
):
    """Create a symbol."""
    sid = f"{path}::{name}#{kind}"
    ch_val = f"'{content_hash}'" if content_hash else "NULL"
    ps_val = f"'{parent_symbol_id}'" if parent_symbol_id else "NULL"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, "
        "language, signature, byte_offset, byte_length, line_start, line_end, "
        "parent_symbol_id, content_hash) "
        f"VALUES ({file_id}, '{sid}', '{name}', '{name}', '{kind}', 'python', "
        f"'def {name}()', {byte_offset}, {byte_length}, {line_start}, {line_end}, "
        f"{ps_val}, {ch_val})"
    )
    await backend.commit()
    return await Symbol.where(symbol_id=sid).first()


class TestSymbolServiceFind:
    async def test_find_symbol(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sym = await _seed_symbol(ctx, file_rec.id)

        result = await SymbolService().find(sym.symbol_id)
        assert result is not None
        assert isinstance(result, SymbolResult)
        assert result.name == "main"

    async def test_find_missing(self, ctx):
        with pytest.raises(SymbolNotFoundError):
            await SymbolService().find("nonexistent::ghost#function")


class TestSymbolServiceEnrichment:
    async def test_with_source(self, ctx):
        source = b"def hello():\n    print('hi')\n"
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=source)
        sym = await _seed_symbol(ctx, file_rec.id, name="hello", byte_offset=0, byte_length=len(source))

        result = await SymbolService().with_source().find(sym.symbol_id)
        assert result.source is not None
        assert "def hello()" in result.source

    async def test_with_file(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sym = await _seed_symbol(ctx, file_rec.id)

        result = await SymbolService().with_file().find(sym.symbol_id)
        assert result.file_record is not None
        assert result.file_record.path == "src/main.py"

    async def test_verified_no_drift(self, ctx):
        source = b"def verified(): pass"
        content_hash = hashlib.sha256(source).hexdigest()
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=source)
        sym = await _seed_symbol(
            ctx,
            file_rec.id,
            name="verified",
            byte_offset=0,
            byte_length=len(source),
            content_hash=content_hash,
        )

        result = await SymbolService().with_source().verified().find(sym.symbol_id)
        assert result.hash_verified is True
        assert result.drift_warning is None


class TestSymbolServiceBatch:
    async def test_find_many(self, ctx):
        repo = await _seed_repo(ctx)
        content = b"def alpha(): pass\ndef beta(): pass\n"
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        sym_a = await _seed_symbol(ctx, file_rec.id, name="alpha", byte_offset=0, byte_length=17)
        sym_b = await _seed_symbol(ctx, file_rec.id, name="beta", byte_offset=18, byte_length=16)

        results = await SymbolService().find_many([sym_a.symbol_id, sym_b.symbol_id])
        assert len(results) == 2
        names = {r.name for r in results}
        assert names == {"alpha", "beta"}

    async def test_find_many_skips_missing(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sym = await _seed_symbol(ctx, file_rec.id)

        results = await SymbolService().find_many([sym.symbol_id, "missing::nope#function"])
        assert len(results) == 1


class TestSymbolServiceOutlines:
    async def test_file_outline(self, ctx):
        repo = await _seed_repo(ctx, name="outline-repo")
        content = b"class Foo:\n    def bar(self): pass\n"
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        cls_sym = await _seed_symbol(
            ctx,
            file_rec.id,
            name="Foo",
            kind="class",
            byte_offset=0,
            byte_length=10,
            line_start=1,
            line_end=2,
        )
        await _seed_symbol(
            ctx,
            file_rec.id,
            name="bar",
            kind="method",
            byte_offset=10,
            byte_length=24,
            line_start=2,
            line_end=2,
            parent_symbol_id=cls_sym.symbol_id,
        )

        outline = await SymbolService().file_outline("outline-repo", "src/main.py")
        assert outline["file"] == "src/main.py"
        assert outline["symbol_count"] == 2
        # Root has one class with one child method
        assert len(outline["outline"]) == 1
        assert outline["outline"][0]["name"] == "Foo"
        assert len(outline["outline"][0]["children"]) == 1
        assert outline["outline"][0]["children"][0]["name"] == "bar"

    async def test_file_tree(self, ctx):
        repo = await _seed_repo(ctx, name="tree-repo")
        await _seed_file_with_blob(ctx, repo.id, path="src/a.py", content=b"x = 1")
        await _seed_file_with_blob(ctx, repo.id, path="src/b.py", content=b"y = 2")
        await _seed_file_with_blob(ctx, repo.id, path="lib/c.py", content=b"z = 3")

        tree = await SymbolService().file_tree("tree-repo", max_depth=3)
        assert "tree" in tree
        assert tree["files"] == 3
        assert "tree-repo/" in tree["tree"]

    async def test_repo_outline(self, ctx):
        repo = await _seed_repo(ctx, name="ro-repo")
        content = b"def func(): pass"
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        await _seed_symbol(ctx, file_rec.id)

        outline = await SymbolService().repo_outline("ro-repo")
        assert outline["repo"] == "ro-repo"
        assert outline["files"] == 1
        assert outline["symbols"] == 1


class TestSymbolResult:
    async def test_repr(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sym = await _seed_symbol(ctx, file_rec.id)
        result = SymbolResult(sym)
        assert "src/main.py::main#function" in repr(result)

    async def test_proxies_model_fields(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sym = await _seed_symbol(ctx, file_rec.id)
        result = SymbolResult(sym)
        assert result.name == "main"
        assert result.kind == "function"

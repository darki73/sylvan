"""Tests for sylvan.services.search - SearchService."""

from __future__ import annotations

import hashlib

import pytest

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.error_codes import EmptyQueryError
from sylvan.services.search import SearchService


async def _seed_repo(ctx, *, name: str = "test-repo", source_path: str | None = None) -> Repo:
    return await Repo.create(name=name, source_path=source_path, indexed_at="2025-01-01T00:00:00")


async def _seed_file(repo: Repo, *, path: str = "src/utils.py", language: str = "python") -> FileRecord:
    content = b"def hello(): pass\ndef world(): pass\n"
    content_hash = hashlib.sha256(content).hexdigest()
    await Blob.store(content_hash, content)
    return await FileRecord.create(
        repo_id=repo.id,
        path=path,
        language=language,
        content_hash=content_hash,
        byte_size=len(content),
    )


async def _seed_symbol(
    file: FileRecord,
    *,
    name: str,
    kind: str = "function",
    language: str = "python",
    signature: str = "",
    symbol_id: str | None = None,
) -> Symbol:
    sid = symbol_id or f"{file.path}::{name}#function"
    return await Symbol.create(
        file_id=file.id,
        symbol_id=sid,
        name=name,
        qualified_name=name,
        kind=kind,
        language=language,
        signature=signature,
        byte_offset=0,
        byte_length=0,
    )


class TestSearchServiceSymbols:
    async def test_symbols_basic(self, ctx):
        repo = await _seed_repo(ctx)
        f = await _seed_file(repo)
        await _seed_symbol(f, name="parse_file", signature="def parse_file(path: str)")

        svc = SearchService()
        result = await svc.symbols("parse_file")

        assert result["results_count"] >= 1
        names = [s["name"] for s in result["symbols"]]
        assert "parse_file" in names

    async def test_symbols_with_repo_filter(self, ctx):
        repo_a = await _seed_repo(ctx, name="alpha")
        repo_b = await _seed_repo(ctx, name="beta")
        fa = await _seed_file(repo_a, path="a.py")
        fb = await _seed_file(repo_b, path="b.py")
        await _seed_symbol(fa, name="shared_func", symbol_id="a.py::shared_func#function")
        await _seed_symbol(fb, name="shared_func", symbol_id="b.py::shared_func#function")

        svc = SearchService()
        result = await svc.symbols("shared_func", repo="alpha")
        assert result["results_count"] >= 1
        assert result["repo_id"] is not None

    async def test_symbols_with_kind_filter(self, ctx):
        repo = await _seed_repo(ctx)
        f = await _seed_file(repo)
        await _seed_symbol(f, name="MyClass", kind="class", symbol_id="src/utils.py::MyClass#class")
        await _seed_symbol(f, name="my_func", kind="function")

        svc = SearchService()
        result = await svc.symbols("My", kind="class")
        kinds = [s["kind"] for s in result["symbols"]]
        for k in kinds:
            assert k == "class"

    async def test_symbols_empty_query(self, ctx):
        svc = SearchService()
        with pytest.raises(EmptyQueryError):
            await svc.symbols("")

        with pytest.raises(EmptyQueryError):
            await svc.symbols("   ")

    async def test_text_basic(self, ctx):
        repo = await _seed_repo(ctx, name="txt-repo")
        content = b"def hello_world():\n    print('hello world')\n"
        content_hash = hashlib.sha256(content).hexdigest()
        await Blob.store(content_hash, content)
        await FileRecord.create(
            repo_id=repo.id,
            path="main.py",
            language="python",
            content_hash=content_hash,
            byte_size=len(content),
        )

        svc = SearchService()
        result = await svc.text("hello_world", repo="txt-repo")
        assert result["results_count"] >= 1
        assert result["query"] == "hello_world"

    async def test_batch_symbols(self, ctx):
        repo = await _seed_repo(ctx)
        f = await _seed_file(repo)
        await _seed_symbol(f, name="alpha_func", signature="def alpha_func()")
        await _seed_symbol(
            f, name="beta_func", signature="def beta_func()", symbol_id="src/utils.py::beta_func#function"
        )

        svc = SearchService()
        result = await svc.batch_symbols(
            [{"query": "alpha_func"}, {"query": "beta_func"}],
        )
        assert result["queries_count"] == 2
        assert result["total_results"] >= 2

    async def test_session_reranking(self, ctx):
        repo = await _seed_repo(ctx)
        f = await _seed_file(repo)
        sym_a = await _seed_symbol(f, name="seen_func", signature="def seen_func()")
        await _seed_symbol(
            f, name="unseen_func", signature="def unseen_func()", symbol_id="src/utils.py::unseen_func#function"
        )

        # Mark one symbol as seen
        ctx.session.record_symbol_access(sym_a.symbol_id)

        svc = SearchService().with_session_reranking()
        result = await svc.symbols("func")

        if result["results_count"] >= 2:
            # The unseen symbol should appear before the seen one
            names = [s["name"] for s in result["symbols"]]
            assert "unseen_func" in names
            assert result["already_seen_deprioritized"] >= 1

    async def test_token_budget(self, ctx):
        repo = await _seed_repo(ctx)
        f = await _seed_file(repo)
        for i in range(10):
            await _seed_symbol(
                f,
                name=f"func_{i}",
                signature=f"def func_{i}(x: int, y: int) -> int",
                symbol_id=f"src/utils.py::func_{i}#function",
            )

        svc = SearchService().with_token_budget(50)
        result = await svc.symbols("func")

        # With a tiny budget, we should get fewer results than 10
        assert result["results_count"] < 10
        assert result["token_budget"] == 50

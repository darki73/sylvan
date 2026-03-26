"""Public Python API for sylvan.

Usage:
    from sylvan import Sylvan

    with Sylvan() as s:
        s.index("/path/to/project", name="my-project")
        results = s.search("dispatch", repo="my-project")
        source = s.get_source(results[0]["symbol_id"])
        impact = s.blast_radius(results[0]["symbol_id"])
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


class Sylvan:
    """High-level Python API for sylvan.

    Handles all backend setup, migrations, context, and extension loading
    internally. All methods are synchronous.

    Args:
        db_path: Path to the SQLite database. Defaults to ~/.sylvan/sylvan.db.
        load_extensions: Whether to load native + user extensions. Defaults to True.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        load_extensions: bool = True,
    ) -> None:
        self._loop = asyncio.new_event_loop()
        self._backend = None
        self._ctx = None
        self._token = None
        self._run(self._setup(db_path, load_extensions))
        # Set context in the main thread AFTER setup completes
        from sylvan.context import set_context

        self._token = set_context(self._ctx)

    def _run(self, coro: Any) -> Any:
        """Run an async coroutine synchronously."""
        return self._loop.run_until_complete(coro)

    async def _setup(
        self,
        db_path: str | Path | None,
        load_extensions: bool,
    ) -> None:
        """Initialize backend, run migrations, set context."""
        from sylvan.config import get_config
        from sylvan.context import SylvanContext
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations
        from sylvan.database.orm.runtime.query_cache import QueryCache
        from sylvan.session.tracker import SessionTracker

        config = get_config()
        path = str(db_path) if db_path else str(config.db_path)

        backend = SQLiteBackend(path)
        await backend.connect()
        await run_migrations(backend)

        ctx = SylvanContext(
            backend=backend,
            config=config,
            session=SessionTracker(),
            cache=QueryCache(),
        )

        self._backend = backend
        self._ctx = ctx

        if load_extensions:
            from sylvan.extensions.loader import load_extensions as _load

            _load()

    def close(self) -> None:
        """Close the database connection and clean up."""
        if self._token:
            from sylvan.context import reset_context

            reset_context(self._token)
            self._token = None
        if self._backend:
            self._run(self._backend.disconnect())
            self._backend = None
        self._loop.close()

    def __enter__(self) -> Sylvan:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Indexing ──────────────────────────────────────────────

    def index(
        self,
        path: str | Path,
        name: str | None = None,
    ) -> dict:
        """Index a local folder.

        Args:
            path: Absolute path to the folder.
            name: Display name for the repo. Defaults to folder name.

        Returns:
            Dict with files_indexed, symbols_extracted, etc.
        """

        async def _index() -> dict:
            from sylvan.indexing.pipeline.orchestrator import index_folder

            result = await index_folder(str(path), name or Path(path).name)
            return {
                "files_indexed": result.files_indexed,
                "files_skipped": result.files_skipped,
                "symbols_extracted": result.symbols_extracted,
                "sections_extracted": result.sections_extracted,
                "imports_extracted": result.imports_extracted,
                "imports_resolved": result.imports_resolved,
                "errors": result.errors,
            }

        return self._run(_index())

    def add_library(self, package: str) -> dict:
        """Index a third-party library.

        Args:
            package: Package spec (e.g. "pip/starlette@1.0.0", "npm/react@18").

        Returns:
            Dict with indexing results.
        """

        async def _add() -> dict:
            from sylvan.libraries.manager import add_library

            return await add_library(package)

        return self._run(_add())

    # ── Search ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        repo: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search for symbols by name, signature, or keyword.

        Args:
            query: Search query.
            repo: Filter to a specific repository.
            kind: Filter by symbol kind (function, class, method, constant, type).
            language: Filter by programming language.
            max_results: Maximum results to return.

        Returns:
            List of symbol dicts with id, name, kind, signature, file, line.
        """

        async def _search() -> list[dict]:
            from sylvan.database.orm import Symbol

            qb = Symbol.search(query)
            if repo:
                qb = qb.in_repo(repo)
            if kind:
                qb = qb.where(kind=kind)
            if language:
                qb = qb.where(language=language)
            qb = qb.limit(max_results)

            results = await qb.get()
            return [
                {
                    "symbol_id": s.symbol_id,
                    "name": s.name,
                    "qualified_name": s.qualified_name,
                    "kind": s.kind,
                    "language": s.language,
                    "file": await s._resolve_file_path(),
                    "signature": s.signature or "",
                    "line": s.line_start,
                }
                for s in results
            ]

        return self._run(_search())

    def search_text(
        self,
        query: str,
        *,
        repo: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Full-text search across file content.

        Args:
            query: Text to search for.
            repo: Filter to a specific repository.
            max_results: Maximum results to return.

        Returns:
            List of match dicts with file, line, match, context.
        """

        async def _search() -> list[dict]:
            from sylvan.tools.search.search_text import search_text

            return await search_text(
                query=query,
                repo=repo,
                max_results=max_results,
            )

        result = self._run(_search())
        return result.get("matches", [])

    # ── Symbol retrieval ──────────────────────────────────────

    def get_source(self, symbol_id: str) -> str:
        """Get the source code of a symbol.

        Args:
            symbol_id: Symbol identifier from search results.

        Returns:
            Source code string.
        """

        async def _get() -> str:
            from sylvan.database.orm import Symbol

            sym = await Symbol.where(symbol_id=symbol_id).with_("file").first()
            if sym is None:
                return ""
            return await sym.get_source() or ""

        return self._run(_get())

    def get_outline(self, repo: str, file_path: str) -> list[dict]:
        """Get a hierarchical symbol outline for a file.

        Args:
            repo: Repository name.
            file_path: Relative file path.

        Returns:
            List of symbol dicts with id, name, kind, signature, line_start, line_end.
        """

        async def _outline() -> list[dict]:
            from sylvan.database.orm import FileRecord, Symbol

            file_rec = (
                await FileRecord.query()
                .join("repos", "repos.id = files.repo_id")
                .where("repos.name", repo)
                .where(path=file_path)
                .first()
            )
            if not file_rec:
                return []

            symbols = await Symbol.where(file_id=file_rec.id).order_by("line_start").get()
            return [
                {
                    "symbol_id": s.symbol_id,
                    "name": s.name,
                    "kind": s.kind,
                    "signature": s.signature or "",
                    "line_start": s.line_start,
                    "line_end": s.line_end,
                }
                for s in symbols
            ]

        return self._run(_outline())

    # ── Analysis ──────────────────────────────────────────────

    def blast_radius(self, symbol_id: str) -> dict:
        """Get the blast radius of a symbol.

        Args:
            symbol_id: Symbol identifier.

        Returns:
            Dict with confirmed and potential affected files.
        """

        async def _blast() -> dict:
            from sylvan.tools.analysis.get_blast_radius import get_blast_radius

            return await get_blast_radius(symbol_id=symbol_id)

        return self._run(_blast())

    def importers(self, repo: str, file_path: str) -> list[dict]:
        """Find files that import a given file.

        Args:
            repo: Repository name.
            file_path: Relative file path.

        Returns:
            List of importer dicts with path, language, symbol_count.
        """

        async def _importers() -> list[dict]:
            from sylvan.tools.analysis.find_importers import find_importers

            result = await find_importers(repo=repo, file_path=file_path)
            return result.get("importers", [])

        return self._run(_importers())

    def dependency_graph(self, repo: str, file_path: str) -> dict:
        """Get the dependency graph for a file.

        Args:
            repo: Repository name.
            file_path: Relative file path.

        Returns:
            Dict with nodes and edges.
        """

        async def _graph() -> dict:
            from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

            return await get_dependency_graph(repo=repo, file_path=file_path)

        return self._run(_graph())

    def class_hierarchy(self, repo: str, class_name: str) -> dict:
        """Get the class hierarchy for a class.

        Args:
            repo: Repository name.
            class_name: Class name to look up.

        Returns:
            Dict with ancestors and descendants.
        """

        async def _hierarchy() -> dict:
            from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy

            return await get_class_hierarchy(repo=repo, class_name=class_name)

        return self._run(_hierarchy())

    # ── Repos ─────────────────────────────────────────────────

    def repos(self) -> list[dict]:
        """List all indexed repositories.

        Returns:
            List of repo dicts with name, file_count, symbol_count, indexed_at.
        """

        async def _repos() -> list[dict]:
            from sylvan.database.orm import Repo

            repos = await Repo.all().get()
            return [
                {
                    "name": r.name,
                    "source_path": r.source_path,
                    "indexed_at": r.indexed_at,
                    "git_head": r.git_head,
                }
                for r in repos
            ]

        return self._run(_repos())

    def remove(self, repo: str) -> dict:
        """Remove an indexed repository and all its data.

        Args:
            repo: Repository name.

        Returns:
            Dict with deletion counts.
        """

        async def _remove() -> dict:
            from sylvan.tools.meta.remove_repo import remove_repo

            return await remove_repo(repo=repo)

        return self._run(_remove())

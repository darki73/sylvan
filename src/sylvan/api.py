"""Public Python API for sylvan.

Usage::

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
    """High-level synchronous API for sylvan code intelligence.

    Manages backend lifecycle, migrations, context, and extension loading
    internally. All public methods are synchronous and return plain dicts
    or lists - no ORM objects leak out.

    Args:
        db_path: Path to the SQLite database file. When ``None``, falls
            back to the path configured in ``~/.sylvan/config.yaml``
            (default ``~/.sylvan/sylvan.db``).
        load_extensions: Whether to discover and load native and user
            extensions at init time. Pass ``False`` to skip extension
            loading for faster startup in scripts that don't need it.

    Example::

        with Sylvan() as s:
            s.index("/code/my-project")
            for sym in s.search("parse", repo="my-project", kind="function"):
                print(sym["name"], sym["signature"])
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
        from sylvan.context import set_context

        self._token = set_context(self._ctx)

    def _run(self, coro: Any) -> Any:
        return self._loop.run_until_complete(coro)

    async def _setup(
        self,
        db_path: str | Path | None,
        load_ext: bool,
    ) -> None:
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

        self._backend = backend
        self._ctx = SylvanContext(
            backend=backend,
            config=config,
            session=SessionTracker(),
            cache=QueryCache(),
        )

        if load_ext:
            from sylvan.extensions.loader import load_extensions

            load_extensions()

    def close(self) -> None:
        """Release the database connection and reset the context.

        Called automatically when used as a context manager. Safe to call
        multiple times.
        """
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

    def index(
        self,
        path: str | Path,
        name: str | None = None,
    ) -> dict:
        """Index a local folder into the sylvan database.

        Parses source files with tree-sitter, extracts symbols, resolves
        imports, and stores everything for search. Incremental - only
        reprocesses files whose content hash changed.

        Args:
            path: Absolute path to the folder to index.
            name: Display name for the repository. Defaults to the
                folder's basename.

        Returns:
            A dict with keys ``files_indexed``, ``symbols_extracted``,
            ``sections_extracted``, ``imports_extracted``,
            ``imports_resolved``, ``files_skipped``, and ``errors``.
        """

        async def _do() -> dict:
            from sylvan.indexing.pipeline.orchestrator import index_folder

            r = await index_folder(str(path), name or Path(path).name)
            return {
                "files_indexed": r.files_indexed,
                "files_skipped": r.files_skipped,
                "symbols_extracted": r.symbols_extracted,
                "sections_extracted": r.sections_extracted,
                "imports_extracted": r.imports_extracted,
                "imports_resolved": r.imports_resolved,
                "errors": r.errors,
            }

        return self._run(_do())

    def add_library(self, package: str) -> dict:
        """Fetch and index a third-party library's source code.

        Downloads the package source from a registry (PyPI, npm, crates.io,
        pkg.go.dev) and indexes it so you can search its symbols.

        Args:
            package: Package specifier in ``manager/name@version`` format.
                Examples: ``"pip/starlette@1.0.0"``, ``"npm/react@18"``,
                ``"cargo/serde"``.

        Returns:
            A dict with indexing results including ``symbol_count`` and
            ``file_count``.
        """

        async def _do() -> dict:
            from sylvan.libraries.manager import add_library

            return await add_library(package)

        return self._run(_do())

    def search(
        self,
        query: str,
        *,
        repo: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search indexed symbols by name, signature, or keyword.

        Uses FTS5 full-text search with BM25 ranking. Results include
        symbol metadata but not source code - use :meth:`get_source`
        to retrieve the actual implementation.

        Args:
            query: Search terms. Matched against symbol name, qualified
                name, signature, docstring, and summary.
            repo: Restrict results to a single repository name.
            kind: Filter by symbol kind. One of ``"function"``,
                ``"class"``, ``"method"``, ``"constant"``, ``"type"``.
            language: Filter by programming language identifier
                (e.g. ``"python"``, ``"typescript"``).
            max_results: Maximum number of results to return.

        Returns:
            A list of dicts, each containing ``symbol_id``, ``name``,
            ``qualified_name``, ``kind``, ``language``, ``file``,
            ``signature``, and ``line``.
        """

        async def _do() -> list[dict]:
            from sylvan.database.orm import Symbol

            qb = Symbol.search(query)
            if repo:
                qb = qb.in_repo(repo)
            if kind:
                qb = qb.where(kind=kind)
            if language:
                qb = qb.where(language=language)

            results = await qb.limit(max_results).get()
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

        return self._run(_do())

    def search_text(
        self,
        query: str,
        *,
        repo: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Search across raw file content (like grep).

        Searches the stored blob content of all indexed files. Useful
        for finding string literals, comments, or patterns that aren't
        captured as symbols.

        Args:
            query: Text to search for (case-insensitive substring match).
            repo: Restrict results to a single repository name.
            max_results: Maximum number of matching lines to return.

        Returns:
            A list of match dicts with ``file_path``, ``line``,
            ``match``, and ``context``.
        """

        async def _do() -> list[dict]:
            from sylvan.tools.search.search_text import search_text

            return await search_text(
                query=query,
                repo=repo,
                max_results=max_results,
            )

        result = self._run(_do())
        return result.get("matches", [])

    def get_source(self, symbol_id: str) -> str:
        """Retrieve the source code of a symbol by its ID.

        Extracts the symbol's byte range from the stored file blob.
        Returns just the symbol's source, not the entire file.

        Args:
            symbol_id: The stable symbol identifier, as returned in
                search results (e.g. ``"src/main.py::main#function"``).

        Returns:
            The symbol's source code as a string, or an empty string
            if the symbol or its blob is not found.
        """

        async def _do() -> str:
            from sylvan.database.orm import Symbol

            sym = await Symbol.where(symbol_id=symbol_id).with_("file").first()
            if sym is None:
                return ""
            return await sym.get_source() or ""

        return self._run(_do())

    def get_outline(self, repo: str, file_path: str) -> list[dict]:
        """Get all symbols in a file, ordered by line number.

        Returns a flat list of every function, class, method, constant,
        and type defined in the file. Cheaper than reading the file -
        only returns metadata, not source.

        Args:
            repo: Repository name as shown in :meth:`repos`.
            file_path: Relative path within the repository
                (e.g. ``"src/main.py"``).

        Returns:
            A list of dicts with ``symbol_id``, ``name``, ``kind``,
            ``signature``, ``line_start``, and ``line_end``.
            Empty list if the file is not indexed.
        """

        async def _do() -> list[dict]:
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

        return self._run(_do())

    def blast_radius(self, symbol_id: str) -> dict:
        """Determine what files are affected if a symbol changes.

        Traces the import graph outward from the symbol's file to find
        confirmed references (file imports the module AND mentions the
        symbol name) and potential references (file imports the module
        but the symbol name isn't found in the source).

        Args:
            symbol_id: The symbol to analyze.

        Returns:
            A dict with ``symbol`` (the target), ``confirmed`` (list of
            files with direct references), ``potential`` (list of files
            that import the module), and ``depth_reached``.
        """

        async def _do() -> dict:
            from sylvan.tools.analysis.get_blast_radius import get_blast_radius

            return await get_blast_radius(symbol_id=symbol_id)

        return self._run(_do())

    def importers(self, repo: str, file_path: str) -> list[dict]:
        """Find all files that import a given file.

        Uses the resolved import graph built during indexing, not
        grep-based matching.

        Args:
            repo: Repository name.
            file_path: Relative path of the file to check.

        Returns:
            A list of dicts with ``path``, ``language``,
            ``symbol_count``, and ``has_importers`` for each
            importing file.
        """

        async def _do() -> list[dict]:
            from sylvan.tools.analysis.find_importers import find_importers

            result = await find_importers(repo=repo, file_path=file_path)
            return result.get("importers", [])

        return self._run(_do())

    def dependency_graph(self, repo: str, file_path: str) -> dict:
        """Get the dependency graph centered on a file.

        Shows both what the file depends on (outgoing edges) and what
        depends on it (incoming edges).

        Args:
            repo: Repository name.
            file_path: Relative path of the file.

        Returns:
            A dict with ``nodes`` (file metadata), ``edges`` (directed
            dependency links), ``node_count``, and ``edge_count``.
        """

        async def _do() -> dict:
            from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph

            return await get_dependency_graph(repo=repo, file_path=file_path)

        return self._run(_do())

    def class_hierarchy(self, repo: str, class_name: str) -> dict:
        """Get the inheritance tree for a class.

        Searches the repository for all classes that inherit from the
        target (descendants) and all classes the target inherits from
        (ancestors).

        Args:
            repo: Repository name.
            class_name: Name of the class to look up.

        Returns:
            A dict with ``target``, ``ancestors``, and ``descendants``.
        """

        async def _do() -> dict:
            from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy

            return await get_class_hierarchy(repo=repo, class_name=class_name)

        return self._run(_do())

    def repos(self) -> list[dict]:
        """List all indexed repositories.

        Returns:
            A list of dicts with ``name``, ``source_path``,
            ``indexed_at``, and ``git_head`` for each repository.
        """

        async def _do() -> list[dict]:
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

        return self._run(_do())

    def remove(self, repo: str) -> dict:
        """Delete an indexed repository and all associated data.

        Removes files, symbols, sections, imports, quality records,
        and references in FK-safe order inside a transaction.

        Args:
            repo: Repository name to delete (as shown in :meth:`repos`).

        Returns:
            A dict with per-table deletion counts.
        """

        async def _do() -> dict:
            from sylvan.tools.meta.remove_repo import remove_repo

            return await remove_repo(repo=repo)

        return self._run(_do())

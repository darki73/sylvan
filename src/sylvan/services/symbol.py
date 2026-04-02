"""Symbol service - fluent query builder for symbol and file browsing.

Usage::

    # MCP tool: single symbol with source
    sym = await SymbolService().with_source().find("path::Class.method#method")
    print(sym.name, sym.source)

    # MCP tool: verified symbol with context lines
    sym = await SymbolService().with_source().verified().with_context_lines(5).find(sid)

    # Batch retrieve
    syms = await SymbolService().with_source().with_file().find_many([sid1, sid2])

    # File outline
    outline = await SymbolService().file_outline("sylvan", "src/sylvan/cli.py")

    # File tree
    tree = await SymbolService().file_tree("sylvan", max_depth=3)
"""

from __future__ import annotations

from sylvan.context import get_context
from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import (
    IndexFileNotFoundError,
    RepoNotFoundError,
    SourceNotAvailableError,
    SymbolNotFoundError,
)
from sylvan.indexing.source_code.extractor import compute_content_hash
from sylvan.logging import get_logger
from sylvan.tools.base.presenters import SymbolPresenter

logger = get_logger(__name__)


def _build_symbol_tree(items: list[dict]) -> list[dict]:
    """Organise flat symbol entries into a parent-child tree structure.

    Args:
        items: Flat list of symbol dicts, each with ``symbol_id`` and
            optional ``parent_symbol_id``.

    Returns:
        List of root-level symbol dicts, each with a ``children`` list.
    """
    root_symbols = []
    by_id: dict[str, dict] = {}
    for item in items:
        symbol_id = item["symbol_id"]
        if symbol_id in by_id:
            logger.debug("duplicate_symbol_id_in_outline", symbol_id=symbol_id)
        by_id[symbol_id] = {**item, "children": []}
    for item in items:
        node = by_id[item["symbol_id"]]
        parent_id = item.get("parent_symbol_id")
        if parent_id and parent_id in by_id:
            by_id[parent_id]["children"].append(node)
        else:
            root_symbols.append(node)
    return root_symbols


def _build_tree_structure(files: list) -> dict:
    """Build a nested dict tree from flat file paths.

    Leaf nodes are ``(language, symbol_count)`` tuples; directory nodes
    are nested dicts.

    Args:
        files: ORM file record list, each with ``.path``, ``.language``,
            and ``symbols_count``.

    Returns:
        Nested dict representing the directory structure.
    """
    root: dict = {}
    for file_record in files:
        parts = file_record.path.split("/")
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = (file_record.language or "", getattr(file_record, "symbols_count", 0))
    return root


def _render_tree(
    node: dict,
    lines: list[str],
    prefix: str,
    depth: int,
    max_depth: int,
) -> bool:
    """Render tree nodes as indented text lines.

    Args:
        node: Current directory dict (files are tuples, dirs are dicts).
        lines: Accumulator list of rendered text lines.
        prefix: Indentation prefix for the current level.
        depth: Current nesting depth (zero-based).
        max_depth: Maximum depth before collapsing.

    Returns:
        True if any branch was truncated due to max_depth.
    """
    truncated = False
    entries = sorted(node.items(), key=lambda x: (isinstance(x[1], tuple), x[0]))

    for i, (name, value) in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        child_prefix = prefix + ("    " if is_last else "\u2502   ")

        if isinstance(value, tuple):
            lang, syms = value
            tag = f"  [{lang}, {syms} sym]" if lang else ""
            lines.append(f"{prefix}{connector}{name}{tag}")
        elif depth >= max_depth:
            count = _count_files(value)
            lines.append(f"{prefix}{connector}{name}/  \u2026 {count} files")
            truncated = True
        else:
            lines.append(f"{prefix}{connector}{name}/")
            if _render_tree(value, lines, child_prefix, depth + 1, max_depth):
                truncated = True
    return truncated


def _count_files(node: dict) -> int:
    """Count total files in a subtree.

    Args:
        node: A directory dict node from the tree.

    Returns:
        Total number of file leaves in the subtree.
    """
    count = 0
    for value in node.values():
        if isinstance(value, tuple):
            count += 1
        else:
            count += _count_files(value)
    return count


class SymbolResult:
    """A Symbol model enriched with optional computed data.

    Model fields (name, kind, signature, etc.) are accessible directly
    via attribute proxy. Extra data is None until loaded by the service.
    """

    __slots__ = (
        "_model",
        "context_lines",
        "drift_warning",
        "file_record",
        "hash_verified",
        "source",
    )

    def __init__(self, model: Symbol) -> None:
        self._model = model
        self.source: str | None = None
        self.file_record: FileRecord | None = None
        self.hash_verified: bool | None = None
        self.drift_warning: str | None = None
        self.context_lines: int | None = None

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    def __repr__(self) -> str:
        return f"<SymbolResult {self._model.symbol_id}>"


class SymbolService:
    """Fluent query builder for symbol retrieval.

    Chain ``with_*()`` methods to declare what data to load,
    then call ``find()`` or ``find_many()`` to execute. Same single-use
    contract as QueryBuilder.
    """

    def __init__(self) -> None:
        self._include_source = False
        self._include_file = False
        self._verify = False
        self._context_lines = 0

    def with_source(self) -> SymbolService:
        """Load the symbol's source code blob."""
        self._include_source = True
        return self

    def with_file(self) -> SymbolService:
        """Load the associated FileRecord."""
        self._include_file = True
        return self

    def verified(self) -> SymbolService:
        """Check hash drift against indexed content."""
        self._verify = True
        return self

    def with_context_lines(self, n: int) -> SymbolService:
        """Include surrounding lines in the source (0-50).

        Args:
            n: Number of context lines above and below.
        """
        self._context_lines = min(max(n, 0), 50)
        return self

    async def find(self, symbol_id: str, repo: str | None = None) -> SymbolResult | None:
        """Find a single symbol by its stable identifier.

        Args:
            symbol_id: The stable symbol identifier.
            repo: Optional repository name filter.

        Returns:
            SymbolResult with requested data loaded, or None.

        Raises:
            SymbolNotFoundError: If no symbol with the given ID exists.
            SourceNotAvailableError: If source is requested but blob is missing.
        """
        ctx = get_context()
        cache = ctx.cache
        cache_key = f"Symbol:{symbol_id}:{repo or ''}"
        found, symbol = cache.get(cache_key)
        if not found:
            query = Symbol.where(symbol_id=symbol_id).with_("file")
            if repo:
                query = (
                    query.join("files", "files.id = symbols.file_id")
                    .join("repos", "repos.id = files.repo_id")
                    .where("repos.name", repo)
                )
            symbol = await query.first()
            if symbol is not None:
                cache.put(cache_key, symbol)
        if symbol is None:
            raise SymbolNotFoundError(symbol_id=symbol_id)

        return await self._enrich_single(symbol, ctx)

    async def find_many(self, symbol_ids: list[str]) -> list[SymbolResult]:
        """Batch retrieve multiple symbols by their stable identifiers.

        Args:
            symbol_ids: List of symbol identifiers to resolve.

        Returns:
            List of SymbolResult for found symbols (missing IDs are skipped).
        """
        ctx = get_context()
        cache = ctx.cache
        results = []

        for sid in symbol_ids:
            cache_key = f"Symbol:{sid}"
            found, symbol = cache.get(cache_key)
            if not found:
                symbol = await Symbol.where(symbol_id=sid).with_("file").first()
                if symbol is not None:
                    cache.put(cache_key, symbol)
            if symbol is None:
                continue

            result = await self._enrich_single(symbol, ctx)
            results.append(result)

        return results

    async def file_outline(self, repo_name: str, file_path: str) -> dict:
        """Build a hierarchical symbol outline for a specific file.

        Args:
            repo_name: Repository name.
            file_path: Relative file path within the repo.

        Returns:
            Dict with 'file' path, 'outline' tree, 'symbol_count',
            'repo_id', and 'file_rec'.

        Raises:
            RepoNotFoundError: If the repository name is not indexed.
            IndexFileNotFoundError: If the file is not in the repo's index.
        """
        repo_obj = await Repo.where(name=repo_name).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo_name)

        file_rec = await FileRecord.query().where(repo_id=repo_obj.id).where(path=file_path).first()
        if file_rec is None:
            raise IndexFileNotFoundError(file_path=file_path, repo=repo_name)

        symbols = await Symbol.in_repo(repo_name).in_file(file_path).order_by("symbols.line_start").get()

        items = [SymbolPresenter.outline(symbol) for symbol in symbols]

        root_symbols = _build_symbol_tree(items)

        return {
            "file": file_path,
            "outline": root_symbols,
            "symbol_count": len(items),
            "repo_id": repo_obj.id,
            "file_rec": file_rec,
        }

    async def file_outlines(self, repo_name: str, file_paths: list[str]) -> dict:
        """Batch build outlines for multiple files in one call.

        Args:
            repo_name: Repository name.
            file_paths: List of relative file paths within the repo.

        Returns:
            Dict with 'outlines' list, 'not_found' list, and 'repo_id'.

        Raises:
            RepoNotFoundError: If the repository name is not indexed.
        """
        repo_obj = await Repo.where(name=repo_name).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo_name)

        outlines = []
        not_found = []

        for fp in file_paths:
            file_rec = await FileRecord.query().where(repo_id=repo_obj.id).where(path=fp).first()
            if file_rec is None:
                not_found.append(fp)
                continue

            symbols = await Symbol.in_repo(repo_name).in_file(fp).order_by("symbols.line_start").get()

            items = [SymbolPresenter.outline(s) for s in symbols]

            tree = _build_symbol_tree(items)
            outlines.append(
                {
                    "file": fp,
                    "outline": tree,
                    "symbol_count": len(items),
                    "file_rec": file_rec,
                }
            )

        return {
            "outlines": outlines,
            "not_found": not_found,
            "repo_id": repo_obj.id,
        }

    async def repo_outline(self, repo_name: str) -> dict:
        """Get a high-level outline of an indexed repository.

        Shows file count, symbol count by kind, language distribution,
        and documentation overview.

        Args:
            repo_name: Repository name.

        Returns:
            Dict with repo statistics including files, symbols, sections,
            doc_files, languages, and symbol_kinds.

        Raises:
            RepoNotFoundError: If the repository name is not indexed.
        """
        repo_obj = await Repo.where(name=repo_name).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo_name)

        repo_id = repo_obj.id

        languages = await FileRecord.where(repo_id=repo_id).where_not_null("language").group_by("language").count()

        symbol_kinds = await (
            Symbol.query()
            .join("files", "files.id = symbols.file_id")
            .where("files.repo_id", repo_id)
            .group_by("symbols.kind")
            .count()
        )

        total_files = await FileRecord.where(repo_id=repo_id).count()

        total_symbols = await (
            Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo_id).count()
        )

        total_sections = await (
            Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo_id).count()
        )

        doc_files = await (
            FileRecord.query()
            .select("DISTINCT files.id")
            .join("sections sec", "sec.file_id = files.id")
            .where("files.repo_id", repo_id)
            .count()
        )

        return {
            "repo": repo_name,
            "repo_id": repo_id,
            "indexed_at": repo_obj.indexed_at,
            "git_head": repo_obj.git_head,
            "files": total_files,
            "symbols": total_symbols,
            "sections": total_sections,
            "doc_files": doc_files,
            "languages": languages if isinstance(languages, dict) else {},
            "symbol_kinds": symbol_kinds if isinstance(symbol_kinds, dict) else {},
        }

    async def file_tree(self, repo_name: str, max_depth: int = 3) -> dict:
        """Get a compact directory tree for an indexed repository.

        Returns an indented text tree (like the ``tree`` command) instead of
        deeply nested JSON - much more token-efficient for LLM consumption.
        Directories beyond max_depth are collapsed with file counts.

        Args:
            repo_name: Repository name.
            max_depth: Maximum directory depth to expand (1-10).

        Returns:
            Dict with 'tree' string, 'repo_id', file count, and truncation flag.

        Raises:
            RepoNotFoundError: If the repository name is not indexed.
        """
        repo_obj = await Repo.where(name=repo_name).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo_name)

        max_depth = min(max(max_depth, 1), 10)

        files = await FileRecord.where(repo_id=repo_obj.id).with_count("symbols").order_by("path").get()

        root = _build_tree_structure(files)

        lines: list[str] = [f"{repo_name}/"]
        truncated = _render_tree(root, lines, prefix="", depth=0, max_depth=max_depth)

        return {
            "tree": "\n".join(lines),
            "repo_id": repo_obj.id,
            "files": len(files),
            "max_depth": max_depth,
            "truncated": truncated,
        }

    async def _enrich_single(self, symbol: Symbol, ctx: object) -> SymbolResult:
        """Wrap a Symbol model and load requested extra data.

        Args:
            symbol: The Symbol model instance.
            ctx: The SylvanContext for session/cache access.

        Returns:
            SymbolResult with source/file/verification populated if requested.
        """
        result = SymbolResult(symbol)
        file_rec = symbol.file

        if self._include_file or self._include_source:
            result.file_record = file_rec

        if self._include_source:
            source = await symbol.get_source()
            if source is None:
                raise SourceNotAvailableError(symbol_id=symbol.symbol_id)

            context_lines = self._context_lines
            if context_lines > 0 and file_rec and symbol.line_start:
                content = await file_rec.get_content()
                if content:
                    all_lines = content.decode("utf-8", errors="replace").splitlines()
                    start = max(0, symbol.line_start - 1 - context_lines)
                    end = min(len(all_lines), (symbol.line_end or symbol.line_start) + context_lines)
                    source = "\n".join(all_lines[start:end])
                    result.context_lines = context_lines

            result.source = source

            if self._verify and symbol.content_hash:
                actual_hash = compute_content_hash(source.encode("utf-8"))
                result.hash_verified = actual_hash == symbol.content_hash
                if not result.hash_verified:
                    result.drift_warning = "Content has changed since last indexing"

        file_path = await symbol._resolve_file_path()
        ctx.session.record_symbol_access(symbol.symbol_id, file_path)

        return result

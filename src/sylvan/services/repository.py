"""Repository service - fluent query builder for repo data.

Usage::

    # MCP tool: needs all repos with stats
    repos = await RepositoryService().with_stats().get()
    for r in repos:
        print(r.name, r.stats["files"], r.stats["symbols"])

    # WS dashboard: non-library repos with stats and languages
    repos = await RepositoryService().exclude_libraries().with_stats().with_languages().get()

    # CLI: just names
    repos = await RepositoryService().exclude_libraries().get()
    for r in repos:
        print(r.name, r.source_path)

    # Single lookup
    repo = await RepositoryService().with_stats().with_languages().find("sylvan")

    # Mutations
    result = await RepositoryService().remove("sylvan")

    # Building blocks (used by WorkspaceService, etc.)
    stats = await load_stats(repo_id)
    langs = await load_languages(repo_id)
"""

from __future__ import annotations

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError


async def load_stats(repo_id: int) -> dict:
    """Load file, symbol, and section counts for a repo.

    Args:
        repo_id: The repo's primary key.

    Returns:
        Dict with files, symbols, and sections counts.
    """
    files = await FileRecord.where(repo_id=repo_id).count()
    symbols = await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo_id).count()
    sections = await (
        Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo_id).count()
    )
    return {"files": files, "symbols": symbols, "sections": sections}


async def load_languages(repo_id: int) -> dict[str, int]:
    """Load language breakdown for a repo.

    Args:
        repo_id: The repo's primary key.

    Returns:
        Dict mapping language name to file count, sorted descending.
    """
    lang_counts = await (
        FileRecord.where(repo_id=repo_id).where_not_null("language").where_not(language="").group_by("language").count()
    )
    if not lang_counts:
        return {}
    return dict(sorted(lang_counts.items(), key=lambda x: x[1], reverse=True))


class RepoResult:
    """A Repo model enriched with optional computed data.

    Model fields (name, source_path, etc.) are accessible directly
    via attribute proxy. Extra data is None until loaded by the service.
    """

    __slots__ = ("_model", "languages", "stats")

    def __init__(self, model: Repo) -> None:
        self._model = model
        self.stats: dict | None = None
        self.languages: dict[str, int] | None = None

    def __getattr__(self, name: str):
        return getattr(self._model, name)

    def __repr__(self) -> str:
        return f"<RepoResult {self._model.name}>"


class RepositoryService:
    """Fluent query builder for repository data.

    Chain ``with_*()`` methods to declare what data to load,
    then call ``get()`` or ``find()`` to execute. Same single-use
    contract as QueryBuilder.
    """

    def __init__(self) -> None:
        self._include_stats = False
        self._include_languages = False
        self._exclude_libraries = False

    def exclude_libraries(self) -> RepositoryService:
        """Filter out library repos (repo_type='library')."""
        self._exclude_libraries = True
        return self

    def with_stats(self) -> RepositoryService:
        """Load file, symbol, and section counts per repo."""
        self._include_stats = True
        return self

    def with_languages(self) -> RepositoryService:
        """Load language breakdown per repo."""
        self._include_languages = True
        return self

    async def get(self) -> list[RepoResult]:
        """Execute the query and return all matching repos.

        Returns:
            List of RepoResult with requested data loaded.
        """
        query = Repo.query().order_by("name")
        if self._exclude_libraries:
            query = query.where_not(repo_type="library")
        repos = await query.get()
        return [await self._enrich(r) for r in repos]

    async def find(self, name: str) -> RepoResult | None:
        """Find a single repo by name.

        Args:
            name: Repository name.

        Returns:
            RepoResult with requested data loaded, or None.
        """
        repo = await Repo.where(name=name).first()
        if repo is None:
            return None
        return await self._enrich(repo)

    async def remove(self, name: str) -> dict:
        """Delete a repository and all associated data via ORM cascade.

        Args:
            name: Repository name.

        Returns:
            Dict with repo name and id.

        Raises:
            RepoNotFoundError: If the repository does not exist.
        """
        repo = await Repo.where(name=name).first()
        if repo is None:
            raise RepoNotFoundError(repo=name)
        repo_id = repo.id

        await _cleanup_vec_tables(repo_id)
        await repo.delete()
        return {"repo": name, "repo_id": repo_id}

    async def _enrich(self, repo: Repo) -> RepoResult:
        """Wrap a Repo model and load requested extra data.

        Args:
            repo: The Repo model instance.

        Returns:
            RepoResult with stats/languages populated if requested.
        """
        result = RepoResult(repo)
        if self._include_stats:
            result.stats = await load_stats(repo.id)
        if self._include_languages:
            result.languages = await load_languages(repo.id)
        return result


async def _cleanup_vec_tables(repo_id: int) -> None:
    """Delete symbol and section vector entries for a repo.

    These are sqlite-vec virtual tables without ORM models,
    so they can't be handled by the cascade delete.

    Args:
        repo_id: The repo's primary key.
    """
    import contextlib

    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()

    symbol_ids = await (
        Symbol.query()
        .select("symbols.symbol_id")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .pluck("symbol_id")
    )
    section_ids = await (
        Section.query()
        .select("sections.section_id")
        .join("files", "files.id = sections.file_id")
        .where("files.repo_id", repo_id)
        .pluck("section_id")
    )

    with contextlib.suppress(Exception):
        for sid in symbol_ids:
            await backend.execute("DELETE FROM symbols_vec WHERE symbol_id = ?", [sid])
    with contextlib.suppress(Exception):
        for sid in section_ids:
            await backend.execute("DELETE FROM sections_vec WHERE section_id = ?", [sid])

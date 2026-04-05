"""Search service - session-aware symbol, text, section, and similarity search.

Usage::

    # Simple symbol search
    results = await SearchService().symbols("parse", repo="sylvan")

    # With session reranking and token budget
    results = await SearchService() \\
        .with_session_reranking() \\
        .with_token_budget(2000) \\
        .symbols("parse", repo="sylvan", kind="function")

    # Batch search
    results = await SearchService().batch_symbols(
        [{"query": "parse"}, {"query": "render"}],
        repo="sylvan",
    )

    # Text search (grep-like)
    results = await SearchService().text("TODO", repo="sylvan")

    # Section search
    results = await SearchService().sections("installation")

    # Similar symbols
    results = await SearchService().similar("src/main.py::main#function")

    # Module-level helpers (used by dashboard, etc.)
    tokens = estimate_entry_tokens(entry_dict)
"""

from __future__ import annotations

import json

from sylvan.context import get_context
from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.error_codes import EmptyQueryError, RepoNotFoundError, SymbolNotFoundError
from sylvan.session.tracker import get_session


def estimate_entry_tokens(entry: dict) -> int:
    """Estimate the token count of a result entry when serialised.

    Args:
        entry: A single search result dict.

    Returns:
        Estimated token count (tiktoken if available, else byte ratio).
    """
    text = json.dumps(entry, default=str)
    return max(1, len(text) // 4)


async def rerank_with_session(
    results: list,
    seen_ids: set[str],
    session: object,
) -> tuple[list[dict], list[dict]]:
    """Separate results into unseen (boosted by file relevance) and already-seen.

    Args:
        results: ORM symbol results from the search query.
        seen_ids: Set of symbol IDs already retrieved this session.
        session: The session tracker instance.

    Returns:
        Two-tuple of (ordered_results, already_seen_results).
    """
    reranked = []
    already_seen = []

    for symbol in results:
        entry = await symbol.to_summary_dict(include_repo=True)
        entry["line"] = entry.pop("line_start")
        del entry["line_end"]

        if symbol.symbol_id in seen_ids:
            entry["_already_retrieved"] = True
            already_seen.append(entry)
        else:
            boost = session.compute_file_boost(entry["file"])
            reranked.append((boost, entry))

    reranked.sort(key=lambda x: -x[0])
    ordered = [r for _, r in reranked]
    ordered.extend(already_seen)
    return ordered, already_seen


def apply_token_budget(formatted: list[dict], token_budget: int) -> tuple[list[dict], int]:
    """Greedy-pack results until the token budget is exhausted.

    Args:
        formatted: Ordered list of result dicts to pack.
        token_budget: Maximum token count to include.

    Returns:
        Two-tuple of (packed_results, tokens_used).
    """
    budgeted = []
    tokens_used = 0
    for entry in formatted:
        entry_tokens = estimate_entry_tokens(entry)
        if tokens_used + entry_tokens > token_budget and budgeted:
            break
        budgeted.append(entry)
        tokens_used += entry_tokens
    return budgeted, tokens_used


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp a numeric parameter to a safe range.

    Args:
        value: The input value.
        low: Minimum allowed value (inclusive).
        high: Maximum allowed value (inclusive).

    Returns:
        The clamped value within [low, high].
    """
    return min(max(value, low), high)


async def _resolve_repo_id(repo: str | None) -> int | None:
    """Look up a repo ID by name.

    Args:
        repo: Repository name, or None.

    Returns:
        The repo's primary key, or None.
    """
    if not repo:
        return None
    repo_obj = await Repo.where(name=repo).first()
    return repo_obj.id if repo_obj else None


async def _compute_file_equivalent_tokens(results: list, formatted: list[dict]) -> int:
    """Compute equivalent tokens if the agent had read full files instead.

    Args:
        results: ORM symbol results.
        formatted: The formatted result dicts.

    Returns:
        Estimated token count for full file reads.
    """
    unique_files = {e.get("file") for e in formatted if e.get("file")}
    equivalent_tokens = 0
    for symbol in results:
        file_path = await symbol._resolve_file_path()
        if file_path in unique_files:
            unique_files.discard(file_path)
            file_rec = symbol.file
            if file_rec and file_rec.byte_size:
                equivalent_tokens += file_rec.byte_size // 4
    return equivalent_tokens


class SearchService:
    """Fluent query builder for search operations.

    Chain ``with_*()`` methods to configure behaviour, then call one of
    the search methods. Same single-use contract as QueryBuilder.
    """

    def __init__(self) -> None:
        self._session_reranking = False
        self._token_budget: int | None = None

    def with_session_reranking(self) -> SearchService:
        """Enable session-aware reranking that deprioritises seen symbols."""
        self._session_reranking = True
        return self

    def with_token_budget(self, budget: int) -> SearchService:
        """Cap results by estimated token count.

        Args:
            budget: Maximum token budget.
        """
        self._token_budget = budget
        return self

    async def symbols(
        self,
        query: str,
        repo: str | None = None,
        kind: str | None = None,
        language: str | None = None,
        file_pattern: str | None = None,
        max_results: int = 20,
    ) -> dict:
        """Search indexed symbols by name, signature, docstring, or keywords.

        Args:
            query: Search query - symbol name, keyword, or description.
            repo: Filter to a specific repository name.
            kind: Filter by symbol kind (function, class, method, etc.).
            language: Filter by programming language.
            file_pattern: Glob pattern to filter by file path.
            max_results: Maximum number of results to return.

        Returns:
            Dict with 'symbols' list, 'results_count', 'query',
            'already_seen_deprioritized', token budget info, and
            token efficiency accumulators.

        Raises:
            EmptyQueryError: If the query is empty or whitespace-only.
        """
        query = str(query)
        ctx = get_context()
        session = ctx.session if ctx.session else get_session()
        session.record_query(query, "find_code")
        max_results = _clamp(max_results, 1, 1000)

        if not query or not query.strip():
            raise EmptyQueryError()

        seen_ids = session.get_seen_symbol_ids()
        use_reranking = self._session_reranking or bool(seen_ids)
        fetch_count = max_results * 2 if use_reranking and seen_ids else max_results

        query_builder = Symbol.search(query)

        if repo:
            query_builder = query_builder.in_repo(repo)
        if kind:
            query_builder = query_builder.where(kind=kind)
        if language:
            query_builder = query_builder.where(language=language)
        if file_pattern:
            query_builder = query_builder.join("files", "files.id = symbols.file_id").where_glob(
                "files.path", file_pattern
            )

        query_builder = query_builder.limit(fetch_count)
        results = await query_builder.get()

        ordered, already_seen = await rerank_with_session(results, seen_ids, session)
        formatted = ordered[:max_results]

        tokens_used = 0
        token_budget = self._token_budget
        if token_budget is not None and token_budget > 0:
            formatted, tokens_used = apply_token_budget(formatted, token_budget)

        returned_tokens = sum(estimate_entry_tokens(e) for e in formatted)
        equivalent_tokens = await _compute_file_equivalent_tokens(results, formatted)
        repo_id = await _resolve_repo_id(repo)

        return {
            "symbols": formatted,
            "results_count": len(formatted),
            "query": query,
            "already_seen_deprioritized": len(already_seen),
            "token_budget": token_budget,
            "tokens_used": tokens_used,
            "returned_tokens": returned_tokens,
            "equivalent_tokens": equivalent_tokens,
            "repo_id": repo_id,
        }

    async def batch_symbols(
        self,
        queries: list[dict],
        repo: str | None = None,
        max_results_per_query: int = 10,
    ) -> dict:
        """Run multiple symbol searches in one call.

        Each query object can override ``repo``, ``kind``, ``language``, and
        ``max_results``. Results are returned grouped by query.

        Args:
            queries: List of query dicts, each with at least a ``query`` key.
            repo: Default repo filter applied to all queries.
            max_results_per_query: Default max results per query.

        Returns:
            Dict with 'results' list (one entry per query), 'queries_count',
            'total_results', and token efficiency accumulators.
        """
        session = get_session()
        all_results = []
        equivalent = 0

        for q in queries:
            query_text = q.get("query", "")
            if not query_text or not query_text.strip():
                all_results.append({"query": query_text, "symbols": [], "error": "empty_query"})
                continue

            session.record_query(query_text, "find_code_batch")

            q_repo = q.get("repo", repo)
            q_kind = q.get("kind")
            q_language = q.get("language")
            q_max = _clamp(q.get("max_results", max_results_per_query), 1, 100)

            query_builder = Symbol.search(query_text)
            if q_repo:
                query_builder = query_builder.in_repo(q_repo)
            if q_kind:
                query_builder = query_builder.where(kind=q_kind)
            if q_language:
                query_builder = query_builder.where(language=q_language)

            results = await query_builder.limit(q_max).get()

            formatted = []
            for symbol in results:
                formatted.append(
                    {
                        "symbol_id": symbol.symbol_id,
                        "name": symbol.name,
                        "kind": symbol.kind,
                        "file": await symbol._resolve_file_path(),
                        "signature": symbol.signature or "",
                    }
                )

            unique_files = set()
            for symbol in results:
                fp = await symbol._resolve_file_path()
                if fp:
                    unique_files.add(fp)
                file_rec = symbol.file
                if file_rec and file_rec.byte_size and fp in unique_files:
                    unique_files.discard(fp)
                    equivalent += file_rec.byte_size // 4

            all_results.append({"query": query_text, "count": len(formatted), "symbols": formatted})

        returned = sum(estimate_entry_tokens(e) for r in all_results for e in r.get("symbols", []))

        return {
            "results": all_results,
            "queries_count": len(queries),
            "total_results": sum(r.get("count", 0) for r in all_results),
            "returned_tokens": returned,
            "equivalent_tokens": equivalent,
        }

    async def text(
        self,
        query: str,
        repo: str | None = None,
        file_pattern: str | None = None,
        max_results: int = 20,
        context_lines: int = 2,
    ) -> dict:
        """Search across file content for text matches (like grep).

        Args:
            query: Text to search for (case-insensitive).
            repo: Repository name filter.
            file_pattern: Glob pattern to filter by file path.
            max_results: Maximum matches to return.
            context_lines: Number of surrounding lines per match.

        Returns:
            Dict with 'matches' list, 'results_count', 'query', and
            token efficiency accumulators.
        """
        query = str(query)
        max_results = _clamp(max_results, 1, 1000)
        context_lines = _clamp(context_lines, 0, 50)

        ctx = get_context()
        ctx.session.record_query(query, "find_text")

        query_builder = FileRecord.query().join("repos", "repos.id = files.repo_id")

        if repo:
            query_builder = query_builder.where("repos.name", repo)
        if file_pattern:
            query_builder = query_builder.where_glob("files.path", file_pattern)

        query_builder = query_builder.order_by("files.path")
        files = await query_builder.get()

        results = []
        query_lower = query.lower()

        for file_record in files:
            await file_record.load("repo")
            repo_obj = file_record.repo
            repo_name = repo_obj.name if repo_obj else ""

            matches = await _search_file_content(file_record, query_lower, context_lines, repo_name)
            for match in matches:
                results.append(match)
                if len(results) >= max_results:
                    break

            if len(results) >= max_results:
                break

        returned_text = json.dumps(results, default=str)
        returned_tokens = max(1, len(returned_text) // 4)
        unique_files: dict[str, int] = {}
        for file_record in files:
            if file_record.path not in unique_files and file_record.byte_size:
                unique_files[file_record.path] = file_record.byte_size // 4
            if len(unique_files) >= len(results):
                break
        equivalent_tokens = sum(unique_files.values())

        repo_id = await _resolve_repo_id(repo)

        return {
            "matches": results,
            "results_count": len(results),
            "query": query,
            "returned_tokens": returned_tokens,
            "equivalent_tokens": equivalent_tokens,
            "repo_id": repo_id,
        }

    async def sections(
        self,
        query: str,
        repo: str | None = None,
        doc_path: str | None = None,
        max_results: int = 10,
    ) -> dict:
        """Search indexed documentation sections by title, summary, or tags.

        Args:
            query: Search query string.
            repo: Filter to a specific repository name.
            doc_path: Filter to a specific document path.
            max_results: Maximum results to return.

        Returns:
            Dict with 'sections' list, 'results_count', 'query', and
            token efficiency accumulators.

        Raises:
            EmptyQueryError: If the query is empty or whitespace-only.
        """
        query = str(query)
        max_results = _clamp(max_results, 1, 1000)

        ctx = get_context()
        ctx.session.record_query(query, "find_docs")

        if not query or not query.strip():
            raise EmptyQueryError()

        query_builder = Section.search(query)

        if repo:
            query_builder = query_builder.in_repo(repo)
        if doc_path:
            query_builder = query_builder.in_doc(doc_path)

        query_builder = query_builder.limit(max_results)
        sections_result = await query_builder.get()

        from sylvan.tools.base.presenters import SectionPresenter

        formatted = []
        for section in sections_result:
            await section.load("file")
            file_rec = section.file
            if file_rec:
                await file_rec.load("repo")
            repo_obj = file_rec.repo if file_rec else None
            d = SectionPresenter.standard(section, doc_path=file_rec.path if file_rec else "")
            del d["tags"]
            d["repo"] = repo_obj.name if repo_obj else ""
            formatted.append(d)

        returned_text = json.dumps(formatted, default=str)
        returned_tokens = max(1, len(returned_text) // 4)
        unique_files: dict[str, int] = {}
        for section in sections_result:
            file_rec = section.file
            if file_rec and file_rec.path not in unique_files and file_rec.byte_size:
                unique_files[file_rec.path] = file_rec.byte_size // 4
        equivalent_tokens = sum(unique_files.values())

        repo_id = await _resolve_repo_id(repo)

        return {
            "sections": formatted,
            "results_count": len(formatted),
            "query": query,
            "returned_tokens": returned_tokens,
            "equivalent_tokens": equivalent_tokens,
            "repo_id": repo_id,
        }

    async def similar(
        self,
        symbol_id: str,
        repo: str | None = None,
        max_results: int = 10,
    ) -> dict:
        """Find symbols semantically similar to a given source symbol.

        Args:
            symbol_id: The stable identifier of the source symbol.
            repo: Optional repository name to restrict results to.
            max_results: Maximum number of similar symbols to return.

        Returns:
            Dict with 'source' summary, 'similar' list, 'results_count',
            and token efficiency accumulators.

        Raises:
            SymbolNotFoundError: If the source symbol does not exist.
            RepoNotFoundError: If the repo filter does not match any indexed repo.
        """
        ctx = get_context()
        ctx.session.record_query(symbol_id, "find_similar_code")

        max_results = _clamp(max_results, 1, 100)

        source = await Symbol.where(symbol_id=symbol_id).first()
        if source is None:
            raise SymbolNotFoundError(symbol_id=symbol_id)

        parts: list[str] = []
        if source.signature:
            parts.append(source.signature)
        if source.docstring:
            parts.append(source.docstring)
        if not parts:
            parts.append(source.name)
        search_text_str = " ".join(parts)

        query_builder = Symbol.similar_to(search_text_str, k=max_results + 1)

        if repo:
            repo_obj = await Repo.where(name=repo).first()
            if repo_obj is None:
                raise RepoNotFoundError(repo=repo)
            query_builder = query_builder.in_repo(repo)

        results = await query_builder.get()

        similar: list[dict] = []
        for symbol in results:
            if symbol.symbol_id == symbol_id:
                continue
            entry = await symbol.to_summary_dict(include_repo=True)
            entry["line"] = entry.pop("line_start")
            del entry["line_end"]
            similar.append(entry)
            if len(similar) >= max_results:
                break

        source_summary = await source.to_summary_dict(include_repo=True)

        returned_tokens = sum(len(str(e)) // 4 for e in similar)
        equivalent_tokens = await _compute_file_equivalent_tokens(results, similar)
        repo_id = await _resolve_repo_id(repo)

        return {
            "source": source_summary,
            "similar": similar,
            "results_count": len(similar),
            "source_symbol": symbol_id,
            "returned_tokens": returned_tokens,
            "equivalent_tokens": equivalent_tokens,
            "repo_id": repo_id,
        }


async def _search_file_content(
    file_record: object,
    query_lower: str,
    context_lines: int,
    repo_name: str,
) -> list[dict]:
    """Search a single file's content for case-insensitive text matches.

    Args:
        file_record: The ORM file record to search.
        query_lower: The lowercased search query.
        context_lines: Number of surrounding lines to include per match.
        repo_name: Display name of the repository.

    Returns:
        List of match dicts with file path, line number, and context.
    """
    content = await Blob.get(file_record.content_hash)
    if content is None:
        return []

    try:
        text = content.decode("utf-8", errors="replace")
    except Exception:
        return []

    matches = []
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if query_lower in line.lower():
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            context = "\n".join(lines[start:end])

            matches.append(
                {
                    "file_path": file_record.path,
                    "repo_name": repo_name,
                    "line": i + 1,
                    "match": line.strip(),
                    "context": context,
                }
            )

    return matches

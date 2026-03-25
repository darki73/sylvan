"""MCP tool: search_columns -- search ecosystem context column metadata."""

from __future__ import annotations

import re
from pathlib import Path

from sylvan.database.orm import Repo
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, clamp, ensure_orm, log_tool_call, wrap_response


def _match_score(query_lower: str, text: str) -> float:
    """Score how well a query matches a text string.

    Args:
        query_lower: Lowercase search query.
        text: Text to match against.

    Returns:
        Score between 0.0 and 1.0.
    """
    text_lower = text.lower()
    if query_lower == text_lower:
        return 1.0
    if query_lower in text_lower:
        return 0.8
    # Check individual words
    words = query_lower.split()
    if not words:
        return 0.0
    matched = sum(1 for w in words if w in text_lower)
    return matched / len(words) * 0.6


def _search_provider_columns(
    provider,
    query: str,
    model_pattern: str | None,
    max_results: int,
) -> list[dict]:
    """Search column metadata from a single provider.

    Args:
        provider: A loaded ecosystem context provider instance.
        query: Search query string.
        model_pattern: Optional glob-like pattern to filter model names.
        max_results: Maximum results to return.

    Returns:
        List of matched column dicts with model, column, description,
        score, and provider fields.
    """
    metadata = provider.get_metadata()
    results = []
    query_lower = query.lower()

    # dbt provider returns {"dbt_columns": {model: {col: desc}}}
    for meta_value in metadata.values():
        if not isinstance(meta_value, dict):
            continue

        for model_name, columns in meta_value.items():
            if not isinstance(columns, dict):
                continue

            if model_pattern:
                pattern = model_pattern.replace("*", ".*")
                if not re.match(pattern, model_name, re.IGNORECASE):
                    continue

            for col_name, col_desc in columns.items():
                combined = f"{col_name} {col_desc} {model_name}"
                score = _match_score(query_lower, combined)
                if score > 0.0:
                    results.append(
                        {
                            "model": model_name,
                            "column": col_name,
                            "description": col_desc,
                            "score": round(score, 3),
                            "provider": provider.name,
                        }
                    )

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:max_results]


@log_tool_call
async def search_columns(
    repo: str,
    query: str,
    model_pattern: str | None = None,
    max_results: int = 20,
) -> dict:
    """Search column metadata from ecosystem context providers.

    Discovers providers (e.g. dbt) for the repository's source path and
    searches their structured column metadata.

    Args:
        repo: Repository name.
        query: Search query for column names or descriptions.
        model_pattern: Optional glob pattern to filter model names.
        max_results: Maximum results to return.

    Returns:
        Tool response dict with ``columns`` list and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = MetaBuilder()
    max_results = clamp(max_results, 1, 200)
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if not repo_obj:
        raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo, _meta=meta.build())

    source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
    if source_root is None or not source_root.exists():
        return wrap_response(
            {"columns": [], "message": "Repository source path is not available on disk."},
            meta.build(),
        )

    from sylvan.providers.ecosystem_context.base import discover_providers

    providers = discover_providers(source_root)

    if not providers:
        meta.set("providers_found", 0)
        return wrap_response(
            {"columns": [], "message": "No ecosystem context providers found for this repo."},
            meta.build(),
        )

    all_results: list[dict] = []
    provider_names = []
    for provider in providers:
        provider_names.append(provider.name)
        matches = _search_provider_columns(provider, query, model_pattern, max_results)
        all_results.extend(matches)

    # Re-sort combined results and trim
    all_results.sort(key=lambda r: r["score"], reverse=True)
    all_results = all_results[:max_results]

    meta.set("count", len(all_results))
    meta.set("providers_found", len(providers))
    meta.set("providers", provider_names)

    return wrap_response(
        {"query": query, "columns": all_results},
        meta.build(),
    )

"""Analysis service - blast radius, importers, hierarchy, quality, and more."""

from __future__ import annotations

import re
from pathlib import Path

from sylvan.database.orm import FileRecord, Quality, Reference, Repo, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.models.file_import import FileImport
from sylvan.error_codes import IndexFileNotFoundError, RepoNotFoundError, SymbolNotFoundError
from sylvan.tools.base.presenters import FilePresenter

_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _tokenize_name(name: str) -> set[str]:
    """Split an identifier into lowercase tokens on camelCase, underscore, and separator boundaries.

    Args:
        name: The identifier string to tokenize.

    Returns:
        Set of lowercase token strings (minimum 2 characters each).
    """
    parts = _CAMEL_RE.sub("_", name)
    tokens = re.split(r"[_\-./]", parts)
    return {t.lower() for t in tokens if len(t) >= 2}


def _score_candidate(candidate: object, target_file_id: int, target_tokens: set[str]) -> float:
    """Compute a relatedness score for a candidate symbol.

    Args:
        candidate: An ORM symbol instance to score.
        target_file_id: The file ID of the target symbol.
        target_tokens: Lowercase name tokens of the target symbol.

    Returns:
        Numeric relatedness score (higher is more related).
    """
    score = 0.0
    if candidate.file_id == target_file_id:
        score += 3.0
    c_tokens = _tokenize_name(candidate.name)
    overlap = target_tokens & c_tokens
    score += 0.5 * len(overlap)
    return score


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
    words = query_lower.split()
    if not words:
        return 0.0
    matched = sum(1 for w in words if w in text_lower)
    return matched / len(words) * 0.6


def _search_provider_columns(
    provider: object,
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


class AnalysisService:
    """Service for code analysis operations.

    Methods are independent operations, not a fluent builder.
    """

    async def blast_radius(self, symbol_id: str, depth: int = 2) -> dict:
        """Estimate the impact of changing a symbol.

        Args:
            symbol_id: The symbol to analyse.
            depth: How many import hops to follow (1-3).

        Returns:
            Dict with confirmed and potential impact lists.
        """
        from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast

        depth = min(max(depth, 1), 3)
        return await _blast(symbol_id, max_depth=depth)

    async def batch_blast_radius(self, symbol_ids: list[str], depth: int = 2) -> dict:
        """Estimate blast radius for multiple symbols in one call.

        Args:
            symbol_ids: List of symbol identifiers to analyse.
            depth: How many import hops to follow (1-3).

        Returns:
            Dict with results list (one per symbol) and summary counts.
        """
        from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast

        depth = min(max(depth, 1), 3)
        results = []
        for sid in symbol_ids:
            try:
                result = await _blast(sid, max_depth=depth)
                entry: dict = {
                    "symbol_id": sid,
                    "confirmed": result.get("confirmed", []),
                    "potential": result.get("potential", []),
                    "total_affected": result.get("total_affected", 0),
                }
                if result.get("truncated"):
                    entry["truncated"] = result["truncated"]
                results.append(entry)
            except Exception as exc:
                results.append({"symbol_id": sid, "error": str(exc)})

        return {
            "results": results,
            "symbols_analysed": len(results),
            "total_affected": sum(r.get("total_affected", 0) for r in results),
        }

    async def find_importers(self, repo: str, file_path: str, max_results: int = 50) -> dict:
        """Find all files that import a given file.

        Args:
            repo: Repository name.
            file_path: The file to find importers of.
            max_results: Maximum results to return.

        Returns:
            Dict with file path and importers list.

        Raises:
            IndexFileNotFoundError: If the target file is not in the index.
        """
        target = await (
            FileRecord.query()
            .join("repos", "repos.id = files.repo_id")
            .where("repos.name", repo)
            .where("files.path", file_path)
            .first()
        )
        if target is None:
            raise IndexFileNotFoundError(file_path=file_path)

        importing_files = await (
            FileRecord.query()
            .select("DISTINCT files.path", "files.language", "files.id")
            .join("file_imports fi", "fi.file_id = files.id")
            .where("fi.resolved_file_id", target.id)
            .order_by("files.path")
            .limit(max_results)
            .get()
        )

        importer_file_ids = [f.id for f in importing_files]
        files_that_are_imported = await _find_files_that_are_imported(importer_file_ids)

        importers = []
        for f in importing_files:
            symbol_count = await Symbol.where(file_id=f.id).count()
            importers.append(
                {
                    "path": f.path,
                    "language": f.language,
                    "symbol_count": symbol_count,
                    "has_importers": f.id in files_that_are_imported,
                }
            )

        return {"file": file_path, "importers": importers}

    async def batch_find_importers(self, repo: str, file_paths: list[str], max_results: int = 20) -> dict:
        """Find importers for multiple files in one call.

        Args:
            repo: Repository name.
            file_paths: List of file paths to find importers of.
            max_results: Maximum importers per file.

        Returns:
            Dict with results list and not_found list.
        """
        results = []
        not_found = []

        for fp in file_paths:
            target = await (
                FileRecord.query()
                .join("repos", "repos.id = files.repo_id")
                .where("repos.name", repo)
                .where("files.path", fp)
                .first()
            )
            if target is None:
                not_found.append(fp)
                continue

            importing_files = await (
                FileRecord.query()
                .select("DISTINCT files.path", "files.language", "files.id")
                .join("file_imports fi", "fi.file_id = files.id")
                .where("fi.resolved_file_id", target.id)
                .order_by("files.path")
                .limit(max_results)
                .get()
            )

            importers = [FilePresenter.brief(f) for f in importing_files]
            results.append(
                {
                    "file": fp,
                    "importer_count": len(importers),
                    "importers": importers,
                }
            )

        return {
            "results": results,
            "not_found": not_found,
            "found": len(results),
            "total_importers": sum(r["importer_count"] for r in results),
        }

    async def class_hierarchy(self, class_name: str, repo: str | None = None) -> dict:
        """Traverse class hierarchy: ancestors and descendants.

        Args:
            class_name: Name of the class to analyse.
            repo: Optional repository name filter.

        Returns:
            Dict with ancestors and descendants lists.
        """
        from sylvan.analysis.structure.class_hierarchy import get_class_hierarchy as _hierarchy

        return await _hierarchy(class_name, repo_name=repo)

    async def references(self, symbol_id: str, direction: str = "to") -> dict:
        """Get references to or from a symbol.

        Args:
            symbol_id: The symbol to query.
            direction: "to" for callers, "from" for callees.

        Returns:
            Dict with references list.
        """
        total_refs = await Reference.query().count()
        if total_refs == 0:
            return {
                "references": [],
                "symbol_id": symbol_id,
                "direction": direction,
                "warning": "Reference graph is empty. Run index_folder to populate it.",
            }

        from sylvan.analysis.structure.reference_graph import get_references_from, get_references_to

        if direction == "from":
            refs = await get_references_from(symbol_id)
        else:
            refs = await get_references_to(symbol_id)

        return {"references": refs, "symbol_id": symbol_id, "direction": direction}

    async def related(self, symbol_id: str, max_results: int = 10) -> dict:
        """Find symbols related to a given symbol by co-location and naming.

        Args:
            symbol_id: The symbol to find relations for.
            max_results: Maximum results to return.

        Returns:
            Dict with related symbols list.

        Raises:
            SymbolNotFoundError: If the symbol does not exist.
            IndexFileNotFoundError: If the symbol's file record is missing.
        """
        target = await Symbol.where(symbol_id=symbol_id).first()
        if target is None:
            raise SymbolNotFoundError(symbol_id=symbol_id)

        target_tokens = _tokenize_name(target.name)
        target_file_id = target.file_id

        target_file = await FileRecord.find(target_file_id)
        if target_file is None:
            raise IndexFileNotFoundError(symbol_id=symbol_id)

        candidates = await (
            Symbol.query()
            .select(
                "symbols.symbol_id",
                "symbols.name",
                "symbols.kind",
                "symbols.language",
                "symbols.signature",
                "symbols.file_id",
                "f.path as file_path",
            )
            .join("files f", "f.id = symbols.file_id")
            .where("f.repo_id", target_file.repo_id)
            .where_not(symbol_id=symbol_id)
            .limit(1000)
            .get()
        )

        scored = []
        for c in candidates:
            score = _score_candidate(c, target_file_id, target_tokens)
            if score > 0:
                scored.append(
                    (
                        score,
                        {
                            "symbol_id": c.symbol_id,
                            "name": c.name,
                            "kind": c.kind,
                            "file_path": getattr(c, "file_path", ""),
                            "signature": c.signature or "",
                        },
                    )
                )

        scored.sort(key=lambda x: -x[0])
        top = scored[:max_results]

        results = [
            {
                "symbol_id": sym["symbol_id"],
                "name": sym["name"],
                "kind": sym["kind"],
                "file": sym["file_path"],
                "signature": sym.get("signature", ""),
                "score": round(score, 2),
            }
            for score, sym in top
        ]

        return {"symbol_id": symbol_id, "related": results}

    async def quality(
        self,
        repo: str,
        untested_only: bool = False,
        undocumented_only: bool = False,
        min_complexity: int = 0,
        limit: int = 50,
    ) -> dict:
        """Get quality metrics for symbols in a repo.

        Args:
            repo: Repository name.
            untested_only: Only show untested symbols.
            undocumented_only: Only show undocumented symbols.
            min_complexity: Minimum cyclomatic complexity threshold.
            limit: Maximum results to return.

        Returns:
            Dict with symbols quality list.

        Raises:
            RepoNotFoundError: If the repo is not indexed.
        """
        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo)

        count = await (
            Quality.query()
            .join("symbols s", "s.symbol_id = quality.symbol_id")
            .join("files f", "f.id = s.file_id")
            .where("f.repo_id", repo_obj.id)
            .count()
        )

        if count == 0:
            from sylvan.analysis.quality.quality_metrics import compute_quality_metrics

            await compute_quality_metrics(repo_obj.id)

        from sylvan.analysis.quality.quality_metrics import get_low_quality_symbols

        results = await get_low_quality_symbols(
            repo,
            min_complexity=min_complexity,
            untested_only=untested_only,
            undocumented_only=undocumented_only,
            limit=limit,
        )

        return {"symbols": results}

    async def quality_report(self, repo: str) -> dict:
        """Generate a comprehensive quality report for a repository.

        Args:
            repo: Indexed repository name.

        Returns:
            Dict with full quality report data.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
        """
        from sylvan.config import get_config

        config = get_config()
        quality_config = config.quality

        repo_obj = await Repo.where(name=repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=repo)

        repo_id = repo_obj.id

        from sylvan.analysis.quality.code_smells import detect_code_smells
        from sylvan.analysis.quality.quality_metrics import compute_quality_metrics
        from sylvan.analysis.quality.test_coverage import analyze_test_coverage

        await compute_quality_metrics(repo_id)
        coverage = await analyze_test_coverage(repo_id)
        smells = await detect_code_smells(repo_id)

        security_findings: list = []
        if quality_config.security_scan:
            from sylvan.analysis.quality.security_scanner import scan_security

            security_findings = await scan_security(repo_id)

        from sylvan.analysis.quality.dead_code import find_dead_code
        from sylvan.analysis.quality.duplication import detect_duplicates

        dead_code = await find_dead_code(repo)
        refs_empty = await Reference.query().count() == 0
        duplicates = await detect_duplicates(repo_id, min_lines=quality_config.duplication_min_lines)

        total = await (
            Quality.query()
            .join("symbols", "symbols.symbol_id = quality.symbol_id")
            .join("files", "files.id = symbols.file_id")
            .where("files.repo_id", repo_id)
            .count()
        )
        doc_count = await (
            Quality.query()
            .join("symbols", "symbols.symbol_id = quality.symbol_id")
            .join("files", "files.id = symbols.file_id")
            .where("files.repo_id", repo_id)
            .where(has_docs=1)
            .count()
        )
        type_count = await (
            Quality.query()
            .join("symbols", "symbols.symbol_id = quality.symbol_id")
            .join("files", "files.id = symbols.file_id")
            .where("files.repo_id", repo_id)
            .where(has_types=1)
            .count()
        )
        doc_coverage = round(doc_count / total * 100, 1) if total > 0 else 0.0
        type_coverage = round(type_count / total * 100, 1) if total > 0 else 0.0

        gate_passed = True
        gate_failures: list[str] = []

        if coverage["coverage_percent"] < quality_config.min_test_coverage:
            gate_passed = False
            gate_failures.append(
                f"Test coverage {coverage['coverage_percent']}% < {quality_config.min_test_coverage}% minimum"
            )
        if doc_coverage < quality_config.min_doc_coverage:
            gate_passed = False
            gate_failures.append(f"Documentation coverage {doc_coverage}% < {quality_config.min_doc_coverage}% minimum")

        critical_security = [f for f in security_findings if f.severity in ("critical", "high")]
        if critical_security:
            gate_passed = False
            gate_failures.append(f"{len(critical_security)} critical/high security finding(s)")

        high_smells = [s for s in smells if s.severity == "high"]
        if high_smells:
            gate_passed = False
            gate_failures.append(f"{len(high_smells)} high-severity code smell(s)")

        return {
            "repository": repo,
            "quality_gate": {
                "passed": gate_passed,
                "failures": gate_failures,
            },
            "coverage": {
                "test_coverage_percent": coverage["coverage_percent"],
                "uncovered_count": len(coverage["uncovered"]),
                "covered_count": len(coverage["covered"]),
                "uncovered_symbols": coverage["uncovered"][:20],
            },
            "documentation": {
                "doc_coverage_percent": doc_coverage,
                "type_coverage_percent": type_coverage,
                "total_symbols": total,
            },
            "code_smells": {
                "total": len(smells),
                "by_severity": {
                    "high": len([s for s in smells if s.severity == "high"]),
                    "medium": len([s for s in smells if s.severity == "medium"]),
                    "low": len([s for s in smells if s.severity == "low"]),
                },
                "items": [
                    {
                        "symbol": s.name,
                        "file": s.file,
                        "line": s.line,
                        "type": s.smell_type,
                        "severity": s.severity,
                        "message": s.message,
                    }
                    for s in smells[:30]
                ],
            },
            "security": {
                "total": len(security_findings),
                "by_severity": {
                    "critical": len([f for f in security_findings if f.severity == "critical"]),
                    "high": len([f for f in security_findings if f.severity == "high"]),
                    "medium": len([f for f in security_findings if f.severity == "medium"]),
                    "low": len([f for f in security_findings if f.severity == "low"]),
                },
                "findings": [
                    {
                        "file": f.file,
                        "line": f.line,
                        "rule": f.rule,
                        "severity": f.severity,
                        "message": f.message,
                        "snippet": f.snippet,
                    }
                    for f in security_findings[:20]
                ],
            },
            "duplication": {
                "duplicate_groups": len(duplicates),
                "groups": [
                    {
                        "hash": g.hash,
                        "line_count": g.line_count,
                        "instances": [
                            {"name": s["name"], "file": s["file"], "line": s["line_start"]} for s in g.symbols
                        ],
                    }
                    for g in duplicates[:10]
                ],
            },
            "dead_code": {
                "total": len(dead_code),
                **({"warning": "Reference graph is empty. Run index_folder to populate it."} if refs_empty else {}),
                "items": [
                    {
                        "name": d["name"],
                        "qualified_name": d["qualified_name"],
                        "kind": d["kind"],
                        "file": d["file_path"],
                        "line": d["line_start"],
                    }
                    for d in dead_code[:30]
                ],
            },
            "gate_passed": gate_passed,
            "test_coverage": coverage["coverage_percent"],
            "doc_coverage": doc_coverage,
            "smells_count": len(smells),
            "security_count": len(security_findings),
            "duplicate_groups": len(duplicates),
            "dead_code_count": len(dead_code),
        }

    async def dependency_graph(
        self,
        repo: str,
        file_path: str,
        direction: str = "both",
        depth: int = 1,
    ) -> dict:
        """Build a file-level import dependency graph around a target file.

        Args:
            repo: Repository name.
            file_path: The file to centre the graph on.
            direction: Traversal direction: "imports", "importers", or "both".
            depth: How many hops to follow (1-3).

        Returns:
            Dict with nodes and edges.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
            IndexFileNotFoundError: If the target file is not in the index.
        """
        depth = min(max(depth, 1), 3)

        repo_obj = await Repo.where(name=repo).first()
        if not repo_obj:
            raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo)

        target = await (
            FileRecord.query()
            .join("repos", "repos.id = files.repo_id")
            .where("repos.name", repo)
            .where("files.path", file_path)
            .first()
        )
        if target is None:
            raise IndexFileNotFoundError(file_path=file_path)

        if direction not in ("imports", "importers", "both"):
            direction = "both"

        nodes: set[int] = set()
        edges: list[tuple[int, int]] = []

        if direction in ("imports", "both"):
            await _bfs_forward(target.id, depth, nodes, edges)
        if direction in ("importers", "both"):
            await _bfs_reverse(target.id, depth, nodes, edges)

        node_details: dict[str, dict] = {}
        id_to_path: dict[int, str] = {}
        for file_id in nodes:
            f = await FileRecord.find(file_id)
            if f:
                sym_count = await Symbol.where(file_id=f.id).count()
                node_details[f.path] = {
                    "language": f.language,
                    "symbol_count": sym_count,
                    "is_target": f.id == target.id,
                }
                id_to_path[f.id] = f.path

        seen_edges: set[tuple[str, str]] = set()
        path_edges = []
        for src_id, tgt_id in edges:
            src_path = id_to_path.get(src_id)
            tgt_path = id_to_path.get(tgt_id)
            if src_path and tgt_path:
                key = (src_path, tgt_path)
                if key not in seen_edges:
                    seen_edges.add(key)
                    path_edges.append({"from": src_path, "to": tgt_path})

        return {
            "target": file_path,
            "nodes": node_details,
            "edges": path_edges,
            "node_count": len(node_details),
            "edge_count": len(path_edges),
            "direction": direction,
            "depth": depth,
        }

    async def rename_symbol(self, symbol_id: str, new_name: str) -> dict:
        """Find all files and lines where a symbol name appears for renaming.

        Args:
            symbol_id: The symbol identifier to rename.
            new_name: The desired new name for the symbol.

        Returns:
            Dict with edits list, symbol info, and hints.
        """
        from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast

        target = await (
            Symbol.query()
            .select("symbols.*", "f.path as file_path", "f.content_hash", "f.repo_id")
            .join("files f", "f.id = symbols.file_id")
            .where("symbols.symbol_id", symbol_id)
            .first()
        )

        if target is None:
            return {"error": "symbol_not_found", "symbol_id": symbol_id}

        old_name = target.name
        target_file_path = getattr(target, "file_path", "")
        target_content_hash = getattr(target, "content_hash", "")

        if not new_name or not new_name.isidentifier():
            return {"error": "invalid_name", "new_name": new_name, "detail": "Must be a valid identifier"}

        if old_name == new_name:
            return {"error": "same_name", "detail": "New name is identical to old name"}

        pattern = re.compile(r"\b" + re.escape(old_name) + r"\b")

        edits: list[dict] = []
        files_with_edits: set[str] = set()
        hint_reads: list[dict] = []

        async def _scan_file(fp: str, content_hash: str) -> None:
            content_bytes = await Blob.get(content_hash)
            if content_bytes is None:
                return
            text = content_bytes.decode("utf-8", errors="replace")
            lines = text.split("\n")
            file_has_edits = False
            for line_num, line in enumerate(lines, start=1):
                if pattern.search(line):
                    edits.append(
                        {
                            "file": fp,
                            "line": line_num,
                            "old_text": line.rstrip("\r"),
                            "new_text": pattern.sub(new_name, line).rstrip("\r"),
                        }
                    )
                    file_has_edits = True
            if file_has_edits:
                files_with_edits.add(fp)
                hint_reads.append(
                    {
                        "read_file": fp,
                        "read_offset": 1,
                        "read_limit": len(lines),
                    }
                )

        if target_content_hash:
            await _scan_file(target_file_path, target_content_hash)

        blast = await _blast(symbol_id, max_depth=2)
        for entry in blast.get("confirmed", []):
            fp = entry.get("file", "")
            if fp and fp != target_file_path:
                file_rec = await FileRecord.where(path=fp).first()
                if file_rec and file_rec.content_hash:
                    await _scan_file(fp, file_rec.content_hash)

        return {
            "symbol": {
                "symbol_id": symbol_id,
                "name": old_name,
                "kind": target.kind,
                "file": target_file_path,
                "line_start": target.line_start,
                "line_end": target.line_end,
            },
            "new_name": new_name,
            "edits": edits,
            "affected_files": len(files_with_edits),
            "total_edits": len(edits),
            "_hints": {"edit": hint_reads},
        }

    async def search_columns(
        self,
        repo: str,
        query: str,
        model_pattern: str | None = None,
        max_results: int = 20,
    ) -> dict:
        """Search column metadata from ecosystem context providers.

        Args:
            repo: Repository name.
            query: Search query for column names or descriptions.
            model_pattern: Optional glob pattern to filter model names.
            max_results: Maximum results to return.

        Returns:
            Dict with columns list and provider info.

        Raises:
            RepoNotFoundError: If the repository is not indexed.
        """
        repo_obj = await Repo.where(name=repo).first()
        if not repo_obj:
            raise RepoNotFoundError(f"Repository '{repo}' is not indexed.", repo_name=repo)

        source_root = Path(repo_obj.source_path) if repo_obj.source_path else None
        if source_root is None or not source_root.exists():
            return {"columns": [], "message": "Repository source path is not available on disk."}

        from sylvan.providers.ecosystem_context.base import discover_providers

        providers = discover_providers(source_root)

        if not providers:
            return {
                "columns": [],
                "providers_found": 0,
                "message": "No ecosystem context providers found for this repo.",
            }

        all_results: list[dict] = []
        provider_names = []
        for provider in providers:
            provider_names.append(provider.name)
            matches = _search_provider_columns(provider, query, model_pattern, max_results)
            all_results.extend(matches)

        all_results.sort(key=lambda r: r["score"], reverse=True)
        all_results = all_results[:max_results]

        return {
            "query": query,
            "columns": all_results,
            "count": len(all_results),
            "providers_found": len(providers),
            "providers": provider_names,
        }


async def _find_files_that_are_imported(importer_file_ids: list[int]) -> set[int]:
    """Determine which of the given file IDs are themselves import targets.

    Args:
        importer_file_ids: List of file IDs to check.

    Returns:
        Set of file IDs from the input that are themselves imported.
    """
    if not importer_file_ids:
        return set()
    rows = await (
        FileImport.query()
        .select("DISTINCT file_imports.resolved_file_id")
        .where_in("file_imports.resolved_file_id", importer_file_ids)
        .get()
    )
    return {row.resolved_file_id for row in rows}


async def _bfs_forward(
    start_id: int,
    max_depth: int,
    nodes: set[int],
    edges: list[tuple[int, int]],
) -> None:
    """BFS forward through imports (what does this file import?).

    Args:
        start_id: Starting file ID.
        max_depth: Maximum traversal depth.
        nodes: Accumulator set of visited file IDs.
        edges: Accumulator list of (source, target) file ID pairs.
    """
    frontier = {start_id}
    nodes.add(start_id)
    for _depth in range(max_depth):
        if not frontier:
            break
        next_frontier: set[int] = set()
        for file_id in frontier:
            imports = await (
                FileImport.query()
                .select("DISTINCT file_imports.resolved_file_id")
                .where("file_imports.file_id", file_id)
                .where_not_null("file_imports.resolved_file_id")
                .get()
            )
            for imp in imports:
                target_id = imp.resolved_file_id
                edges.append((file_id, target_id))
                if target_id not in nodes:
                    nodes.add(target_id)
                    next_frontier.add(target_id)
        frontier = next_frontier


async def _bfs_reverse(
    start_id: int,
    max_depth: int,
    nodes: set[int],
    edges: list[tuple[int, int]],
) -> None:
    """BFS reverse through imports (what imports this file?).

    Args:
        start_id: Starting file ID.
        max_depth: Maximum traversal depth.
        nodes: Accumulator set of visited file IDs.
        edges: Accumulator list of (source, target) file ID pairs.
    """
    frontier = {start_id}
    nodes.add(start_id)
    for _depth in range(max_depth):
        if not frontier:
            break
        next_frontier: set[int] = set()
        for target_id in frontier:
            importers = await (
                FileImport.query()
                .select("DISTINCT file_imports.file_id")
                .where("file_imports.resolved_file_id", target_id)
                .get()
            )
            for imp in importers:
                source_id = imp.file_id
                edges.append((source_id, target_id))
                if source_id not in nodes:
                    nodes.add(source_id)
                    next_frontier.add(source_id)
        frontier = next_frontier


def _diff_symbols(old_syms: list[dict], new_syms: list[dict]) -> dict[str, list[dict]]:
    """Compute added, removed, and changed symbols between two snapshots.

    Args:
        old_syms: Symbol dicts from the old commit.
        new_syms: Symbol dicts from the current index.

    Returns:
        Dict with added, removed, changed, and unchanged_count.
    """
    old_map = {(s["qualified_name"], s["kind"]): s for s in old_syms}
    new_map = {(s["qualified_name"], s["kind"]): s for s in new_syms}

    old_keys = set(old_map)
    new_keys = set(new_map)

    added = [
        {"qualified_name": k[0], "kind": k[1], "signature": new_map[k]["signature"]}
        for k in sorted(new_keys - old_keys)
    ]
    removed = [
        {"qualified_name": k[0], "kind": k[1], "signature": old_map[k]["signature"]}
        for k in sorted(old_keys - new_keys)
    ]

    changed = []
    unchanged_count = 0
    for k in sorted(old_keys & new_keys):
        old_s = old_map[k]
        new_s = new_map[k]
        if old_s["content_hash"] != new_s["content_hash"]:
            entry: dict = {"qualified_name": k[0], "kind": k[1]}
            if old_s["signature"] != new_s["signature"]:
                entry["old_signature"] = old_s["signature"]
                entry["new_signature"] = new_s["signature"]
            else:
                entry["signature"] = new_s["signature"]
            changed.append(entry)
        else:
            unchanged_count += 1

    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged_count": unchanged_count,
    }

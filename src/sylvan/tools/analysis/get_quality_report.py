"""MCP tool: get_quality_report -- comprehensive code quality analysis."""

from sylvan.config import get_config
from sylvan.database.orm import Quality, Repo
from sylvan.error_codes import RepoNotFoundError
from sylvan.tools.support.response import MetaBuilder, ensure_orm, log_tool_call, wrap_response


@log_tool_call
async def get_quality_report(repo: str) -> dict:
    """Generate a comprehensive quality report for a repository.

    Runs all quality analyzers and returns a unified report including
    test coverage, code smells, security findings, duplication, and
    quality gate pass/fail status.

    Args:
        repo: Indexed repository name.

    Returns:
        Tool response dict with quality report and ``_meta`` envelope.

    Raises:
        RepoNotFoundError: If the repository is not indexed.
    """
    meta = MetaBuilder()
    ensure_orm()
    config = get_config()
    quality_config = config.quality

    repo_obj = await Repo.where(name=repo).first()
    if repo_obj is None:
        raise RepoNotFoundError(repo=repo, _meta=meta.build())

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
    from sylvan.database.orm import Reference

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
            f"Test coverage {coverage['coverage_percent']}% "
            f"< {quality_config.min_test_coverage}% minimum"
        )
    if doc_coverage < quality_config.min_doc_coverage:
        gate_passed = False
        gate_failures.append(
            f"Documentation coverage {doc_coverage}% "
            f"< {quality_config.min_doc_coverage}% minimum"
        )

    critical_security = [f for f in security_findings if f.severity in ("critical", "high")]
    if critical_security:
        gate_passed = False
        gate_failures.append(f"{len(critical_security)} critical/high security finding(s)")

    high_smells = [s for s in smells if s.severity == "high"]
    if high_smells:
        gate_passed = False
        gate_failures.append(f"{len(high_smells)} high-severity code smell(s)")

    report = {
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
                        {"name": s["name"], "file": s["file"], "line": s["line_start"]}
                        for s in g.symbols
                    ],
                }
                for g in duplicates[:10]
            ],
        },
        "dead_code": {
            "total": len(dead_code),
            **({"warning": "Reference graph is empty. Run index_folder to populate it."}
               if refs_empty else {}),
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
    }

    meta.set("gate_passed", gate_passed)
    meta.set("test_coverage", coverage["coverage_percent"])
    meta.set("doc_coverage", doc_coverage)
    meta.set("smells_count", len(smells))
    meta.set("security_count", len(security_findings))
    meta.set("duplicate_groups", len(duplicates))
    meta.set("dead_code_count", len(dead_code))

    return wrap_response(report, meta.build())

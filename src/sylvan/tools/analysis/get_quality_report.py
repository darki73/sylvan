"""MCP tool: get_quality_report -- comprehensive code quality analysis."""

from sylvan.tools.support.response import ensure_orm, get_meta, inject_meta, log_tool_call, wrap_response


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
    meta = get_meta()
    ensure_orm()

    from sylvan.error_codes import SylvanError

    try:
        from sylvan.services.analysis import AnalysisService

        report = await AnalysisService().quality_report(repo)
    except SylvanError as exc:
        raise inject_meta(exc, meta) from exc

    meta.set("gate_passed", report.pop("gate_passed"))
    meta.set("test_coverage", report.pop("test_coverage"))
    meta.set("doc_coverage", report.pop("doc_coverage"))
    meta.set("smells_count", report.pop("smells_count"))
    meta.set("security_count", report.pop("security_count"))
    meta.set("duplicate_groups", report.pop("duplicate_groups"))
    meta.set("dead_code_count", report.pop("dead_code_count"))

    return wrap_response(report, meta.build())

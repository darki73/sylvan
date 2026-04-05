"""MCP tool: get_quality_report."""

from sylvan.tools.base import HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class GetQualityReport(Tool):
    name = "code_health_report"
    category = "analysis"
    description = (
        "Comprehensive static quality analysis for a repository. Returns test "
        "coverage, documentation coverage, code smells, security findings, "
        "code duplication, and quality gate pass/fail. No test execution needed."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.analysis import AnalysisService

        report = await AnalysisService().quality_report(p.repo)

        meta = get_meta()
        meta.extra("gate_passed", report.pop("gate_passed"))
        meta.extra("test_coverage", report.pop("test_coverage"))
        meta.extra("doc_coverage", report.pop("doc_coverage"))
        meta.extra("smells_count", report.pop("smells_count"))
        meta.extra("security_count", report.pop("security_count"))
        meta.extra("duplicate_groups", report.pop("duplicate_groups"))
        meta.extra("dead_code_count", report.pop("dead_code_count"))
        return report

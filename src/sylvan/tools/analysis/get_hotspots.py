"""Hotspot detection tool - finds complex, frequently-changed code."""

from sylvan.tools.base.params import HasRepo, ToolParams, schema_field
from sylvan.tools.base.tool import Tool


class GetHotspots(Tool):
    name = "risky_to_change"
    category = "analysis"
    description = (
        "Ranks symbols by risk: combines cyclomatic complexity with git churn rate. "
        "High hotspot scores mean the code is both complex and frequently changed. "
        "Configurable time window and complexity threshold."
    )

    class Params(HasRepo, ToolParams):
        days: int = schema_field(default=90, ge=1, le=365, description="Days of git history to analyze")
        top_n: int = schema_field(default=20, ge=1, le=100, description="Number of hotspots to return")
        min_complexity: int = schema_field(default=2, ge=1, description="Minimum cyclomatic complexity to consider")

    async def handle(self, p: Params) -> dict:
        from sylvan.database.orm import Repo, Symbol
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.git.churn import get_file_churn, hotspot_score
        from sylvan.tools.base.meta import get_meta

        repo_obj = await Repo.where(name=p.repo).first()
        if repo_obj is None:
            raise RepoNotFoundError(repo=p.repo)

        symbols = await (
            Symbol.query()
            .select(
                "symbols.symbol_id",
                "symbols.name",
                "symbols.qualified_name",
                "symbols.kind",
                "symbols.language",
                "symbols.signature",
                "symbols.cyclomatic",
                "symbols.max_nesting",
                "symbols.param_count",
                "symbols.line_start",
                "symbols.line_end",
                "f.path",
            )
            .join("files f", "f.id = symbols.file_id")
            .where("f.repo_id", repo_obj.id)
            .where_raw(f"symbols.cyclomatic >= {p.min_complexity}")
            .order_by("symbols.cyclomatic", "DESC")
            .limit(200)
            .get()
        )

        if not symbols:
            get_meta().results_count(0)
            return {"hotspots": [], "assessment": "No complex symbols found"}

        repo_path = repo_obj.source_path
        churn_cache: dict[str, dict] = {}
        hotspots = []

        for sym in symbols:
            file_path = getattr(sym, "path", "")
            if not file_path:
                continue

            if file_path not in churn_cache:
                churn_cache[file_path] = get_file_churn(repo_path, file_path, days=p.days)

            churn = churn_cache[file_path]
            score = hotspot_score(sym.cyclomatic, churn["commit_count"])

            if score <= 3:
                assessment = "low"
            elif score <= 10:
                assessment = "medium"
            else:
                assessment = "high"

            hotspots.append(
                {
                    "symbol_id": sym.symbol_id,
                    "name": sym.name,
                    "qualified_name": sym.qualified_name,
                    "kind": sym.kind,
                    "file": file_path,
                    "line_start": sym.line_start,
                    "line_end": sym.line_end,
                    "cyclomatic": sym.cyclomatic,
                    "max_nesting": sym.max_nesting,
                    "param_count": sym.param_count,
                    "commit_count": churn["commit_count"],
                    "unique_authors": churn["unique_authors"],
                    "churn_per_week": churn["churn_per_week"],
                    "hotspot_score": score,
                    "assessment": assessment,
                }
            )

        hotspots.sort(key=lambda h: h["hotspot_score"], reverse=True)
        hotspots = hotspots[: p.top_n]

        get_meta().results_count(len(hotspots))

        result = {"hotspots": hotspots}
        if hotspots:
            high_count = sum(1 for h in hotspots if h["assessment"] == "high")
            medium_count = sum(1 for h in hotspots if h["assessment"] == "medium")
            result["summary"] = f"{high_count} high, {medium_count} medium risk hotspots"
            self.hints().next_symbol(hotspots[0]["symbol_id"]).apply(result)

        return result

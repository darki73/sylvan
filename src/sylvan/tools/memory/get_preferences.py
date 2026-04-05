"""MCP tool: get_preferences, load all applicable preferences."""

from sylvan.tools.base import HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class GetPreferences(Tool):
    name = "load_user_rules"
    category = "retrieval"
    description = (
        "Returns the user's behavioral rules for this repo: code style, test "
        "patterns, commit format, interaction preferences. Merges global, "
        "workspace, and repo scopes (repo wins). One DB query, no inference."
    )

    class Params(HasRepo, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from sylvan.services.preference import PreferenceService

        result = await PreferenceService().get_all(p.repo)
        meta = get_meta()
        meta.repo(p.repo)
        meta.results_count(result["count"])
        return result

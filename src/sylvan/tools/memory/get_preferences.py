"""MCP tool: get_preferences, load all applicable preferences."""

from sylvan.tools.base import HasRepo, Tool, ToolParams
from sylvan.tools.base.meta import get_meta


class GetPreferences(Tool):
    name = "get_preferences"
    category = "retrieval"
    description = (
        "CALL THIS FIRST at the start of every session, before doing any work. "
        "Returns the user's behavioral rules: how they want you to write code, "
        "run tests, format commits, and interact. Without this, you risk repeating "
        "mistakes the user already corrected in a previous session. Merges rules "
        "from global, workspace, and repo scopes (repo wins over workspace wins "
        "over global for the same key). These preferences complement your harness "
        "defaults with project-specific rules. One DB query, no inference."
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

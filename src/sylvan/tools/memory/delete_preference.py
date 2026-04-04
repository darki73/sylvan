"""MCP tool: delete_preference, remove a behavioral preference."""

from sylvan.tools.base import Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class DeletePreference(Tool):
    name = "delete_preference"
    category = "meta"
    description = (
        "Delete a preference that is no longer needed. Specify the same key "
        "and scope used when saving. For global scope, scope_id is not needed."
    )

    class Params(ToolParams):
        key: str = schema_field(
            description="Preference key to delete",
        )
        scope: str = schema_field(
            description="Scope level: 'global', 'workspace', or 'repo'",
            enum=["global", "workspace", "repo"],
        )
        scope_id: int | None = schema_field(
            default=None,
            description="Target ID: repo ID or workspace ID. Required for workspace/repo scope.",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.preference import PreferenceService

        result = await PreferenceService().delete(p.key, p.scope, p.scope_id)
        meta = get_meta()
        meta.extra("status", result["status"])
        return result

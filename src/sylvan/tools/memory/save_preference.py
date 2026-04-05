"""MCP tool: save_preference, store agent behavioral instruction."""

from sylvan.tools.base import Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class SavePreference(Tool):
    name = "save_user_rule"
    category = "meta"
    description = (
        "Saves a behavioral rule the user established. Key should be descriptive "
        "(e.g. 'test_style'). Instruction must be actionable as a standalone rule. "
        "Scope: global (all repos), workspace, or repo."
    )

    class Params(ToolParams):
        key: str = schema_field(
            description="Descriptive preference key (e.g. 'test_style', 'commit_format')",
        )
        instruction: str = schema_field(
            description="Actionable instruction for the agent",
        )
        scope: str = schema_field(
            description="Scope level: 'global', 'workspace', or 'repo'",
            enum=["global", "workspace", "repo"],
        )
        scope_id: int | None = schema_field(
            default=None,
            description="Target ID: repo ID or workspace ID. Required for workspace/repo scope, ignored for global.",
        )

    async def handle(self, p: Params) -> dict:
        from sylvan.services.preference import PreferenceService

        result = await PreferenceService().save(p.key, p.instruction, p.scope, p.scope_id)
        meta = get_meta()
        meta.extra("status", result["status"])
        meta.extra("scope", result["scope"])
        return result

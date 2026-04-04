"""MCP tool: save_preference, store agent behavioral instruction."""

from sylvan.tools.base import Tool, ToolParams, schema_field
from sylvan.tools.base.meta import get_meta


class SavePreference(Tool):
    name = "save_preference"
    category = "meta"
    description = (
        "Save this when the user corrects your behavior or establishes a rule. "
        "Triggers: the user says 'don't do X', 'always do Y', 'I prefer Z', "
        "or pushes back on your approach: that is a preference, save it. "
        "Use this for project or workflow rules that should follow the codebase, "
        "not the user. Your harness memory is better for personal identity and "
        "cross-project preferences. Key should be descriptive "
        "(e.g. 'test_style', 'commit_format'). Instruction must be actionable, "
        "write it as a direct rule a future agent can follow without context. "
        "Scope: 'global' applies to all repos, 'workspace' to repos in a "
        "workspace, 'repo' to one repository. Pass the numeric ID from "
        "list_repos as scope_id for workspace/repo scopes."
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

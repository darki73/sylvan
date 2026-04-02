"""Tests for sylvan.tools.meta.editor_setup -- editor detection, setup checking, and config writing."""

from __future__ import annotations

import json

from sylvan.tools.meta.editor_setup import (
    EditorKind,
    SetupAction,
    apply_setup,
    build_elicitation_message,
    check_setup,
    detect_editor,
    get_settings_file,
)


class TestDetectEditor:
    def test_claude_code(self):
        assert detect_editor("claude-code") == EditorKind.CLAUDE_CODE

    def test_cursor(self):
        assert detect_editor("cursor") == EditorKind.CURSOR

    def test_windsurf(self):
        assert detect_editor("windsurf") == EditorKind.WINDSURF

    def test_copilot(self):
        assert detect_editor("copilot") == EditorKind.COPILOT

    def test_github_copilot(self):
        assert detect_editor("github-copilot") == EditorKind.COPILOT

    def test_vscode_copilot(self):
        assert detect_editor("vscode-copilot") == EditorKind.COPILOT

    def test_unknown_client(self):
        assert detect_editor("emacs-lsp") == EditorKind.UNKNOWN

    def test_case_insensitive(self):
        assert detect_editor("Claude-Code") == EditorKind.CLAUDE_CODE
        assert detect_editor("CURSOR") == EditorKind.CURSOR

    def test_whitespace_stripped(self):
        assert detect_editor("  claude-code  ") == EditorKind.CLAUDE_CODE

    def test_substring_match(self):
        assert detect_editor("my-claude-code-fork") == EditorKind.CLAUDE_CODE
        assert detect_editor("cursor-nightly") == EditorKind.CURSOR

    def test_empty_string(self):
        assert detect_editor("") == EditorKind.UNKNOWN


class TestCheckSetupClaudeCode:
    def test_no_claude_dir(self, tmp_path):
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        assert len(actions) == 1
        assert actions[0].action == "create_settings"

    def test_settings_valid_and_complete(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "permissions": {"allow": ["mcp__sylvan__*"]},
            "hooks": {
                "SubagentStart": [{"matcher": "*", "hooks": [{"command": "echo sylvan"}]}],
                "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"command": "echo sylvan reindex"}]}],
                "UserPromptSubmit": [{"matcher": "*", "hooks": [{"command": "echo hookEventName"}]}],
            },
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        assert actions == []

    def test_missing_permission(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "permissions": {"allow": []},
            "hooks": {
                "SubagentStart": [{"matcher": "*", "hooks": [{"command": "echo sylvan"}]}],
                "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"command": "echo sylvan"}]}],
                "UserPromptSubmit": [{"matcher": "*", "hooks": [{"command": "echo hookEventName"}]}],
            },
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        action_types = {a.action for a in actions}
        assert "add_permission" in action_types

    def test_missing_subagent_hook(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "permissions": {"allow": ["mcp__sylvan__*"]},
            "hooks": {
                "SubagentStart": [],
                "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"command": "echo sylvan"}]}],
                "UserPromptSubmit": [{"matcher": "*", "hooks": [{"command": "echo hookEventName"}]}],
            },
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        action_types = {a.action for a in actions}
        assert "add_subagent_hook" in action_types
        assert "add_post_tool_hook" not in action_types
        assert "add_time_hook" not in action_types

    def test_missing_post_tool_hook(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "permissions": {"allow": ["mcp__sylvan__*"]},
            "hooks": {
                "SubagentStart": [{"matcher": "*", "hooks": [{"command": "echo sylvan"}]}],
                "PostToolUse": [],
                "UserPromptSubmit": [{"matcher": "*", "hooks": [{"command": "echo hookEventName"}]}],
            },
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        action_types = {a.action for a in actions}
        assert "add_post_tool_hook" in action_types
        assert "add_subagent_hook" not in action_types
        assert "add_time_hook" not in action_types

    def test_missing_time_hook(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        settings = {
            "permissions": {"allow": ["mcp__sylvan__*"]},
            "hooks": {
                "SubagentStart": [{"matcher": "*", "hooks": [{"command": "echo sylvan"}]}],
                "PostToolUse": [{"matcher": "Edit|Write", "hooks": [{"command": "echo sylvan"}]}],
            },
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(settings), encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        action_types = {a.action for a in actions}
        assert "add_time_hook" in action_types
        assert "add_subagent_hook" not in action_types
        assert "add_post_tool_hook" not in action_types

    def test_invalid_json(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.local.json").write_text("{not valid json", encoding="utf-8")
        actions = check_setup(EditorKind.CLAUDE_CODE, tmp_path)
        assert len(actions) == 1
        assert actions[0].action == "fix_json"


class TestCheckSetupUnknown:
    def test_unknown_editor_returns_empty(self, tmp_path):
        actions = check_setup(EditorKind.UNKNOWN, tmp_path)
        assert actions == []


class TestBuildElicitationMessage:
    def test_empty_actions(self):
        msg = build_elicitation_message([], "settings.json")
        assert msg == ""

    def test_create_settings_action(self):
        actions = [
            SetupAction(
                action="create_settings",
                path=".claude/settings.local.json",
                detail="Create the file.",
            )
        ]
        msg = build_elicitation_message(actions, ".claude/settings.local.json")
        assert "create" in msg.lower()
        assert ".claude/settings.local.json" in msg

    def test_permission_only(self):
        actions = [
            SetupAction(
                action="add_permission",
                path=".claude/settings.local.json",
                detail="Add permission.",
            )
        ]
        msg = build_elicitation_message(actions, ".claude/settings.local.json")
        assert "permission" in msg.lower()
        # Should not mention hooks since only permission is missing.
        assert "hook" not in msg.lower()

    def test_hooks_only(self):
        actions = [
            SetupAction(
                action="add_subagent_hook",
                path=".claude/settings.local.json",
                detail="Add hook.",
            )
        ]
        msg = build_elicitation_message(actions, ".claude/settings.local.json")
        assert "hook" in msg.lower()
        # Should not mention permissions since only hooks are missing.
        assert "permission" not in msg.lower()

    def test_multiple_actions(self):
        actions = [
            SetupAction(
                action="add_permission",
                path=".claude/settings.local.json",
                detail="Add permission.",
            ),
            SetupAction(
                action="add_subagent_hook",
                path=".claude/settings.local.json",
                detail="Add hook.",
            ),
        ]
        msg = build_elicitation_message(actions, ".claude/settings.local.json")
        assert "permission" in msg.lower()
        assert "hook" in msg.lower()


class TestApplySetupClaudeCode:
    def test_creates_file_from_scratch(self, tmp_path):
        apply_setup(EditorKind.CLAUDE_CODE, tmp_path)

        settings_path = tmp_path / ".claude" / "settings.local.json"
        assert settings_path.exists()

        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "mcp__sylvan__*" in settings["permissions"]["allow"]
        assert "SubagentStart" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]
        assert "UserPromptSubmit" in settings["hooks"]

    def test_merges_into_existing_without_destroying_content(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        existing = {
            "permissions": {"allow": ["mcp__other_tool__*"]},
            "hooks": {
                "PreToolUse": [{"matcher": "*", "hooks": [{"command": "echo hi"}]}],
            },
            "custom_key": "user_value",
        }
        (settings_dir / "settings.local.json").write_text(json.dumps(existing), encoding="utf-8")

        apply_setup(EditorKind.CLAUDE_CODE, tmp_path)

        settings_path = settings_dir / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

        # Original permission preserved.
        assert "mcp__other_tool__*" in settings["permissions"]["allow"]
        # Sylvan permission added.
        assert "mcp__sylvan__*" in settings["permissions"]["allow"]
        # Original hook preserved.
        assert "PreToolUse" in settings["hooks"]
        # Sylvan hooks added.
        assert "SubagentStart" in settings["hooks"]
        assert "PostToolUse" in settings["hooks"]
        # User's custom key preserved.
        assert settings["custom_key"] == "user_value"

    def test_idempotent_does_not_duplicate(self, tmp_path):
        apply_setup(EditorKind.CLAUDE_CODE, tmp_path)
        apply_setup(EditorKind.CLAUDE_CODE, tmp_path)

        settings_path = tmp_path / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

        # Permission should appear exactly once.
        assert settings["permissions"]["allow"].count("mcp__sylvan__*") == 1

    def test_unknown_editor_is_noop(self, tmp_path):
        apply_setup(EditorKind.UNKNOWN, tmp_path)
        assert not (tmp_path / ".claude").exists()


class TestGetSettingsFile:
    def test_claude_code(self):
        assert get_settings_file(EditorKind.CLAUDE_CODE) == ".claude/settings.local.json"

    def test_cursor(self):
        assert get_settings_file(EditorKind.CURSOR) == ".cursor/hooks.json"

    def test_windsurf(self):
        assert get_settings_file(EditorKind.WINDSURF) == ".windsurf/hooks.json"

    def test_copilot(self):
        assert get_settings_file(EditorKind.COPILOT) == ".github/hooks/sylvan.json"

    def test_unknown(self):
        assert get_settings_file(EditorKind.UNKNOWN) == ""

"""Tests for the hook builder system."""

import json
import subprocess

import pytest

from sylvan.tools.meta.hook_builder import (
    POST_TOOL_HOOK,
    PROMPT_SUBMIT_EVENTS,
    SUBAGENT_HOOK,
    Hook,
    TimeHook,
    time_hook_for,
)


def _bash_works() -> bool:
    """Check if bash can actually execute commands with date."""
    try:
        r = subprocess.run(
            ["bash", "-c", "echo ok"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0 and "ok" in r.stdout
    except (FileNotFoundError, OSError):
        return False


_NEEDS_BASH = pytest.mark.skipif(not _bash_works(), reason="working bash not available")


def _run_hook(command: str) -> str:
    """Run a hook command through bash and return stdout."""
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


class TestHook:
    def test_to_dict_structure(self):
        h = Hook("TestEvent").context("hello world")
        d = h.to_dict()
        assert d["type"] == "command"
        assert d["timeout"] == 5
        assert "command" in d

    @_NEEDS_BASH
    def test_output_is_valid_json(self):
        h = Hook("TestEvent").context("some context")
        d = h.to_dict()
        parsed = json.loads(_run_hook(d["command"]))
        assert parsed["hookSpecificOutput"]["hookEventName"] == "TestEvent"
        assert parsed["hookSpecificOutput"]["additionalContext"] == "some context"

    @_NEEDS_BASH
    def test_multiple_context_parts_joined(self):
        h = Hook("E").context("first.").context("second.").context("third.")
        d = h.to_dict()
        parsed = json.loads(_run_hook(d["command"]))
        assert parsed["hookSpecificOutput"]["additionalContext"] == "first. second. third."

    @_NEEDS_BASH
    def test_special_characters_in_context(self):
        h = Hook("E").context("quotes: \"hello\" and 'world'")
        d = h.to_dict()
        parsed = json.loads(_run_hook(d["command"]))
        assert "quotes:" in parsed["hookSpecificOutput"]["additionalContext"]

    def test_custom_timeout(self):
        h = Hook("E", timeout=30)
        assert h.to_dict()["timeout"] == 30


class TestTimeHook:
    def test_to_dict_structure(self):
        th = TimeHook()
        d = th.to_dict()
        assert d["type"] == "command"
        assert d["timeout"] == 5

    @_NEEDS_BASH
    def test_output_is_valid_json(self):
        th = TimeHook()
        d = th.to_dict()
        output = _run_hook(d["command"])
        parsed = json.loads(output)
        assert "hookSpecificOutput" in parsed
        assert "Current date and time:" in parsed["hookSpecificOutput"]["additionalContext"]

    @_NEEDS_BASH
    def test_custom_event_name(self):
        th = TimeHook(event="beforeSubmitPrompt")
        d = th.to_dict()
        parsed = json.loads(_run_hook(d["command"]))
        assert parsed["hookSpecificOutput"]["hookEventName"] == "beforeSubmitPrompt"

    @_NEEDS_BASH
    def test_default_event_is_user_prompt_submit(self):
        th = TimeHook()
        d = th.to_dict()
        parsed = json.loads(_run_hook(d["command"]))
        assert parsed["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


class TestTimeHookForEditor:
    def test_claude_code(self):
        assert time_hook_for("claude_code").event == "UserPromptSubmit"

    def test_cursor(self):
        assert time_hook_for("cursor").event == "beforeSubmitPrompt"

    def test_windsurf(self):
        assert time_hook_for("windsurf").event == "pre_user_prompt"

    def test_copilot(self):
        assert time_hook_for("copilot").event == "UserPromptSubmit"

    def test_unknown_falls_back(self):
        assert time_hook_for("unknown_editor").event == "UserPromptSubmit"


class TestPromptSubmitEvents:
    def test_all_editors_have_events(self):
        for editor in ("claude_code", "cursor", "windsurf", "copilot"):
            assert editor in PROMPT_SUBMIT_EVENTS

    def test_event_names_are_strings(self):
        for editor, event in PROMPT_SUBMIT_EVENTS.items():
            assert isinstance(event, str) and len(event) > 0, f"{editor} invalid"


class TestPrebuiltHooks:
    @_NEEDS_BASH
    def test_subagent_hook_valid_json(self):
        parsed = json.loads(_run_hook(SUBAGENT_HOOK.to_dict()["command"]))
        assert parsed["hookSpecificOutput"]["hookEventName"] == "SubagentStart"
        assert "mcp__sylvan__" in parsed["hookSpecificOutput"]["additionalContext"]

    @_NEEDS_BASH
    def test_post_tool_hook_valid_json(self):
        parsed = json.loads(_run_hook(POST_TOOL_HOOK.to_dict()["command"]))
        assert parsed["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "index_file" in parsed["hookSpecificOutput"]["additionalContext"]


class TestEditorConfigs:
    def test_claude_code_has_correct_time_key(self):
        from sylvan.tools.meta.editor_setup import _claude_code_settings_content

        assert "UserPromptSubmit" in _claude_code_settings_content()["hooks"]

    def test_cursor_has_correct_time_key(self):
        from sylvan.tools.meta.editor_setup import _build_cursor_hooks

        hooks = _build_cursor_hooks()["hooks"]
        assert "beforeSubmitPrompt" in hooks
        assert "UserPromptSubmit" not in hooks

    def test_windsurf_has_correct_time_key(self):
        from sylvan.tools.meta.editor_setup import _build_windsurf_hooks

        hooks = _build_windsurf_hooks()["hooks"]
        assert "pre_user_prompt" in hooks
        assert "UserPromptSubmit" not in hooks

    def test_copilot_has_correct_time_key(self):
        from sylvan.tools.meta.editor_setup import _build_copilot_hooks

        assert "UserPromptSubmit" in _build_copilot_hooks()["hooks"]

    def test_all_editors_have_three_hook_types(self):
        from sylvan.tools.meta.editor_setup import (
            _build_copilot_hooks,
            _build_cursor_hooks,
            _build_windsurf_hooks,
            _claude_code_settings_content,
        )

        for name, fn in [
            ("claude_code", _claude_code_settings_content),
            ("cursor", _build_cursor_hooks),
            ("windsurf", _build_windsurf_hooks),
            ("copilot", _build_copilot_hooks),
        ]:
            hooks = fn()["hooks"]
            assert len(hooks) == 3, f"{name} should have 3 hook types, got {len(hooks)}"

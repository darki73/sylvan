"""Tests for the ambient discovery engine (see_also + did_you_know)."""

import pytest

from sylvan.tools.support.discovery import (
    _CONTEXTUAL_MAP,
    _CONTEXTUAL_ON_TAG,
    _ONE_LINERS,
    DiscoveryEngine,
    get_engine,
    reset_engine,
)


@pytest.fixture()
def engine():
    """Fresh discovery engine for each test."""
    return DiscoveryEngine()


class TestRecordCall:
    def test_increments_call_count(self, engine):
        engine.record_call("find_code")
        assert engine.call_count == 1
        engine.record_call("read_symbol")
        assert engine.call_count == 2

    def test_tracks_tools_used(self, engine):
        engine.record_call("find_code")
        engine.record_call("read_symbol")
        assert engine.tools_used == {"find_code", "read_symbol"}

    def test_adds_to_tools_surfaced(self, engine):
        engine.record_call("find_code")
        assert "find_code" in engine.tools_surfaced

    def test_get_preferences_sets_loaded(self, engine):
        assert not engine.preferences_loaded
        engine.record_call("load_user_rules")
        assert engine.preferences_loaded

    def test_other_tools_dont_set_loaded(self, engine):
        engine.record_call("find_code")
        assert not engine.preferences_loaded


class TestSeeAlso:
    def test_contextual_from_tags(self, engine):
        engine.record_call("find_code")
        items = engine._pick_see_also("find_code", ["result_has_class"])
        assert len(items) >= 1
        # Should contain class hierarchy or blast radius
        text = " ".join(items)
        assert "inheritance_chain" in text or "what_breaks_if_i_change" in text

    def test_contextual_from_tool_map(self, engine):
        engine.record_call("find_code")
        items = engine._pick_see_also("find_code", [])
        assert len(items) >= 1
        # find_code maps to read_symbol, understand_symbol, what_breaks_if_i_change
        text = " ".join(items)
        assert any(name in text for name in _CONTEXTUAL_MAP["find_code"])

    def test_silent_when_no_context(self, engine):
        engine.record_call("delete_repo_index")
        items = engine._pick_see_also("delete_repo_index", [])
        assert items == []

    def test_no_repeats(self, engine):
        engine.record_call("find_code")
        engine._pick_see_also("find_code", [])
        surfaced_after_1 = set(engine.tools_surfaced)

        engine.record_call("find_code")
        items2 = engine._pick_see_also("find_code", [])

        # Second call should not repeat the same tools
        for item in items2:
            for name in _ONE_LINERS:
                if name in item and name in surfaced_after_1:
                    # This tool was already surfaced, shouldn't appear again
                    # unless it was also in tools_used (which re-adds it)
                    assert name in engine.tools_used

    def test_max_three_items(self, engine):
        engine.record_call("find_code")
        items = engine._pick_see_also(
            "find_code",
            ["result_has_class", "high_complexity"],
        )
        assert len(items) <= 3

    def test_discovery_piggybacks_on_context(self, engine):
        engine.record_call("find_code")
        items = engine._pick_see_also("find_code", ["result_has_class"])
        # Should have contextual items + possibly a discovery item
        assert len(items) >= 1
        assert len(items) <= 3

    def test_empty_results_suggest_alternatives(self, engine):
        engine.record_call("find_code")
        items = engine._pick_see_also("find_code", ["result_empty"])
        text = " ".join(items)
        # Empty results should suggest index_library_source, find_text, or find_docs
        assert any(name in text for name in _CONTEXTUAL_ON_TAG["result_empty"])


class TestDidYouKnow:
    def test_preferences_on_first_call(self, engine):
        engine.preference_count = 5
        engine.record_call("find_code")
        dyk = engine._pick_did_you_know("find_code", [], "myapp")
        assert dyk is not None
        assert "5 saved preferences" in dyk
        assert "load_user_rules" in dyk

    def test_no_preferences_nudge_when_zero(self, engine):
        engine.preference_count = 0
        engine.record_call("find_code")
        dyk = engine._pick_did_you_know("find_code", [], "myapp")
        assert dyk is None or "preferences" not in dyk

    def test_no_preferences_nudge_when_loaded(self, engine):
        engine.preference_count = 5
        engine.preferences_loaded = True
        engine.record_call("find_code")
        dyk = engine._pick_did_you_know("find_code", [], "myapp")
        assert dyk is None or "preferences" not in dyk

    def test_preferences_only_on_first_call(self, engine):
        engine.preference_count = 5
        # Simulate a few calls first
        for _ in range(3):
            engine.record_call("read_symbol")
        dyk = engine._pick_did_you_know("read_symbol", [], "myapp")
        # Not first call, so no preferences nudge
        assert dyk is None or "preferences" not in dyk

    def test_complexity_nudge(self, engine):
        engine.record_call("read_symbol")
        dyk = engine._pick_did_you_know(
            "read_symbol",
            ["high_complexity", "complexity:14"],
            "myapp",
        )
        assert dyk is not None
        assert "14" in dyk
        assert "risky_to_change" in dyk

    def test_empty_results_with_memories(self, engine):
        engine.memory_count = 8
        engine.record_call("find_code")
        dyk = engine._pick_did_you_know(
            "find_code",
            ["result_empty"],
            "myapp",
        )
        assert dyk is not None
        assert "recall_previous_sessions" in dyk
        assert "8 memories" in dyk

    def test_max_four_per_session(self, engine):
        engine.preference_count = 5
        # Fire 4 dyk slots
        engine.record_call("find_code")
        engine._pick_did_you_know("find_code", [], "myapp")  # slot 1

        # Advance past gap
        for _ in range(5):
            engine.record_call("read_symbol")
        engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")  # slot 2

        for _ in range(5):
            engine.record_call("read_symbol")
        engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")  # slot 3

        for _ in range(5):
            engine.record_call("read_symbol")
        engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")  # slot 4

        # 5th should be None
        for _ in range(5):
            engine.record_call("read_symbol")
        dyk = engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")
        assert dyk is None

    def test_gap_constraint(self, engine):
        engine.record_call("read_symbol")
        engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")

        # Immediately after (call 2), should be blocked by gap
        engine.record_call("read_symbol")
        dyk = engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")
        assert dyk is None

    def test_first_call_exempt_from_gap(self, engine):
        engine.preference_count = 3
        engine.record_call("find_code")
        # First call should always work regardless of gap
        dyk = engine._pick_did_you_know("find_code", [], "myapp")
        assert dyk is not None

    def test_meta_nudge_fires_mid_session(self, engine):
        engine.preference_count = 5

        # Call 1: preferences
        engine.record_call("find_code")
        engine._pick_did_you_know("find_code", [], "myapp")

        # Calls 2-5: advance past gap
        for _ in range(4):
            engine.record_call("read_symbol")

        # Call 6: contextual (to get dyk_count to 2)
        engine.record_call("read_symbol")
        engine._pick_did_you_know("read_symbol", ["high_complexity"], "myapp")

        # Calls 7-10: advance past gap
        for _ in range(4):
            engine.record_call("read_symbol")

        # Call 11: should be meta nudge (dyk_count=2, call >= 6)
        engine.record_call("find_code")
        dyk = engine._pick_did_you_know("find_code", [], "myapp")
        assert dyk is not None
        assert "available" in dyk
        assert engine._dyk_meta_shown

    def test_meta_nudge_only_fires_once(self, engine):
        engine._dyk_meta_shown = True
        engine._dyk_count = 2
        engine.call_count = 8
        assert not engine._should_meta_nudge()

    def test_late_session_remember_this(self, engine):
        # Simulate 12+ calls
        for _ in range(12):
            engine.record_call("read_symbol")
        dyk = engine._pick_did_you_know("read_symbol", [], "myapp")
        assert dyk is not None
        assert "remember_this" in dyk


class TestBuildDiscoveryTags:
    """Test the tag builder on Tool (via a minimal mock)."""

    def test_empty_symbols_list(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"symbols": []})
        assert "result_empty" in tags

    def test_class_in_results(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags(
            {
                "symbols": [{"kind": "class", "name": "Foo"}],
            }
        )
        assert "result_has_class" in tags
        assert "result_empty" not in tags

    def test_high_complexity(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"complexity": 12})
        assert "high_complexity" in tags
        assert "complexity:12" in tags

    def test_low_complexity_no_tag(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"complexity": 3})
        assert "high_complexity" not in tags

    def test_untested(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"has_tests": False})
        assert "untested" in tags

    def test_long_symbol(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"line_count": 95})
        assert "long_symbol" in tags

    def test_many_importers(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags(
            {
                "importers": [{"file": "a.py"}],
                "total": 15,
            }
        )
        assert "many_importers" in tags

    def test_no_tags_for_normal_result(self):
        from sylvan.tools.base.tool import Tool

        tool = Tool()
        tags = tool._build_discovery_tags({"name": "foo", "source": "..."})
        assert tags == []


class TestEnrichAsync:
    @pytest.mark.asyncio()
    async def test_enrich_adds_see_also(self):
        engine = DiscoveryEngine()
        result = {"symbols": [{"kind": "class", "name": "Foo"}]}
        await engine.enrich(result, "find_code", tags=["result_has_class"])
        assert "see_also" in result
        assert len(result["see_also"]) >= 1

    @pytest.mark.asyncio()
    async def test_enrich_adds_did_you_know(self):
        engine = DiscoveryEngine(preference_count=5)
        result = {"symbols": []}
        await engine.enrich(result, "find_code", tags=[], repo="myapp")
        assert "did_you_know" in result
        assert "preferences" in result["did_you_know"]

    @pytest.mark.asyncio()
    async def test_enrich_silent_when_nothing_relevant(self):
        engine = DiscoveryEngine()
        result = {"status": "removed"}
        await engine.enrich(result, "delete_repo_index", tags=[])
        assert "see_also" not in result
        # dyk might fire for late session, but on call 1 with no prefs it won't
        assert "did_you_know" not in result

    @pytest.mark.asyncio()
    async def test_enrich_increments_call_count(self):
        engine = DiscoveryEngine()
        result = {}
        await engine.enrich(result, "find_code")
        assert engine.call_count == 1
        await engine.enrich(result, "read_symbol")
        assert engine.call_count == 2


class TestSingleton:
    def test_get_engine_returns_same_instance(self):
        reset_engine()
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_reset_engine_creates_new(self):
        reset_engine()
        e1 = get_engine()
        reset_engine()
        e2 = get_engine()
        assert e1 is not e2


class TestOneLinerCatalog:
    def test_all_contextual_map_tools_have_one_liners(self):
        for tool_name, related in _CONTEXTUAL_MAP.items():
            assert tool_name in _ONE_LINERS, f"{tool_name} in contextual map but missing one-liner"
            for name in related:
                assert name in _ONE_LINERS, f"{name} (related to {tool_name}) missing one-liner"

    def test_all_tag_tools_have_one_liners(self):
        for tag, tools in _CONTEXTUAL_ON_TAG.items():
            for name in tools:
                assert name in _ONE_LINERS, f"{name} (tag {tag}) missing one-liner"

    def test_one_liners_start_with_tool_name(self):
        for name, liner in _ONE_LINERS.items():
            assert liner.startswith(f"{name}:"), f"One-liner for {name} should start with '{name}:'"

    def test_no_empty_one_liners(self):
        for name, liner in _ONE_LINERS.items():
            assert len(liner) > len(name) + 2, f"One-liner for {name} is too short"


class TestSessionProgression:
    """Test realistic multi-call session behavior."""

    @pytest.mark.asyncio()
    async def test_twelve_call_session(self):
        engine = DiscoveryEngine(preference_count=3, memory_count=5)

        calls = [
            ("find_code", ["result_has_class"]),
            ("read_symbol", []),
            ("read_symbol", []),
            ("who_depends_on_this", ["many_importers"]),
            ("read_symbol", ["high_complexity", "complexity:12"]),
            ("find_code", ["result_has_class"]),
            ("read_symbol", []),
            ("find_code", ["result_empty"]),
            ("find_code", []),
            ("read_symbol", []),
            ("who_depends_on_this", []),
            ("read_symbol", []),
        ]

        dyk_messages = []
        see_also_counts = []

        for tool_name, tags in calls:
            result = {}
            await engine.enrich(result, tool_name, tags=tags, repo="myapp")
            see_also_counts.append(len(result.get("see_also", [])))
            if "did_you_know" in result:
                dyk_messages.append(result["did_you_know"])

        # Preferences should fire on call 1
        assert any("preferences" in msg for msg in dyk_messages)

        # Should have some see_also items
        total_see_also = sum(see_also_counts)
        assert total_see_also > 0

        # Some calls should be silent (no see_also)
        assert 0 in see_also_counts

        # dyk should not exceed max
        assert len(dyk_messages) <= engine.DYK_MAX

        # Tools surfaced should be more than tools used
        assert len(engine.tools_surfaced) > len(engine.tools_used)

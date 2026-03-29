"""Tests for sylvan.session.tracker — session state tracking."""

from __future__ import annotations

import time

from sylvan.session.tracker import SessionTracker


class TestRecordSymbolAccess:
    def test_records_symbol(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("sym1")
        assert tracker.is_symbol_seen("sym1")

    def test_records_file_path(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("sym1", file_path="src/main.py")
        files = tracker.get_working_files()
        assert "src/main.py" in files

    def test_multiple_symbols_tracked(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("sym1")
        tracker.record_symbol_access("sym2")
        assert tracker.is_symbol_seen("sym1")
        assert tracker.is_symbol_seen("sym2")


class TestIsSymbolSeen:
    def test_unseen_symbol_returns_false(self):
        tracker = SessionTracker()
        assert tracker.is_symbol_seen("never_seen") is False

    def test_seen_symbol_returns_true(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("seen_sym")
        assert tracker.is_symbol_seen("seen_sym") is True


class TestComputeFileBoost:
    def test_unknown_file_returns_zero(self):
        tracker = SessionTracker()
        assert tracker.compute_file_boost("unknown.py") == 0.0

    def test_recently_accessed_file_full_boost(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("sym", file_path="recent.py")
        boost = tracker.compute_file_boost("recent.py")
        assert boost == 1.0

    def test_boost_decays_with_age(self):
        tracker = SessionTracker()
        # Manually set an old timestamp
        tracker._working_files["old.py"] = time.monotonic() - 120  # 2 minutes ago
        boost = tracker.compute_file_boost("old.py")
        assert boost == 0.5

    def test_very_old_file_negligible_boost(self):
        tracker = SessionTracker()
        tracker._working_files["ancient.py"] = time.monotonic() - 2000  # ~33 min ago
        boost = tracker.compute_file_boost("ancient.py")
        assert boost == 0.0

    def test_five_minute_boundary(self):
        tracker = SessionTracker()
        tracker._working_files["medium.py"] = time.monotonic() - 400  # ~6.7 min ago
        boost = tracker.compute_file_boost("medium.py")
        assert boost == 0.2


class TestGetSessionStats:
    def test_initial_stats(self):
        tracker = SessionTracker()
        stats = tracker.get_session_stats()
        assert stats["tool_calls"] == 0
        assert stats["symbols_retrieved"] == 0
        assert stats["sections_retrieved"] == 0
        assert stats["files_touched"] == 0
        assert stats["queries"] == 0
        assert stats["tokens_returned"] == 0
        assert stats["tokens_avoided"] == 0

    def test_stats_after_activity(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("sym1", file_path="a.py")
        tracker.record_symbol_access("sym2", file_path="b.py")
        tracker.record_section_access("sec1")
        tracker.record_query("hello", "search_symbols")
        stats = tracker.get_session_stats()
        assert stats["symbols_retrieved"] == 2
        assert stats["sections_retrieved"] == 1
        assert stats["files_touched"] == 2
        assert stats["queries"] == 1
        assert stats["tool_calls"] == 0  # record_query no longer increments; _dispatch handles it

    def test_duration_positive(self):
        tracker = SessionTracker()
        stats = tracker.get_session_stats()
        assert stats["duration_seconds"] >= 0


class TestRecordSavings:
    def test_accumulates_savings(self):
        tracker = SessionTracker()
        tracker.record_tool_call("get_symbol", category="retrieval", tokens_returned=100, tokens_equivalent=500)
        tracker.record_tool_call("get_symbol", category="retrieval", tokens_returned=50, tokens_equivalent=250)
        stats = tracker.get_session_stats()
        assert stats["tokens_returned"] == 150
        assert stats["tokens_avoided"] == 600


class TestGetSeenSymbolIds:
    def test_returns_set(self):
        tracker = SessionTracker()
        tracker.record_symbol_access("a")
        tracker.record_symbol_access("b")
        ids = tracker.get_seen_symbol_ids()
        assert ids == {"a", "b"}


class TestGetWorkingFiles:
    def test_ordered_most_recent_first(self):
        tracker = SessionTracker()
        tracker._working_files["old.py"] = time.monotonic() - 100
        tracker._working_files["new.py"] = time.monotonic()
        files = tracker.get_working_files()
        assert files[0] == "new.py"

    def test_max_count(self):
        tracker = SessionTracker()
        for i in range(20):
            tracker._working_files[f"file{i}.py"] = time.monotonic() + i
        files = tracker.get_working_files(max_count=5)
        assert len(files) == 5


class TestGetRecentQueries:
    def test_returns_recent_queries(self):
        tracker = SessionTracker()
        tracker.record_query("first", "search")
        tracker.record_query("second", "search")
        queries = tracker.get_recent_queries()
        assert queries == ["first", "second"]

    def test_max_count(self):
        tracker = SessionTracker()
        for i in range(20):
            tracker.record_query(f"q{i}", "search")
        queries = tracker.get_recent_queries(max_count=3)
        assert len(queries) == 3

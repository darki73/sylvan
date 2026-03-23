"""Tests for sylvan.database.orm.runtime.search_helpers — FTS5 query preparation and RRF."""

from __future__ import annotations

from sylvan.database.orm.runtime.search_helpers import prepare_fts_query, reciprocal_rank_fusion

# ── prepare_fts_query ───────────────────────────────────────────


class TestPrepareFtsQuery:
    """Tests for FTS5 query cleaning."""

    def test_simple_terms(self):
        result = prepare_fts_query("hello world")
        assert result == "hello OR world"

    def test_strips_special_chars(self):
        result = prepare_fts_query("foo(bar)")
        assert "(" not in result
        assert ")" not in result
        assert "foo" in result
        assert "bar" in result

    def test_filters_fts5_keywords(self):
        result = prepare_fts_query("find AND delete NOT keep")
        # AND and NOT are FTS5 keywords, should be stripped
        assert "AND" not in result.split(" OR ")
        assert "NOT" not in result.split(" OR ")
        assert "find" in result
        assert "delete" in result
        assert "keep" in result

    def test_filters_short_terms(self):
        result = prepare_fts_query("a go hi there")
        # single-char "a" should be filtered; "go" has length 2
        assert "a" not in result.split(" OR ")
        assert "go" in result

    def test_empty_after_filtering(self):
        result = prepare_fts_query("a b")
        assert result == ""

    def test_preserves_underscores_and_hyphens(self):
        result = prepare_fts_query("my_func some-thing")
        assert "my_func" in result
        assert "some-thing" in result

    def test_completely_empty_input(self):
        assert prepare_fts_query("") == ""

    def test_only_special_chars(self):
        assert prepare_fts_query("@#$%^&*") == ""

    def test_or_keyword_filtered(self):
        result = prepare_fts_query("OR NEAR")
        assert result == ""

    def test_mixed_case_keywords(self):
        result = prepare_fts_query("And Or Not")
        # "And" uppercased is "AND" — should be filtered
        assert result == ""


# ── reciprocal_rank_fusion ──────────────────────────────────────


class TestReciprocalRankFusion:
    """Tests for RRF merging of FTS5 + vector results."""

    def test_fts_only(self):
        fts = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        result = reciprocal_rank_fusion(fts, [], id_key="id")
        ids = [r["id"] for r in result]
        assert ids == ["a", "b", "c"]

    def test_vec_only(self):
        vec = [{"id": "x"}, {"id": "y"}]
        result = reciprocal_rank_fusion([], vec, id_key="id")
        ids = [r["id"] for r in result]
        assert ids == ["x", "y"]

    def test_both_empty(self):
        assert reciprocal_rank_fusion([], [], id_key="id") == []

    def test_merges_overlapping_results(self):
        fts = [{"id": "a", "name": "alpha"}, {"id": "b", "name": "beta"}]
        vec = [{"id": "b", "name": "beta"}, {"id": "c", "name": "gamma"}]
        result = reciprocal_rank_fusion(fts, vec, id_key="id")
        ids = [r["id"] for r in result]
        # "b" appears in both, should get the highest fused score
        assert "b" in ids
        assert "a" in ids
        assert "c" in ids
        # "b" should rank first (highest combined score)
        assert ids[0] == "b"

    def test_weights_affect_ranking(self):
        fts = [{"id": "fts_top"}, {"id": "shared"}]
        vec = [{"id": "vec_top"}, {"id": "shared"}]

        # Heavy FTS weight
        r1 = reciprocal_rank_fusion(fts, vec, id_key="id", fts_weight=0.9, vec_weight=0.1)
        ids1 = [r["id"] for r in r1]

        # Heavy vec weight
        r2 = reciprocal_rank_fusion(fts, vec, id_key="id", fts_weight=0.1, vec_weight=0.9)
        ids2 = [r["id"] for r in r2]

        # "shared" should be top in both cases (it appears in both lists)
        assert ids1[0] == "shared"
        assert ids2[0] == "shared"

    def test_preserves_data(self):
        fts = [{"id": "a", "name": "alpha", "score": 1.0}]
        vec = [{"id": "b", "name": "beta", "distance": 0.5}]
        result = reciprocal_rank_fusion(fts, vec, id_key="id")
        a = next(r for r in result if r["id"] == "a")
        b = next(r for r in result if r["id"] == "b")
        assert a["name"] == "alpha"
        assert b["name"] == "beta"

    def test_fts_preferred_on_conflict_data(self):
        """When same id in both, FTS data is used (it's inserted first in lookup)."""
        fts = [{"id": "x", "source": "fts"}]
        vec = [{"id": "x", "source": "vec"}]
        result = reciprocal_rank_fusion(fts, vec, id_key="id")
        assert len(result) == 1
        assert result[0]["source"] == "fts"

"""Ambient tool discovery: ``see_also`` and ``did_you_know``.

Injects contextual tool suggestions and rare high-value nudges into
tool responses. Designed to expose the full tool catalog to agents
over the course of a session without requiring explicit instructions.

Three mechanisms:

- **see_also**: 1-3 one-liner tool descriptions appended to responses
  when contextual matches exist. Silent when nothing is relevant.
- **did_you_know**: rare (max 4 per session) high-value nudges about
  the current response or session state.
- **Session tracking**: which tools have been surfaced, used, and
  nudged, so nothing repeats.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

_ONE_LINERS: dict[str, str] = {
    "find_code": (
        "find_code: find functions, classes, methods by name or keyword. ~50 tokens per result vs ~2000 for grep"
    ),
    "find_code_batch": "find_code_batch: multiple symbol searches in one call",
    "find_text": "find_text: full-text search for comments, strings, TODOs that symbol search misses",
    "find_docs": "find_docs: search documentation by title or content, returns section IDs without loading files",
    "find_similar_code": "find_similar_code: vector search for code patterns similar to a known symbol",
    "read_symbol": "read_symbol: exact source of one function or class. ~50-200 tokens vs ~2000 for the full file",
    "read_symbols": "read_symbols: batch source retrieval for multiple symbols",
    "understand_symbol": (
        "understand_symbol: source + imports + callers + siblings in one call (replaces 3-5 separate lookups)"
    ),
    "whats_in_file": "whats_in_file: all symbols in a file with signatures and line numbers, no content loaded",
    "whats_in_files": "whats_in_files: batch outlines for multiple files",
    "project_structure": "project_structure: directory tree with language and symbol counts per directory",
    "read_doc_section": "read_doc_section: one doc heading's content by ID. ~100 tokens vs ~2000 for the full file",
    "read_doc_sections": "read_doc_sections: batch retrieval for multiple doc sections",
    "doc_table_of_contents": "doc_table_of_contents: structured table of contents for all indexed docs",
    "doc_tree": "doc_tree: nested doc tree grouped by document with depth control",
    "what_breaks_if_i_change": "what_breaks_if_i_change: confirmed vs potential impact before changing a symbol",
    "what_breaks_if_i_change_these": "what_breaks_if_i_change_these: impact analysis for multiple symbols at once",
    "who_depends_on_this": "who_depends_on_this: all files that import a module, with dead-end detection",
    "who_depends_on_these": "who_depends_on_these: importers for multiple files in one call",
    "who_calls_this": "who_calls_this: symbol-level callers or callees, not file-level grep",
    "what_does_this_call": "what_does_this_call: every function this symbol depends on, with signatures",
    "what_calls_this": "what_calls_this: every function that calls this symbol",
    "inheritance_chain": "inheritance_chain: ancestors and descendants of a class",
    "import_graph": "import_graph: file-level import graph with symbol counts per node",
    "rename_everywhere": "rename_everywhere: exact edit locations for renaming, ready to apply",
    "risky_to_change": "risky_to_change: symbols ranked by complexity x git churn",
    "find_tech_debt": "find_tech_debt: per-symbol metrics: has_tests, has_docs, complexity score",
    "code_health_report": "code_health_report: full static analysis with quality gate",
    "who_touched_this": "who_touched_this: blame, change frequency, recent commits for a file or symbol",
    "whats_changed_recently": (
        "whats_changed_recently: files changed in last N commits with language and symbol counts"
    ),
    "what_changed_in_symbols": "what_changed_in_symbols: symbols added, removed, or changed between commits",
    "repo_overview": "repo_overview: file count, languages, symbol breakdown",
    "repo_deep_dive": "repo_deep_dive: full orientation with stats, tree, languages, and manifest contents",
    "where_to_start": "where_to_start: entry points and unexplored areas adapted to your session",
    "load_user_rules": (
        "load_user_rules: user's behavioral rules for this repo (code style, test patterns, commit format)"
    ),
    "save_user_rule": "save_user_rule: persist a behavioral rule for future agents",
    "remember_this": "remember_this: persist decisions and context, vector-searchable across agents and machines",
    "recall_previous_sessions": "recall_previous_sessions: find past decisions by meaning, not keywords",
    "index_library_source": "index_library_source: index a third-party library's source for API lookup",
    "migration_guide": "migration_guide: symbols added, removed, changed between two versions",
    "check_version_drift": "check_version_drift: installed deps vs indexed versions",
    "related_code": "related_code: symbols related by co-location, shared imports, or name similarity",
    "find_columns": "find_columns: column metadata from dbt and other ecosystem providers",
    "search_all_repos": "search_all_repos: search symbols across all repos in a workspace",
    "cross_repo_impact": "cross_repo_impact: cross-repo impact analysis",
    "reindex_file": "reindex_file: single-file reindex after an edit",
    "index_project": "index_project: index a local folder for search (incremental on re-runs)",
    "index_multi_repo": "index_multi_repo: index multiple folders as a workspace with cross-repo imports",
    "connection_config": "connection_config: MCP connection config for subagents",
}

_CONTEXTUAL_MAP: dict[str, list[str]] = {
    "find_code": ["read_symbol", "understand_symbol", "what_breaks_if_i_change"],
    "find_text": ["find_code", "find_docs"],
    "read_symbol": ["what_breaks_if_i_change", "what_calls_this", "what_does_this_call"],
    "understand_symbol": ["what_breaks_if_i_change", "who_depends_on_this"],
    "whats_in_file": ["read_symbol", "who_depends_on_this"],
    "who_depends_on_this": ["what_breaks_if_i_change", "import_graph"],
    "who_calls_this": ["what_breaks_if_i_change", "understand_symbol"],
    "what_calls_this": ["what_does_this_call", "what_breaks_if_i_change"],
    "what_does_this_call": ["what_calls_this", "understand_symbol"],
    "inheritance_chain": ["what_breaks_if_i_change", "find_similar_code"],
    "find_docs": ["read_doc_section", "doc_table_of_contents"],
    "read_doc_section": ["find_docs", "doc_tree"],
    "risky_to_change": ["what_breaks_if_i_change", "find_tech_debt"],
    "find_tech_debt": ["risky_to_change", "code_health_report"],
    "index_library_source": ["migration_guide", "find_code"],
}

_CONTEXTUAL_ON_TAG: dict[str, list[str]] = {
    "result_has_class": ["inheritance_chain", "what_breaks_if_i_change"],
    "result_empty": ["index_library_source", "find_text", "find_docs"],
    "high_complexity": ["risky_to_change", "what_breaks_if_i_change"],
    "untested": ["find_tech_debt"],
    "long_symbol": ["what_does_this_call", "understand_symbol"],
    "many_importers": ["what_breaks_if_i_change", "import_graph"],
}

_TOOL_CATEGORIES: dict[str, str] = {
    "find_code": "search",
    "find_code_batch": "search",
    "find_text": "search",
    "find_docs": "search",
    "find_similar_code": "search",
    "find_columns": "search",
    "search_all_repos": "search",
    "read_symbol": "reading",
    "read_symbols": "reading",
    "understand_symbol": "reading",
    "whats_in_file": "reading",
    "whats_in_files": "reading",
    "project_structure": "reading",
    "read_doc_section": "reading",
    "read_doc_sections": "reading",
    "doc_table_of_contents": "reading",
    "doc_tree": "reading",
    "repo_overview": "reading",
    "repo_deep_dive": "reading",
    "who_depends_on_this": "impact",
    "who_depends_on_these": "impact",
    "what_breaks_if_i_change": "impact",
    "what_breaks_if_i_change_these": "impact",
    "who_calls_this": "impact",
    "what_does_this_call": "impact",
    "what_calls_this": "impact",
    "inheritance_chain": "impact",
    "import_graph": "impact",
    "cross_repo_impact": "impact",
    "rename_everywhere": "impact",
    "risky_to_change": "quality",
    "find_tech_debt": "quality",
    "code_health_report": "quality",
    "who_touched_this": "history",
    "whats_changed_recently": "history",
    "what_changed_in_symbols": "history",
    "load_user_rules": "memory",
    "save_user_rule": "memory",
    "remember_this": "memory",
    "recall_previous_sessions": "memory",
    "index_library_source": "library",
    "migration_guide": "library",
    "check_version_drift": "library",
}

_CATEGORY_AFFINITY: dict[str, list[str]] = {
    "search": ["reading", "impact", "memory"],
    "reading": ["impact", "quality", "history"],
    "impact": ["reading", "quality", "history"],
    "quality": ["impact", "reading"],
    "history": ["impact", "reading"],
    "library": ["search", "reading"],
    "memory": ["search", "reading"],
}

_DISCOVERY_TIERS: list[list[str]] = [
    [
        "understand_symbol",
        "what_breaks_if_i_change",
        "what_calls_this",
        "load_user_rules",
        "recall_previous_sessions",
        "whats_in_file",
        "project_structure",
        "repo_deep_dive",
    ],
    [
        "inheritance_chain",
        "import_graph",
        "rename_everywhere",
        "find_similar_code",
        "risky_to_change",
        "find_tech_debt",
        "remember_this",
        "who_touched_this",
        "what_changed_in_symbols",
        "index_library_source",
        "migration_guide",
    ],
    [
        "find_code_batch",
        "whats_in_files",
        "read_symbols",
        "who_depends_on_these",
        "what_breaks_if_i_change_these",
        "cross_repo_impact",
        "search_all_repos",
        "find_docs",
        "code_health_report",
        "check_version_drift",
        "related_code",
    ],
    [
        "reindex_file",
        "index_project",
        "connection_config",
        "where_to_start",
        "whats_changed_recently",
    ],
]


@dataclass
class DiscoveryEngine:
    """Tracks session state and picks see_also / did_you_know entries.

    Create one per session (typically via ``get_engine()``).
    Call ``enrich()`` after each tool response to inject discovery fields.
    """

    tools_used: set[str] = field(default_factory=set)
    tools_surfaced: set[str] = field(default_factory=set)
    call_count: int = 0

    _dyk_count: int = 0
    _dyk_last_at: int = 0
    _dyk_meta_shown: bool = False
    DYK_MAX: int = 4
    DYK_MIN_GAP: int = 4

    preference_count: int = 0
    preferences_loaded: bool = False
    memory_count: int = 0

    _repo_counts_loaded: set[str] = field(default_factory=set)

    def record_call(self, tool_name: str) -> None:
        self.call_count += 1
        self.tools_used.add(tool_name)
        self.tools_surfaced.add(tool_name)
        if tool_name == "load_user_rules":
            self.preferences_loaded = True

    async def _load_repo_counts(self, repo: str | None) -> None:
        """Lazily load preference/memory counts for a repo.

        Uses PreferenceService.get_all for accurate merged count (handles
        global + workspace + repo scopes with dedup). Memory count is a
        simple row count since we just need to know if any exist.
        Runs once per repo per session.
        """
        if not repo or repo in self._repo_counts_loaded:
            return
        self._repo_counts_loaded.add(repo)
        try:
            from sylvan.services.preference import PreferenceService

            result = await PreferenceService().get_all(repo)
            self.preference_count = result.get("count", 0)
        except Exception:  # noqa: S110
            pass
        try:
            from sylvan.database.orm.models.memory import Memory
            from sylvan.database.orm.models.repository import Repository

            repo_obj = await Repository.where(name=repo).first()
            if repo_obj:
                self.memory_count = await Memory.where(repo_id=repo_obj.id).count()
        except Exception:  # noqa: S110
            pass

    async def enrich(
        self,
        result: dict,
        tool_name: str,
        *,
        tags: list[str] | None = None,
        repo: str | None = None,
    ) -> dict:
        """Inject ``see_also`` and ``did_you_know`` into a tool response.

        Args:
            result: The tool response dict (mutated in place).
            tool_name: Name of the tool that just ran.
            tags: Result characteristics (e.g. ``["result_empty"]``).
            repo: Current repo name for memory/preference nudges.

        Returns:
            The same result dict, possibly with new keys.
        """
        self.record_call(tool_name)
        tags = tags or []

        await self._load_repo_counts(repo)

        see_also = self._pick_see_also(tool_name, tags)
        if see_also:
            result["see_also"] = see_also

        dyk = self._pick_did_you_know(tool_name, tags, repo)
        if dyk:
            result["did_you_know"] = dyk

        return result

    def _pick_see_also(
        self,
        tool_name: str,
        tags: list[str],
    ) -> list[str]:
        items: list[str] = []

        for tag in tags:
            related = _CONTEXTUAL_ON_TAG.get(tag, [])
            for name in related:
                if name not in self.tools_surfaced and len(items) < 2:
                    liner = _ONE_LINERS.get(name)
                    if liner:
                        items.append(liner)
                        self.tools_surfaced.add(name)

        if len(items) < 2:
            related = _CONTEXTUAL_MAP.get(tool_name, [])
            for name in related:
                if name not in self.tools_surfaced and len(items) < 2:
                    liner = _ONE_LINERS.get(name)
                    if liner:
                        items.append(liner)
                        self.tools_surfaced.add(name)

        if not items:
            return []

        if len(items) < 3:
            pick = self._pick_discovery()
            if pick:
                items.append(pick)

        return items

    def _pick_discovery(self) -> str | None:
        """Pick a discovery one-liner from affinity-matched tiers."""
        active_cats = {_TOOL_CATEGORIES[t] for t in self.tools_used if t in _TOOL_CATEGORIES}
        affinity = set()
        for cat in active_cats:
            affinity.update(_CATEGORY_AFFINITY.get(cat, []))
        affinity -= active_cats

        unseen = set(_ONE_LINERS) - self.tools_surfaced

        affinity_picks = [t for t in unseen if _TOOL_CATEGORIES.get(t) in affinity]

        pool = affinity_picks or list(unseen)
        if not pool:
            return None

        for tier in _DISCOVERY_TIERS:
            tier_set = set(tier)
            matches = [t for t in pool if t in tier_set]
            if matches:
                name = random.choice(matches)  # noqa: S311
                liner = _ONE_LINERS.get(name)
                if liner:
                    self.tools_surfaced.add(name)
                    return liner

        name = random.choice(pool)  # noqa: S311
        liner = _ONE_LINERS.get(name)
        if liner:
            self.tools_surfaced.add(name)
            return liner
        return None

    def _can_dyk(self) -> bool:
        if self._dyk_count >= self.DYK_MAX:
            return False
        if self.call_count == 1:
            return True
        return self.call_count - self._dyk_last_at >= self.DYK_MIN_GAP

    def _record_dyk(self) -> None:
        self._dyk_count += 1
        self._dyk_last_at = self.call_count

    def _pick_did_you_know(
        self,
        tool_name: str,
        tags: list[str],
        repo: str | None,
    ) -> str | None:
        if not self._can_dyk():
            return None

        if self.call_count == 1 and self.preference_count > 0 and not self.preferences_loaded:
            self._record_dyk()
            call = f"load_user_rules(repo='{repo}')" if repo else "load_user_rules()"
            return f"This repo has {self.preference_count} saved preferences from previous sessions. {call} loads them."

        if self._should_meta_nudge():
            self._record_dyk()
            self._dyk_meta_shown = True
            used = len(self.tools_used)
            seen = len(self.tools_surfaced)
            total = len(_ONE_LINERS)
            return (
                f"You've used {used} sylvan tools and seen {seen} mentioned. "
                f"There are {total}+ available. Names describe what they do."
            )

        if "high_complexity" in tags:
            complexity = None
            if isinstance(tags, list):
                for tag in tags:
                    if tag.startswith("complexity:"):
                        complexity = tag.split(":")[1]
            msg = "High complexity symbol."
            if complexity:
                msg = f"Complexity: {complexity}."
            msg += " risky_to_change ranks symbols by complexity x git churn."
            self._record_dyk()
            return msg

        if (
            "result_empty" in tags
            and repo
            and self.memory_count > 0
            and "recall_previous_sessions" not in self.tools_used
        ):
            self._record_dyk()
            return (
                f"No results in project code. recall_previous_sessions(query=..., "
                f"repo='{repo}') checks if this was discussed in a "
                f"previous session ({self.memory_count} memories available)."
            )

        if self.call_count >= 12 and "remember_this" not in self.tools_used and self._dyk_count < self.DYK_MAX:
            self._record_dyk()
            return (
                "You've done significant exploration this session. "
                "remember_this persists decisions and context for future "
                "sessions, searchable by meaning across agents and machines."
            )

        return None

    def _should_meta_nudge(self) -> bool:
        if self._dyk_meta_shown:
            return False
        if self._dyk_count < 2:
            return False
        return self.call_count >= 6


_engine: DiscoveryEngine | None = None


def get_engine() -> DiscoveryEngine:
    """Get or create the session-scoped discovery engine."""
    global _engine
    if _engine is None:
        _engine = DiscoveryEngine()
    return _engine


def reset_engine() -> None:
    """Reset for a new session (or testing)."""
    global _engine
    _engine = None

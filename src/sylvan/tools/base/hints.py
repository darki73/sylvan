"""Hint builder for tool responses.

Builds structured ``_hints`` blocks that tell the agent what to do next.
All hint formats are defined here - tools call builder methods instead of
constructing raw dicts. This guarantees consistent field names across all
tools and maps directly to the agent's native tool parameters (Read, Edit,
Bash, and sylvan MCP tools).
"""

from __future__ import annotations


class HintBuilder:
    """Accumulates hints and serializes them into the ``_hints`` response block."""

    def __init__(self) -> None:
        self._reads: list[dict] = []
        self._edits: list[dict] = []
        self._reindexes: list[str] = []
        self._test_files: list[str] = []
        self._next: dict[str, str] = {}
        self._working_files: list[str] = []

    def read(self, file_path: str, line_start: int, line_end: int, context: int = 5) -> HintBuilder:
        """Hint the agent to read a specific file region.

        Maps directly to the Read tool's ``file_path``, ``offset``, ``limit`` params.
        Can be called multiple times for multiple regions.
        """
        self._reads.append(
            {
                "file_path": file_path,
                "offset": max(1, line_start - context),
                "limit": (line_end - line_start) + (context * 2),
            }
        )
        return self

    def edit(self, file_path: str, first_line: str) -> HintBuilder:
        """Hint the agent to edit a symbol.

        Maps to the Edit tool. Can be called multiple times for multiple locations.
        """
        self._edits.append(
            {
                "file_path": file_path,
                "old_string_starts_with": first_line.strip(),
            }
        )
        return self

    def reindex(self, repo: str, file_path: str) -> HintBuilder:
        """Hint the agent to reindex a file after editing.

        Can be called multiple times for multiple files (e.g. after rename).
        """
        self._reindexes.append(f"index_file(repo='{repo}', file_path='{file_path}')")
        return self

    def test_files(self, paths: list[str]) -> HintBuilder:
        """Hint which test files to run after making changes."""
        self._test_files = paths[:5]
        return self

    def next_tool(self, label: str, call: str) -> HintBuilder:
        """Suggest a follow-up sylvan tool call."""
        self._next[label] = call
        return self

    def next_importers(self, repo: str, file_path: str) -> HintBuilder:
        self._next["find_callers"] = f"find_importers(repo='{repo}', file_path='{file_path}')"
        return self

    def next_blast_radius(self, symbol_id: str) -> HintBuilder:
        self._next["blast_radius"] = f"get_blast_radius(symbol_id='{symbol_id}')"
        return self

    def next_dependency_graph(self, repo: str, file_path: str) -> HintBuilder:
        self._next["dependency_graph"] = f"get_dependency_graph(repo='{repo}', file_path='{file_path}')"
        return self

    def next_symbol(self, symbol_id: str) -> HintBuilder:
        self._next["get_source"] = f"get_symbol(symbol_id='{symbol_id}')"
        return self

    def next_outline(self, repo: str, file_path: str) -> HintBuilder:
        self._next["outline"] = f"get_file_outline(repo='{repo}', file_path='{file_path}')"
        return self

    def next_search(self, query: str, repo: str | None = None, kind: str | None = None) -> HintBuilder:
        """Suggest a narrower search when results were truncated."""
        parts = [f"query='{query}'"]
        if repo:
            parts.append(f"repo='{repo}'")
        if kind:
            parts.append(f"kind='{kind}'")
        self._next["search_deeper"] = f"search_symbols({', '.join(parts)})"
        return self

    def working_files(self, files: list[str], limit: int = 3) -> HintBuilder:
        """Set the working files list."""
        self._working_files = files[:limit]
        return self

    def working_files_from_session(self) -> HintBuilder:
        """Pull working files from the session tracker."""
        try:
            from sylvan.session.tracker import get_session

            needs = get_session().predict_next_needs()
            wf = needs.get("working_files", [])
            if wf:
                self._working_files = wf[:3]
        except Exception:  # noqa: S110
            pass
        return self

    def build(self) -> dict | None:
        """Serialize accumulated hints into a dict, or None if empty."""
        hints: dict = {}

        if self._working_files:
            hints["working_files"] = self._working_files
        if self._reads:
            hints["read"] = self._reads
        if self._edits:
            hints["edit"] = self._edits
        if self._reindexes:
            hints["reindex"] = self._reindexes
        if self._test_files:
            hints["test_files"] = self._test_files
        if self._next:
            hints["next"] = self._next

        return hints or None

    def apply(self, result: dict) -> None:
        """Build hints and attach to result["_hints"] if non-empty."""
        built = self.build()
        if built:
            result["_hints"] = built

    def for_symbol(
        self,
        symbol_id: str,
        file_path: str,
        line_start: int | None = None,
        line_end: int | None = None,
        first_line: str | None = None,
        repo: str | None = None,
    ) -> HintBuilder:
        """Standard hint block for any tool that returns a symbol.

        Adds read hints (if line numbers available), edit hint (if first line
        available), reindex hint, and next-tool suggestions.
        """
        if file_path and line_start is not None and line_end is not None:
            self.read(file_path, line_start, line_end)

        if file_path and first_line:
            self.edit(file_path, first_line)

        if repo and file_path:
            self.reindex(repo, file_path)
            self.next_importers(repo, file_path)
            self.next_dependency_graph(repo, file_path)

        if symbol_id:
            self.next_blast_radius(symbol_id)

        self.working_files_from_session()
        return self

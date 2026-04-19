"""Performance regression test for rust-backed discovery.

Runs the sylvan repo itself through ``discover_files`` and asserts the
wall time stays under a generous budget. Guards against regressions
that might slip past correctness tests (accidental sync I/O, lost
parallelism, bloated filter loops, etc.).

Skipped by default because perf tests are noisy on shared CI runners
and contribute nothing on a day-to-day test loop. Opt in with::

    SYLVAN_RUN_PERF_TESTS=1 uv run pytest tests/test_discovery_perf.py

The budget is intentionally loose. A tight budget would flap on slow
runners; this test catches order-of-magnitude regressions, not micro
slowdowns.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from sylvan.indexing.discovery.file_discovery import discover_files

_SYLVAN_REPO = Path(__file__).resolve().parent.parent

# Sylvan repo has ~500-600 files. Rust debug-build discovery runs in
# ~75ms locally. Budget is intentionally ~10x that so a warm but CPU-
# constrained CI runner still passes comfortably.
_BUDGET_MS = 1000


pytestmark = pytest.mark.skipif(
    os.environ.get("SYLVAN_RUN_PERF_TESTS") != "1",
    reason="perf tests opt-in via SYLVAN_RUN_PERF_TESTS=1",
)


def test_discovery_on_sylvan_repo_within_budget() -> None:
    # First call warms the filesystem cache; the perf assertion covers
    # the second call to keep cold-cache IO out of the measurement.
    discover_files(_SYLVAN_REPO)

    start = time.perf_counter()
    result = discover_files(_SYLVAN_REPO)
    elapsed_ms = (time.perf_counter() - start) * 1000

    assert result.files, "discovery should return at least one file"
    assert elapsed_ms < _BUDGET_MS, (
        f"discovery wall time regressed: {elapsed_ms:.1f}ms (budget {_BUDGET_MS}ms, files={len(result.files)})"
    )

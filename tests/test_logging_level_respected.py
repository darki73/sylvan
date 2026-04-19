"""Integration test for the primary audit fix of PR 5.

Spawns a subprocess so sylvan.logging's one-shot init runs freshly, then
asserts that DEBUG events emitted at INFO level do NOT appear in the
rotated log file (the long-standing bug the Rust port fixes).
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def _run_logging_child(sylvan_home: Path, *, level: str) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        """
        import os, sys, time

        os.environ["SYLVAN_HOME"] = sys.argv[1]
        os.environ["SYLVAN_LOG_LEVEL"] = sys.argv[2]

        from sylvan.logging import get_logger

        logger = get_logger("sylvan.test.levelcheck")
        logger.debug("DEBUG-MARKER-zxqw")
        logger.info("INFO-MARKER-zxqw")
        logger.warning("WARN-MARKER-zxqw")

        time.sleep(0.3)
        """
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(sylvan_home), level],
        capture_output=True,
        text=True,
        check=True,
    )


def _read_rotated_logs(log_dir: Path) -> str:
    contents: list[str] = []
    for candidate in sorted(log_dir.glob("sylvan.log*")):
        contents.append(candidate.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(contents)


def test_info_level_filters_debug_events_from_file(tmp_path: Path) -> None:
    _run_logging_child(tmp_path, level="INFO")

    log_dir = tmp_path / "logs"
    assert log_dir.is_dir(), "sylvan logs dir should be created on init"
    text = _read_rotated_logs(log_dir)

    assert "DEBUG-MARKER-zxqw" not in text, (
        "DEBUG events must not reach the log file when level=INFO (primary audit fix)"
    )
    assert "INFO-MARKER-zxqw" in text
    assert "WARN-MARKER-zxqw" in text


def test_debug_level_allows_debug_events_in_file(tmp_path: Path) -> None:
    _run_logging_child(tmp_path, level="DEBUG")

    log_dir = tmp_path / "logs"
    text = _read_rotated_logs(log_dir)

    assert "DEBUG-MARKER-zxqw" in text
    assert "INFO-MARKER-zxqw" in text
    assert "WARN-MARKER-zxqw" in text

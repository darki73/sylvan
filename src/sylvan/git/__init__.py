"""Git integration helpers."""

import subprocess
from pathlib import Path


def run_git(root: Path, args: list[str], timeout: int = 15) -> str | None:
    """Run a git command and return stdout, or ``None`` on failure.

    Uses :class:`subprocess.Popen` with ``stdin=DEVNULL`` and
    ``stderr=DEVNULL`` to avoid Windows IOCP pipe conflicts when called
    from anyio worker threads.

    Args:
        root: Working directory for the git command.
        args: Arguments to pass after ``git``.
        timeout: Maximum seconds to wait for the process.

    Returns:
        Stripped stdout string on success, or ``None`` on any failure.
    """
    try:
        proc = subprocess.Popen(
            ["git", *args],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, _ = proc.communicate(timeout=timeout)
        if proc.returncode == 0:
            return stdout.decode("utf-8", errors="replace").strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        try:
            proc.kill()
            proc.wait()
        except Exception:  # noqa: S110 -- best-effort process cleanup
            pass
    return None

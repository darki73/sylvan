"""Cluster discovery -- determine leader/follower role on startup."""

import json
import os
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sylvan.logging import get_logger

logger = get_logger(__name__)

_LEADER_FILE = Path.home() / ".sylvan" / "leader.json"


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running.

    Uses OpenProcess on Windows (os.kill sends CtrlBreakEvent which
    would terminate the target process).

    Args:
        pid: Process ID to check.

    Returns:
        True if the process exists and is running.
    """
    import sys

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False

    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _port_available(port: int) -> bool:
    """Check if a TCP port is available for binding.

    Args:
        port: Port number to check.

    Returns:
        True if the port can be bound.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def discover_role(port: int = 32400) -> tuple[str, str, str, dict | None]:
    """Determine whether this instance should be leader or follower.

    Checks for an existing leader by reading ``~/.sylvan/leader.json``
    and verifying the PID is alive. If no living leader exists and the
    cluster port is available, this instance becomes leader.

    Args:
        port: The cluster port to check.

    Returns:
        Tuple of (role, instance_id, coding_session_id, leader_info).
        role is ``"leader"`` or ``"follower"``.
        instance_id is a unique ID for this instance.
        coding_session_id is the coding session this instance belongs to.
        leader_info is the leader.json data if follower, None if leader.
    """
    instance_id = uuid.uuid4().hex[:12]

    # Check if leader.json exists with a living leader
    if _LEADER_FILE.exists():
        try:
            data = json.loads(_LEADER_FILE.read_text())
            leader_pid = data.get("pid")
            if leader_pid and _is_pid_alive(leader_pid) and leader_pid != os.getpid():
                coding_session_id = data.get("coding_session_id", "")
                logger.info(
                    "follower_mode",
                    leader_pid=leader_pid,
                    instance_id=instance_id,
                    coding_session_id=coding_session_id,
                )
                return "follower", instance_id, coding_session_id, data
        except (json.JSONDecodeError, OSError):
            pass

    # Try to become leader
    if _port_available(port):
        coding_session_id = f"cs-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
        leader_data = {
            "pid": os.getpid(),
            "session_id": instance_id,
            "coding_session_id": coding_session_id,
            "started_at": datetime.now(UTC).isoformat(),
            "http_port": port,
        }
        _LEADER_FILE.parent.mkdir(parents=True, exist_ok=True)
        _LEADER_FILE.write_text(json.dumps(leader_data, indent=2))
        logger.info(
            "leader_mode",
            port=port,
            instance_id=instance_id,
            coding_session_id=coding_session_id,
        )
        return "leader", instance_id, coding_session_id, None

    # Port taken but no leader file or dead PID - read leader info
    if _LEADER_FILE.exists():
        try:
            data = json.loads(_LEADER_FILE.read_text())
            coding_session_id = data.get("coding_session_id", "")
            logger.info(
                "follower_mode_port_taken",
                instance_id=instance_id,
                coding_session_id=coding_session_id,
            )
            return "follower", instance_id, coding_session_id, data
        except (json.JSONDecodeError, OSError):
            pass

    # Can't determine - fallback to standalone (leader without dashboard)
    coding_session_id = f"cs-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    logger.warning("standalone_mode", instance_id=instance_id, coding_session_id=coding_session_id)
    return "leader", instance_id, coding_session_id, None


def cleanup_leader() -> None:
    """Remove leader.json if this process is the leader.

    Called on shutdown to allow the next instance to claim leadership.
    Only removes the file if the current PID matches the recorded leader.
    """
    if _LEADER_FILE.exists():
        try:
            data = json.loads(_LEADER_FILE.read_text())
            if data.get("pid") == os.getpid():
                _LEADER_FILE.unlink()
                logger.info("leader_file_cleaned")
        except (json.JSONDecodeError, OSError):
            pass

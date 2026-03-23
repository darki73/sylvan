"""SQLite connection factory with WAL mode and sqlite-vec."""

import sqlite3
from pathlib import Path

import sqlite_vec

from sylvan.config import get_config


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode and extensions loaded.

    Configures journal_mode=WAL, foreign_keys=ON, synchronous=NORMAL,
    and busy_timeout=5000. Loads the sqlite-vec extension for vector search.

    Args:
        db_path: Path to the SQLite database file. Defaults to the
            configured database path from ``get_config()``.

    Returns:
        A fully configured SQLite connection with WAL mode and sqlite-vec loaded.
    """
    if db_path is None:
        db_path = get_config().db_path

    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    return conn

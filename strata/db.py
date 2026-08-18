"""SQLite connection factory and migration runner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrations import MIGRATIONS


def connect(db_path: Path | str) -> sqlite3.Connection:
    # One connection per request, but FastAPI may open it in a threadpool
    # thread and use it on the event loop thread for async routes.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply pending numbered migrations. Additive-only, safe to rerun."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    for version, step in MIGRATIONS:
        if version in applied:
            continue
        if callable(step):
            # Python steps handle what pure SQL cannot (e.g. table rebuilds).
            step(conn)
            with conn:
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )
        else:
            with conn:
                conn.executescript(step)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
                )

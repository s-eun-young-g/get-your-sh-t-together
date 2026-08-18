"""Learn-page metadata: headliners, day streaks, and progress numbers."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from .frontier import frontier


def headliner(conn: sqlite3.Connection, track_id: int) -> tuple[str, sqlite3.Row] | None:
    """The one line a track leads with: learning now > last learned > latest."""
    row = conn.execute(
        "SELECT * FROM nodes WHERE track_id = ? AND learning_now = 1 AND done_at IS NULL"
        " ORDER BY id DESC LIMIT 1",
        (track_id,),
    ).fetchone()
    if row:
        return ("learning now", row)
    row = conn.execute(
        "SELECT * FROM nodes WHERE track_id = ? AND done_at IS NOT NULL"
        " ORDER BY done_at DESC, id DESC LIMIT 1",
        (track_id,),
    ).fetchone()
    if row:
        return ("last learned", row)
    rows = frontier(conn, track_id, limit=1)
    if rows:
        return ("latest", rows[0])
    return None


def log_day(conn: sqlite3.Connection, source: str = "manual") -> None:
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO learning_log (day, source)"
            " VALUES (date('now', 'localtime'), ?)",
            (source,),
        )


def logged_today(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM learning_log WHERE day = date('now', 'localtime')"
        ).fetchone()
        is not None
    )


def streak(conn: sqlite3.Connection) -> int:
    """Consecutive learning days. Yesterday keeps a streak alive so a streak
    is never lost before the day is over."""
    days = {r["day"] for r in conn.execute("SELECT day FROM learning_log")}
    d = date.today()
    if d.isoformat() not in days:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


def progress(conn: sqlite3.Connection, track_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(done_at IS NOT NULL) AS done"
        " FROM nodes WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    total, done = row["total"] or 0, row["done"] or 0
    return {"total": total, "done": done, "pct": round(100 * done / total) if total else 0}

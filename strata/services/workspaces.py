"""Work areas: one per job, school, or side gig.

bootstrap() runs once per database (guarded by the table being empty) to
carry pre-workspace installs forward: the old job/school prefs become the
first workspaces and previously tagged tasks and classes are attached.
"""

from __future__ import annotations

import sqlite3


def active(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM workspaces WHERE archived_at IS NULL ORDER BY position, id"
    ).fetchall()


def first_of_kind(conn: sqlite3.Connection, kind: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM workspaces WHERE archived_at IS NULL AND kind = ?"
        " ORDER BY position, id LIMIT 1",
        (kind,),
    ).fetchone()


def create(conn: sqlite3.Connection, name: str, kind: str) -> int:
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM workspaces"
    ).fetchone()["p"]
    return conn.execute(
        "INSERT INTO workspaces (name, kind, position) VALUES (?, ?, ?)",
        (name, kind if kind in ("job", "school", "growth") else "job", pos),
    ).lastrowid


def by_name(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM workspaces WHERE archived_at IS NULL AND lower(name) = ?"
        " ORDER BY position, id LIMIT 1",
        (name.strip().lower(),),
    ).fetchone()


def bootstrap(conn: sqlite3.Connection, prefs: dict) -> None:
    if conn.execute("SELECT COUNT(*) AS n FROM workspaces").fetchone()["n"]:
        return
    with conn:
        job_id = school_id = None
        if prefs.get("mod_job", "1") == "1":
            job_id = create(conn, prefs.get("job_label") or "Job", "job")
        if prefs.get("mod_school", "1") == "1":
            school_id = create(conn, prefs.get("school_label") or "School", "school")
        if job_id:
            conn.execute(
                "UPDATE tasks SET workspace_id = ? WHERE context = 'job'"
                " AND workspace_id IS NULL",
                (job_id,),
            )
        if school_id:
            conn.execute(
                "UPDATE classes SET workspace_id = ? WHERE workspace_id IS NULL",
                (school_id,),
            )

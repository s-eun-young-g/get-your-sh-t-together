"""School logic: assignments sorted by deadline and burden."""

from __future__ import annotations

import sqlite3
from datetime import date

# Heavier work sorts first within the same due date.
BURDEN_SQL = "CASE burden WHEN 'l' THEN 0 WHEN 'm' THEN 1 ELSE 2 END"
BURDEN_LABEL = {"s": "small", "m": "medium", "l": "big"}
START_EARLY_DAYS = 10


def open_assignments(
    conn: sqlite3.Connection,
    class_id: int | None = None,
    workspace_id: int | None = None,
) -> list[dict]:
    where = "a.done_at IS NULL"
    args: tuple = ()
    if class_id is not None:
        where += " AND a.class_id = ?"
        args = (class_id,)
    if workspace_id is not None:
        where += " AND c.workspace_id = ?"
        args = (*args, workspace_id)
    rows = conn.execute(
        f"""
        SELECT a.*, c.name AS class_name FROM assignments a
        JOIN classes c ON c.id = a.class_id
        WHERE {where} AND c.archived_at IS NULL
        ORDER BY a.due_date IS NULL, a.due_date, {BURDEN_SQL}, a.id
        """,
        args,
    ).fetchall()
    return [decorate(r) for r in rows]


def decorate_due(due_date: str | None, burden: str) -> dict:
    """Human due label + start-early nudge, reusable for tasks too."""
    days = None
    if due_date:
        try:
            days = (date.fromisoformat(due_date) - date.today()).days
        except ValueError:
            days = None
    if days is None:
        label = "no deadline"
    elif days < 0:
        label = f"overdue {-days}d"
    elif days == 0:
        label = "due today"
    elif days == 1:
        label = "due tomorrow"
    else:
        label = f"due in {days}d"
    return {
        "days_left": days,
        "due_label": label,
        "start_early": burden == "l" and days is not None and 0 <= days <= START_EARLY_DAYS,
    }


def decorate(row: sqlite3.Row) -> dict:
    """Attach display fields: a human due label and a start-early nudge."""
    d = dict(row)
    d.update(decorate_due(d["due_date"], d["burden"]))
    d["burden_label"] = BURDEN_LABEL.get(d["burden"], "medium")
    return d

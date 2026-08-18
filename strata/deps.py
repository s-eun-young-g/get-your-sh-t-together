"""Shared request-scoped helpers used by every route module."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fastapi import Request

from . import db


def get_conn(request: Request):
    conn = db.connect(request.app.state.settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    templates = request.app.state.templates
    return templates.TemplateResponse(request, name, ctx or {}, status_code=status_code)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def age_days(iso: str | None) -> int:
    if not iso:
        return 0
    then = datetime.fromisoformat(iso.replace("Z", "")).replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - then).days)


def reindex(conn: sqlite3.Connection, table: str, where_col: str, where_val) -> None:
    """Rewrite positions 0..n-1 for one list, preserving current order."""
    rows = conn.execute(
        f"SELECT id FROM {table} WHERE {where_col} = ? ORDER BY position, id",
        (where_val,),
    ).fetchall()
    for i, row in enumerate(rows):
        conn.execute(f"UPDATE {table} SET position = ? WHERE id = ?", (i, row["id"]))

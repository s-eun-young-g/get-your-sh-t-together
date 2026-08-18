"""Life-module logic: bills and renewals, appointments, meal planning."""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date


def add_months(d: date, months: int) -> date:
    """Calendar-aware month addition; Jan 31 + 1 month clamps to Feb 28/29."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def decorate_bill(row: sqlite3.Row) -> dict:
    d = dict(row)
    days = (date.fromisoformat(d["next_due"]) - date.today()).days
    d["days"] = days
    d["due"] = days <= 0
    if days < 0:
        d["due_label"] = f"overdue {-days}d"
    elif days == 0:
        d["due_label"] = "due today"
    elif days == 1:
        d["due_label"] = "due tomorrow"
    else:
        d["due_label"] = f"in {days}d"
    return d


def active_bills(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bills WHERE archived_at IS NULL ORDER BY next_due, id"
    ).fetchall()
    return [decorate_bill(r) for r in rows]


def bills_due(conn: sqlite3.Connection, within_days: int = 3) -> list[dict]:
    return [b for b in active_bills(conn) if b["days"] <= within_days]


def mark_bill_paid(conn: sqlite3.Connection, bill_id: int) -> None:
    bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    if bill is None or bill["archived_at"]:
        return
    with conn:
        if bill["every_months"]:
            # Advance from the due date, not today, so cadence never drifts.
            nxt = add_months(date.fromisoformat(bill["next_due"]), bill["every_months"])
            conn.execute("UPDATE bills SET next_due = ? WHERE id = ?", (nxt.isoformat(), bill_id))
        else:
            conn.execute(
                "UPDATE bills SET archived_at = datetime('now') WHERE id = ?", (bill_id,)
            )


def open_appointments(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT * FROM appointments WHERE resolved_at IS NULL ORDER BY id"
    ).fetchall()
    return {
        "needs_booking": [r for r in rows if r["status"] == "needs_booking"],
        "booked": sorted(
            (r for r in rows if r["status"] == "booked"),
            key=lambda r: (r["when_at"] or "9999", r["id"]),
        ),
    }


def appointments_today(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM appointments WHERE resolved_at IS NULL AND status = 'booked'"
        " AND when_at = date('now', 'localtime') ORDER BY id"
    ).fetchall()


def next_upcoming(conn: sqlite3.Connection, bills: bool = True, appts: bool = True):
    """The soonest future money or appointment item: (days, name) or None."""
    items = []
    if bills:
        items += [(b["days"], b["name"]) for b in active_bills(conn) if b["days"] >= 0]
    if appts:
        from datetime import date as _date

        for a in open_appointments(conn)["booked"]:
            if a["when_at"]:
                days = (_date.fromisoformat(a["when_at"]) - _date.today()).days
                if days >= 0:
                    items.append((days, a["title"]))
    return min(items) if items else None


def grocery_new_week(conn: sqlite3.Connection) -> None:
    """Staples uncheck for the next run; bought one-offs leave the list."""
    with conn:
        conn.execute("DELETE FROM grocery_items WHERE staple = 0 AND checked = 1")
        conn.execute("UPDATE grocery_items SET checked = 0 WHERE staple = 1")

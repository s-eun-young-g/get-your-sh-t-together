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


# How far ahead a renewal surfaces as a keep-or-cancel decision.
RENEWAL_LEAD_DAYS = 14

MODE_LABELS = {"manual": "I pay it", "auto": "autopays", "renewal": "renews"}


def money_label(value: float) -> str:
    return "$" + f"{value:,.2f}".rstrip("0").rstrip(".")


def decorate_bill(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d["mode"] != "manual" and d["every_months"]:
        # Autopay and renewals charge without her; a passed date means it
        # happened, so display rolls to the next cycle instead of "overdue".
        due = date.fromisoformat(d["next_due"])
        while due < date.today():
            due = add_months(due, d["every_months"])
        d["next_due"] = due.isoformat()
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
    d["amount_label"] = money_label(d["amount"]) if d["amount"] else ""
    d["mode_label"] = MODE_LABELS[d["mode"]]
    return d


def active_bills(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bills WHERE archived_at IS NULL ORDER BY next_due, id"
    ).fetchall()
    return sorted((decorate_bill(r) for r in rows), key=lambda b: (b["next_due"], b["id"]))


def bills_due(conn: sqlite3.Connection, within_days: int = 3) -> list[dict]:
    # Only bills she pays herself belong on home; autopay and renewals
    # never need a "paid" tick.
    return [
        b for b in active_bills(conn)
        if b["mode"] == "manual" and b["days"] <= within_days
    ]


def renewals_due(conn: sqlite3.Connection) -> list[dict]:
    """Renewals inside their decision window: keep or cancel."""
    return [
        b for b in active_bills(conn)
        if b["mode"] == "renewal" and b["days"] <= RENEWAL_LEAD_DAYS
    ]


def bill_groups(conn: sqlite3.Connection) -> dict:
    bills = active_bills(conn)
    return {
        "to_pay": [b for b in bills if b["mode"] == "manual" and b["days"] <= 7],
        "decide": [
            b for b in bills
            if b["mode"] == "renewal" and b["days"] <= RENEWAL_LEAD_DAYS
        ],
        "autopilot": [b for b in bills if b["mode"] == "auto"],
    }


def monthly_load(bills: list[dict]) -> float | None:
    """Total recurring cost per month across everything with an amount."""
    priced = [b for b in bills if b["amount"] and b["every_months"]]
    if not priced:
        return None
    return sum(b["amount"] / b["every_months"] for b in priced)


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


CARD_USAGES = [("daily", "daily"), ("occasion", "on occasion"), ("dead", "dead")]


def decorate_card(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["usage_label"] = dict(CARD_USAGES).get(d["usage"], d["usage"])
    d["due_label"] = ""
    if d["due_date"]:
        # Card payments come monthly; a passed date rolls to the next cycle.
        due = date.fromisoformat(d["due_date"])
        while due < date.today():
            due = add_months(due, 1)
        days = (due - date.today()).days
        d["due_label"] = "payment due today" if days == 0 else f"payment in {days}d"
    return d


def active_cards(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM credit_cards WHERE archived_at IS NULL"
        " ORDER BY CASE usage WHEN 'daily' THEN 0 WHEN 'occasion' THEN 1 ELSE 2 END,"
        " position, id"
    ).fetchall()
    return [decorate_card(r) for r in rows]


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

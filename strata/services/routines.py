"""Recurring life upkeep: things that come back on a cadence.

The mechanic is deliberately guilt-free: a routine knows only when it was
last done and how often it recurs. Overdue shows as "due", never as a broken
streak or a red number.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

# Starter library of recurring tasks people with ADHD commonly drop.
# (key, name, every_days)
PRESETS = [
    ("meds-refill", "refill prescriptions", 30),
    ("laundry", "laundry", 7),
    ("sheets", "change sheets", 14),
    ("trash", "trash and recycling night", 7),
    ("plants", "water plants", 7),
    ("groceries", "grocery run", 7),
    ("weekly-reset", "weekly reset (mail pile, bag, desk)", 7),
    ("call-family", "call family", 7),
    ("email-sweep", "email triage sweep", 7),
    ("money-checkin", "money check-in (statements, subscriptions)", 30),
    ("backup", "back up phone and laptop", 30),
    ("haircut", "haircut", 42),
    ("dentist", "dentist checkup", 180),
    ("doctor", "annual physical (book it)", 365),
    ("car-service", "car oil change or service", 180),
]


def add_preset(conn: sqlite3.Connection, key: str) -> None:
    preset = next((p for p in PRESETS if p[0] == key), None)
    if preset is None:
        return
    with conn:
        conn.execute(
            "INSERT INTO routines (name, every_days, preset_key) VALUES (?, ?, ?)"
            " ON CONFLICT(preset_key) DO UPDATE SET active = 1",
            (preset[1], preset[2], preset[0]),
        )


def unused_presets(conn: sqlite3.Connection) -> list[tuple]:
    used = {
        r["preset_key"]
        for r in conn.execute(
            "SELECT preset_key FROM routines WHERE preset_key IS NOT NULL AND active = 1"
        )
    }
    return [p for p in PRESETS if p[0] not in used]


def decorate(row: sqlite3.Row) -> dict:
    d = dict(row)
    if d["last_done"]:
        due_on = date.fromisoformat(d["last_done"]) + timedelta(days=d["every_days"])
    else:
        due_on = date.today()
    days = (due_on - date.today()).days
    d["days"] = days
    d["due"] = days <= 0
    if days <= 0:
        d["due_label"] = "due"
    elif days == 1:
        d["due_label"] = "tomorrow"
    else:
        d["due_label"] = f"in {days}d"
    return d


def list_active(conn: sqlite3.Connection) -> list[dict]:
    rows = [
        decorate(r)
        for r in conn.execute("SELECT * FROM routines WHERE active = 1")
    ]
    rows.sort(key=lambda r: (r["days"], r["id"]))
    return rows


def due(conn: sqlite3.Connection, limit: int = 3) -> list[dict]:
    return [r for r in list_active(conn) if r["due"]][:limit]


def mark_done(conn: sqlite3.Connection, routine_id: int) -> None:
    with conn:
        conn.execute(
            "UPDATE routines SET last_done = date('now', 'localtime') WHERE id = ?",
            (routine_id,),
        )

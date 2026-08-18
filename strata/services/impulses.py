"""Anti-impulsivity logic: cooldown timers and the honesty ledger.

The stats celebrate what waiting killed for free. Regret data is framed as
information about which categories of impulse to trust, never as failure.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

CATEGORIES = [
    ("shopping", "shopping"),
    ("food", "food"),
    ("social", "social"),
    ("other", "other"),
]

# Slider stops: 30 minutes, hourly through 23 hours, daily through 6 days,
# weekly through 3 weeks, a month, then indefinitely.
INDEFINITE = 60 * 24 * 365 * 100  # sentinel: never opens on its own

SLIDER_STOPS: list[tuple[int, str]] = (
    [(30, "30 minutes"), (60, "1 hour")]
    + [(h * 60, f"{h} hours") for h in range(2, 24)]
    + [(1440, "1 day")]
    + [(d * 1440, f"{d} days") for d in range(2, 7)]
    + [(10080, "1 week"), (20160, "2 weeks"), (30240, "3 weeks")]
    + [(43200, "1 month"), (INDEFINITE, "indefinitely")]
)

DEFAULT_STOP_INDEX = next(
    i for i, (minutes, _) in enumerate(SLIDER_STOPS) if minutes == 1440
)


def _remaining_minutes(row: sqlite3.Row) -> int:
    created = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - created).total_seconds() / 60
    return max(0, int(row["wait_minutes"] - elapsed))


def decorate(row: sqlite3.Row) -> dict:
    d = dict(row)
    if row["wait_minutes"] >= INDEFINITE:
        d["ready"] = False
        d["wait_label"] = "parked indefinitely"
        return d
    remaining = _remaining_minutes(row)
    d["ready"] = remaining == 0
    if remaining == 0:
        d["wait_label"] = "ready"
    elif remaining < 60:
        d["wait_label"] = f"opens in {remaining}m"
    elif remaining < 48 * 60:
        d["wait_label"] = f"opens in {remaining // 60}h"
    else:
        d["wait_label"] = f"opens in {remaining // 1440}d"
    return d


def waiting(conn: sqlite3.Connection) -> list[dict]:
    rows = [
        decorate(r)
        for r in conn.execute(
            "SELECT * FROM impulses WHERE status = 'waiting' ORDER BY created_at, id"
        )
    ]
    # Ready ones first: they are the decisions to make.
    return sorted(rows, key=lambda r: (not r["ready"], r["id"]))


def unlogged(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM impulses WHERE status = 'acted' AND regret IS NULL"
        " ORDER BY acted_at, id"
    ).fetchall()


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT"
        "  SUM(status = 'released') AS let_go,"
        "  SUM(status = 'acted') AS acted,"
        "  SUM(regret = 1) AS regretted,"
        "  SUM(regret = 0) AS no_regret"
        " FROM impulses"
    ).fetchone()
    return {k: row[k] or 0 for k in ("let_go", "acted", "regretted", "no_regret")}

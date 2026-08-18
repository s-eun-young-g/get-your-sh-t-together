"""The anhedonia rescue list.

When nothing sounds appealing, choosing is the broken part, so the page
serves exactly one suggestion. Outcomes are logged honestly, and the stats
exist to contradict anhedonia's central lie: the record shows that forcing
it has actually helped before, with numbers.
"""

from __future__ import annotations

import sqlite3

# Low-activation-energy things that sometimes cut through. (key, title)
PRESETS = [
    ("shower", "take a shower"),
    ("walk", "walk around the block, no phone"),
    ("song", "play one song you love, loud"),
    ("text", "text someone without overthinking it"),
    ("outside", "sit outside for five minutes"),
    ("tidy", "tidy one surface for five minutes"),
    ("stretch", "stretch on the floor"),
    ("water-snack", "water and a real snack"),
    ("drive", "drive or ride somewhere, anywhere"),
    ("old-photos", "look through your favorite photos"),
]


def add_preset(conn: sqlite3.Connection, key: str) -> None:
    preset = next((p for p in PRESETS if p[0] == key), None)
    if preset is None:
        return
    with conn:
        conn.execute(
            "INSERT INTO rescue_items (title, preset_key) VALUES (?, ?)"
            " ON CONFLICT(preset_key) DO UPDATE SET active = 1",
            (preset[1], preset[0]),
        )


def unused_presets(conn: sqlite3.Connection) -> list[tuple]:
    used = {
        r["preset_key"]
        for r in conn.execute(
            "SELECT preset_key FROM rescue_items WHERE preset_key IS NOT NULL AND active = 1"
        )
    }
    return [p for p in PRESETS if p[0] not in used]


def decorate(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["record"] = f"helped {d['helped']} of {d['tries']}" if d["tries"] else "untried"
    return d


def suggestion(conn: sqlite3.Connection) -> dict | None:
    """One thing to try: best track record first, rotating through the list
    (a "not this" tap stamps last_suggested, pushing the item to the back)."""
    row = conn.execute(
        "SELECT * FROM rescue_items WHERE active = 1 AND pending_at IS NULL"
        " ORDER BY last_suggested IS NOT NULL, last_suggested,"
        "  CAST(helped AS REAL) / MAX(tries, 1) DESC, tries, id"
        " LIMIT 1"
    ).fetchone()
    return decorate(row) if row else None


def pending(conn: sqlite3.Connection) -> list[dict]:
    return [
        decorate(r)
        for r in conn.execute(
            "SELECT * FROM rescue_items WHERE active = 1 AND pending_at IS NOT NULL"
            " ORDER BY pending_at, id"
        )
    ]


def all_items(conn: sqlite3.Connection) -> list[dict]:
    return [
        decorate(r)
        for r in conn.execute(
            "SELECT * FROM rescue_items WHERE active = 1"
            " ORDER BY CAST(helped AS REAL) / MAX(tries, 1) DESC, tries DESC, id"
        )
    ]


def log_outcome(conn: sqlite3.Connection, item_id: int, helped: bool) -> None:
    with conn:
        conn.execute(
            "UPDATE rescue_items SET tries = tries + 1, helped = helped + ?,"
            " pending_at = NULL WHERE id = ? AND pending_at IS NOT NULL",
            (1 if helped else 0, item_id),
        )


def stats(conn: sqlite3.Connection) -> dict:
    row = conn.execute(
        "SELECT SUM(tries) AS tries, SUM(helped) AS helped FROM rescue_items"
    ).fetchone()
    return {"tries": row["tries"] or 0, "helped": row["helped"] or 0}

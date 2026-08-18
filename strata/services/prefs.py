"""Key-value personalization prefs.

The app keeps one dict on app.state, shared with the Jinja globals, and
mutates it in place when settings are saved so every template sees updates.
"""

from __future__ import annotations

import sqlite3

DEFAULTS = {
    "name": "",
    "manifesto": "",
    "job_label": "Job",
    "school_label": "School",
    # Section toggles: "1" on, "0" off. All on by default; the settings page
    # is where a new user shapes the app to their life (no survey needed).
    "mod_job": "1",
    "mod_school": "1",
    "mod_evenings": "1",
    "mod_packing": "1",
    "mod_routines": "1",
    "mod_finance": "1",
    "mod_appointments": "1",
    "mod_meals": "1",
    "mod_pause": "1",
    "mod_rescue": "0",
}


def load(conn: sqlite3.Connection) -> dict:
    prefs = dict(DEFAULTS)
    for row in conn.execute("SELECT key, value FROM prefs"):
        prefs[row["key"]] = row["value"]
    return prefs


def save(conn: sqlite3.Connection, values: dict) -> None:
    with conn:
        for key, value in values.items():
            if key not in DEFAULTS:
                continue
            conn.execute(
                "INSERT INTO prefs (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value).strip()),
            )

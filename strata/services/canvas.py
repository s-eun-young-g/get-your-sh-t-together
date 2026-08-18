"""Pull courses and assignments from a Canvas LMS instance.

Outbound-only, so it works on a laptop with no deploy. Gated on
CANVAS_BASE_URL + CANVAS_TOKEN. Sync rules mirror seed_sync: Canvas owns
title and due date, the user owns burden edits and done state.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.request
from datetime import datetime

log = logging.getLogger("strata.canvas")


def fetch_json(base_url: str, path: str, token: str):
    req = urllib.request.Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _due_date(due_at: str | None) -> str | None:
    """Canvas due_at is UTC; convert to the local date so 11:59pm stays on its day."""
    if not due_at:
        return None
    dt = datetime.fromisoformat(due_at.replace("Z", "+00:00")).astimezone()
    return dt.date().isoformat()


def _default_burden(points) -> str:
    if points is None:
        return "m"
    if points >= 80:
        return "l"
    if points >= 25:
        return "m"
    return "s"


def sync(
    conn: sqlite3.Connection,
    base_url: str,
    token: str,
    fetch=fetch_json,
    workspace_id: int | None = None,
) -> dict:
    """Upsert classes and assignments. Returns counts for the UI."""
    counts = {"classes": 0, "new": 0, "updated": 0}
    try:
        courses = fetch(base_url, "/api/v1/courses?enrollment_state=active&per_page=100", token)
    except Exception:
        log.warning("canvas course fetch failed", exc_info=True)
        return {"error": "Could not reach Canvas. Check CANVAS_BASE_URL and CANVAS_TOKEN."}

    for course in courses:
        name = course.get("name")
        cid = course.get("id")
        if not name or cid is None:
            continue
        with conn:
            existing = conn.execute(
                "SELECT id FROM classes WHERE canvas_course_id = ?", (cid,)
            ).fetchone()
            if existing:
                class_id = existing["id"]
                conn.execute("UPDATE classes SET name = ? WHERE id = ?", (name, class_id))
            else:
                class_id = conn.execute(
                    "INSERT INTO classes (name, canvas_course_id, workspace_id)"
                    " VALUES (?, ?, ?)",
                    (name, cid, workspace_id),
                ).lastrowid
                counts["classes"] += 1

        try:
            assignments = fetch(
                base_url, f"/api/v1/courses/{cid}/assignments?per_page=100&order_by=due_at", token
            )
        except Exception:
            log.warning("canvas assignment fetch failed for course %s", cid, exc_info=True)
            continue

        for a in assignments:
            aid, title = a.get("id"), a.get("name")
            if aid is None or not title:
                continue
            due = _due_date(a.get("due_at"))
            with conn:
                existing = conn.execute(
                    "SELECT id FROM assignments WHERE canvas_id = ?", (aid,)
                ).fetchone()
                if existing:
                    # Canvas owns title/due date; never touch burden or done_at.
                    conn.execute(
                        "UPDATE assignments SET title = ?, due_date = ?, class_id = ?"
                        " WHERE canvas_id = ?",
                        (title, due, class_id, aid),
                    )
                    counts["updated"] += 1
                else:
                    conn.execute(
                        "INSERT INTO assignments (class_id, title, due_date, burden, canvas_id)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (class_id, title, due, _default_burden(a.get("points_possible")), aid),
                    )
                    counts["new"] += 1
    return counts

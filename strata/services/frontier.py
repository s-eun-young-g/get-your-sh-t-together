"""Learn-tree logic: frontier derivation, cycle checks, node/edge creation.

Lock state is never stored. A node is available when it is not done and every
prerequisite is done; everything else follows from the edges at query time.
"""

from __future__ import annotations

import re
import sqlite3

FRONTIER_SQL = """
SELECT n.* FROM nodes n
WHERE n.track_id = ? AND n.done_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM node_edges e
    JOIN nodes p ON p.id = e.prereq_id
    WHERE e.node_id = n.id AND p.done_at IS NULL
  )
ORDER BY n.position, n.id
"""


def frontier(conn: sqlite3.Connection, track_id: int, limit: int = 5) -> list[sqlite3.Row]:
    return conn.execute(FRONTIER_SQL + " LIMIT ?", (track_id, limit)).fetchall()


def frontier_ids(conn: sqlite3.Connection, track_id: int) -> set[int]:
    return {r["id"] for r in conn.execute(FRONTIER_SQL, (track_id,))}


def would_cycle(conn: sqlite3.Connection, prereq_id: int, node_id: int) -> bool:
    """True if adding prereq -> node would create a cycle (or a self-edge)."""
    if prereq_id == node_id:
        return True
    row = conn.execute(
        """
        WITH RECURSIVE anc(id) AS (
          SELECT ?
          UNION
          SELECT e.prereq_id FROM node_edges e JOIN anc ON e.node_id = anc.id
        )
        SELECT 1 FROM anc WHERE id = ? LIMIT 1
        """,
        (prereq_id, node_id),
    ).fetchone()
    return row is not None


def add_edge(conn: sqlite3.Connection, prereq_id: int, node_id: int, origin: str) -> bool:
    """Insert an edge unless it would cycle. Returns True if inserted or present."""
    if would_cycle(conn, prereq_id, node_id):
        return False
    # Both nodes must belong to the same track (v1 rule).
    tracks = conn.execute(
        "SELECT COUNT(DISTINCT track_id) AS n FROM nodes WHERE id IN (?, ?)",
        (prereq_id, node_id),
    ).fetchone()
    if tracks["n"] != 1:
        return False
    conn.execute(
        "INSERT OR IGNORE INTO node_edges (prereq_id, node_id, origin) VALUES (?, ?, ?)",
        (prereq_id, node_id, origin),
    )
    return True


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "node"


def unique_slug(conn: sqlite3.Connection, track_id: int, title: str) -> str:
    base = slugify(title)
    slug, n = base, 1
    while conn.execute(
        "SELECT 1 FROM nodes WHERE track_id = ? AND slug = ?", (track_id, slug)
    ).fetchone():
        n += 1
        slug = f"{base}-{n}"
    return slug


def create_node(
    conn: sqlite3.Connection,
    track_id: int,
    title: str,
    summary: str,
    origin: str,
    prereq_ids: list[int],
) -> int:
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM nodes WHERE track_id = ?",
        (track_id,),
    ).fetchone()["p"]
    cur = conn.execute(
        "INSERT INTO nodes (track_id, slug, title, summary, origin, position)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (track_id, unique_slug(conn, track_id, title), title, summary, origin, pos),
    )
    node_id = cur.lastrowid
    for pid in prereq_ids:
        add_edge(conn, pid, node_id, origin)
    return node_id

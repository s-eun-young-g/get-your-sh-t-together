"""Idempotent sync of seed YAML files into the learn tables.

Rules, in order of importance:
- never touch done_at
- never modify or delete user/ai nodes or edges
- seed nodes get title/summary/position refreshed; missing seed nodes are inserted
- nodes absent from the seed file are left alone
- seed edges are inserted (cycle-checked); seed edges gone from the file are
  deleted, which can only unlock more, never destroy progress
- slugs are permanent keys; a cyclic seed file aborts that track with a warning
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import yaml

from .frontier import add_edge

log = logging.getLogger("strata.seed_sync")


def sync_all(conn: sqlite3.Connection, seeds_dir: Path) -> None:
    if not seeds_dir.is_dir():
        return
    for path in sorted(seeds_dir.glob("*.yaml")):
        try:
            sync_track(conn, yaml.safe_load(path.read_text()))
        except Exception:
            log.warning("seed sync failed for %s, skipping", path.name, exc_info=True)


def _has_cycle(node_slugs: set[str], edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, list[str]] = {s: [] for s in node_slugs}
    for prereq, node in edges:
        if prereq in graph and node in graph:
            graph[prereq].append(node)
    state: dict[str, int] = {}

    def visit(s: str) -> bool:
        if state.get(s) == 1:
            return True
        if state.get(s) == 2:
            return False
        state[s] = 1
        if any(visit(t) for t in graph[s]):
            return True
        state[s] = 2
        return False

    return any(visit(s) for s in node_slugs)


def sync_track(conn: sqlite3.Connection, data: dict) -> None:
    track_slug = data["slug"]
    seed_nodes = data.get("nodes", [])
    seed_edges: list[tuple[str, str]] = []
    for n in seed_nodes:
        for prereq in n.get("after", []):
            seed_edges.append((prereq, n["slug"]))

    if _has_cycle({n["slug"] for n in seed_nodes}, seed_edges):
        log.warning("seed file for track %s has a prerequisite cycle, skipping", track_slug)
        return

    with conn:
        conn.execute(
            "INSERT INTO tracks (slug, name, position) VALUES (?, ?, ?)"
            " ON CONFLICT(slug) DO UPDATE SET name = excluded.name, position = excluded.position",
            (track_slug, data["name"], data.get("position", 0)),
        )
        track_id = conn.execute(
            "SELECT id FROM tracks WHERE slug = ?", (track_slug,)
        ).fetchone()["id"]

        for pos, n in enumerate(seed_nodes):
            existing = conn.execute(
                "SELECT id, origin FROM nodes WHERE track_id = ? AND slug = ?",
                (track_id, n["slug"]),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO nodes (track_id, slug, title, summary, origin, position)"
                    " VALUES (?, ?, ?, ?, 'seed', ?)",
                    (track_id, n["slug"], n["title"], n.get("summary", ""), pos),
                )
            elif existing["origin"] == "seed":
                conn.execute(
                    "UPDATE nodes SET title = ?, summary = ?, position = ? WHERE id = ?",
                    (n["title"], n.get("summary", ""), pos, existing["id"]),
                )
            else:
                log.warning(
                    "seed slug %s/%s collides with a %s node, leaving it alone",
                    track_slug, n["slug"], existing["origin"],
                )

        ids = {
            r["slug"]: r["id"]
            for r in conn.execute("SELECT id, slug FROM nodes WHERE track_id = ?", (track_id,))
        }
        wanted = {
            (ids[p], ids[c]) for p, c in seed_edges if p in ids and c in ids
        }
        current = {
            (r["prereq_id"], r["node_id"])
            for r in conn.execute(
                "SELECT e.prereq_id, e.node_id FROM node_edges e"
                " JOIN nodes n ON n.id = e.node_id"
                " WHERE n.track_id = ? AND e.origin = 'seed'",
                (track_id,),
            )
        }
        for prereq_id, node_id in wanted - current:
            add_edge(conn, prereq_id, node_id, "seed")
        for prereq_id, node_id in current - wanted:
            conn.execute(
                "DELETE FROM node_edges WHERE prereq_id = ? AND node_id = ? AND origin = 'seed'",
                (prereq_id, node_id),
            )

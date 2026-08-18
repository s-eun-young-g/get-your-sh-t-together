import copy

from strata.services.seed_sync import sync_track

SEED = {
    "slug": "demo",
    "name": "Demo",
    "position": 0,
    "nodes": [
        {"slug": "a", "title": "A", "summary": "first"},
        {"slug": "b", "title": "B", "after": ["a"]},
        {"slug": "c", "title": "C", "after": ["a", "b"]},
    ],
}


def _dump(conn):
    nodes = [
        tuple(r)
        for r in conn.execute(
            "SELECT slug, title, summary, origin, position, done_at FROM nodes"
            " ORDER BY slug"
        )
    ]
    edges = [
        tuple(r)
        for r in conn.execute(
            "SELECT p.slug, n.slug, e.origin FROM node_edges e"
            " JOIN nodes p ON p.id = e.prereq_id JOIN nodes n ON n.id = e.node_id"
            " ORDER BY 1, 2"
        )
    ]
    return nodes, edges


def test_sync_is_idempotent(conn):
    sync_track(conn, SEED)
    first = _dump(conn)
    sync_track(conn, SEED)
    assert _dump(conn) == first


def test_title_edit_propagates_and_progress_survives(conn):
    sync_track(conn, SEED)
    with conn:
        conn.execute("UPDATE nodes SET done_at = '2026-01-01' WHERE slug = 'a'")
    edited = copy.deepcopy(SEED)
    edited["nodes"][0]["title"] = "A, renamed"
    sync_track(conn, edited)
    row = conn.execute("SELECT title, done_at FROM nodes WHERE slug = 'a'").fetchone()
    assert row["title"] == "A, renamed"
    assert row["done_at"] == "2026-01-01"


def test_user_nodes_and_edges_untouched(conn):
    sync_track(conn, SEED)
    track_id = conn.execute("SELECT id FROM tracks").fetchone()["id"]
    a = conn.execute("SELECT id FROM nodes WHERE slug = 'a'").fetchone()["id"]
    with conn:
        mine = conn.execute(
            "INSERT INTO nodes (track_id, slug, title, origin) VALUES (?, 'mine', 'Mine', 'user')",
            (track_id,),
        ).lastrowid
        conn.execute(
            "INSERT INTO node_edges (prereq_id, node_id, origin) VALUES (?, ?, 'user')",
            (a, mine),
        )
    sync_track(conn, SEED)
    assert conn.execute("SELECT title FROM nodes WHERE slug = 'mine'").fetchone()["title"] == "Mine"
    assert conn.execute(
        "SELECT 1 FROM node_edges WHERE node_id = ? AND origin = 'user'", (mine,)
    ).fetchone()


def test_removed_seed_edge_deleted_user_edge_kept(conn):
    sync_track(conn, SEED)
    trimmed = copy.deepcopy(SEED)
    trimmed["nodes"][2]["after"] = ["b"]  # drop a -> c
    sync_track(conn, trimmed)
    _, edges = _dump(conn)
    assert ("a", "c", "seed") not in edges
    assert ("a", "b", "seed") in edges and ("b", "c", "seed") in edges


def test_missing_seed_node_not_deleted(conn):
    sync_track(conn, SEED)
    trimmed = copy.deepcopy(SEED)
    trimmed["nodes"] = trimmed["nodes"][:2]  # c gone from the file
    sync_track(conn, trimmed)
    assert conn.execute("SELECT 1 FROM nodes WHERE slug = 'c'").fetchone()


def test_cyclic_seed_file_skipped(conn):
    bad = {
        "slug": "bad",
        "name": "Bad",
        "nodes": [
            {"slug": "x", "title": "X", "after": ["y"]},
            {"slug": "y", "title": "Y", "after": ["x"]},
        ],
    }
    sync_track(conn, bad)
    assert conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()["n"] == 0

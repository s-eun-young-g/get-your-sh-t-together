from strata.services.frontier import (
    add_edge,
    create_node,
    frontier,
    unique_slug,
    would_cycle,
)


def _track(conn, slug="t"):
    with conn:
        return conn.execute(
            "INSERT INTO tracks (slug, name) VALUES (?, ?)", (slug, slug)
        ).lastrowid


def _node(conn, track_id, slug, done=False):
    with conn:
        return conn.execute(
            "INSERT INTO nodes (track_id, slug, title, done_at) VALUES (?, ?, ?, ?)",
            (track_id, slug, slug, "2026-01-01 00:00:00" if done else None),
        ).lastrowid


def test_frontier_excludes_locked_and_done(conn):
    t = _track(conn)
    a = _node(conn, t, "a", done=True)
    b = _node(conn, t, "b")
    c = _node(conn, t, "c")
    with conn:
        add_edge(conn, a, b, "seed")  # satisfied: a is done
        add_edge(conn, b, c, "seed")  # locked: b is open
    names = [r["slug"] for r in frontier(conn, t)]
    assert names == ["b"]


def test_completion_unlocks_dependents(conn):
    t = _track(conn)
    a = _node(conn, t, "a")
    b = _node(conn, t, "b")
    with conn:
        add_edge(conn, a, b, "seed")
    assert [r["slug"] for r in frontier(conn, t)] == ["a"]
    with conn:
        conn.execute("UPDATE nodes SET done_at = datetime('now') WHERE id = ?", (a,))
    assert [r["slug"] for r in frontier(conn, t)] == ["b"]


def test_cycle_rejected(conn):
    t = _track(conn)
    a = _node(conn, t, "a")
    b = _node(conn, t, "b")
    c = _node(conn, t, "c")
    with conn:
        assert add_edge(conn, a, b, "user")
        assert add_edge(conn, b, c, "user")
    assert would_cycle(conn, c, a)  # transitive
    assert would_cycle(conn, b, a)  # direct
    assert would_cycle(conn, a, a)  # self
    with conn:
        assert not add_edge(conn, c, a, "user")
    assert not conn.execute(
        "SELECT 1 FROM node_edges WHERE prereq_id = ? AND node_id = ?", (c, a)
    ).fetchone()


def test_cross_track_edge_rejected(conn):
    t1, t2 = _track(conn, "t1"), _track(conn, "t2")
    a = _node(conn, t1, "a")
    b = _node(conn, t2, "b")
    with conn:
        assert not add_edge(conn, a, b, "user")


def test_slug_collision_suffixes(conn):
    t = _track(conn)
    with conn:
        first = create_node(conn, t, "Read a 10-K", "", "user", [])
        second = create_node(conn, t, "Read a 10-K", "", "user", [])
    slugs = {
        r["slug"]
        for r in conn.execute("SELECT slug FROM nodes WHERE id IN (?, ?)", (first, second))
    }
    assert slugs == {"read-a-10-k", "read-a-10-k-2"}
    assert unique_slug(conn, t, "Read a 10-K") == "read-a-10-k-3"

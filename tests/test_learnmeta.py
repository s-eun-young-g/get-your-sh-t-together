from datetime import date, timedelta

from strata.services.learnmeta import headliner, progress, streak


def _track_with_nodes(app_db, slug="hardware"):
    t = app_db.execute("SELECT id FROM tracks WHERE slug = ?", (slug,)).fetchone()["id"]
    nodes = app_db.execute(
        "SELECT id, slug FROM nodes WHERE track_id = ? ORDER BY position LIMIT 3", (t,)
    ).fetchall()
    return t, nodes


def test_headliner_priority(client, app_db):
    track_id, nodes = _track_with_nodes(app_db)
    label, node = headliner(app_db, track_id)
    assert label == "latest"

    client.post(f"/learn/nodes/{nodes[0]['id']}/done")
    label, node = headliner(app_db, track_id)
    assert label == "last learned" and node["id"] == nodes[0]["id"]

    client.post(f"/learn/nodes/{nodes[1]['id']}/focus")
    label, node = headliner(app_db, track_id)
    assert label == "learning now" and node["id"] == nodes[1]["id"]


def test_multiple_learning_now(client, app_db):
    track_id, nodes = _track_with_nodes(app_db)
    client.post(f"/learn/nodes/{nodes[0]['id']}/focus")
    client.post(f"/learn/nodes/{nodes[1]['id']}/focus")
    focused = app_db.execute(
        "SELECT id FROM nodes WHERE track_id = ? AND learning_now = 1", (track_id,)
    ).fetchall()
    assert {r["id"] for r in focused} == {nodes[0]["id"], nodes[1]["id"]}
    client.post(f"/learn/nodes/{nodes[1]['id']}/focus")
    assert app_db.execute(
        "SELECT COUNT(*) AS n FROM nodes WHERE learning_now = 1"
    ).fetchone()["n"] == 1


def test_streak_from_node_done_and_manual(client, app_db):
    assert streak(app_db) == 0
    _, nodes = _track_with_nodes(app_db)
    client.post(f"/learn/nodes/{nodes[0]['id']}/done")
    assert streak(app_db) == 1
    client.post("/learn/log-today")  # idempotent same day
    assert streak(app_db) == 1
    with app_db:
        app_db.execute(
            "INSERT INTO learning_log (day) VALUES (?)",
            ((date.today() - timedelta(days=1)).isoformat(),),
        )
    assert streak(app_db) == 2
    html = client.get("/learn").text
    assert "2 day streak" in html and "learned today" in html


def test_streak_survives_until_tomorrow(client, app_db):
    with app_db:
        app_db.execute(
            "INSERT INTO learning_log (day) VALUES (?)",
            ((date.today() - timedelta(days=1)).isoformat(),),
        )
    assert streak(app_db) == 1  # yesterday only: streak alive, not broken


def test_progress_and_bars_on_index(client, app_db):
    track_id, nodes = _track_with_nodes(app_db)
    client.post(f"/learn/nodes/{nodes[0]['id']}/done")
    p = progress(app_db, track_id)
    assert p["done"] == 1 and p["pct"] > 0
    html = client.get("/learn").text
    assert 'class="progress"' in html and 'summary class="reveal"' in html


def test_node_sources_and_notes(client, app_db):
    track_id, nodes = _track_with_nodes(app_db)
    nid = nodes[0]["id"]
    client.post(
        f"/learn/nodes/{nid}/resources",
        data={"title": "Chip War", "url": "https://example.com", "kind": "book"},
    )
    row = app_db.execute("SELECT * FROM resources").fetchone()
    assert row["node_id"] == nid and row["track_id"] == track_id
    html = client.get(f"/learn/tracks/{track_id}").text
    assert "Chip War" in html and "add a source" in html
    client.post(f"/learn/nodes/{nid}/note", data={"text": "asianometry video was great"})
    client.post(f"/learn/nodes/{nid}/note", data={"text": "x" * 120})
    html = client.get(f"/learn/tracks/{track_id}").text
    assert "asianometry video was great" in html
    assert ("x" * 90) + "..." in html and ("x" * 91) not in html
    assert app_db.execute("SELECT COUNT(*) AS n FROM node_notes").fetchone()["n"] == 2
    rid = row["id"]
    client.post(f"/learn/resources/{rid}/delete")
    assert "Chip War" not in client.get(f"/learn/tracks/{track_id}").text


def test_home_learn_tile_shows_focus(client, app_db):
    _, nodes = _track_with_nodes(app_db)
    client.post(f"/learn/nodes/{nodes[0]['id']}/focus")
    title = app_db.execute(
        "SELECT title FROM nodes WHERE id = ?", (nodes[0]["id"],)
    ).fetchone()["title"]
    assert f"learning now: {title}" in client.get("/").text


def test_manifesto_on_home(client):
    client.post(
        "/settings",
        data={"name": "", "manifesto": "Build the thing. Stay curious.", "mod_evenings": "1"},
    )
    home = client.get("/").text
    assert "Build the thing. Stay curious." in home


def test_home_is_the_board(client):
    home = client.get("/").text
    assert ">Today</h2>" in home and "Frog pen" in home
    assert ">Next</h2>" not in home
    assert 'href="/now/sort"' in home and ">clear<" in home  # inbox tile, empty state
    client.post("/capture", data={"title": "loose thought"})
    home = client.get("/").text
    assert "1 to sort" in home and "latest: loose thought" in home


def test_home_tiles_link_tabs(client):
    home = client.get("/").text
    for href in ("/work", "/life", "/model", "/learn", "/pause"):
        assert f'href="{href}"' in home


def test_track_notes_autosave(client, app_db):
    t, _ = _track_with_nodes(app_db)
    r = client.post(f"/learn/tracks/{t}/notes", data={"notes": "chip war ch 3 was great"})
    assert r.status_code == 204
    assert app_db.execute(
        "SELECT notes FROM tracks WHERE id = ?", (t,)
    ).fetchone()["notes"] == "chip war ch 3 was great"




def test_headliner_latest_label(client, app_db):
    t, _ = _track_with_nodes(app_db)
    label, _node = headliner(app_db, t)
    assert label == "latest"


def test_manifesto_composes_inline(client):
    home = client.get("/").text
    assert 'name="manifesto"' in home  # compose form right on the page
    client.post("/manifesto", data={"manifesto": "build the thing"})
    home = client.get("/").text
    assert "build the thing" in home and 'name="manifesto"' not in home

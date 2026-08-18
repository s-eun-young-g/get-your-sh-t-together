def _titles(conn, horizon):
    return [
        r["title"]
        for r in conn.execute(
            "SELECT title FROM tasks WHERE horizon = ? AND done_at IS NULL"
            " ORDER BY position, id",
            (horizon,),
        )
    ]


def test_capture_lands_in_inbox(client, app_db):
    client.post("/capture", data={"title": "call the dentist"})
    assert _titles(app_db, "inbox") == ["call the dentist"]


def test_capture_blank_is_ignored(client, app_db):
    client.post("/capture", data={"title": "   "})
    assert _titles(app_db, "inbox") == []


def test_create_and_move(client, app_db):
    client.post("/now/tasks", data={"title": "write memo", "horizon": "today"})
    task_id = app_db.execute("SELECT id FROM tasks").fetchone()["id"]
    client.post(f"/now/tasks/{task_id}/move", data={"horizon": "inbox"})
    assert _titles(app_db, "today") == []
    assert _titles(app_db, "inbox") == ["write memo"]


def test_done_keeps_row(client, app_db):
    client.post("/now/tasks", data={"title": "ship it", "horizon": "today"})
    task_id = app_db.execute("SELECT id FROM tasks").fetchone()["id"]
    client.post(f"/now/tasks/{task_id}/done")
    row = app_db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["done_at"] is not None
    client.post(f"/now/tasks/{task_id}/undone")
    row = app_db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["done_at"] is None


def test_today_digest_assembles_from_tabs(client, app_db):
    # pinned task
    client.post("/now/tasks", data={"title": "pinned thing", "horizon": "today"})
    # a work task becomes the workspace's next-up
    ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "urgent deck", "due_date": "tomorrow", "effort_minutes": "60", "dread": "3"},
    )
    home = client.get("/").text
    assert "pinned thing" in home and "urgent deck" in home
    assert "chip-hue-work" in home and "chip-hue-learn" in home  # learn headliner rides along
    assert "add to today" not in home


def test_sweep_demotes_only_stale(client, app_db):
    client.post("/now/tasks", data={"title": "fresh", "horizon": "today"})
    client.post("/now/tasks", data={"title": "stale", "horizon": "today"})
    with app_db:
        app_db.execute(
            "UPDATE tasks SET updated_at = datetime('now', '-5 days') WHERE title = 'stale'"
        )
    client.post("/now/sweep")
    assert _titles(app_db, "today") == ["fresh"]
    assert _titles(app_db, "inbox") == ["stale"]


def test_capture_shows_inbox_count(client):
    r = client.post("/capture", data={"title": "one thing"})
    assert "1 in inbox" in r.text
    assert "jotted" in r.text


def test_now_redirects_home(client):
    r = client.get("/now", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"


def test_sort_mode_deals_one_at_a_time(client, app_db):
    for title in ("first thought", "second thought"):
        client.post("/capture", data={"title": title})
    html = client.get("/now/sort").text
    assert "first thought" in html and "second thought" not in html
    first = app_db.execute("SELECT id FROM tasks WHERE title = 'first thought'").fetchone()["id"]
    r = client.post(f"/now/tasks/{first}/skip")
    assert "second thought" in r.text  # skipped to the back, next card dealt
    second = app_db.execute("SELECT id FROM tasks WHERE title = 'second thought'").fetchone()["id"]
    r = client.post(f"/now/tasks/{second}/move", data={"horizon": "today", "frame": "sort"})
    assert "first thought" in r.text
    ws = app_db.execute("SELECT id, name FROM workspaces WHERE kind = 'job'").fetchone()
    r = client.post(f"/now/tasks/{first}/sort_tag", data={"workspace_id": str(ws["id"])})
    assert "inbox zero" in r.text
    row = app_db.execute("SELECT * FROM tasks WHERE id = ?", (first,)).fetchone()
    assert row["workspace_id"] == ws["id"] and row["horizon"] == "inbox"

def _plan(client, app_db, name="Tonight", start=""):
    client.post("/life/plans", data={"name": name, "start_time": start})
    return app_db.execute(
        "SELECT id FROM evening_plans ORDER BY id DESC LIMIT 1"
    ).fetchone()["id"]


def test_plan_with_timeline(client, app_db):
    pid = _plan(client, app_db, start="18:00")
    client.post(f"/life/plans/{pid}/items", data={"title": "laundry", "minutes": "30"})
    client.post(f"/life/plans/{pid}/items", data={"title": "call mom", "minutes": "20"})
    client.post(f"/life/plans/{pid}/items", data={"title": "stretch", "minutes": "15"})
    html = client.get("/life").text
    assert "18:00" in html and "18:30" in html and "18:50" in html
    assert "1h 5m left" in html


def test_plan_without_start_has_total_only(client, app_db):
    pid = _plan(client, app_db)
    client.post(f"/life/plans/{pid}/items", data={"title": "dishes", "minutes": "25"})
    html = client.get("/life").text
    assert "0h 25m left" in html


def test_reorder_shifts_timeline(client, app_db):
    pid = _plan(client, app_db, start="19:00")
    client.post(f"/life/plans/{pid}/items", data={"title": "first", "minutes": "60"})
    client.post(f"/life/plans/{pid}/items", data={"title": "second", "minutes": "10"})
    second = app_db.execute(
        "SELECT id FROM evening_items WHERE title = 'second'"
    ).fetchone()["id"]
    r = client.post(f"/life/items/{second}/move", data={"direction": "up"})
    assert r.text.index("second") < r.text.index("first")


def test_done_items_leave_the_total(client, app_db):
    pid = _plan(client, app_db)
    client.post(f"/life/plans/{pid}/items", data={"title": "dishes", "minutes": "25"})
    client.post(f"/life/plans/{pid}/items", data={"title": "trash", "minutes": "5"})
    item = app_db.execute("SELECT id FROM evening_items WHERE title = 'dishes'").fetchone()["id"]
    html = client.post(f"/life/items/{item}/toggle").text
    assert "0h 5m left" in html


def test_archive_plan(client, app_db):
    pid = _plan(client, app_db, name="Old plan")
    client.post(f"/life/plans/{pid}/archive")
    assert "Old plan" not in client.get("/life").text

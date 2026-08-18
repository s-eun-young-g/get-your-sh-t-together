from strata.services import canvas
from strata.services.school import open_assignments


def _class(conn, name, canvas_course_id=None):
    with conn:
        return conn.execute(
            "INSERT INTO classes (name, canvas_course_id) VALUES (?, ?)",
            (name, canvas_course_id),
        ).lastrowid


def _assign(conn, class_id, title, due=None, burden="m", done=None, canvas_id=None):
    with conn:
        return conn.execute(
            "INSERT INTO assignments (class_id, title, due_date, burden, done_at, canvas_id)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (class_id, title, due, burden, done, canvas_id),
        ).lastrowid


def test_sorted_by_deadline_then_burden(conn):
    c = _class(conn, "6.031")
    _assign(conn, c, "small later", due="2030-01-05", burden="s")
    _assign(conn, c, "big same day", due="2030-01-05", burden="l")
    _assign(conn, c, "soonest", due="2030-01-02", burden="s")
    _assign(conn, c, "no deadline", due=None, burden="l")
    _assign(conn, c, "already done", due="2030-01-01", done="2026-01-01")
    titles = [a["title"] for a in open_assignments(conn)]
    assert titles == ["soonest", "big same day", "small later", "no deadline"]


def test_start_early_nudge_only_for_big_and_close(conn):
    from datetime import date, timedelta

    c = _class(conn, "6.031")
    soon = (date.today() + timedelta(days=3)).isoformat()
    far = (date.today() + timedelta(days=60)).isoformat()
    _assign(conn, c, "big soon", due=soon, burden="l")
    _assign(conn, c, "big far", due=far, burden="l")
    _assign(conn, c, "small soon", due=soon, burden="s")
    rows = {a["title"]: a for a in open_assignments(conn)}
    assert rows["big soon"]["start_early"]
    assert not rows["big far"]["start_early"]
    assert not rows["small soon"]["start_early"]


def _fake_fetch(base, path, token):
    assert token == "tok"
    if path.startswith("/api/v1/courses?"):
        return [
            {"id": 11, "name": "6.031 Software Construction"},
            {"id": 12, "name": "7.012 Biology"},
            {"id": 13},  # no name, skipped
        ]
    if "/courses/11/" in path:
        return [
            {"id": 501, "name": "PS1", "due_at": "2030-02-10T04:59:00Z", "points_possible": 10},
            {"id": 502, "name": "Project", "due_at": "2030-03-01T04:59:00Z", "points_possible": 100},
            {"id": 503, "name": "No due date", "due_at": None, "points_possible": None},
        ]
    return []


def test_canvas_sync_creates_and_updates(conn):
    result = canvas.sync(conn, "https://canvas.test", "tok", fetch=_fake_fetch)
    assert result == {"classes": 2, "new": 3, "updated": 0}
    rows = {r["title"]: r for r in conn.execute("SELECT * FROM assignments")}
    assert rows["PS1"]["burden"] == "s"
    assert rows["Project"]["burden"] == "l"
    assert rows["No due date"]["due_date"] is None

    # Resync: user's burden edit and done state survive; title/due follow Canvas.
    with conn:
        conn.execute("UPDATE assignments SET burden = 'm', done_at = '2026-01-01' WHERE canvas_id = 501")

    def edited_fetch(base, path, token):
        data = _fake_fetch(base, path, token)
        if "/courses/11/" in path:
            data[0]["name"] = "PS1 revised"
        return data

    result = canvas.sync(conn, "https://canvas.test", "tok", fetch=edited_fetch)
    assert result["new"] == 0 and result["updated"] == 3 and result["classes"] == 0
    row = conn.execute("SELECT * FROM assignments WHERE canvas_id = 501").fetchone()
    assert row["title"] == "PS1 revised"
    assert row["burden"] == "m"
    assert row["done_at"] == "2026-01-01"


def test_canvas_sync_unreachable_is_calm(conn):
    def boom(base, path, token):
        raise OSError("no network")

    result = canvas.sync(conn, "https://canvas.test", "tok", fetch=boom)
    assert "error" in result


def test_work_page_flow(client, app_db):
    school_ws = app_db.execute(
        "SELECT id FROM workspaces WHERE kind = 'school'"
    ).fetchone()["id"]
    r = client.post(f"/work/workspaces/{school_ws}/classes", data={"name": "6.031"})
    assert "6.031" in r.text
    class_id = app_db.execute("SELECT id FROM classes").fetchone()["id"]
    client.post(
        f"/work/classes/{class_id}/assignments",
        data={"title": "PS1", "due_date": "2030-01-02", "burden": "l"},
    )
    html = client.get("/work").text
    assert "PS1" in html and "big" in html
    aid = app_db.execute("SELECT id FROM assignments").fetchone()["id"]
    client.post(f"/work/assignments/{aid}/done")
    assert app_db.execute("SELECT done_at FROM assignments").fetchone()["done_at"]


def test_workspace_tasks_and_untagging(client, app_db):
    job_ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]
    client.post(
        f"/work/workspaces/{job_ws}/tasks",
        data={"title": "prep standup", "due_date": "2030-01-05", "effort_minutes": "30", "dread": "1"},
    )
    row = app_db.execute("SELECT * FROM tasks").fetchone()
    assert row["workspace_id"] == job_ws
    assert "prep standup" in client.get("/work").text
    client.post(f"/now/tasks/{row['id']}/workspace", data={"workspace_id": "0", "frame": "work"})
    assert "prep standup" not in client.get("/work").text


def test_natural_language_deadlines():
    from datetime import date, timedelta

    from strata.services.dates import parse_when

    today = date(2026, 8, 18)  # a tuesday
    assert parse_when("2026-09-01", today) == "2026-09-01"
    assert parse_when("9/1", today) == "2026-09-01"
    assert parse_when("sep 1", today) == "2026-09-01"
    assert parse_when("September 1, 2027", today) == "2027-09-01"
    assert parse_when("1 sep", today) == "2026-09-01"
    assert parse_when("jan 5", today) == "2027-01-05"  # passed this year -> next
    assert parse_when("tomorrow", today) == "2026-08-19"
    assert parse_when("in 2w", today) == "2026-09-01"
    assert parse_when("friday", today) == "2026-08-21"
    assert parse_when("whenever vibes", today) is None

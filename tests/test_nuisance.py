from strata import db
from strata.routes.now import next_nuisance, nuisance_pen, open_tasks


def _mk(conn, title, **kw):
    cols = {"title": title, "horizon": "next", "nuisance": 1} | kw
    keys = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    with conn:
        return conn.execute(
            f"INSERT INTO tasks ({keys}) VALUES ({marks})", tuple(cols.values())
        ).lastrowid


def test_nuisances_hidden_from_horizon_lists(conn):
    _mk(conn, "call insurance")
    assert open_tasks(conn, "next") == []
    assert [r["title"] for r in nuisance_pen(conn)] == ["call insurance"]


def test_daily_slot_picks_pinned_else_oldest(conn):
    _mk(conn, "older", created_at="2026-01-01 00:00:00")
    newer = _mk(conn, "newer", created_at="2026-06-01 00:00:00")
    assert next_nuisance(conn)["title"] == "older"
    with conn:
        conn.execute("UPDATE tasks SET pinned = 1 WHERE id = ?", (newer,))
    assert next_nuisance(conn)["title"] == "newer"


def test_snooze_hides_until_date(conn):
    tid = _mk(conn, "renew passport")
    with conn:
        conn.execute(
            "UPDATE tasks SET snoozed_until = date('now', '+2 days') WHERE id = ?", (tid,)
        )
    assert next_nuisance(conn) is None
    with conn:
        conn.execute(
            "UPDATE tasks SET snoozed_until = date('now', '-1 day') WHERE id = ?", (tid,)
        )
    assert next_nuisance(conn)["title"] == "renew passport"


def test_blitz_flow(client, app_db):
    client.post("/now/tasks", data={"title": "email landlord", "horizon": "inbox", "nuisance": "1"})
    html = client.get("/now/blitz").text
    assert "email landlord" in html
    tid = app_db.execute("SELECT id FROM tasks").fetchone()["id"]
    r = client.post(f"/now/tasks/{tid}/done", data={"frame": "blitz"})
    assert "Pen is clear" in r.text


def test_snooze_route_sets_date(client, app_db):
    client.post("/now/tasks", data={"title": "book flights", "horizon": "inbox", "nuisance": "1"})
    tid = app_db.execute("SELECT id FROM tasks").fetchone()["id"]
    client.post(f"/now/tasks/{tid}/snooze", data={"days": "3"})
    row = app_db.execute("SELECT snoozed_until FROM tasks WHERE id = ?", (tid,)).fetchone()
    assert row["snoozed_until"] is not None

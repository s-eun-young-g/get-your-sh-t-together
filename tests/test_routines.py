from datetime import date, timedelta

from strata.services.routines import PRESETS, add_preset, due, list_active, unused_presets


def _mk(conn, name, every=7, last=None):
    with conn:
        return conn.execute(
            "INSERT INTO routines (name, every_days, last_done) VALUES (?, ?, ?)",
            (name, every, last),
        ).lastrowid


def test_never_done_is_due_today(conn):
    _mk(conn, "laundry")
    rows = list_active(conn)
    assert rows[0]["due"] and rows[0]["due_label"] == "due"


def test_done_recently_is_not_due(conn):
    _mk(conn, "laundry", every=7, last=date.today().isoformat())
    rows = list_active(conn)
    assert not rows[0]["due"]
    assert rows[0]["days"] == 7


def test_overdue_sorts_first(conn):
    _mk(conn, "fresh", every=7, last=date.today().isoformat())
    _mk(conn, "overdue", every=7, last=(date.today() - timedelta(days=30)).isoformat())
    assert [r["name"] for r in list_active(conn)] == ["overdue", "fresh"]
    assert [r["name"] for r in due(conn)] == ["overdue"]


def test_mark_done_resets_clock(client, app_db):
    rid = _mk(app_db, "trash", every=7, last=(date.today() - timedelta(days=9)).isoformat())
    client.post(f"/life/routines/{rid}/done")
    row = app_db.execute("SELECT last_done FROM routines WHERE id = ?", (rid,)).fetchone()
    assert row["last_done"] == date.today().isoformat()


def test_preset_add_and_dedupe(client, app_db):
    client.post("/life/routines/preset", data={"key": "laundry"})
    client.post("/life/routines/preset", data={"key": "laundry"})
    assert app_db.execute("SELECT COUNT(*) AS n FROM routines").fetchone()["n"] == 1
    assert "laundry" not in {p[0] for p in unused_presets(app_db)}
    assert len(unused_presets(app_db)) == len(PRESETS) - 1


def test_pause_reoffers_preset(client, app_db):
    client.post("/life/routines/preset", data={"key": "dentist"})
    rid = app_db.execute("SELECT id FROM routines").fetchone()["id"]
    client.post(f"/life/routines/{rid}/pause")
    assert "dentist" in {p[0] for p in unused_presets(app_db)}
    # Re-adding reactivates the same row instead of duplicating.
    add_preset(app_db, "dentist")
    assert app_db.execute("SELECT COUNT(*) AS n FROM routines").fetchone()["n"] == 1
    assert app_db.execute("SELECT active FROM routines").fetchone()["active"] == 1


def test_due_routines_on_home_tile(client, app_db):
    _mk(app_db, "water plants", every=7, last=(date.today() - timedelta(days=10)).isoformat())
    home = client.get("/").text
    assert "water plants" in home and "1 due" in home


def test_home_hides_routines_when_toggled_off(client, app_db):
    _mk(app_db, "water plants")
    client.post("/settings", data={"name": "", "mod_evenings": "1"})
    assert "water plants" not in client.get("/").text

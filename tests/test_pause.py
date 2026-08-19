from strata.services.impulses import INDEFINITE, SLIDER_STOPS, stats, waiting


def test_slider_stops_shape():
    minutes = [m for m, _ in SLIDER_STOPS]
    labels = [label for _, label in SLIDER_STOPS]
    assert minutes[0] == 30 and labels[0] == "30 minutes"
    assert 23 * 60 in minutes and 1440 in minutes and 10080 in minutes
    assert labels[-1] == "indefinitely" and minutes[-1] == INDEFINITE
    assert minutes == sorted(minutes)


def test_indefinite_never_ready(client, app_db):
    _park(client, "quit my job", str(INDEFINITE))
    with app_db:
        app_db.execute("UPDATE impulses SET created_at = datetime('now', '-90 days')")
    row = waiting(app_db)[0]
    assert not row["ready"] and row["wait_label"] == "parked indefinitely"
    iid = app_db.execute("SELECT id FROM impulses").fetchone()["id"]
    client.post(f"/pause/impulses/{iid}/release")
    assert app_db.execute("SELECT status FROM impulses").fetchone()["status"] == "released"
    html = client.get("/pause").text
    assert "show let go" in html


def _park(client, title="that jacket", wait="1440", category="shopping"):
    client.post(
        "/pause/impulses",
        data={"title": title, "category": category, "wait_minutes": wait},
    )


def test_parked_impulse_waits(client, app_db):
    _park(client)
    row = waiting(app_db)[0]
    assert not row["ready"]
    assert "opens in" in row["wait_label"]
    html = client.get("/pause").text
    assert "that jacket" in html
    assert "doing it" not in html  # act button hidden during cooldown


def test_didnt_wait_is_always_available(client, app_db):
    _park(client)
    iid = app_db.execute("SELECT id FROM impulses").fetchone()["id"]
    html = client.get("/pause").text
    assert "let it go" in html and "didn't wait" in html
    client.post(f"/pause/impulses/{iid}/act")
    row = app_db.execute("SELECT * FROM impulses").fetchone()
    assert row["status"] == "acted" and row["acted_at"]


def test_release_allowed_anytime(client, app_db):
    _park(client)
    iid = app_db.execute("SELECT id FROM impulses").fetchone()["id"]
    client.post(f"/pause/impulses/{iid}/release")
    assert app_db.execute("SELECT status FROM impulses").fetchone()["status"] == "released"
    assert stats(app_db)["let_go"] == 1


def _expire(app_db, iid):
    with app_db:
        app_db.execute(
            "UPDATE impulses SET created_at = datetime('now', '-2 days') WHERE id = ?",
            (iid,),
        )


def test_ready_act_and_regret_ledger(client, app_db):
    _park(client, "risky text", category="social")
    iid = app_db.execute("SELECT id FROM impulses").fetchone()["id"]
    _expire(app_db, iid)

    html = client.get("/pause").text
    assert "still want it?" in html

    client.post(f"/pause/impulses/{iid}/act")
    row = app_db.execute("SELECT * FROM impulses").fetchone()
    assert row["status"] == "acted" and row["acted_at"]
    assert "how did it go?" in client.get("/pause").text

    client.post(f"/pause/impulses/{iid}/regret", data={"regret": "1"})
    s = stats(app_db)
    assert s == {"let_go": 0, "acted": 1, "regretted": 1, "no_regret": 0}
    html = client.get("/pause").text
    assert "waiting killed 0 impulses" in html or "you acted on 1" in html


def test_worth_it_logging(client, app_db):
    _park(client, "ice cream", "30", "food")
    iid = app_db.execute("SELECT id FROM impulses").fetchone()["id"]
    _expire(app_db, iid)
    client.post(f"/pause/impulses/{iid}/act")
    client.post(f"/pause/impulses/{iid}/regret", data={"regret": "0"})
    assert stats(app_db)["no_regret"] == 1


def test_pause_toggle_hides_nav(client):
    assert 'href="/pause"' in client.get("/now").text
    client.post("/settings", data={"name": "", "mod_evenings": "1"})
    assert 'href="/pause"' not in client.get("/now").text

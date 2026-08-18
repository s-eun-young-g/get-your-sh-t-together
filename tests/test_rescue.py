from strata.services.rescue import PRESETS, stats, suggestion, unused_presets


def _add(client, title):
    client.post("/rescue/items", data={"title": title})


def test_rescue_hidden_by_default(client):
    # The feature is parked until it is better formulated; routes stay live.
    assert "I'm so bored I could die" not in client.get("/").text
    assert client.get("/rescue").status_code == 200


def test_one_suggestion_at_a_time(client, app_db):
    _add(client, "shower")
    _add(client, "walk")
    html = client.get("/rescue").text
    assert html.count("Try this") == 1


def test_try_then_outcome_updates_record(client, app_db):
    _add(client, "one song loud")
    iid = app_db.execute("SELECT id FROM rescue_items").fetchone()["id"]
    client.post(f"/rescue/items/{iid}/try")
    html = client.get("/rescue").text
    assert "did it help" in html
    client.post(f"/rescue/items/{iid}/outcome", data={"helped": "1"})
    row = app_db.execute("SELECT * FROM rescue_items").fetchone()
    assert row["tries"] == 1 and row["helped"] == 1 and row["pending_at"] is None
    assert "helped 1 of 1" in client.get("/rescue").text
    assert "helped 1 of 1 time" in client.get("/rescue").text


def test_outcome_without_try_is_ignored(client, app_db):
    _add(client, "stretch")
    iid = app_db.execute("SELECT id FROM rescue_items").fetchone()["id"]
    client.post(f"/rescue/items/{iid}/outcome", data={"helped": "1"})
    row = app_db.execute("SELECT tries FROM rescue_items").fetchone()
    assert row["tries"] == 0


def test_best_record_suggested_first_and_skip_rotates(client, app_db):
    _add(client, "reliable")
    _add(client, "unproven")
    rid = app_db.execute("SELECT id FROM rescue_items WHERE title = 'reliable'").fetchone()["id"]
    client.post(f"/rescue/items/{rid}/try")
    client.post(f"/rescue/items/{rid}/outcome", data={"helped": "1"})
    assert suggestion(app_db)["title"] == "reliable"
    client.post(f"/rescue/items/{rid}/skip")
    assert suggestion(app_db)["title"] == "unproven"


def test_presets_dedupe_and_retire(client, app_db):
    client.post("/rescue/preset", data={"key": "shower"})
    client.post("/rescue/preset", data={"key": "shower"})
    assert app_db.execute("SELECT COUNT(*) AS n FROM rescue_items").fetchone()["n"] == 1
    assert len(unused_presets(app_db)) == len(PRESETS) - 1
    iid = app_db.execute("SELECT id FROM rescue_items").fetchone()["id"]
    client.post(f"/rescue/items/{iid}/retire")
    assert suggestion(app_db) is None
    assert len(unused_presets(app_db)) == len(PRESETS)


def test_stats_counts_forced_wins(client, app_db):
    _add(client, "walk")
    iid = app_db.execute("SELECT id FROM rescue_items").fetchone()["id"]
    for helped in ("1", "0", "1"):
        client.post(f"/rescue/items/{iid}/try")
        client.post(f"/rescue/items/{iid}/outcome", data={"helped": helped})
    assert stats(app_db) == {"tries": 3, "helped": 2}
    assert "helped 2 of 3 times" in client.get("/rescue").text

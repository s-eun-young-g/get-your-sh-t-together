def _board(client, app_db, buckets=("take", "donate")):
    client.post("/model/boards", data={"name": "The move"})
    board = app_db.execute("SELECT id FROM boards").fetchone()["id"]
    ids = []
    for name in buckets:
        client.post(f"/model/boards/{board}/buckets", data={"name": name})
        ids.append(
            app_db.execute(
                "SELECT id FROM buckets WHERE name = ?", (name,)
            ).fetchone()["id"]
        )
    return board, ids


def test_boards_start_empty(client, app_db):
    client.post("/model/boards", data={"name": "The move"})
    assert app_db.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"] == 0


def test_sub_buckets_nest(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(
        f"/model/boards/{board}/buckets", data={"name": "sentimental", "parent_id": str(take)}
    )
    sub = app_db.execute("SELECT * FROM buckets WHERE name = 'sentimental'").fetchone()
    assert sub["parent_id"] == take
    html = client.get(f"/model/boards/{board}").text
    assert 'value="sentimental"' in html
    client.post(f"/model/buckets/{take}/cards", data={"title": "old letters"})
    assert "to take / sentimental" in client.get(f"/model/boards/{board}").text


def test_card_moves_into_sub_bucket(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(f"/model/boards/{board}/buckets", data={"name": "books", "parent_id": str(take)})
    sub = app_db.execute("SELECT id FROM buckets WHERE name = 'books'").fetchone()["id"]
    client.post(f"/model/buckets/{take}/cards", data={"title": "field guides"})
    card = app_db.execute("SELECT id FROM cards").fetchone()["id"]
    client.post(f"/model/cards/{card}/move", data={"bucket_id": str(sub)})
    assert app_db.execute("SELECT bucket_id FROM cards").fetchone()["bucket_id"] == sub


def test_delete_bucket_with_children_blocked(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(f"/model/boards/{board}/buckets", data={"name": "books", "parent_id": str(take)})
    r = client.post(f"/model/buckets/{take}/delete")
    assert "sub-buckets" in r.text
    assert app_db.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"] == 3


def test_delete_sub_bucket_moves_cards_to_parent(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(f"/model/boards/{board}/buckets", data={"name": "books", "parent_id": str(take)})
    sub = app_db.execute("SELECT id FROM buckets WHERE name = 'books'").fetchone()["id"]
    client.post(f"/model/buckets/{sub}/cards", data={"title": "field guides"})
    client.post(f"/model/buckets/{sub}/delete")
    assert app_db.execute("SELECT bucket_id FROM cards").fetchone()["bucket_id"] == take


def test_delete_last_bucket_with_cards_blocked(client, app_db):
    board, ids = _board(client, app_db, buckets=("only",))
    client.post(f"/model/buckets/{ids[0]}/cards", data={"title": "orphan"})
    r = client.post(f"/model/buckets/{ids[0]}/delete")
    assert "somewhere to go" in r.text
    assert app_db.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"] == 1


def test_delete_empty_bucket_always_allowed(client, app_db):
    board, ids = _board(client, app_db, buckets=("only",))
    client.post(f"/model/buckets/{ids[0]}/delete")
    assert app_db.execute("SELECT COUNT(*) AS n FROM buckets").fetchone()["n"] == 0


def test_notes_autosave(client, app_db):
    client.post("/model/boards", data={"name": "The move"})
    board = app_db.execute("SELECT id FROM boards").fetchone()["id"]
    r = client.post(f"/model/boards/{board}/notes", data={"notes": "keep the plants"})
    assert r.status_code == 204
    assert app_db.execute("SELECT notes FROM boards").fetchone()["notes"] == "keep the plants"


def test_board_delete_from_index(client, app_db):
    client.post("/model/boards", data={"name": "scratch"})
    board = app_db.execute("SELECT id FROM boards").fetchone()["id"]
    r = client.post(f"/model/boards/{board}/delete")
    assert r.headers.get("hx-redirect") == "/model"
    assert app_db.execute("SELECT COUNT(*) AS n FROM boards").fetchone()["n"] == 0
    html = client.get("/model").text
    assert "archive" in html or "boards" in html

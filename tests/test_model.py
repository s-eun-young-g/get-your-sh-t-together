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
    assert f'class="cat-title" href="/model/categories/{sub["id"]}">sentimental</a>' in html
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
    assert "subcategories" in r.text
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


def test_category_page_shows_name_and_crumb(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(
        f"/model/boards/{board}/buckets", data={"name": "sentimental", "parent_id": str(take)}
    )
    sub = app_db.execute("SELECT id FROM buckets WHERE name = 'sentimental'").fetchone()["id"]
    r = client.get(f"/model/categories/{sub}")
    assert r.status_code == 200
    assert "sentimental" in r.text
    assert "&larr; The move" in r.text
    assert f'href="/model/categories/{take}">take</a>' in r.text


def test_card_add_with_view_bucket_returns_category_partial(client, app_db):
    board, (take, _) = _board(client, app_db)
    r = client.post(
        f"/model/buckets/{take}/cards",
        data={"title": "old letters", "view_bucket": str(take)},
    )
    assert "&larr;" in r.text
    assert 'class="columns' not in r.text
    assert "old letters" in r.text


def test_delete_viewed_category_redirects_to_parent(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(f"/model/boards/{board}/buckets", data={"name": "books", "parent_id": str(take)})
    sub = app_db.execute("SELECT id FROM buckets WHERE name = 'books'").fetchone()["id"]
    r = client.post(f"/model/buckets/{sub}/delete", data={"view_bucket": str(sub)})
    assert r.headers.get("hx-redirect") == f"/model/categories/{take}"
    r = client.post(f"/model/buckets/{take}/delete", data={"view_bucket": str(take)})
    assert r.headers.get("hx-redirect") == f"/model/boards/{board}"


def test_deep_nesting_collapses_on_board(client, app_db):
    board, ids = _board(client, app_db, buckets=("keep",))
    client.post(
        f"/model/boards/{board}/buckets", data={"name": "midlayer", "parent_id": str(ids[0])}
    )
    mid = app_db.execute("SELECT id FROM buckets WHERE name = 'midlayer'").fetchone()["id"]
    client.post(f"/model/boards/{board}/buckets", data={"name": "deepcat", "parent_id": str(mid)})
    html = client.get(f"/model/boards/{board}").text
    assert "deepcat" not in html
    assert 'class="quiet-link more"' in html
    assert "deepcat" in client.get(f"/model/categories/{mid}").text


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


def test_card_link_hyperlinks_the_title(client, app_db):
    board, (take, _) = _board(client, app_db)
    client.post(f"/model/buckets/{take}/cards", data={"title": "insurance quotes"})
    card = app_db.execute("SELECT id FROM cards").fetchone()["id"]
    client.post(f"/model/cards/{card}/link", data={"url": "example.com/quotes"})
    row = app_db.execute("SELECT url FROM cards").fetchone()
    assert row["url"] == "https://example.com/quotes"  # scheme added for bare domains
    html = client.get(f"/model/boards/{board}").text
    assert 'href="https://example.com/quotes"' in html
    assert ">insurance quotes</a>" in html
    client.post(f"/model/cards/{card}/link", data={"url": ""})
    html = client.get(f"/model/boards/{board}").text
    assert ">insurance quotes</span>" in html  # back to plain text

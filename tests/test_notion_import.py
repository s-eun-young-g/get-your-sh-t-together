import io
import zipfile

from strata.services.notion_import import parse_export

HEX = "3f2b8c9d4e5f6a7b8c9d0e1f2a3b4c5d"


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _export() -> bytes:
    md = b"# Moving checklist\n\nCall the movers.\nCancel the internet.\n"
    csv_narrow = (
        "﻿Name,Status\nfix login,doing\n".encode()
    )
    csv_all = (
        "﻿Name,Status,Owner\n"
        "fix login,doing,sofia\n"
        "write spec,done,sofia\n"
        "ship beta,doing,ana\n"
    ).encode()
    return _zip({
        f"Export/Moving checklist {HEX}.md": md,
        f"Export/Sprint {HEX}.csv": csv_narrow,
        f"Export/Sprint {HEX}_all.csv": csv_all,
    })


def test_parse_export_pages_and_databases():
    items = parse_export(_export())
    kinds = {i["kind"] for i in items}
    assert kinds == {"page", "database"}
    page = next(i for i in items if i["kind"] == "page")
    assert page["title"] == "Moving checklist"
    assert "Call the movers." in page["digest"]
    dbs = [i for i in items if i["kind"] == "database"]
    assert len(dbs) == 1  # the narrow twin of the _all file is skipped
    assert dbs[0]["title"] == "Sprint"
    assert "3 rows" in dbs[0]["digest"]


def test_parse_export_recurses_into_part_zips():
    inner = _export()
    items = parse_export(_zip({"Part-1.zip": inner}))
    assert {i["title"] for i in items} == {"Moving checklist", "Sprint"}


def test_parse_export_rejects_junk():
    assert parse_export(b"not a zip at all") == []
    assert parse_export(_zip({"photo.png": b"\x89PNG"})) == []


def _upload(client):
    return client.post(
        "/import/notion/upload",
        files={"file": ("export.zip", _export(), "application/zip")},
        follow_redirects=True,
    )


def test_upload_lists_candidates(client):
    r = _upload(client)
    assert "found 1 pages and 1 databases" in r.text
    assert "Moving checklist" in r.text and "Sprint" in r.text
    assert "split categories by" in r.text
    assert 'value="Status" checked' in r.text  # suggested grouping column


def test_page_to_inbox(client, app_db):
    _upload(client)
    pid = app_db.execute(
        "SELECT id FROM imported_pages WHERE kind = 'page'"
    ).fetchone()["id"]
    client.post("/import/notion/act", data={"action": "inbox", "page_ids": str(pid)})
    task = app_db.execute("SELECT * FROM tasks").fetchone()
    assert task["title"] == "Moving checklist" and task["source"] == "notion"
    assert app_db.execute(
        "SELECT status FROM imported_pages WHERE id = ?", (pid,)
    ).fetchone()["status"] == "used"


def test_database_rows_to_inbox(client, app_db):
    _upload(client)
    did = app_db.execute(
        "SELECT id FROM imported_pages WHERE kind = 'database'"
    ).fetchone()["id"]
    client.post("/import/notion/act", data={"action": "inbox", "page_ids": str(did)})
    titles = {t["title"] for t in app_db.execute("SELECT title FROM tasks")}
    assert titles == {"fix login", "write spec", "ship beta"}


def test_database_to_board_grouped(client, app_db):
    _upload(client)
    did = app_db.execute(
        "SELECT id FROM imported_pages WHERE kind = 'database'"
    ).fetchone()["id"]
    r = client.post(
        f"/import/notion/{did}/board",
        data={"group_col": "Status"},
        follow_redirects=False,
    )
    board = app_db.execute("SELECT * FROM boards").fetchone()
    assert board["name"] == "Sprint"
    assert r.headers["location"] == f"/model/boards/{board['id']}"
    buckets = {
        b["name"]: b["id"] for b in app_db.execute("SELECT * FROM buckets")
    }
    assert set(buckets) == {"doing", "done"}
    doing = [
        c["title"] for c in app_db.execute(
            "SELECT title FROM cards WHERE bucket_id = ? ORDER BY position",
            (buckets["doing"],),
        )
    ]
    assert doing == ["fix login", "ship beta"]


def test_dismiss(client, app_db):
    _upload(client)
    pid = app_db.execute(
        "SELECT id FROM imported_pages WHERE kind = 'page'"
    ).fetchone()["id"]
    client.post("/import/notion/act", data={"action": "dismiss", "page_ids": str(pid)})
    assert "Moving checklist" not in client.get("/import/notion").text
    assert app_db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0

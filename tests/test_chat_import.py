import io
import json
import zipfile

from strata.services import suggest
from strata.services.chat_import import parse_export
from strata.services.suggest import _parse_actions

SAMPLE = [
    {
        "title": "How do GPUs work",
        "create_time": 1750000000.0,
        "mapping": {
            "a": {"message": {"author": {"role": "system"}, "content": {"parts": ["sys"]}}},
            "b": {
                "message": {
                    "author": {"role": "user"},
                    "create_time": 1750000001.0,
                    "content": {"content_type": "text", "parts": ["explain why GPUs beat CPUs at matrix math"]},
                }
            },
        },
    },
    {"title": "Dinner ideas", "create_time": 1760000000.0, "mapping": {}},
    {"weird": True},
]


def test_parse_json_export():
    rows = parse_export(json.dumps(SAMPLE).encode())
    assert [r["title"] for r in rows] == ["Dinner ideas", "How do GPUs work"]
    gpu = rows[1]
    assert gpu["digest"].startswith("explain why GPUs")
    assert gpu["created"] is not None


def test_parse_zip_export():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", json.dumps(SAMPLE))
        zf.writestr("user.json", "{}")
    rows = parse_export(buf.getvalue())
    assert len(rows) == 2  # the junk entry is skipped


def test_parse_garbage_is_calm():
    assert parse_export(b"not json") == []
    assert parse_export(b'{"not": "a list"}') == []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("other.txt", "hi")
    assert parse_export(buf.getvalue()) == []


def test_parse_actions_validation():
    text = json.dumps([
        {"track_slug": "hardware", "kind": "done", "node_slug": "gpus"},
        {"track_slug": "ai", "kind": "new", "title": "KV cache", "summary": "s", "prereq_slugs": ["inference"]},
        {"kind": "new", "title": "no track"},
        {"track_slug": "ai", "kind": "done"},
    ])
    actions = _parse_actions(text)
    assert len(actions) == 2
    assert actions[0]["kind"] == "done" and actions[1]["title"] == "KV cache"


def _upload(client, payload=SAMPLE):
    return client.post(
        "/learn/import/upload",
        files={"file": ("conversations.json", json.dumps(payload).encode(), "application/json")},
        follow_redirects=False,
    )


def test_upload_and_filter(client, app_db):
    r = _upload(client)
    assert r.status_code == 303
    assert app_db.execute("SELECT COUNT(*) AS n FROM imported_chats").fetchone()["n"] == 2
    html = client.get("/learn/import?q=GPU").text
    assert "How do GPUs work" in html and "Dinner ideas" not in html
    # Re-upload replaces pending rows instead of duplicating.
    _upload(client)
    assert app_db.execute("SELECT COUNT(*) AS n FROM imported_chats").fetchone()["n"] == 2


def test_add_selected_as_items(client, app_db):
    _upload(client)
    cid = app_db.execute(
        "SELECT id FROM imported_chats WHERE title = 'How do GPUs work'"
    ).fetchone()["id"]
    track = app_db.execute("SELECT id, name FROM tracks WHERE slug = 'hardware'").fetchone()
    client.post(
        "/learn/import/act",
        data={"action": "add", "chat_ids": str(cid), "track_id": str(track["id"])},
    )
    node = app_db.execute(
        "SELECT * FROM nodes WHERE title = 'How do GPUs work'"
    ).fetchone()
    assert node and node["origin"] == "user" and node["track_id"] == track["id"]
    assert app_db.execute(
        "SELECT status FROM imported_chats WHERE id = ?", (cid,)
    ).fetchone()["status"] == "used"


def test_dismiss_selected(client, app_db):
    _upload(client)
    cid = app_db.execute(
        "SELECT id FROM imported_chats WHERE title = 'Dinner ideas'"
    ).fetchone()["id"]
    client.post("/learn/import/act", data={"action": "dismiss", "chat_ids": str(cid)})
    assert app_db.execute(
        "SELECT status FROM imported_chats WHERE id = ?", (cid,)
    ).fetchone()["status"] == "dismissed"
    assert "Dinner ideas" not in client.get("/learn/import").text


def test_map_requires_key(client, app_db):
    _upload(client)
    cid = app_db.execute("SELECT id FROM imported_chats LIMIT 1").fetchone()["id"]
    r = client.post(
        "/learn/import/act",
        data={"action": "map", "chat_ids": str(cid)},
        follow_redirects=False,
    )
    assert "anthropic_api_key" in r.headers["location"].replace("+", " ").replace("%20", " ")
    assert app_db.execute(
        "SELECT status FROM imported_chats WHERE id = ?", (cid,)
    ).fetchone()["status"] == "new"


def test_map_flow_and_done_accept(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from strata import db
    from strata.app import create_app
    from tests.conftest import make_settings

    monkeypatch.setattr(
        suggest,
        "map_chats",
        lambda key, tracks, chats: [
            {"kind": "done", "track_slug": "hardware", "node_slug": "gpus"},
            {"kind": "new", "track_slug": "ai", "title": "KV cache", "summary": "s", "prereq_slugs": []},
            {"kind": "done", "track_slug": "hardware", "node_slug": "not-a-node"},
        ],
    )
    app = create_app(make_settings(tmp_path, api_key="k"))
    with TestClient(app) as client:
        conn = db.connect(make_settings(tmp_path).db_path)
        from strata.app import SEEDS_DIR
        from strata.services.seed_sync import sync_all

        sync_all(conn, SEEDS_DIR / "learn")
        _upload(client)
        cid = conn.execute("SELECT id FROM imported_chats LIMIT 1").fetchone()["id"]
        client.post("/learn/import/act", data={"action": "map", "chat_ids": str(cid)})

        pending = conn.execute("SELECT * FROM suggestions WHERE status = 'pending'").fetchall()
        assert len(pending) == 2  # the unknown node_slug was skipped
        assert conn.execute(
            "SELECT status FROM imported_chats WHERE id = ?", (cid,)
        ).fetchone()["status"] == "used"

        done_s = next(
            s for s in pending if json.loads(s["payload"]).get("kind") == "done"
        )
        client.post(f"/learn/suggestions/{done_s['id']}/accept")
        node = conn.execute("SELECT done_at FROM nodes WHERE slug = 'gpus'").fetchone()
        assert node["done_at"] is not None

        new_s = next(
            s for s in pending if json.loads(s["payload"]).get("kind") == "new"
        )
        client.post(f"/learn/suggestions/{new_s['id']}/accept")
        assert conn.execute(
            "SELECT 1 FROM nodes WHERE title = 'KV cache' AND origin = 'ai'"
        ).fetchone()
        conn.close()


CLAUDE_SAMPLE = [
    {
        "name": "How transformers work",
        "created_at": "2026-05-01T12:00:00Z",
        "chat_messages": [
            {"sender": "assistant", "text": "hello"},
            {"sender": "human", "text": "explain attention like I know linear algebra"},
        ],
    },
    {"name": "Trip ideas", "created_at": "2026-06-01T09:00:00Z", "chat_messages": []},
]


def test_parse_claude_export():
    rows = parse_export(json.dumps(CLAUDE_SAMPLE).encode())
    assert [r["title"] for r in rows] == ["Trip ideas", "How transformers work"]
    assert rows[1]["digest"].startswith("explain attention")
    assert rows[1]["created"] == "2026-05-01"


def test_parse_mixed_export():
    rows = parse_export(json.dumps(SAMPLE + CLAUDE_SAMPLE).encode())
    assert len(rows) == 4

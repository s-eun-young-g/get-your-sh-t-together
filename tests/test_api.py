from fastapi.testclient import TestClient

from strata.app import create_app
from strata.config import Settings
from tests.conftest import make_settings


def _client_with_token(tmp_path, token="sekrit", password=""):
    settings = Settings(
        data_dir=tmp_path,
        password=password,
        port=8020,
        anthropic_api_key="",
        capture_token=token,
        secret="test-secret",
    )
    return TestClient(create_app(settings)), settings


def test_capture_disabled_without_token(client):
    r = client.post("/api/capture", json={"title": "x"})
    assert r.status_code == 503


def test_capture_rejects_bad_token(tmp_path):
    client, _ = _client_with_token(tmp_path)
    r = client.post(
        "/api/capture", json={"title": "x"}, headers={"Authorization": "Bearer wrong"}
    )
    assert r.status_code == 401
    r = client.post("/api/capture", json={"title": "x"})
    assert r.status_code == 401


def test_capture_inserts_with_source(tmp_path):
    client, settings = _client_with_token(tmp_path)
    r = client.post(
        "/api/capture",
        json={"title": "follow up with vendor", "source": "slack", "context": "job", "nuisance": True},
        headers={"Authorization": "Bearer sekrit"},
    )
    assert r.status_code == 200 and r.json()["ok"]

    from strata import db

    conn = db.connect(settings.db_path)
    row = conn.execute("SELECT * FROM tasks").fetchone()
    job_ws = conn.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]
    assert row["title"] == "follow up with vendor"
    assert row["horizon"] == "inbox"
    assert row["source"] == "slack"
    assert row["workspace_id"] == job_ws
    assert row["nuisance"] == 1

    # A workspace can also be named directly; unknown names are ignored.
    client.post(
        "/api/capture",
        json={"title": "quiz prep", "workspace": "school"},
        headers={"Authorization": "Bearer sekrit"},
    )
    school_ws = conn.execute("SELECT id FROM workspaces WHERE kind = 'school'").fetchone()["id"]
    row = conn.execute("SELECT * FROM tasks WHERE title = 'quiz prep'").fetchone()
    assert row["workspace_id"] == school_ws
    conn.close()


def test_capture_requires_title(tmp_path):
    client, _ = _client_with_token(tmp_path)
    r = client.post(
        "/api/capture", json={"source": "slack"}, headers={"Authorization": "Bearer sekrit"}
    )
    assert r.status_code == 400


def test_capture_bypasses_cookie_gate(tmp_path):
    client, _ = _client_with_token(tmp_path, password="hunter2")
    r = client.post(
        "/api/capture",
        json={"title": "from outside"},
        headers={"Authorization": "Bearer sekrit"},
        follow_redirects=False,
    )
    assert r.status_code == 200

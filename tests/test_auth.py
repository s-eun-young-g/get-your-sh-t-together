from fastapi.testclient import TestClient

from strata.app import create_app
from tests.conftest import make_settings


def test_auth_disabled_by_default(client):
    assert client.get("/").status_code == 200


def test_auth_enforced_with_password(tmp_path):
    app = create_app(make_settings(tmp_path, password="hunter2"))
    with TestClient(app) as c:
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

        assert c.post("/login", data={"password": "wrong"}).status_code == 401

        r = c.post("/login", data={"password": "hunter2"}, follow_redirects=False)
        assert r.status_code == 303
        assert c.get("/").status_code == 200

        c.post("/logout")
        r = c.get("/", follow_redirects=False)
        assert r.status_code == 303


def test_static_open_without_login(tmp_path):
    app = create_app(make_settings(tmp_path, password="hunter2"))
    with TestClient(app) as c:
        assert c.get("/static/style.css").status_code == 200

import pytest
from fastapi.testclient import TestClient

from strata import db
from strata.app import create_app
from strata.config import Settings


def make_settings(tmp_path, password="", api_key=""):
    return Settings(
        data_dir=tmp_path,
        password=password,
        port=8020,
        anthropic_api_key=api_key,
        secret="test-secret",
    )


@pytest.fixture
def conn(tmp_path):
    c = db.connect(tmp_path / "unit.db")
    db.migrate(c)
    yield c
    c.close()


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings):
    # The app no longer auto-seeds learn tracks; most tests still assume the
    # seed trees exist, so load them here explicitly.
    from strata.app import SEEDS_DIR
    from strata.services.seed_sync import sync_all

    app = create_app(settings)
    with TestClient(app) as c:
        seed_conn = db.connect(settings.db_path)
        try:
            sync_all(seed_conn, SEEDS_DIR / "learn")
        finally:
            seed_conn.close()
        yield c


@pytest.fixture
def app_db(settings):
    """A second connection into the same database the client's app uses."""
    c = db.connect(settings.db_path)
    yield c
    c.close()

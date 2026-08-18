from strata import db


def test_migrate_fresh_and_rerun(tmp_path):
    c = db.connect(tmp_path / "m.db")
    db.migrate(c)
    tables = {
        r["name"]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {
        "tasks", "pack_templates", "pack_template_items", "trips", "trip_templates",
        "trip_items", "boards", "buckets", "cards", "tracks", "nodes", "node_edges",
        "suggestions", "schema_migrations",
    } <= tables

    # Rerunning on an existing database applies nothing and raises nothing.
    db.migrate(c)
    versions = [r["version"] for r in c.execute("SELECT version FROM schema_migrations")]
    assert versions == sorted(set(versions))
    c.close()


def test_migrate_preserves_data(tmp_path):
    c = db.connect(tmp_path / "m.db")
    db.migrate(c)
    with c:
        c.execute("INSERT INTO tasks (title) VALUES ('keep me')")
    db.migrate(c)
    assert c.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 1
    c.close()

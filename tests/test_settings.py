LIFE_ON = {"mod_evenings": "1", "mod_packing": "1", "mod_routines": "1"}


def test_default_workspaces_bootstrap(client):
    work = client.get("/work").text
    assert 'value="job"' in work and 'value="school"' in work


def test_rename_workspace_flows_to_board(client, app_db):
    ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]
    client.post(f"/work/workspaces/{ws}/rename", data={"name": "Sedona"})
    assert 'value="Sedona"' in client.get("/work").text
    client.post("/capture", data={"title": "email board deck"})
    assert ">sedona</button>" in client.get("/now/sort").text


def test_multiple_jobs_each_get_a_section(client, app_db):
    client.post("/work/workspaces", data={"name": "Freelance", "kind": "job"})
    work = client.get("/work").text
    assert 'value="job"' in work and 'value="Freelance"' in work
    assert app_db.execute(
        "SELECT COUNT(*) AS n FROM workspaces WHERE kind = 'job' AND archived_at IS NULL"
    ).fetchone()["n"] == 2


def test_archive_workspace_keeps_tasks(client, app_db):
    ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "keep me", "due_date": "2030-01-05", "effort_minutes": "30", "dread": "1"},
    )
    client.post(f"/work/workspaces/{ws}/archive")
    assert 'value="job" aria-label="workspace name"' not in client.get("/work").text
    row = app_db.execute("SELECT * FROM tasks WHERE title = 'keep me'").fetchone()
    assert row is not None


def test_name_greeting(client):
    client.post("/settings", data={"name": "Sofia"} | LIFE_ON)
    assert "hi sofia" in client.get("/").text


def test_life_toggles_hide_sections_and_nav(client):
    client.post("/settings", data={"name": "", "mod_evenings": "1"})
    life = client.get("/life").text
    assert "<h2>evening plan</h2>" in life
    assert "Routines" not in life and "Packing" not in life
    assert 'href="/life"' in client.get("/now").text

    client.post("/settings", data={"name": ""})
    assert 'href="/life"' not in client.get("/now").text


def test_settings_page_renders_saved_note(client):
    client.post("/settings", data={"name": "Sofia"} | LIFE_ON)
    html = client.get("/settings?saved=1").text
    assert "saved" in html and 'value="Sofia"' in html


def test_settings_lists_imports_and_connections(client):
    html = client.get("/settings").text
    assert 'href="/learn/import"' in html
    assert 'href="/import/notion"' in html
    assert "canvas_base_url" in html  # off states explain how to turn them on
    assert "gcal_ics_url" in html

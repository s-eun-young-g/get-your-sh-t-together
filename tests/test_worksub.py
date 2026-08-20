def _job_ws(app_db):
    return app_db.execute("SELECT id FROM workspaces WHERE kind = 'job'").fetchone()["id"]


def test_job_areas_flow(client, app_db):
    ws = _job_ws(app_db)
    client.post(f"/work/workspaces/{ws}/areas", data={"name": "eval pipeline"})
    area = app_db.execute("SELECT id FROM areas").fetchone()["id"]
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "score baselines", "dest": f"a:{area}", "due_date": "2030-01-10",
              "effort_minutes": "120", "dread": "4"},
    )
    html = client.get("/work").text
    assert "eval pipeline" in html and "score baselines" in html

    client.post(f"/work/areas/{area}/visibility")
    html = client.get("/work").text
    assert "score baselines" not in html and ">eval pipeline</button>" in html
    client.post(f"/work/areas/{area}/visibility")
    assert "score baselines" in client.get("/work").text

    client.post(f"/work/areas/{area}/archive")
    html = client.get("/work").text
    assert "eval pipeline" not in html
    # its tasks survive on the board
    assert app_db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 1


def test_class_visibility(client, app_db):
    school = app_db.execute("SELECT id FROM workspaces WHERE kind = 'school'").fetchone()["id"]
    client.post(f"/work/workspaces/{school}/classes", data={"name": "6.031"})
    cid = app_db.execute("SELECT id FROM classes").fetchone()["id"]
    client.post(f"/work/classes/{cid}/visibility")
    html = client.get("/work").text
    assert ">6.031</button>" in html  # hidden chip to bring it back
    client.post(f"/work/classes/{cid}/visibility")
    assert "6.031" in client.get("/work").text


def test_growth_monologue(client, app_db):
    client.post("/work/workspaces", data={"name": "Future", "kind": "growth"})
    ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'growth'").fetchone()["id"]
    client.post(f"/work/workspaces/{ws}/feature", data={"feature": "monologue"})
    assert "ramble" in client.get("/work").text
    r = client.post(f"/work/workspaces/{ws}/monologue", data={"monologue": "what if grad school"})
    assert r.status_code == 204
    assert app_db.execute(
        "SELECT monologue FROM workspaces WHERE id = ?", (ws,)
    ).fetchone()["monologue"] == "what if grad school"

    # growth has no meetings toggle and no invented pipeline
    work = client.get("/work").text
    assert "someday" not in work and "applications" not in work


def test_meetings_on_school_too(client, app_db):
    school = app_db.execute("SELECT id FROM workspaces WHERE kind = 'school'").fetchone()["id"]
    client.post(f"/work/workspaces/{school}/feature", data={"feature": "meetings"})
    client.post(f"/work/workspaces/{school}/agendas", data={"name": "office hours"})
    agenda = app_db.execute("SELECT id FROM agendas").fetchone()["id"]
    client.post(f"/work/agendas/{agenda}/items", data={"text": "ask about pset 3"})
    html = client.get("/work").text
    assert "office hours" in html and "ask about pset 3" in html

    item = app_db.execute("SELECT id FROM agenda_items").fetchone()["id"]
    client.post(f"/work/agenda-items/{item}/done")
    assert "ask about pset 3" not in client.get("/work").text
    client.post(f"/work/agendas/{agenda}/archive")
    assert "office hours" not in client.get("/work").text




def test_burden_is_computed(client, app_db):
    from strata.routes.work import compute_burden

    assert compute_burden(15, 1) == "s"       # quick and fine
    assert compute_burden(60, 3) == "m"       # an hour of ugh
    assert compute_burden(480, 4) == "l"      # a day of dread
    ws = _job_ws(app_db)
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "quarterly report", "due_date": "2030-02-01",
              "effort_minutes": "480", "dread": "5"},
    )
    row = app_db.execute("SELECT * FROM tasks").fetchone()
    assert row["burden"] == "l" and row["due_date"] == "2030-02-01"
    html = client.get("/work").text
    assert "big" in html and "due in" in html


def test_task_without_deadline_rejected(client, app_db):
    ws = _job_ws(app_db)
    client.post(f"/work/workspaces/{ws}/tasks", data={"title": "vague thing"})
    assert app_db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0


def test_sorting_into_class_creates_assignment(client, app_db):
    school = app_db.execute("SELECT id FROM workspaces WHERE kind = 'school'").fetchone()["id"]
    client.post(f"/work/workspaces/{school}/classes", data={"name": "6.031"})
    cid = app_db.execute("SELECT id FROM classes").fetchone()["id"]
    client.post(
        f"/work/workspaces/{school}/tasks",
        data={"title": "PS2", "dest": f"c:{cid}", "due_date": "2030-03-01",
              "effort_minutes": "240", "dread": "3"},
    )
    a = app_db.execute("SELECT * FROM assignments").fetchone()
    assert a["class_id"] == cid and a["burden"] == "l"
    assert app_db.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()["n"] == 0


def test_growth_moves_are_dated_tasks(client, app_db):
    client.post("/work/workspaces", data={"name": "Future", "kind": "growth"})
    ws = app_db.execute("SELECT id FROM workspaces WHERE kind = 'growth'").fetchone()["id"]
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "apply to the fellowship", "notes": "an application",
              "due_kind": "about", "due_date": "2030-04-01",
              "effort_minutes": "480", "dread": "3"},
    )
    row = app_db.execute("SELECT * FROM tasks").fetchone()
    assert row["due_kind"] == "about" and row["notes"] == "an application"
    html = client.get("/work").text
    assert "add a move" in html and "an application" in html and "~due in" in html


def test_soon_deadline_flavor(client, app_db):
    ws = _job_ws(app_db)
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "loose end", "due_kind": "soon", "effort_minutes": "30", "dread": "2"},
    )
    row = app_db.execute("SELECT * FROM tasks").fetchone()
    assert row["due_kind"] == "soon" and row["due_date"] is None
    assert ">soon</span>" in client.get("/work").text


def test_meeting_dates(client, app_db):
    school = app_db.execute("SELECT id FROM workspaces WHERE kind = 'school'").fetchone()["id"]
    client.post(f"/work/workspaces/{school}/feature", data={"feature": "meetings"})
    client.post(
        f"/work/workspaces/{school}/agendas", data={"name": "lab meeting", "when": "tomorrow"}
    )
    row = app_db.execute("SELECT * FROM agendas").fetchone()
    assert row["when_at"] is not None
    assert "due tomorrow" in client.get("/work").text
    client.post(f"/work/agendas/{row['id']}/when", data={"when": "in 2w"})
    assert app_db.execute("SELECT when_at FROM agendas").fetchone()["when_at"] > row["when_at"]


def test_task_notes_autosave(client, app_db):
    client.post("/work/workspaces", data={"name": "consulting", "kind": "job"})
    ws = app_db.execute("SELECT id FROM workspaces WHERE name = 'consulting'").fetchone()["id"]
    client.post(
        f"/work/workspaces/{ws}/tasks",
        data={"title": "draft the memo", "due_date": "tomorrow", "effort_minutes": "30", "dread": "1"},
    )
    tid = app_db.execute("SELECT id FROM tasks WHERE title = 'draft the memo'").fetchone()["id"]
    r = client.post(f"/now/tasks/{tid}/notes", data={"notes": "ask Dana for the numbers"})
    assert r.status_code == 204
    assert app_db.execute(
        "SELECT notes FROM tasks WHERE id = ?", (tid,)
    ).fetchone()["notes"] == "ask Dana for the numbers"
    assert "ask Dana for the numbers" in client.get("/work").text


def test_assignment_notes_autosave(client, app_db):
    client.post("/work/workspaces", data={"name": "school", "kind": "school"})
    sid = app_db.execute(
        "SELECT id FROM workspaces WHERE name = 'school'"
    ).fetchone()["id"]
    client.post(f"/work/workspaces/{sid}/classes", data={"name": "bio"})
    cid = app_db.execute("SELECT id FROM classes").fetchone()["id"]
    client.post(f"/work/classes/{cid}/assignments", data={"title": "lab writeup", "due_date": "2030-01-05"})
    aid = app_db.execute("SELECT id FROM assignments").fetchone()["id"]
    r = client.post(f"/work/assignments/{aid}/notes", data={"notes": "cite the CRISPR paper"})
    assert r.status_code == 204
    assert app_db.execute(
        "SELECT notes FROM assignments WHERE id = ?", (aid,)
    ).fetchone()["notes"] == "cite the CRISPR paper"

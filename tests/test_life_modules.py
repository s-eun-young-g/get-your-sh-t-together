from datetime import date, timedelta

from strata.services.lifeops import add_months


def test_add_months_clamps():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)
    assert add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


def test_monthly_bill_advances_from_due_date(client, app_db):
    due = date.today().isoformat()
    client.post("/life/bills", data={"name": "rent", "next_due": due, "every_months": "1"})
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    client.post(f"/life/bills/{bid}/paid")
    row = app_db.execute("SELECT * FROM bills").fetchone()
    assert row["next_due"] == add_months(date.today(), 1).isoformat()
    assert row["archived_at"] is None


def test_one_time_renewal_archives_on_paid(client, app_db):
    client.post("/life/bills", data={"name": "global entry", "next_due": "2027-03-01", "every_months": "0"})
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    client.post(f"/life/bills/{bid}/paid")
    assert app_db.execute("SELECT archived_at FROM bills").fetchone()["archived_at"]
    assert "global entry" not in client.get("/life").text


def test_appointment_book_flow(client, app_db):
    client.post("/life/appointments", data={"title": "orthodontist"})
    aid = app_db.execute("SELECT id FROM appointments").fetchone()["id"]
    assert "booked it" in client.get("/life").text
    when = (date.today() + timedelta(days=7)).isoformat()
    client.post(f"/life/appointments/{aid}/book", data={"when_at": when})
    row = app_db.execute("SELECT * FROM appointments").fetchone()
    assert row["status"] == "booked" and row["when_at"] == when
    client.post(f"/life/appointments/{aid}/done")
    assert "orthodontist" not in client.get("/life").text


def test_appointment_today_on_home(client, app_db):
    client.post("/life/appointments", data={"title": "eye exam"})
    aid = app_db.execute("SELECT id FROM appointments").fetchone()["id"]
    client.post(f"/life/appointments/{aid}/book", data={"when_at": date.today().isoformat()})
    home = client.get("/").text
    assert "eye exam" in home and "1 due" in home


def test_bill_due_on_home(client, app_db):
    client.post("/life/bills", data={"name": "rent", "next_due": date.today().isoformat(), "every_months": "1"})
    assert "rent" in client.get("/").text



def test_life_module_toggles(client):
    client.post("/settings", data={"name": "", "mod_evenings": "1"})
    life = client.get("/life").text
    assert "show all recurring" not in life  # section gone; its re-add button may remain
    assert "Appointments" not in life
    assert "groceries" not in life
    assert "Evening plan" in life


def test_bad_dates_are_rejected_calmly(client, app_db):
    client.post("/life/bills", data={"name": "rent", "next_due": "whenever vibes", "every_months": "1"})
    assert app_db.execute("SELECT COUNT(*) AS n FROM bills").fetchone()["n"] == 0
    client.post("/life/appointments", data={"title": "gp"})
    aid = app_db.execute("SELECT id FROM appointments").fetchone()["id"]
    r = client.post(f"/life/appointments/{aid}/book", data={"when_at": "no clue"})
    assert r.status_code == 200
    assert app_db.execute("SELECT status FROM appointments").fetchone()["status"] == "needs_booking"
    assert client.get("/life").status_code == 200


def test_grocery_lists_mirror_packing(client, app_db):
    client.post("/pack/templates", data={"name": "staples", "kind": "grocery"})
    t = app_db.execute("SELECT * FROM pack_templates").fetchone()
    assert t["kind"] == "grocery"
    client.post(f"/pack/templates/{t['id']}/items", data={"label": "eggs"})
    # grocery templates live on /pack/groceries, not the packing page
    assert "staples" in client.get("/pack/groceries").text
    assert "staples" not in client.get("/pack").text

    client.post("/pack/trips", data={"name": "sunday run", "template_ids": str(t["id"]), "kind": "grocery"})
    run = app_db.execute("SELECT * FROM trips").fetchone()
    assert run["kind"] == "grocery"
    assert "sunday run" in client.get("/life").text
    assert "sunday run" not in client.get("/pack").text
    # the checklist machinery is the same
    item = app_db.execute("SELECT id FROM trip_items").fetchone()["id"]
    client.post(f"/pack/trip-items/{item}/toggle")
    assert app_db.execute("SELECT checked FROM trip_items").fetchone()["checked"] == 1


def test_natural_dates_in_bills(client, app_db):
    client.post("/life/bills", data={"name": "rent", "next_due": "sep 1", "every_months": "1"})
    row = app_db.execute("SELECT next_due FROM bills").fetchone()
    assert row is not None and row["next_due"].endswith("-09-01")


def test_financials_upcoming_vs_hidden(client, app_db):
    from datetime import date, timedelta

    soon = (date.today() + timedelta(days=3)).isoformat()
    far = (date.today() + timedelta(days=60)).isoformat()
    client.post("/life/bills", data={"name": "rent", "next_due": soon, "every_months": "1"})
    client.post("/life/bills", data={"name": "car registration", "next_due": far, "every_months": "12"})
    life = client.get("/life").text
    upcoming = life.split("show all recurring")[0]
    assert "rent" in upcoming and "car registration" not in upcoming
    assert "car registration" in life  # in the hidden full list


def test_credit_cards(client, app_db):
    client.post(
        "/life/cards",
        data={"name": "sapphire", "use_for": "dining, flights", "wins": "3x points, lounge"},
    )
    life = client.get("/life").text
    assert "sapphire" in life and "use for: dining, flights" in life and "wins: 3x points" in life
    cid = app_db.execute("SELECT id FROM credit_cards").fetchone()["id"]
    client.post(f"/life/cards/{cid}/delete")
    assert "sapphire" not in client.get("/life").text

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


def test_autopay_bill_stays_off_home(client, app_db):
    due = date.today().isoformat()
    client.post("/life/bills", data={
        "name": "spotify", "next_due": due, "every_months": "1", "mode": "auto",
    })
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    home = client.get("/").text
    assert f"/life/bills/{bid}/paid" not in home  # no tick, nothing to do
    assert "all clear" in home  # the life tile does not count it as due
    html = client.get("/life").text
    assert "on autopilot (1)" in html
    assert "nothing needs you." in html


def test_autopay_rolls_past_charges_forward(client, app_db):
    from strata.services.lifeops import active_bills

    stale = (date.today() - timedelta(days=40)).isoformat()
    client.post("/life/bills", data={
        "name": "icloud", "next_due": stale, "every_months": "1", "mode": "auto",
    })
    b = active_bills(app_db)[0]
    assert b["days"] >= 0
    assert "overdue" not in b["due_label"]


def test_renewal_surfaces_as_decision(client, app_db):
    soon = (date.today() + timedelta(days=10)).isoformat()
    client.post("/life/bills", data={
        "name": "hulu", "next_due": soon, "every_months": "12", "mode": "renewal",
    })
    html = client.get("/life").text
    assert "decide before it renews" in html
    assert "keeping it" in html and "cancelled it" in html
    assert "hulu" in client.get("/").text  # life tile counts the decision


def test_renewal_keep_moves_to_next_cycle(client, app_db):
    soon = date.today() + timedelta(days=10)
    client.post("/life/bills", data={
        "name": "hulu", "next_due": soon.isoformat(), "every_months": "12", "mode": "renewal",
    })
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    client.post(f"/life/bills/{bid}/keep")
    row = app_db.execute("SELECT * FROM bills").fetchone()
    assert row["next_due"] == add_months(soon, 12).isoformat()
    assert row["archived_at"] is None
    assert "decide before it renews" not in client.get("/life").text


def test_renewal_cancel_archives(client, app_db):
    soon = (date.today() + timedelta(days=5)).isoformat()
    client.post("/life/bills", data={
        "name": "hulu", "next_due": soon, "every_months": "12", "mode": "renewal",
    })
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    client.post(f"/life/bills/{bid}/cancel")
    assert app_db.execute("SELECT archived_at FROM bills").fetchone()["archived_at"]
    assert "hulu" not in client.get("/life").text


def test_amounts_and_monthly_load(client, app_db):
    due = (date.today() + timedelta(days=20)).isoformat()
    client.post("/life/bills", data={
        "name": "rent", "next_due": due, "every_months": "1",
        "amount": "$1,400", "mode": "manual",
    })
    client.post("/life/bills", data={
        "name": "insurance", "next_due": due, "every_months": "6",
        "amount": "600", "mode": "auto",
    })
    assert app_db.execute(
        "SELECT amount FROM bills WHERE name = 'rent'"
    ).fetchone()["amount"] == 1400.0
    html = client.get("/life").text
    assert "recurring load: about $1,500/mo" in html
    assert "$1,400" in html


def test_bad_amount_is_dropped(client, app_db):
    due = date.today().isoformat()
    client.post("/life/bills", data={
        "name": "rent", "next_due": due, "every_months": "1", "amount": "idk",
    })
    assert app_db.execute("SELECT amount FROM bills").fetchone()["amount"] is None


def test_bill_mode_retag(client, app_db):
    due = date.today().isoformat()
    client.post("/life/bills", data={"name": "spotify", "next_due": due, "every_months": "1"})
    bid = app_db.execute("SELECT id FROM bills").fetchone()["id"]
    client.post(f"/life/bills/{bid}/mode", data={"mode": "auto"})
    assert app_db.execute("SELECT mode FROM bills").fetchone()["mode"] == "auto"
    client.post(f"/life/bills/{bid}/mode", data={"mode": "nonsense"})
    assert app_db.execute("SELECT mode FROM bills").fetchone()["mode"] == "auto"

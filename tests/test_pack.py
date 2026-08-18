from strata.services.pack_ops import instantiate_trip, offer_back, pending_offers


def _template(conn, name, labels):
    with conn:
        tid = conn.execute(
            "INSERT INTO pack_templates (name) VALUES (?)", (name,)
        ).lastrowid
        for i, label in enumerate(labels):
            conn.execute(
                "INSERT INTO pack_template_items (template_id, label, position)"
                " VALUES (?, ?, ?)",
                (tid, label, i),
            )
    return tid


def _labels(conn, trip_id):
    return [
        r["label"]
        for r in conn.execute(
            "SELECT label FROM trip_items WHERE trip_id = ? ORDER BY position", (trip_id,)
        )
    ]


def test_multi_template_dedupe(conn):
    a = _template(conn, "conference", ["Laptop", "Charger", "Badge"])
    b = _template(conn, "international", ["Passport", "charger ", "Adapter"])
    trip = instantiate_trip(conn, "Berlin", [a, b])
    assert _labels(conn, trip) == ["Laptop", "Charger", "Badge", "Passport", "Adapter"]


def test_template_edit_after_trip_leaves_trip_alone(conn):
    a = _template(conn, "beach", ["Sunscreen"])
    trip = instantiate_trip(conn, "Lisbon", [a])
    with conn:
        conn.execute("UPDATE pack_template_items SET label = 'SPF 50' WHERE label = 'Sunscreen'")
    assert _labels(conn, trip) == ["Sunscreen"]


def test_template_delete_leaves_trip_items(conn):
    a = _template(conn, "beach", ["Sunscreen"])
    trip = instantiate_trip(conn, "Lisbon", [a])
    with conn:
        conn.execute("DELETE FROM pack_templates WHERE id = ?", (a,))
    rows = conn.execute("SELECT * FROM trip_items WHERE trip_id = ?", (trip,)).fetchall()
    assert [r["label"] for r in rows] == ["Sunscreen"]
    assert rows[0]["source_template_item_id"] is None


def test_offer_back_inserts_once_and_skips_existing(conn):
    a = _template(conn, "conference", ["Laptop"])
    trip = instantiate_trip(conn, "SF", [a])
    with conn:
        added = conn.execute(
            "INSERT INTO trip_items (trip_id, label, added_during_trip) VALUES (?, 'HDMI dongle', 1)",
            (trip,),
        ).lastrowid
        dupe = conn.execute(
            "INSERT INTO trip_items (trip_id, label, added_during_trip) VALUES (?, 'laptop', 1)",
            (trip,),
        ).lastrowid
    assert len(pending_offers(conn, trip)) == 2

    offer_back(conn, added, a)
    offer_back(conn, added, a)  # resolved offers cannot double-insert
    offer_back(conn, dupe, a)  # label already in template, marks accepted without insert

    labels = [
        r["label"]
        for r in conn.execute(
            "SELECT label FROM pack_template_items WHERE template_id = ? ORDER BY position",
            (a,),
        )
    ]
    assert labels == ["Laptop", "HDMI dongle"]
    assert pending_offers(conn, trip) == []


def test_offer_dismiss(conn):
    a = _template(conn, "conference", [])
    trip = instantiate_trip(conn, "SF", [a])
    with conn:
        added = conn.execute(
            "INSERT INTO trip_items (trip_id, label, added_during_trip) VALUES (?, 'Melatonin', 1)",
            (trip,),
        ).lastrowid
    offer_back(conn, added, None)
    assert pending_offers(conn, trip) == []
    assert conn.execute("SELECT COUNT(*) AS n FROM pack_template_items").fetchone()["n"] == 0


def test_close_is_idempotent_and_blocks_toggle(client, app_db):
    client.post("/pack/templates", data={"name": "beach"})
    template_id = app_db.execute("SELECT id FROM pack_templates").fetchone()["id"]
    client.post(f"/pack/templates/{template_id}/items", data={"label": "Towel"})
    client.post("/pack/trips", data={"name": "Nice", "template_ids": str(template_id)})
    trip_id = app_db.execute("SELECT id FROM trips").fetchone()["id"]

    client.post(f"/pack/trips/{trip_id}/close")
    first = app_db.execute("SELECT closed_at FROM trips").fetchone()["closed_at"]
    client.post(f"/pack/trips/{trip_id}/close")
    assert app_db.execute("SELECT closed_at FROM trips").fetchone()["closed_at"] == first

    item_id = app_db.execute("SELECT id FROM trip_items").fetchone()["id"]
    client.post(f"/pack/trip-items/{item_id}/toggle")
    assert app_db.execute("SELECT checked FROM trip_items").fetchone()["checked"] == 0

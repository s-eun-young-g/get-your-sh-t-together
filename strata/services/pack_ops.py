"""Packing flows: trip instantiation from templates and offer-back."""

from __future__ import annotations

import sqlite3


def _norm(label: str) -> str:
    return " ".join(label.split()).lower()


def instantiate_trip(
    conn: sqlite3.Connection, name: str, template_ids: list[int], kind: str = "pack"
) -> int:
    """Create a trip by snapshot-copying items from one or more templates.

    Labels are deduped case-insensitively across templates; the first
    occurrence wins and carries the lineage pointer.
    """
    with conn:
        cur = conn.execute("INSERT INTO trips (name, kind) VALUES (?, ?)", (name, kind))
        trip_id = cur.lastrowid
        seen: set[str] = set()
        pos = 0
        for tid in template_ids:
            conn.execute(
                "INSERT OR IGNORE INTO trip_templates (trip_id, template_id) VALUES (?, ?)",
                (trip_id, tid),
            )
            rows = conn.execute(
                "SELECT id, label FROM pack_template_items WHERE template_id = ?"
                " ORDER BY position, id",
                (tid,),
            ).fetchall()
            for r in rows:
                key = _norm(r["label"])
                if key in seen:
                    continue
                seen.add(key)
                conn.execute(
                    "INSERT INTO trip_items (trip_id, label, position, source_template_item_id)"
                    " VALUES (?, ?, ?, ?)",
                    (trip_id, r["label"], pos, r["id"]),
                )
                pos += 1
    return trip_id


def offer_back(conn: sqlite3.Connection, trip_item_id: int, template_id: int | None) -> None:
    """Resolve one offer: add to a template (if given) or dismiss."""
    item = conn.execute("SELECT * FROM trip_items WHERE id = ?", (trip_item_id,)).fetchone()
    if item is None or not item["added_during_trip"] or item["offer_status"] is not None:
        return
    with conn:
        if template_id is None:
            conn.execute(
                "UPDATE trip_items SET offer_status = 'dismissed' WHERE id = ?",
                (trip_item_id,),
            )
            return
        exists = conn.execute(
            "SELECT 1 FROM pack_template_items WHERE template_id = ?"
            " AND lower(trim(label)) = ?",
            (template_id, _norm(item["label"])),
        ).fetchone()
        if not exists:
            pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM pack_template_items"
                " WHERE template_id = ?",
                (template_id,),
            ).fetchone()["p"]
            conn.execute(
                "INSERT INTO pack_template_items (template_id, label, position) VALUES (?, ?, ?)",
                (template_id, item["label"], pos),
            )
        conn.execute(
            "UPDATE trip_items SET offer_status = 'accepted' WHERE id = ?",
            (trip_item_id,),
        )


def pending_offers(conn: sqlite3.Connection, trip_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM trip_items WHERE trip_id = ? AND added_during_trip = 1"
        " AND offer_status IS NULL ORDER BY position, id",
        (trip_id,),
    ).fetchall()

"""PACK: reusable templates, snapshot trips, offer-back."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from ..deps import get_conn, render, utcnow
from ..services import pack_ops

router = APIRouter(prefix="/pack")


NOUNS = {"pack": "trip", "grocery": "run"}


def _templates(conn: sqlite3.Connection, kind: str = "pack") -> list[dict]:
    out = []
    for t in conn.execute(
        "SELECT * FROM pack_templates WHERE kind = ? ORDER BY name", (kind,)
    ):
        items = conn.execute(
            "SELECT * FROM pack_template_items WHERE template_id = ? ORDER BY position, id",
            (t["id"],),
        ).fetchall()
        out.append({"row": t, "items": items})
    return out


def _index_ctx(conn: sqlite3.Connection, kind: str = "pack") -> dict:
    return {
        "kind": kind,
        "noun": NOUNS.get(kind, "trip"),
        "templates": _templates(conn, kind),
        "trips": conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM trip_items i"
            "  WHERE i.trip_id = t.id AND i.checked = 0) AS unchecked"
            " FROM trips t WHERE kind = ? ORDER BY status = 'closed', created_at DESC",
            (kind,),
        ).fetchall(),
    }


def _trip_ctx(conn: sqlite3.Connection, trip_id: int) -> dict:
    trip = conn.execute("SELECT * FROM trips WHERE id = ?", (trip_id,)).fetchone()
    items = conn.execute(
        "SELECT * FROM trip_items WHERE trip_id = ? ORDER BY position, id", (trip_id,)
    ).fetchall()
    sources = conn.execute(
        "SELECT p.* FROM pack_templates p JOIN trip_templates tt ON tt.template_id = p.id"
        " WHERE tt.trip_id = ? ORDER BY p.name",
        (trip_id,),
    ).fetchall()
    return {
        "trip": trip,
        "items": items,
        "sources": sources,
        "offers": pack_ops.pending_offers(conn, trip_id),
        "unchecked": sum(1 for i in items if not i["checked"]),
    }


@router.get("")
def pack_page(request: Request, conn=Depends(get_conn)):
    return render(request, "pack/index.html", _index_ctx(conn))


@router.get("/groceries", include_in_schema=False)
def groceries_page(request: Request, conn=Depends(get_conn)):
    return render(request, "pack/index.html", _index_ctx(conn, "grocery"))


@router.post("/templates")
def create_template(
    request: Request, conn=Depends(get_conn), name: str = Form(...), kind: str = Form("pack")
):
    name = name.strip()
    kind = kind if kind in NOUNS else "pack"
    if name:
        with conn:
            conn.execute(
                "INSERT INTO pack_templates (name, kind) VALUES (?, ?)"
                " ON CONFLICT(name) DO NOTHING",
                (name, kind),
            )
    return render(request, "pack/_index_body.html", _index_ctx(conn, kind))


def _template_kind(conn: sqlite3.Connection, template_id: int) -> str:
    row = conn.execute(
        "SELECT kind FROM pack_templates WHERE id = ?", (template_id,)
    ).fetchone()
    return row["kind"] if row else "pack"


@router.post("/templates/{template_id}/items")
def add_template_item(
    request: Request, template_id: int, conn=Depends(get_conn), label: str = Form(...)
):
    label = label.strip()
    if label:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM pack_template_items"
            " WHERE template_id = ?",
            (template_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO pack_template_items (template_id, label, position)"
                " VALUES (?, ?, ?)",
                (template_id, label, pos),
            )
    return render(
        request, "pack/_index_body.html", _index_ctx(conn, _template_kind(conn, template_id))
    )


@router.post("/template-items/{item_id}/delete")
def delete_template_item(request: Request, item_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT template_id FROM pack_template_items WHERE id = ?", (item_id,)
    ).fetchone()
    kind = _template_kind(conn, row["template_id"]) if row else "pack"
    with conn:
        conn.execute("DELETE FROM pack_template_items WHERE id = ?", (item_id,))
    return render(request, "pack/_index_body.html", _index_ctx(conn, kind))


@router.post("/templates/{template_id}/delete")
def delete_template(request: Request, template_id: int, conn=Depends(get_conn)):
    kind = _template_kind(conn, template_id)
    with conn:
        conn.execute("DELETE FROM pack_templates WHERE id = ?", (template_id,))
    return render(request, "pack/_index_body.html", _index_ctx(conn, kind))


@router.post("/trips")
def create_trip(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(...),
    template_ids: list[int] = Form([]),
    kind: str = Form("pack"),
):
    kind = kind if kind in NOUNS else "pack"
    name = name.strip() or NOUNS[kind]
    trip_id = pack_ops.instantiate_trip(conn, name, template_ids, kind)
    return Response(headers={"HX-Redirect": f"/pack/trips/{trip_id}"})


@router.get("/trips/{trip_id}")
def trip_page(request: Request, trip_id: int, conn=Depends(get_conn)):
    return render(request, "pack/trip.html", _trip_ctx(conn, trip_id))


@router.post("/trips/{trip_id}/items")
def add_trip_item(
    request: Request, trip_id: int, conn=Depends(get_conn), label: str = Form(...)
):
    label = label.strip()
    trip = conn.execute("SELECT status FROM trips WHERE id = ?", (trip_id,)).fetchone()
    if label and trip and trip["status"] == "active":
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM trip_items WHERE trip_id = ?",
            (trip_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO trip_items (trip_id, label, position, added_during_trip)"
                " VALUES (?, ?, ?, 1)",
                (trip_id, label, pos),
            )
    return render(request, "pack/_trip_body.html", _trip_ctx(conn, trip_id))


@router.post("/trip-items/{item_id}/toggle")
def toggle_trip_item(request: Request, item_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT i.trip_id, i.checked, t.status FROM trip_items i"
        " JOIN trips t ON t.id = i.trip_id WHERE i.id = ?",
        (item_id,),
    ).fetchone()
    if row and row["status"] == "active":
        with conn:
            conn.execute(
                "UPDATE trip_items SET checked = ? WHERE id = ?",
                (0 if row["checked"] else 1, item_id),
            )
    return render(request, "pack/_trip_body.html", _trip_ctx(conn, row["trip_id"]))


@router.post("/trips/{trip_id}/close")
def close_trip(request: Request, trip_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE trips SET status = 'closed', closed_at = ?"
            " WHERE id = ? AND status = 'active'",
            (utcnow(), trip_id),
        )
    return render(request, "pack/_trip_body.html", _trip_ctx(conn, trip_id))


@router.post("/trips/{trip_id}/reopen")
def reopen_trip(request: Request, trip_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE trips SET status = 'active', closed_at = NULL WHERE id = ?", (trip_id,)
        )
    return render(request, "pack/_trip_body.html", _trip_ctx(conn, trip_id))


@router.post("/trip-items/{item_id}/offer")
def offer(
    request: Request,
    item_id: int,
    conn=Depends(get_conn),
    template_id: int = Form(0),
    dismiss: int = Form(0),
):
    row = conn.execute(
        "SELECT trip_id FROM trip_items WHERE id = ?", (item_id,)
    ).fetchone()
    pack_ops.offer_back(conn, item_id, None if dismiss else template_id)
    return render(request, "pack/_trip_body.html", _trip_ctx(conn, row["trip_id"]))

"""RESCUE: the I'm-so-bored-I-could-die flow."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_conn, render
from ..services import rescue

router = APIRouter(prefix="/rescue")


def rescue_ctx(conn: sqlite3.Connection) -> dict:
    return {
        "suggestion": rescue.suggestion(conn),
        "pending": rescue.pending(conn),
        "items": rescue.all_items(conn),
        "unused_presets": rescue.unused_presets(conn),
        "stats": rescue.stats(conn),
    }


@router.get("")
def rescue_page(request: Request, conn=Depends(get_conn)):
    return render(request, "rescue/index.html", rescue_ctx(conn))


def _body(request: Request, conn: sqlite3.Connection):
    return render(request, "rescue/_body.html", rescue_ctx(conn))


@router.post("/items")
def add_item(request: Request, conn=Depends(get_conn), title: str = Form(...)):
    title = title.strip()
    if title:
        with conn:
            conn.execute("INSERT INTO rescue_items (title) VALUES (?)", (title,))
    return _body(request, conn)


@router.post("/preset")
def add_preset(request: Request, conn=Depends(get_conn), key: str = Form(...)):
    rescue.add_preset(conn, key)
    return _body(request, conn)


@router.post("/items/{item_id}/try")
def try_item(request: Request, item_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE rescue_items SET pending_at = datetime('now')"
            " WHERE id = ? AND active = 1",
            (item_id,),
        )
    return _body(request, conn)


@router.post("/items/{item_id}/skip")
def skip_item(request: Request, item_id: int, conn=Depends(get_conn)):
    # "not this" pushes the item to the back of the rotation.
    with conn:
        conn.execute(
            "UPDATE rescue_items SET last_suggested = datetime('now') WHERE id = ?",
            (item_id,),
        )
    return _body(request, conn)


@router.post("/items/{item_id}/outcome")
def outcome(
    request: Request, item_id: int, conn=Depends(get_conn), helped: int = Form(...)
):
    rescue.log_outcome(conn, item_id, bool(helped))
    return _body(request, conn)


@router.post("/items/{item_id}/retire")
def retire_item(request: Request, item_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE rescue_items SET active = 0, pending_at = NULL WHERE id = ?",
            (item_id,),
        )
    return _body(request, conn)

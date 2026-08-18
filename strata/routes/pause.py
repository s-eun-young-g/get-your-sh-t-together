"""PAUSE: anti-impulsivity. Catch the impulse, wait it out, decide on purpose."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_conn, render
from ..services import impulses

router = APIRouter(prefix="/pause")


def pause_ctx(conn: sqlite3.Connection) -> dict:
    return {
        "waiting": impulses.waiting(conn),
        "unlogged": impulses.unlogged(conn),
        "released": conn.execute(
            "SELECT * FROM impulses WHERE status = 'released'"
            " ORDER BY created_at DESC LIMIT 30"
        ).fetchall(),
        "acted_log": conn.execute(
            "SELECT * FROM impulses WHERE status = 'acted' AND regret IS NOT NULL"
            " ORDER BY acted_at DESC LIMIT 30"
        ).fetchall(),
        "stats": impulses.stats(conn),
        "categories": impulses.CATEGORIES,
        "wait_stops": impulses.SLIDER_STOPS,
        "default_stop": impulses.DEFAULT_STOP_INDEX,
    }


@router.get("")
def pause_page(request: Request, conn=Depends(get_conn)):
    return render(request, "pause/index.html", pause_ctx(conn))


def _body(request: Request, conn: sqlite3.Connection):
    return render(request, "pause/_body.html", pause_ctx(conn))


@router.post("/impulses")
def add_impulse(
    request: Request,
    conn=Depends(get_conn),
    title: str = Form(...),
    category: str = Form("shopping"),
    wait_minutes: int = Form(1440),
):
    title = title.strip()
    if category not in {c for c, _ in impulses.CATEGORIES}:
        category = "other"
    if title:
        with conn:
            conn.execute(
                "INSERT INTO impulses (title, category, wait_minutes) VALUES (?, ?, ?)",
                (title, category, max(1, min(wait_minutes, impulses.INDEFINITE))),
            )
    return _body(request, conn)


def _transition(conn: sqlite3.Connection, impulse_id: int, ready_required: bool, **fields):
    row = conn.execute("SELECT * FROM impulses WHERE id = ?", (impulse_id,)).fetchone()
    if row is None or row["status"] != "waiting":
        return
    if ready_required and not impulses.decorate(row)["ready"]:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(
            f"UPDATE impulses SET {sets} WHERE id = ?", (*fields.values(), impulse_id)
        )


@router.post("/impulses/{impulse_id}/release")
def release_impulse(request: Request, impulse_id: int, conn=Depends(get_conn)):
    # Letting go is allowed at any time, even mid-cooldown.
    _transition(conn, impulse_id, ready_required=False, status="released")
    return _body(request, conn)


@router.post("/impulses/{impulse_id}/act")
def act_on_impulse(request: Request, impulse_id: int, conn=Depends(get_conn)):
    # Honesty over gates: "I didn't wait" is always available; the record
    # is what teaches, not a lock.
    _transition(conn, impulse_id, ready_required=False, status="acted")
    with conn:
        conn.execute(
            "UPDATE impulses SET acted_at = datetime('now')"
            " WHERE id = ? AND status = 'acted' AND acted_at IS NULL",
            (impulse_id,),
        )
    return _body(request, conn)


@router.post("/impulses/{impulse_id}/regret")
def log_regret(
    request: Request, impulse_id: int, conn=Depends(get_conn), regret: int = Form(...)
):
    with conn:
        conn.execute(
            "UPDATE impulses SET regret = ? WHERE id = ? AND status = 'acted'",
            (1 if regret else 0, impulse_id),
        )
    return _body(request, conn)


@router.post("/impulses/{impulse_id}/delete")
def delete_impulse(request: Request, impulse_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM impulses WHERE id = ?", (impulse_id,))
    return _body(request, conn)

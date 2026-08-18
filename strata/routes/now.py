"""NOW: layered tasks, inbox triage, nuisance pen, blitz mode."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_conn, render, reindex, utcnow
from ..services import workspaces as ws_svc

router = APIRouter(prefix="/now")

STALE_DAYS = 3
HORIZONS = ("inbox", "today")


def open_tasks(conn: sqlite3.Connection, horizon: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT t.*, w.name AS ws_name FROM tasks t"
        " LEFT JOIN workspaces w ON w.id = t.workspace_id"
        " WHERE t.horizon = ? AND t.nuisance = 0 AND t.done_at IS NULL"
        " ORDER BY t.position, t.id",
        (horizon,),
    ).fetchall()


def nuisance_pen(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM tasks WHERE nuisance = 1 AND done_at IS NULL"
        " ORDER BY pinned DESC, created_at, id"
    ).fetchall()


def next_nuisance(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM tasks WHERE nuisance = 1 AND done_at IS NULL"
        " AND (snoozed_until IS NULL OR snoozed_until <= date('now'))"
        " ORDER BY pinned DESC, created_at, id LIMIT 1"
    ).fetchone()


def momentum(conn: sqlite3.Connection) -> dict:
    done_today = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE done_at >= date('now')"
    ).fetchone()["n"]
    nuisances_week = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE nuisance = 1"
        " AND done_at >= date('now', '-6 days')"
    ).fetchone()["n"]
    return {"done_today": done_today, "nuisances_week": nuisances_week}


def inbox_tasks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The true inbox: captured, undecided, unassigned. A task tagged with a
    workspace has been sorted; its home is that work area's backlog."""
    return conn.execute(
        "SELECT t.*, NULL AS ws_name FROM tasks t"
        " WHERE t.horizon = 'inbox' AND t.nuisance = 0 AND t.done_at IS NULL"
        " AND t.workspace_id IS NULL"
        " ORDER BY t.position, t.id"
    ).fetchall()


def next_inbox(conn: sqlite3.Connection) -> sqlite3.Row | None:
    rows = inbox_tasks(conn)
    return rows[0] if rows else None


def _frame_response(request: Request, conn: sqlite3.Connection, frame: str):
    if frame == "sort":
        return render(
            request,
            "now/_sort_card.html",
            {
                "task": next_inbox(conn),
                "remaining": len(inbox_tasks(conn)),
                "workspaces": ws_svc.active(conn),
            },
        )
    if frame == "work":
        from .work import work_ctx

        return render(request, "work/_body.html", work_ctx(request, conn))
    if frame == "blitz":
        return render(
            request,
            "now/_blitz_card.html",
            {"task": next_nuisance(conn), "remaining": len(nuisance_pen(conn))},
        )
    from .home import build_home_ctx

    return render(
        request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs)
    )


@router.get("")
def now_page():
    # The board merged into home.
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/", status_code=303)


@router.get("/sort")
def sort_page(request: Request, conn=Depends(get_conn)):
    return render(
        request,
        "now/sort.html",
        {
            "task": next_inbox(conn),
            "remaining": len(inbox_tasks(conn)),
            "workspaces": ws_svc.active(conn),
        },
    )


@router.post("/tasks/{task_id}/skip")
def skip_task(request: Request, task_id: int, conn=Depends(get_conn)):
    # Push to the back of the inbox and deal the next card.
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tasks WHERE horizon = 'inbox'"
    ).fetchone()["p"]
    _touch(conn, task_id, position=pos)
    return _frame_response(request, conn, "sort")


@router.post("/tasks/{task_id}/sort_tag")
def sort_tag(
    request: Request, task_id: int, conn=Depends(get_conn), workspace_id: int = Form(0)
):
    # Tag with a work area and move on: it now lives on the work page.
    pos = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tasks WHERE horizon = 'inbox'"
    ).fetchone()["p"]
    _touch(conn, task_id, workspace_id=workspace_id or None, position=pos)
    return _frame_response(request, conn, "sort")


@router.get("/blitz")
def blitz_page(request: Request, conn=Depends(get_conn)):
    return render(
        request,
        "now/blitz.html",
        {"task": next_nuisance(conn), "remaining": len(nuisance_pen(conn))},
    )


@router.post("/tasks")
def create_task(
    request: Request,
    conn=Depends(get_conn),
    title: str = Form(...),
    horizon: str = Form("today"),
    nuisance: int = Form(0),
    context: str = Form(""),
):
    if horizon not in HORIZONS:
        horizon = "today"
    title = title.strip()
    if title:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tasks WHERE horizon = ?",
            (horizon,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO tasks (title, horizon, nuisance, context, position)"
                " VALUES (?, ?, ?, ?, ?)",
                (title, horizon, 1 if nuisance else 0, context, pos),
            )
    return _frame_response(request, conn, "board")


def _touch(conn: sqlite3.Connection, task_id: int, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(
            f"UPDATE tasks SET {sets}, updated_at = ? WHERE id = ?",
            (*fields.values(), utcnow(), task_id),
        )


@router.post("/tasks/{task_id}/move")
def move_task(
    request: Request,
    task_id: int,
    conn=Depends(get_conn),
    horizon: str = Form(...),
    frame: str = Form("board"),
):
    if horizon in HORIZONS:
        old = conn.execute("SELECT horizon FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if old:
            pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tasks WHERE horizon = ?",
                (horizon,),
            ).fetchone()["p"]
            _touch(conn, task_id, horizon=horizon, position=pos, nuisance=0)
            with conn:
                reindex(conn, "tasks", "horizon", old["horizon"])
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/workspace")
def set_workspace(
    request: Request,
    task_id: int,
    conn=Depends(get_conn),
    workspace_id: int = Form(0),
    frame: str = Form("board"),
):
    _touch(conn, task_id, workspace_id=workspace_id or None)
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/nuisance")
def flag_nuisance(
    request: Request, task_id: int, conn=Depends(get_conn), frame: str = Form("board")
):
    row = conn.execute("SELECT nuisance FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row:
        _touch(conn, task_id, nuisance=0 if row["nuisance"] else 1, pinned=0)
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/done")
def done_task(
    request: Request, task_id: int, conn=Depends(get_conn), frame: str = Form("board")
):
    _touch(conn, task_id, done_at=utcnow(), pinned=0)
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/undone")
def undone_task(
    request: Request, task_id: int, conn=Depends(get_conn), frame: str = Form("board")
):
    _touch(conn, task_id, done_at=None)
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/delete")
def delete_task(
    request: Request, task_id: int, conn=Depends(get_conn), frame: str = Form("board")
):
    with conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/snooze")
def snooze_task(
    request: Request,
    task_id: int,
    conn=Depends(get_conn),
    days: int = Form(3),
    frame: str = Form("board"),
):
    until = (date.today() + timedelta(days=max(1, days))).isoformat()
    _touch(conn, task_id, snoozed_until=until, pinned=0)
    return _frame_response(request, conn, frame)


@router.post("/tasks/{task_id}/pin")
def pin_task(
    request: Request, task_id: int, conn=Depends(get_conn), frame: str = Form("board")
):
    row = conn.execute("SELECT pinned FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row:
        with conn:
            conn.execute("UPDATE tasks SET pinned = 0 WHERE nuisance = 1")
        _touch(conn, task_id, pinned=0 if row["pinned"] else 1, snoozed_until=None)
    return _frame_response(request, conn, frame)


@router.post("/sweep")
def sweep(request: Request, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE tasks SET horizon = 'inbox', updated_at = ?"
            " WHERE horizon = 'today' AND nuisance = 0 AND done_at IS NULL"
            f" AND updated_at <= datetime('now', '-{STALE_DAYS} days')",
            (utcnow(),),
        )
        reindex(conn, "tasks", "horizon", "inbox")
    return _frame_response(request, conn, "home")

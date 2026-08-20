"""WORK hub: one section per workspace (job task list, or school with classes)."""

from __future__ import annotations

import sqlite3
from datetime import date as _date

from fastapi import APIRouter, Depends, Form, Request

from ..deps import get_conn, render
from ..services import canvas, school, workspaces

router = APIRouter(prefix="/work")

SORT_DATE = "(CASE WHEN due_kind = 'soon' THEN date('now', '+7 day') ELSE due_date END)"
TASK_ORDER = (
    f"{SORT_DATE} IS NULL, {SORT_DATE},"
    " CASE burden WHEN 'l' THEN 0 WHEN 'm' THEN 1 WHEN 's' THEN 2 ELSE 3 END, id"
)

# Burden is computed, not chosen: how long it will take x how much you dread it.
EFFORT_STOPS = [
    (15, "15m"), (30, "30m"), (60, "1h"), (120, "2h"),
    (240, "half a day"), (480, "a day"), (960, "multi-day"),
]
EFFORT_DEFAULT = 2  # 1h
DREAD_CHOICES = [(1, "fine"), (2, "meh"), (3, "ugh"), (4, "dread"), (5, "horror")]


def compute_burden(effort_minutes: int, dread: int) -> str:
    effort_score = 1 + sum(1 for m, _ in EFFORT_STOPS[:4] if effort_minutes > m)
    total = effort_score + max(1, min(dread, 5))
    if total <= 4:
        return "s"
    if total <= 7:
        return "m"
    return "l"


def _decorate_task(t) -> dict:
    d = dict(t)
    kind = d.get("due_kind") or "on"
    if kind == "soon":
        d["due_label"] = "soon"
        d["start_early"] = (d.get("burden") or "") == "l"
    elif d.get("due_date"):
        d.update(school.decorate_due(d["due_date"], d.get("burden") or "m"))
        if kind == "about":
            d["due_label"] = "~" + d["due_label"]
    else:
        d["due_label"], d["start_early"] = "", False
    d["burden_label"] = school.BURDEN_LABEL.get(d.get("burden") or "", "")
    return d

def _agendas(conn: sqlite3.Connection, workspace_id: int) -> list[dict]:
    out = []
    for a in conn.execute(
        "SELECT * FROM agendas WHERE workspace_id = ? AND archived_at IS NULL"
        " ORDER BY position, id",
        (workspace_id,),
    ):
        items = conn.execute(
            "SELECT * FROM agenda_items WHERE agenda_id = ? AND done_at IS NULL ORDER BY id",
            (a["id"],),
        ).fetchall()
        d = {"row": a, "items": items}
        d.update(school.decorate_due(a["when_at"], ""))
        out.append(d)
    return out


def _classes(conn: sqlite3.Connection, workspace_id: int) -> list[dict]:
    out = []
    for c in conn.execute(
        "SELECT * FROM classes WHERE archived_at IS NULL AND workspace_id = ?"
        " AND hidden = 0 ORDER BY name",
        (workspace_id,),
    ):
        rows = conn.execute(
            "SELECT * FROM assignments WHERE class_id = ?"
            f" ORDER BY done_at IS NOT NULL, due_date IS NULL, due_date, {school.BURDEN_SQL}, id",
            (c["id"],),
        ).fetchall()
        out.append({"row": c, "assignments": [school.decorate(r) for r in rows]})
    return out


def _areas(conn: sqlite3.Connection, workspace_id: int) -> tuple[list[dict], list]:
    visible, hidden = [], []
    for a in conn.execute(
        "SELECT * FROM areas WHERE workspace_id = ? AND archived_at IS NULL"
        " ORDER BY position, id",
        (workspace_id,),
    ):
        if a["hidden"]:
            hidden.append(a)
            continue
        tasks = conn.execute(
            "SELECT * FROM tasks WHERE area_id = ? AND done_at IS NULL"
            f" ORDER BY {TASK_ORDER}",
            (a["id"],),
        ).fetchall()
        visible.append({"row": a, "tasks": [_decorate_task(t) for t in tasks]})
    return visible, hidden


def work_ctx(request: Request, conn: sqlite3.Connection) -> dict:
    sections = []
    for ws in workspaces.active(conn):
        section = {
            "ws": ws,
            "tasks": [
                _decorate_task(t)
                for t in conn.execute(
                    "SELECT * FROM tasks WHERE workspace_id = ? AND area_id IS NULL"
                    f" AND done_at IS NULL ORDER BY {TASK_ORDER}",
                    (ws["id"],),
                )
            ],
        }
        section["done_tasks"] = conn.execute(
            "SELECT * FROM tasks WHERE workspace_id = ? AND done_at IS NOT NULL"
            " ORDER BY done_at DESC LIMIT 15",
            (ws["id"],),
        ).fetchall()
        if ws["kind"] == "job":
            section["areas"], section["hidden_areas"] = _areas(conn, ws["id"])
        if ws["kind"] == "school":
            section["classes"] = _classes(conn, ws["id"])
            section["hidden_classes"] = conn.execute(
                "SELECT * FROM classes WHERE workspace_id = ? AND archived_at IS NULL"
                " AND hidden = 1 ORDER BY name",
                (ws["id"],),
            ).fetchall()
            section["due_soon"] = school.open_assignments(conn, workspace_id=ws["id"])
        if ws["has_meetings"] and ws["kind"] != "growth":
            section["meetings"] = _agendas(conn, ws["id"])
        sections.append(section)
    return {
        "sections": sections,
        "effort_stops": EFFORT_STOPS,
        "effort_default": EFFORT_DEFAULT,
        "dread_choices": DREAD_CHOICES,
        "canvas_enabled": request.app.state.settings.canvas_enabled,
        "capture_token_set": bool(request.app.state.settings.capture_token),
    }


@router.get("")
def work_page(request: Request, conn=Depends(get_conn)):
    return render(request, "work/index.html", work_ctx(request, conn))


def _body(request: Request, conn: sqlite3.Connection, **extra):
    ctx = work_ctx(request, conn)
    ctx.update(extra)
    return render(request, "work/_body.html", ctx)


@router.post("/workspaces")
def add_workspace(
    request: Request, conn=Depends(get_conn), name: str = Form(...), kind: str = Form("job")
):
    name = name.strip()
    if name:
        with conn:
            workspaces.create(conn, name, kind)
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/rename")
def rename_workspace(
    request: Request, ws_id: int, conn=Depends(get_conn), name: str = Form(...)
):
    if name.strip():
        with conn:
            conn.execute(
                "UPDATE workspaces SET name = ? WHERE id = ?", (name.strip(), ws_id)
            )
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/delete")
def delete_workspace(request: Request, ws_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM tasks WHERE workspace_id = ?", (ws_id,))
        conn.execute("DELETE FROM workspaces WHERE id = ?", (ws_id,))
    return _body(request, conn)


@router.post("/areas/{area_id}/delete")
def delete_area(request: Request, area_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM tasks WHERE area_id = ?", (area_id,))
        conn.execute("DELETE FROM areas WHERE id = ?", (area_id,))
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/archive")
def archive_workspace(request: Request, ws_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE workspaces SET archived_at = datetime('now') WHERE id = ?", (ws_id,)
        )
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/tasks")
def add_workspace_task(
    request: Request,
    ws_id: int,
    conn=Depends(get_conn),
    title: str = Form(...),
    dest: str = Form(""),
    due_date: str = Form(""),
    due_kind: str = Form("on"),
    notes: str = Form(""),
    effort_minutes: int = Form(60),
    dread: int = Form(2),
):
    title = title.strip()
    if due_kind not in ("on", "about", "soon"):
        due_kind = "on"
    from ..services.dates import parse_when

    due = parse_when(due_date)
    if due_kind == "soon":
        due = None
    burden = compute_burden(effort_minutes, dread)
    if title and (due or due_kind == "soon"):
        if dest.startswith("c:"):
            # School: sorting into a class makes it an assignment.
            with conn:
                conn.execute(
                    "INSERT INTO assignments (class_id, title, due_date, burden)"
                    " VALUES (?, ?, ?, ?)",
                    (int(dest[2:]), title, due, burden),
                )
        else:
            area_id = int(dest[2:]) if dest.startswith("a:") else None
            pos = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tasks"
                " WHERE horizon = 'inbox'"
            ).fetchone()["p"]
            with conn:
                conn.execute(
                    "INSERT INTO tasks (title, notes, horizon, workspace_id, area_id,"
                    " position, due_date, due_kind, burden, effort_minutes, dread)"
                    " VALUES (?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, notes.strip(), ws_id, area_id, pos, due, due_kind,
                     burden, effort_minutes, dread),
                )
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/areas")
def add_area(request: Request, ws_id: int, conn=Depends(get_conn), name: str = Form(...)):
    name = name.strip()
    if name:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM areas WHERE workspace_id = ?",
            (ws_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO areas (workspace_id, name, position) VALUES (?, ?, ?)",
                (ws_id, name, pos),
            )
    return _body(request, conn)


@router.post("/areas/{area_id}/visibility")
def toggle_area(request: Request, area_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("UPDATE areas SET hidden = 1 - hidden WHERE id = ?", (area_id,))
    return _body(request, conn)


@router.post("/areas/{area_id}/archive")
def archive_area(request: Request, area_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE areas SET archived_at = datetime('now') WHERE id = ?", (area_id,)
        )
    return _body(request, conn)


@router.post("/classes/{class_id}/visibility")
def toggle_class(request: Request, class_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("UPDATE classes SET hidden = 1 - hidden WHERE id = ?", (class_id,))
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/monologue")
def save_monologue(
    request: Request, ws_id: int, conn=Depends(get_conn), monologue: str = Form("")
):
    with conn:
        conn.execute(
            "UPDATE workspaces SET monologue = ? WHERE id = ?", (monologue, ws_id)
        )
    from fastapi.responses import Response

    return Response(status_code=204)


@router.post("/workspaces/{ws_id}/classes")
def add_class(request: Request, ws_id: int, conn=Depends(get_conn), name: str = Form(...)):
    name = name.strip()
    if name:
        with conn:
            conn.execute(
                "INSERT INTO classes (name, workspace_id) VALUES (?, ?)", (name, ws_id)
            )
    return _body(request, conn)


@router.post("/classes/{class_id}/archive")
def archive_class(request: Request, class_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE classes SET archived_at = datetime('now') WHERE id = ?", (class_id,)
        )
    return _body(request, conn)


@router.post("/classes/{class_id}/assignments")
def add_assignment(
    request: Request,
    class_id: int,
    conn=Depends(get_conn),
    title: str = Form(...),
    due_date: str = Form(""),
    burden: str = Form("m"),
):
    title = title.strip()
    if burden not in ("s", "m", "l"):
        burden = "m"
    try:
        due_date = _date.fromisoformat(due_date.strip()).isoformat()
    except (ValueError, AttributeError):
        due_date = ""
    if title:
        with conn:
            conn.execute(
                "INSERT INTO assignments (class_id, title, due_date, burden) VALUES (?, ?, ?, ?)",
                (class_id, title, due_date or None, burden),
            )
    return _body(request, conn)


@router.post("/assignments/{assignment_id}/done")
def assignment_done(
    request: Request, assignment_id: int, conn=Depends(get_conn), frame: str = Form("work")
):
    with conn:
        conn.execute(
            "UPDATE assignments SET done_at = datetime('now') WHERE id = ?", (assignment_id,)
        )
    if frame == "home":
        from .home import build_home_ctx

        return render(
            request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings)
        )
    return _body(request, conn)


@router.post("/assignments/{assignment_id}/undone")
def assignment_undone(request: Request, assignment_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("UPDATE assignments SET done_at = NULL WHERE id = ?", (assignment_id,))
    return _body(request, conn)


@router.post("/assignments/{assignment_id}/burden")
def assignment_burden(
    request: Request, assignment_id: int, conn=Depends(get_conn), burden: str = Form("m")
):
    if burden in ("s", "m", "l"):
        with conn:
            conn.execute(
                "UPDATE assignments SET burden = ? WHERE id = ?", (burden, assignment_id)
            )
    return _body(request, conn)


@router.post("/assignments/{assignment_id}/notes")
def assignment_notes(
    request: Request, assignment_id: int, conn=Depends(get_conn), notes: str = Form("")
):
    from fastapi.responses import Response

    with conn:
        conn.execute(
            "UPDATE assignments SET notes = ? WHERE id = ?", (notes, assignment_id)
        )
    return Response(status_code=204)


@router.post("/assignments/{assignment_id}/delete")
def assignment_delete(request: Request, assignment_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/feature")
def toggle_feature(
    request: Request, ws_id: int, conn=Depends(get_conn), feature: str = Form(...)
):
    col = {"meetings": "has_meetings", "monologue": "has_monologue"}.get(feature)
    if col:
        with conn:
            conn.execute(
                f"UPDATE workspaces SET {col} = 1 - {col} WHERE id = ?", (ws_id,)
            )
    return _body(request, conn)


@router.post("/workspaces/{ws_id}/agendas")
def add_agenda(
    request: Request,
    ws_id: int,
    conn=Depends(get_conn),
    name: str = Form(...),
    when: str = Form(""),
):
    from ..services.dates import parse_when

    name = name.strip()
    if name:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM agendas WHERE workspace_id = ?",
            (ws_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO agendas (workspace_id, name, position, when_at)"
                " VALUES (?, ?, ?, ?)",
                (ws_id, name, pos, parse_when(when)),
            )
    return _body(request, conn)


@router.post("/agendas/{agenda_id}/when")
def set_agenda_when(
    request: Request, agenda_id: int, conn=Depends(get_conn), when: str = Form("")
):
    from ..services.dates import parse_when

    with conn:
        conn.execute(
            "UPDATE agendas SET when_at = ? WHERE id = ?", (parse_when(when), agenda_id)
        )
    return _body(request, conn)


@router.post("/agendas/{agenda_id}/items")
def add_agenda_item(
    request: Request, agenda_id: int, conn=Depends(get_conn), text: str = Form(...)
):
    text = text.strip()
    if text:
        with conn:
            conn.execute(
                "INSERT INTO agenda_items (agenda_id, text) VALUES (?, ?)", (agenda_id, text)
            )
    return _body(request, conn)


@router.post("/agenda-items/{item_id}/done")
def agenda_item_done(request: Request, item_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE agenda_items SET done_at = datetime('now') WHERE id = ?", (item_id,)
        )
    return _body(request, conn)


@router.post("/agendas/{agenda_id}/archive")
def archive_agenda(request: Request, agenda_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE agendas SET archived_at = datetime('now') WHERE id = ?", (agenda_id,)
        )
    return _body(request, conn)


@router.post("/canvas/sync")
def canvas_sync(request: Request, conn=Depends(get_conn)):
    settings = request.app.state.settings
    if not settings.canvas_enabled:
        return _body(request, conn, canvas_result="canvas is not configured.")
    ws = workspaces.first_of_kind(conn, "school")
    if ws is None:
        with conn:
            ws_id = workspaces.create(conn, "school", "school")
    else:
        ws_id = ws["id"]
    result = canvas.sync(conn, settings.canvas_base_url, settings.canvas_token, workspace_id=ws_id)
    if "error" in result:
        msg = result["error"]
    else:
        msg = (
            f"synced: {result['new']} new, {result['updated']} updated"
            f"{', ' + str(result['classes']) + ' new classes' if result['classes'] else ''}."
        )
    return _body(request, conn, canvas_result=msg)

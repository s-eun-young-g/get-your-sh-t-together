"""Home page, quick capture, and the optional login gate.

Home is the manifesto, the frog, and one gamified tile per tab: each tile is
a click-through summary with a progress read, not another list to manage.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import auth
from ..deps import get_conn, render

router = APIRouter()


def _tiles(conn: sqlite3.Connection, prefs: dict) -> list[dict]:
    from . import now as now_routes
    from ..services import impulses, learnmeta, lifeops
    from ..services import routines as routines_svc

    on = lambda key: prefs.get(key, "1") == "1"  # noqa: E731
    tiles = []

    inbox = now_routes.inbox_tasks(conn)
    tiles.append(
        {
            "href": "/now/sort",
            "label": "inbox",
            "big": f"{len(inbox)} to sort" if inbox else "clear",
            "pct": None if inbox else 100,
            "sub": "latest: " + inbox[-1]["title"] if inbox else "nothing waiting",
        }
    )

    due = conn.execute(
        "SELECT a.title, a.due_date FROM assignments a"
        " JOIN classes c ON c.id = a.class_id"
        " WHERE a.done_at IS NULL AND c.archived_at IS NULL AND a.due_date IS NOT NULL"
        " ORDER BY a.due_date LIMIT 1"
    ).fetchone()
    open_work = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks t JOIN workspaces w ON w.id = t.workspace_id"
        " WHERE t.done_at IS NULL AND w.archived_at IS NULL"
    ).fetchone()["n"]
    work_sub = f"up next: {due['title']}" if due else "nothing active"
    tiles.append(
        {
            "href": "/work",
            "label": "work",
            "big": f"{open_work} open",
            "pct": None,
            "sub": work_sub,
        }
    )

    life_on = any(
        on(k)
        for k in (
            "mod_routines", "mod_finance", "mod_appointments",
            "mod_meals", "mod_evenings", "mod_packing",
        )
    )
    if life_on:
        due_names = []
        if on("mod_appointments"):
            due_names += [a["title"] for a in lifeops.appointments_today(conn)]
        if on("mod_finance"):
            due_names += [b["name"] for b in lifeops.bills_due(conn)]
            due_names += [b["name"] for b in lifeops.renewals_due(conn)]
        if on("mod_routines"):
            due_names += [r["name"] for r in routines_svc.due(conn)]
        if due_names:
            life_sub = ", ".join(due_names[:3])
        else:
            nxt = lifeops.next_upcoming(
                conn, bills=on("mod_finance"), appts=on("mod_appointments")
            )
            if nxt is None and on("mod_routines"):
                upcoming = [
                    (r["days"], r["name"])
                    for r in routines_svc.list_active(conn)
                    if r["days"] > 0
                ]
                nxt = min(upcoming) if upcoming else None
            life_sub = (
                f"up next: {nxt[1]}, in {nxt[0]}d" if nxt else "nothing active"
            )
        tiles.append(
            {
                "href": "/life",
                "label": "life",
                "big": "all clear" if not due_names else f"{len(due_names)} due",
                "pct": 100 if not due_names else None,
                "sub": life_sub,
            }
        )

    boards = conn.execute(
        "SELECT COUNT(*) AS n FROM boards WHERE archived_at IS NULL"
    ).fetchone()["n"]
    latest = conn.execute(
        "SELECT name FROM boards WHERE archived_at IS NULL ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    tiles.append(
        {
            "href": "/model",
            "label": "model",
            "big": f"{boards} board{'' if boards == 1 else 's'}",
            "pct": None,
            "sub": latest["name"] if latest else "nothing active",
        }
    )

    prog = conn.execute(
        "SELECT COUNT(*) AS total, SUM(done_at IS NOT NULL) AS done FROM nodes"
    ).fetchone()
    total_nodes, done_nodes = prog["total"] or 0, prog["done"] or 0
    streak = learnmeta.streak(conn)
    from ..services.frontier import frontier

    learn_sub = "nothing active"
    for t in conn.execute("SELECT id FROM tracks ORDER BY position, name"):
        rows = frontier(conn, t["id"], limit=1)
        if rows:
            learn_sub = f"up next: {rows[0]['title']}"
            break
    focus = conn.execute(
        "SELECT title FROM nodes WHERE learning_now = 1 AND done_at IS NULL"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    tiles.append(
        {
            "href": "/learn",
            "label": "learn",
            "big": f"{streak} day streak" if streak else f"{done_nodes} learned",
            "pct": round(100 * done_nodes / total_nodes) if total_nodes else 0,
            "sub": f"learning now: {focus['title']}" if focus else learn_sub,
        }
    )

    if on("mod_pause"):
        s = impulses.stats(conn)
        parked = impulses.waiting(conn)
        ready = sum(1 for p in parked if p["ready"])
        tiles.append(
            {
                "href": "/pause",
                "label": "pause",
                "big": f"{s['let_go']} let go",
                "pct": None,
                "sub": (
                    f"{ready} ready to revisit"
                    if ready
                    else f"{len(parked)} parked" if parked else "nothing active"
                ),
            }
        )
    return tiles


def _today_digest(conn: sqlite3.Connection, prefs: dict) -> list[dict]:
    """Today assembles itself: the next-up thing from each tab, plus anything
    deliberately pinned, each with a tick and nothing else."""
    from . import now as now_routes
    from . import work as work_routes
    from ..services import learnmeta, lifeops, school, workspaces
    from ..services import routines as routines_svc

    on = lambda key: prefs.get(key, "1") == "1"  # noqa: E731
    items = []

    for t in now_routes.open_tasks(conn, "today"):
        d = work_routes._decorate_task(t)
        items.append({
            "title": t["title"], "chip": t["ws_name"] or "pinned", "hue": "now",
            "meta": d["due_label"], "post": f"/now/tasks/{t['id']}/done",
        })

    for ws in workspaces.active(conn):
        if ws["kind"] == "school":
            due = school.open_assignments(conn, workspace_id=ws["id"])
            if due:
                a = due[0]
                items.append({
                    "title": a["title"], "chip": ws["name"], "hue": "work",
                    "meta": a["due_label"], "post": f"/work/assignments/{a['id']}/done",
                })
        else:
            t = conn.execute(
                "SELECT * FROM tasks WHERE workspace_id = ? AND done_at IS NULL"
                " AND nuisance = 0 AND horizon <> 'today'"
                f" ORDER BY {work_routes.TASK_ORDER} LIMIT 1",
                (ws["id"],),
            ).fetchone()
            if t:
                d = work_routes._decorate_task(t)
                items.append({
                    "title": t["title"], "chip": ws["name"], "hue": "work",
                    "meta": d["due_label"], "post": f"/now/tasks/{t['id']}/done",
                })

    head = None
    for tr in conn.execute("SELECT * FROM tracks ORDER BY position, name"):
        h = learnmeta.headliner(conn, tr["id"])
        if h and h[0] == "learning now":
            head = h[1]
            break
        if h and head is None and h[1]["done_at"] is None:
            head = h[1]
    if head is not None and head["done_at"] is None:
        items.append({
            "title": head["title"], "chip": "learn", "hue": "learn",
            "meta": "", "post": f"/learn/nodes/{head['id']}/done",
        })

    if on("mod_routines"):
        for r in routines_svc.due(conn, limit=2):
            items.append({
                "title": r["name"], "chip": "life", "hue": "life",
                "meta": f"every {r['every_days']}d", "post": f"/life/routines/{r['id']}/done",
            })
    if on("mod_finance"):
        for b in lifeops.bills_due(conn)[:2]:
            items.append({
                "title": b["name"], "chip": "life", "hue": "life",
                "meta": b["due_label"], "post": f"/life/bills/{b['id']}/paid",
            })
    if on("mod_appointments"):
        for a in lifeops.appointments_today(conn):
            items.append({
                "title": a["title"], "chip": "life", "hue": "life",
                "meta": "today", "post": f"/life/appointments/{a['id']}/done",
            })
    return items


def build_home_ctx(
    conn: sqlite3.Connection, prefs: dict | None = None, settings=None
) -> dict:
    from . import now as now_routes
    from ..services import gcal, workspaces

    prefs = prefs or {}
    inbox = now_routes.inbox_tasks(conn)
    stale_count = conn.execute(
        "SELECT COUNT(*) AS n FROM tasks WHERE horizon = 'today' AND nuisance = 0"
        f" AND done_at IS NULL AND updated_at <= datetime('now', '-{now_routes.STALE_DAYS} days')"
    ).fetchone()["n"]
    return {
        "gcal_today": gcal.today(settings) if settings else [],
        "today_items": _today_digest(conn, prefs),
        "inbox": inbox,
        "nuisances": now_routes.nuisance_pen(conn),
        "workspaces": workspaces.active(conn),
        "stale_days": now_routes.STALE_DAYS,
        "stale_count": stale_count,
        "tiles": _tiles(conn, prefs),
        "momentum": now_routes.momentum(conn),
        "inbox_count": len(inbox),
        "manifesto": prefs.get("manifesto", ""),
    }


@router.get("/")
def home(request: Request, conn=Depends(get_conn)):
    return render(request, "home.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings))


@router.post("/capture")
def capture(
    request: Request,
    conn=Depends(get_conn),
    title: str = Form(""),
    nuisance: int = Form(0),
    from_home: int = Form(0),
):
    title = title.strip()
    if title:
        with conn:
            conn.execute(
                "INSERT INTO tasks (title, horizon, nuisance) VALUES (?, 'inbox', ?)",
                (title, 1 if nuisance else 0),
            )
    from . import now as now_routes

    count = len(now_routes.inbox_tasks(conn))
    ctx = {"captured": bool(title), "inbox_count": count}
    if from_home:
        # Refresh the merged board below the capture bar in the same swap.
        ctx.update(build_home_ctx(conn, request.app.state.prefs, request.app.state.settings))
        ctx["capture_from_home"] = True
        return render(request, "_capture_home.html", ctx)
    return render(request, "_capture.html", ctx)


@router.post("/manifesto")
def set_manifesto(request: Request, conn=Depends(get_conn), manifesto: str = Form("")):
    from ..services import prefs as prefs_svc

    prefs_svc.save(conn, {"manifesto": manifesto.strip()})
    request.app.state.prefs.clear()
    request.app.state.prefs.update(prefs_svc.load(conn))
    return render(request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings))


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", {"error": ""})


@router.post("/login")
def login(request: Request, password: str = Form("")):
    settings = request.app.state.settings
    if settings.auth_enabled and auth.check_password(settings.password, password):
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(
            auth.COOKIE_NAME,
            auth.make_token(settings.secret),
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 90,
        )
        return resp
    return render(request, "login.html", {"error": "that is not the password."}, 401)


@router.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp

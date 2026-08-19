"""LIFE hub: evening time-block plans plus packing shortcuts."""

from __future__ import annotations

import sqlite3
from datetime import date as _date
from datetime import datetime, timedelta


def _valid_date(value: str) -> str | None:
    from ..services.dates import parse_when

    return parse_when(value)

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from ..deps import get_conn, render, reindex
from ..services import lifeops
from ..services import prefs as prefs_svc
from ..services import routines as routines_svc

router = APIRouter(prefix="/life")

# Stop lists for the shared sliders: (value, label) pairs.
CADENCE_STOPS = [
    (1, "daily"), (2, "every 2 days"), (3, "every 3 days"), (7, "weekly"),
    (10, "every 10 days"), (14, "every 2 weeks"), (21, "every 3 weeks"),
    (30, "monthly"), (60, "every 2 months"), (90, "quarterly"),
    (180, "every 6 months"), (365, "yearly"),
]
CADENCE_DEFAULT = 3  # weekly

MINUTE_STOPS = [
    (5, "5m"), (10, "10m"), (15, "15m"), (20, "20m"), (30, "30m"), (45, "45m"),
    (60, "1h"), (90, "1h 30m"), (120, "2h"), (180, "3h"),
]
MINUTE_DEFAULT = 4  # 30m

START_STOPS = [("", "no start time")] + [
    (f"{h:02d}:{m:02d}", f"{h}:{m:02d}")
    for h in range(16, 24)
    for m in (0, 30)
]

BILL_CADENCES = [
    (0, "one time"), (1, "monthly"), (3, "quarterly"),
    (6, "every 6 months"), (12, "yearly"),
]

BILL_MODES = list(lifeops.MODE_LABELS.items())

LIFE_SECTIONS = {
    "mod_routines": ("routines", "recurring upkeep that resurfaces when due"),
    "mod_finance": ("financials", "recurring charges plus card strategy"),
    "mod_appointments": ("appointments", "needs-booking versus booked"),
    "mod_meals": ("grocery lists", "reusable lists, fresh checklist per run"),
    "mod_evenings": ("evening plans", "loose after-work lists with time blocks"),
    "mod_packing": ("packing", "reusable templates, fresh checklist per trip"),
}


@router.post("/sections")
def toggle_section(
    request: Request, conn=Depends(get_conn), key: str = Form(...), on: int = Form(1)
):
    if key in LIFE_SECTIONS:
        prefs_svc.save(conn, {key: "1" if on else "0"})
        request.app.state.prefs.clear()
        request.app.state.prefs.update(prefs_svc.load(conn))
    return _body(request, conn)


def _timeline(plan: sqlite3.Row, items: list[sqlite3.Row]) -> list[dict]:
    """Attach a clock time to each item when the plan has a start time."""
    out = []
    cursor = None
    if plan["start_time"]:
        try:
            h, m = plan["start_time"].split(":")
            cursor = datetime(2000, 1, 1, int(h), int(m))
        except ValueError:
            cursor = None
    for r in items:
        d = dict(r)
        d["at"] = f"{cursor.hour}:{cursor.minute:02d}" if cursor else None
        if cursor:
            cursor += timedelta(minutes=r["minutes"])
        out.append(d)
    return out


def life_ctx(
    conn: sqlite3.Connection, plan_id: int | None = None, settings=None
) -> dict:
    from ..services import gcal

    plans = conn.execute(
        "SELECT * FROM evening_plans WHERE archived_at IS NULL ORDER BY id DESC"
    ).fetchall()
    plan = None
    if plan_id is not None:
        plan = next((p for p in plans if p["id"] == plan_id), None)
    if plan is None and plans:
        plan = plans[0]
    items = []
    if plan:
        rows = conn.execute(
            "SELECT * FROM evening_items WHERE plan_id = ? ORDER BY position, id",
            (plan["id"],),
        ).fetchall()
        items = _timeline(plan, rows)
    start_index = 0
    if plan and plan["start_time"]:
        start_index = next(
            (i for i, (v, _) in enumerate(START_STOPS) if v == plan["start_time"]), 0
        )
    return {
        "cadence_stops": CADENCE_STOPS,
        "cadence_default": CADENCE_DEFAULT,
        "minute_stops": MINUTE_STOPS,
        "minute_default": MINUTE_DEFAULT,
        "start_stops": START_STOPS,
        "start_index": start_index,
        "bill_cadences": BILL_CADENCES,
        "plan": plan,
        "items": items,
        "total_minutes": sum(i["minutes"] for i in items if not i["done"]),
        "other_plans": [p for p in plans if not plan or p["id"] != plan["id"]],
        "trips": conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM trip_items i"
            "  WHERE i.trip_id = t.id AND i.checked = 0) AS unchecked"
            " FROM trips t WHERE status = 'active' ORDER BY created_at DESC"
        ).fetchall(),
        "sections": LIFE_SECTIONS,
        "routines": routines_svc.list_active(conn),
        "unused_presets": routines_svc.unused_presets(conn),
        "bills": lifeops.active_bills(conn),
        "bill_groups": lifeops.bill_groups(conn),
        "monthly_load_label": (
            lifeops.money_label(load)
            if (load := lifeops.monthly_load(lifeops.active_bills(conn)))
            else ""
        ),
        "bill_modes": BILL_MODES,
        "cards": conn.execute(
            "SELECT * FROM credit_cards WHERE archived_at IS NULL ORDER BY position, id"
        ).fetchall(),
        "appointments": lifeops.open_appointments(conn),
        "gcal_week": gcal.events(settings) if settings else [],
        "grocery_runs": conn.execute(
            "SELECT t.*, (SELECT COUNT(*) FROM trip_items i"
            "  WHERE i.trip_id = t.id AND i.checked = 0) AS unchecked"
            " FROM trips t WHERE status = 'active' AND kind = 'grocery'"
            " ORDER BY created_at DESC"
        ).fetchall(),
    }


@router.get("")
def life_page(request: Request, conn=Depends(get_conn)):
    return render(
        request, "life/index.html", life_ctx(conn, settings=request.app.state.settings)
    )


@router.get("/plans/{plan_id}")
def plan_page(request: Request, plan_id: int, conn=Depends(get_conn)):
    return render(
        request,
        "life/index.html",
        life_ctx(conn, plan_id, settings=request.app.state.settings),
    )


def _body(request: Request, conn: sqlite3.Connection, plan_id: int | None = None):
    return render(
        request,
        "life/_body.html",
        life_ctx(conn, plan_id, settings=request.app.state.settings),
    )


@router.post("/plans")
def create_plan(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(""),
    start_time: str = Form(""),
):
    name = name.strip() or "Tonight"
    with conn:
        cur = conn.execute(
            "INSERT INTO evening_plans (name, start_time) VALUES (?, ?)",
            (name, start_time or None),
        )
    return _body(request, conn, cur.lastrowid)


@router.post("/plans/{plan_id}/start")
def set_start(
    request: Request, plan_id: int, conn=Depends(get_conn), start_time: str = Form("")
):
    with conn:
        conn.execute(
            "UPDATE evening_plans SET start_time = ? WHERE id = ?",
            (start_time or None, plan_id),
        )
    return _body(request, conn, plan_id)


@router.post("/plans/{plan_id}/archive")
def archive_plan(request: Request, plan_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE evening_plans SET archived_at = datetime('now') WHERE id = ?", (plan_id,)
        )
    return _body(request, conn)


@router.post("/plans/{plan_id}/items")
def add_item(
    request: Request,
    plan_id: int,
    conn=Depends(get_conn),
    title: str = Form(...),
    minutes: int = Form(30),
):
    title = title.strip()
    if title:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM evening_items WHERE plan_id = ?",
            (plan_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO evening_items (plan_id, title, minutes, position) VALUES (?, ?, ?, ?)",
                (plan_id, title, max(5, min(minutes, 480)), pos),
            )
    return _body(request, conn, plan_id)


def _item_plan(conn: sqlite3.Connection, item_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM evening_items WHERE id = ?", (item_id,)
    ).fetchone()


@router.post("/items/{item_id}/toggle")
def toggle_item(request: Request, item_id: int, conn=Depends(get_conn)):
    item = _item_plan(conn, item_id)
    with conn:
        conn.execute(
            "UPDATE evening_items SET done = ? WHERE id = ?",
            (0 if item["done"] else 1, item_id),
        )
    return _body(request, conn, item["plan_id"])


@router.post("/items/{item_id}/delete")
def delete_item(request: Request, item_id: int, conn=Depends(get_conn)):
    item = _item_plan(conn, item_id)
    with conn:
        conn.execute("DELETE FROM evening_items WHERE id = ?", (item_id,))
        reindex(conn, "evening_items", "plan_id", item["plan_id"])
    return _body(request, conn, item["plan_id"])


def _parse_amount(raw: str) -> float | None:
    raw = raw.strip().lstrip("$").replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


@router.post("/bills")
def add_bill(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(...),
    next_due: str = Form(...),
    every_months: int = Form(0),
    amount: str = Form(""),
    mode: str = Form("manual"),
):
    name = name.strip()
    next_due = _valid_date(next_due)
    if mode not in {m for m, _ in BILL_MODES}:
        mode = "manual"
    if name and next_due:
        with conn:
            conn.execute(
                "INSERT INTO bills (name, next_due, every_months, amount, mode)"
                " VALUES (?, ?, ?, ?, ?)",
                (name, next_due, every_months or None, _parse_amount(amount), mode),
            )
    return _body(request, conn)


@router.post("/bills/{bill_id}/paid")
def bill_paid(
    request: Request, bill_id: int, conn=Depends(get_conn), frame: str = Form("life")
):
    lifeops.mark_bill_paid(conn, bill_id)
    if frame == "home":
        from .home import build_home_ctx

        return render(
            request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings)
        )
    return _body(request, conn)


@router.post("/bills/{bill_id}/mode")
def bill_mode(
    request: Request, bill_id: int, conn=Depends(get_conn), mode: str = Form(...)
):
    if mode in {m for m, _ in BILL_MODES}:
        with conn:
            conn.execute("UPDATE bills SET mode = ? WHERE id = ?", (mode, bill_id))
    return _body(request, conn)


@router.post("/bills/{bill_id}/keep")
def bill_keep(request: Request, bill_id: int, conn=Depends(get_conn)):
    # Keeping a renewal just moves the decision to the next cycle.
    lifeops.mark_bill_paid(conn, bill_id)
    return _body(request, conn)


@router.post("/bills/{bill_id}/cancel")
def bill_cancel(request: Request, bill_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE bills SET archived_at = datetime('now') WHERE id = ?", (bill_id,)
        )
    return _body(request, conn)


@router.post("/cards")
def add_card(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(...),
    use_for: str = Form(""),
    wins: str = Form(""),
):
    name = name.strip()
    if name:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM credit_cards"
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO credit_cards (name, use_for, wins, position) VALUES (?, ?, ?, ?)",
                (name, use_for.strip(), wins.strip(), pos),
            )
    return _body(request, conn)


@router.post("/cards/{card_id}/delete")
def delete_card(request: Request, card_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM credit_cards WHERE id = ?", (card_id,))
    return _body(request, conn)


@router.post("/bills/{bill_id}/delete")
def delete_bill(request: Request, bill_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
    return _body(request, conn)


@router.post("/appointments")
def add_appointment(request: Request, conn=Depends(get_conn), title: str = Form(...)):
    title = title.strip()
    if title:
        with conn:
            conn.execute("INSERT INTO appointments (title) VALUES (?)", (title,))
    return _body(request, conn)


@router.post("/appointments/{appt_id}/book")
def book_appointment(
    request: Request, appt_id: int, conn=Depends(get_conn), when_at: str = Form(...)
):
    when_at = _valid_date(when_at)
    if when_at:
        with conn:
            conn.execute(
                "UPDATE appointments SET status = 'booked', when_at = ? WHERE id = ?",
                (when_at, appt_id),
            )
    return _body(request, conn)


@router.post("/appointments/{appt_id}/done")
def appointment_done(
    request: Request, appt_id: int, conn=Depends(get_conn), frame: str = Form("life")
):
    with conn:
        conn.execute(
            "UPDATE appointments SET resolved_at = datetime('now') WHERE id = ?", (appt_id,)
        )
    if frame == "home":
        from .home import build_home_ctx

        return render(
            request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings)
        )
    return _body(request, conn)


@router.post("/appointments/{appt_id}/delete")
def delete_appointment(request: Request, appt_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM appointments WHERE id = ?", (appt_id,))
    return _body(request, conn)


@router.post("/routines")
def add_routine(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(...),
    every_days: int = Form(7),
):
    name = name.strip()
    if name:
        with conn:
            conn.execute(
                "INSERT INTO routines (name, every_days) VALUES (?, ?)",
                (name, max(1, min(every_days, 730))),
            )
    return _body(request, conn)


@router.post("/routines/preset")
def add_routine_preset(request: Request, conn=Depends(get_conn), key: str = Form(...)):
    routines_svc.add_preset(conn, key)
    return _body(request, conn)


@router.post("/routines/{routine_id}/done")
def routine_done(
    request: Request, routine_id: int, conn=Depends(get_conn), frame: str = Form("life")
):
    routines_svc.mark_done(conn, routine_id)
    if frame == "home":
        from .home import build_home_ctx

        return render(request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings))
    return _body(request, conn)


@router.post("/routines/{routine_id}/pause")
def routine_pause(request: Request, routine_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("UPDATE routines SET active = 0 WHERE id = ?", (routine_id,))
    return _body(request, conn)


@router.post("/routines/{routine_id}/delete")
def routine_delete(request: Request, routine_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM routines WHERE id = ?", (routine_id,))
    return _body(request, conn)


@router.post("/items/{item_id}/move")
def move_item(
    request: Request, item_id: int, conn=Depends(get_conn), direction: str = Form("up")
):
    item = _item_plan(conn, item_id)
    with conn:
        reindex(conn, "evening_items", "plan_id", item["plan_id"])
        item = _item_plan(conn, item_id)
        swap_pos = item["position"] + (-1 if direction == "up" else 1)
        other = conn.execute(
            "SELECT id FROM evening_items WHERE plan_id = ? AND position = ?",
            (item["plan_id"], swap_pos),
        ).fetchone()
        if other:
            conn.execute(
                "UPDATE evening_items SET position = ? WHERE id = ?",
                (swap_pos, item_id),
            )
            conn.execute(
                "UPDATE evening_items SET position = ? WHERE id = ?",
                (item["position"], other["id"]),
            )
    return _body(request, conn, item["plan_id"])

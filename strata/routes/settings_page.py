"""Personalization settings: name and life-section toggles.

Work areas are managed on the work page itself (add one per job or school),
so settings only carries what has no better home.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from ..deps import get_conn, render
from ..services import prefs as prefs_svc

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request):
    return render(request, "settings.html", {"saved": False})


@router.post("/settings")
def save_settings(
    request: Request,
    conn=Depends(get_conn),
    name: str = Form(""),
    manifesto: str = Form(""),
    mod_evenings: str = Form("0"),
    mod_packing: str = Form("0"),
    mod_routines: str = Form("0"),
    mod_finance: str = Form("0"),
    mod_appointments: str = Form("0"),
    mod_meals: str = Form("0"),
    mod_pause: str = Form("0"),
    mod_rescue: str = Form("0"),
):
    def flag(v: str) -> str:
        return "1" if v == "1" else "0"

    prefs_svc.save(
        conn,
        {
            "name": name.strip(),
            "manifesto": manifesto.strip(),
            "mod_evenings": flag(mod_evenings),
            "mod_packing": flag(mod_packing),
            "mod_routines": flag(mod_routines),
            "mod_finance": flag(mod_finance),
            "mod_appointments": flag(mod_appointments),
            "mod_meals": flag(mod_meals),
            "mod_pause": flag(mod_pause),
            "mod_rescue": flag(mod_rescue),
        },
    )
    # Mutate the shared dict in place so templates pick it up immediately.
    request.app.state.prefs.clear()
    request.app.state.prefs.update(prefs_svc.load(conn))
    return RedirectResponse("/settings?saved=1", status_code=303)

"""Machine capture endpoint for Slack workflows, Granola/Zapier, Shortcuts, curl.

Token auth, separate from the cookie gate. Nothing is enabled unless
STRATA_CAPTURE_TOKEN is set.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from ..deps import get_conn

router = APIRouter(prefix="/api")


@router.post("/capture")
async def api_capture(request: Request, conn=Depends(get_conn)):
    settings = request.app.state.settings
    if not settings.capture_token:
        return JSONResponse(
            {"error": "capture is disabled; set STRATA_CAPTURE_TOKEN"}, status_code=503
        )
    auth_header = request.headers.get("authorization", "")
    if auth_header != f"Bearer {settings.capture_token}":
        return JSONResponse({"error": "bad token"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "body must be JSON"}, status_code=400)

    title = str(body.get("title", "")).strip()
    if not title:
        return JSONResponse({"error": "title is required"}, status_code=400)
    source = str(body.get("source", "api")).strip()[:32] or "api"
    nuisance = 1 if body.get("nuisance") else 0

    # Workspace by name ("workspace": "Sedona"), or legacy "context": "job"
    # meaning the first job-kind workspace. Unknown names are ignored.
    from ..services import workspaces

    ws = None
    wanted = str(body.get("workspace", "")).strip()
    if wanted:
        ws = workspaces.by_name(conn, wanted)
    elif body.get("context") == "job":
        ws = workspaces.first_of_kind(conn, "job")

    with conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, horizon, workspace_id, nuisance, source)"
            " VALUES (?, 'inbox', ?, ?, ?)",
            (title[:500], ws["id"] if ws else None, nuisance, source),
        )
    return {"ok": True, "id": cur.lastrowid}

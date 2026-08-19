"""LEARN: dependency-tree tracks, frontier suggestions, AI expansion."""

from __future__ import annotations

import json
import sqlite3
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from ..deps import get_conn, render, utcnow
from ..services import chat_import, learnmeta, suggest
from ..services.frontier import create_node, frontier, frontier_ids

RESOURCE_KINDS = ("article", "book", "pdf", "video", "course", "other")

router = APIRouter(prefix="/learn")

def _counts(conn: sqlite3.Connection, track_id: int) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS total, SUM(done_at IS NOT NULL) AS done"
        " FROM nodes WHERE track_id = ?",
        (track_id,),
    ).fetchone()
    return {"total": row["total"], "done": row["done"] or 0}


def _notes_by_node(conn: sqlite3.Connection, track_id: int) -> dict:
    out: dict[int, list] = {}
    for r in conn.execute(
        "SELECT nn.* FROM node_notes nn JOIN nodes n ON n.id = nn.node_id"
        " WHERE n.track_id = ? ORDER BY nn.id",
        (track_id,),
    ):
        out.setdefault(r["node_id"], []).append(r)
    return out


def _resources_by_node(conn: sqlite3.Connection, track_id: int) -> dict:
    out: dict[int, list] = {}
    for r in conn.execute(
        "SELECT * FROM resources WHERE track_id = ? AND node_id IS NOT NULL ORDER BY id",
        (track_id,),
    ):
        out.setdefault(r["node_id"], []).append(r)
    return out


def _track_ctx(
    conn: sqlite3.Connection, track_id: int, new_ids: set[int] | None = None
) -> dict:
    track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    return {
        "track": track,
        "frontier": frontier(conn, track_id),
        "new_ids": new_ids or set(),
        "counts": _counts(conn, track_id),
        "progress": learnmeta.progress(conn, track_id),
        "resources_by_node": _resources_by_node(conn, track_id),
        "notes_by_node": _notes_by_node(conn, track_id),
        "resource_kinds": RESOURCE_KINDS,
        "all_nodes": conn.execute(
            "SELECT * FROM nodes WHERE track_id = ? ORDER BY position, id", (track_id,)
        ).fetchall(),
        "pending": conn.execute(
            "SELECT * FROM suggestions WHERE track_id = ? AND status = 'pending'"
            " ORDER BY id",
            (track_id,),
        ).fetchall(),
        "loads": json.loads,
    }


def _index_ctx(conn: sqlite3.Connection) -> dict:
    tracks = []
    for t in conn.execute("SELECT * FROM tracks ORDER BY position, name"):
        tracks.append(
            {
                "row": t,
                "frontier": frontier(conn, t["id"]),
                "headliner": learnmeta.headliner(conn, t["id"]),
                "progress": learnmeta.progress(conn, t["id"]),
            }
        )
    return {
        "tracks": tracks,
        "streak": learnmeta.streak(conn),
        "logged_today": learnmeta.logged_today(conn),
    }


@router.get("")
def learn_page(request: Request, conn=Depends(get_conn)):
    return render(request, "learn/index.html", _index_ctx(conn))


@router.post("/tracks")
def add_track(request: Request, conn=Depends(get_conn), name: str = Form(...)):
    from ..services.frontier import slugify

    name = name.strip()
    if name:
        base = slugify(name)
        slug, n = base, 1
        while conn.execute("SELECT 1 FROM tracks WHERE slug = ?", (slug,)).fetchone():
            n += 1
            slug = f"{base}-{n}"
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM tracks"
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO tracks (slug, name, position) VALUES (?, ?, ?)",
                (slug, name, pos),
            )
    return render(request, "learn/_index_body.html", _index_ctx(conn))


@router.post("/log-today")
def log_today(request: Request, conn=Depends(get_conn)):
    learnmeta.log_day(conn, "manual")
    return render(request, "learn/_index_body.html", _index_ctx(conn))


@router.get("/tracks/{track_id}")
def track_page(request: Request, track_id: int, conn=Depends(get_conn)):
    return render(request, "learn/track.html", _track_ctx(conn, track_id))


def _toggle(conn: sqlite3.Connection, node_id: int, done: bool) -> tuple[int, set[int]]:
    node = conn.execute("SELECT track_id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    track_id = node["track_id"]
    before = frontier_ids(conn, track_id)
    with conn:
        conn.execute(
            "UPDATE nodes SET done_at = ?, learning_now = 0 WHERE id = ?",
            (utcnow() if done else None, node_id),
        )
        conn.execute("UPDATE tracks SET touched_at = ? WHERE id = ?", (utcnow(), track_id))
    if done:
        learnmeta.log_day(conn, "node")
    return track_id, frontier_ids(conn, track_id) - before


@router.post("/nodes/{node_id}/done")
def node_done(
    request: Request, node_id: int, conn=Depends(get_conn), frame: str = Form("track")
):
    track_id, new_ids = _toggle(conn, node_id, True)
    if frame == "home":
        from .home import build_home_ctx

        return render(
            request, "_home_blocks.html", build_home_ctx(conn, request.app.state.prefs, request.app.state.settings)
        )
    if frame == "learn":
        return render(request, "learn/_index_body.html", _index_ctx(conn))
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id, new_ids))


@router.post("/nodes/{node_id}/focus")
def node_focus(
    request: Request, node_id: int, conn=Depends(get_conn), frame: str = Form("track")
):
    node = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    track_id = node["track_id"]
    with conn:
        if node["learning_now"]:
            conn.execute("UPDATE nodes SET learning_now = 0 WHERE id = ?", (node_id,))
        else:
            conn.execute(
                "UPDATE nodes SET learning_now = 1 WHERE id = ? AND done_at IS NULL",
                (node_id,),
            )
    if frame == "learn":
        return render(request, "learn/_index_body.html", _index_ctx(conn))
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id))


@router.post("/nodes/{node_id}/resources")
def add_node_resource(
    request: Request,
    node_id: int,
    conn=Depends(get_conn),
    title: str = Form(...),
    url: str = Form(""),
    kind: str = Form("article"),
):
    node = conn.execute("SELECT track_id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    title = title.strip()
    if kind not in RESOURCE_KINDS:
        kind = "other"
    if title:
        with conn:
            conn.execute(
                "INSERT INTO resources (track_id, node_id, title, url, kind)"
                " VALUES (?, ?, ?, ?, ?)",
                (node["track_id"], node_id, title, url.strip(), kind),
            )
    return render(request, "learn/_track_body.html", _track_ctx(conn, node["track_id"]))


@router.post("/nodes/{node_id}/note")
def add_node_note(
    request: Request, node_id: int, conn=Depends(get_conn), text: str = Form(...)
):
    node = conn.execute("SELECT track_id FROM nodes WHERE id = ?", (node_id,)).fetchone()
    text = text.strip()
    if text:
        with conn:
            conn.execute(
                "INSERT INTO node_notes (node_id, text) VALUES (?, ?)", (node_id, text)
            )
    return render(request, "learn/_track_body.html", _track_ctx(conn, node["track_id"]))


@router.post("/notes/{note_id}/delete")
def delete_node_note(request: Request, note_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT n.track_id FROM node_notes nn JOIN nodes n ON n.id = nn.node_id"
        " WHERE nn.id = ?",
        (note_id,),
    ).fetchone()
    with conn:
        conn.execute("DELETE FROM node_notes WHERE id = ?", (note_id,))
    return render(request, "learn/_track_body.html", _track_ctx(conn, row["track_id"]))


@router.post("/resources/{resource_id}/delete")
def delete_resource(request: Request, resource_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT track_id FROM resources WHERE id = ?", (resource_id,)
    ).fetchone()
    with conn:
        conn.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
    return render(request, "learn/_track_body.html", _track_ctx(conn, row["track_id"]))


@router.post("/nodes/{node_id}/undone")
def node_undone(request: Request, node_id: int, conn=Depends(get_conn)):
    track_id, _ = _toggle(conn, node_id, False)
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id))


@router.post("/tracks/{track_id}/nodes")
def add_node(
    request: Request,
    track_id: int,
    conn=Depends(get_conn),
    title: str = Form(...),
    summary: str = Form(""),
):
    title = title.strip()
    if title:
        with conn:
            create_node(conn, track_id, title, summary.strip(), "user", [])
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id))


@router.post("/tracks/{track_id}/notes")
def save_track_notes(
    request: Request, track_id: int, conn=Depends(get_conn), notes: str = Form("")
):
    with conn:
        conn.execute("UPDATE tracks SET notes = ? WHERE id = ?", (notes, track_id))
    from fastapi.responses import Response

    return Response(status_code=204)


def _import_redirect(msg: str, q: str = "") -> RedirectResponse:
    params = {"msg": msg}
    if q:
        params["q"] = q
    return RedirectResponse(
        f"/learn/import?{urllib.parse.urlencode(params)}", status_code=303
    )


@router.get("/import")
def import_page(request: Request, conn=Depends(get_conn), q: str = "", msg: str = ""):
    where, args = "status = 'new'", ()
    if q:
        where += " AND title LIKE ?"
        args = (f"%{q}%",)
    chats = conn.execute(
        f"SELECT * FROM imported_chats WHERE {where}"
        " ORDER BY chat_created IS NULL, chat_created DESC, id DESC",
        args,
    ).fetchall()
    return render(
        request,
        "learn/import.html",
        {
            "chats": chats,
            "q": q,
            "msg": msg,
            "tracks": conn.execute("SELECT * FROM tracks ORDER BY position, name").fetchall(),
        },
    )


@router.post("/import/upload")
async def import_upload(request: Request, conn=Depends(get_conn), file: UploadFile = File(...)):
    data = await file.read()
    rows = chat_import.parse_export(data)
    if not rows:
        return _import_redirect(
            "Could not find conversations in that file. Upload conversations.json or the export zip."
        )
    with conn:
        conn.execute("DELETE FROM imported_chats WHERE status = 'new'")
        for r in rows:
            conn.execute(
                "INSERT INTO imported_chats (title, chat_created, digest) VALUES (?, ?, ?)",
                (r["title"], r["created"], r["digest"]),
            )
    return _import_redirect(f"Found {len(rows)} conversations. Pick the learning ones.")


@router.post("/import/act")
def import_act(
    request: Request,
    conn=Depends(get_conn),
    action: str = Form(...),
    chat_ids: list[int] = Form([]),
    track_id: int = Form(0),
    q: str = Form(""),
):
    if not chat_ids:
        return _import_redirect("Nothing selected.", q)
    marks = ",".join("?" for _ in chat_ids)
    chats = conn.execute(
        f"SELECT * FROM imported_chats WHERE status = 'new' AND id IN ({marks})",
        chat_ids,
    ).fetchall()

    if action == "dismiss":
        with conn:
            conn.execute(
                f"UPDATE imported_chats SET status = 'dismissed' WHERE id IN ({marks})",
                chat_ids,
            )
        return _import_redirect(f"Dismissed {len(chats)}.", q)

    if action == "add":
        track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if track is None:
            return _import_redirect("Pick a track first.", q)
        with conn:
            for c in chats:
                create_node(conn, track_id, c["title"], c["digest"], "user", [])
            conn.execute(
                f"UPDATE imported_chats SET status = 'used' WHERE id IN ({marks})",
                chat_ids,
            )
        return _import_redirect(f"Added {len(chats)} items to {track['name']}.", q)

    if action == "map":
        settings = request.app.state.settings
        if not settings.ai_enabled:
            return _import_redirect("Set ANTHROPIC_API_KEY to map with Claude.", q)
        tracks = []
        track_ids = {}
        for t in conn.execute("SELECT * FROM tracks ORDER BY position, name"):
            track_ids[t["slug"]] = t["id"]
            nodes = conn.execute(
                "SELECT * FROM nodes WHERE track_id = ? ORDER BY position, id", (t["id"],)
            ).fetchall()
            tracks.append({"slug": t["slug"], "name": t["name"], "nodes": nodes})
        actions = suggest.map_chats(settings.anthropic_api_key, tracks, chats)
        inserted = 0
        with conn:
            for a in actions:
                tid = track_ids.get(a["track_slug"])
                if tid is None:
                    continue
                payload = dict(a)
                if a["kind"] == "done":
                    node = conn.execute(
                        "SELECT title FROM nodes WHERE track_id = ? AND slug = ?"
                        " AND done_at IS NULL",
                        (tid, a["node_slug"]),
                    ).fetchone()
                    if node is None:
                        continue
                    payload["node_title"] = node["title"]
                conn.execute(
                    "INSERT INTO suggestions (track_id, payload) VALUES (?, ?)",
                    (tid, json.dumps(payload)),
                )
                inserted += 1
            if inserted:
                conn.execute(
                    f"UPDATE imported_chats SET status = 'used' WHERE id IN ({marks})",
                    chat_ids,
                )
        if not inserted:
            return _import_redirect("No mappings this time. Try fewer, clearer chats.", q)
        return _import_redirect(
            f"Created {inserted} suggestions. Review them on their track pages in Learn.", q
        )

    return _import_redirect("Unknown action.", q)


def _resolve_suggestion(conn: sqlite3.Connection, suggestion_id: int, accept: bool) -> int:
    s = conn.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
    if s is None or s["status"] != "pending":
        return s["track_id"] if s else 0
    with conn:
        if accept:
            p = json.loads(s["payload"])
            if p.get("kind") == "done":
                conn.execute(
                    "UPDATE nodes SET done_at = ? WHERE track_id = ? AND slug = ?"
                    " AND done_at IS NULL",
                    (utcnow(), s["track_id"], p.get("node_slug", "")),
                )
            else:
                prereq_ids = [
                    r["id"]
                    for slug in p.get("prereq_slugs", [])
                    if (
                        r := conn.execute(
                            "SELECT id FROM nodes WHERE track_id = ? AND slug = ?",
                            (s["track_id"], slug),
                        ).fetchone()
                    )
                ]
                create_node(
                    conn, s["track_id"], p["title"], p.get("summary", ""), "ai", prereq_ids
                )
        conn.execute(
            "UPDATE suggestions SET status = ?, resolved_at = ? WHERE id = ?",
            ("accepted" if accept else "dismissed", utcnow(), suggestion_id),
        )
    return s["track_id"]


@router.post("/suggestions/{suggestion_id}/accept")
def accept_suggestion(request: Request, suggestion_id: int, conn=Depends(get_conn)):
    track_id = _resolve_suggestion(conn, suggestion_id, True)
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id))


@router.post("/suggestions/{suggestion_id}/dismiss")
def dismiss_suggestion(request: Request, suggestion_id: int, conn=Depends(get_conn)):
    track_id = _resolve_suggestion(conn, suggestion_id, False)
    return render(request, "learn/_track_body.html", _track_ctx(conn, track_id))

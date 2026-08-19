"""Import a Notion workspace export: pages and databases arrive as
candidates to triage, never auto-imported. Pages and database rows can join
the inbox as tasks; a database can become a model board, grouped by any of
its columns."""

from __future__ import annotations

import json
import urllib.parse

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from ..deps import get_conn, render
from ..services import notion_import

router = APIRouter(prefix="/import/notion")


def _redirect(msg: str = ""):
    url = "/import/notion"
    if msg:
        url += "?" + urllib.parse.urlencode({"msg": msg})
    return RedirectResponse(url, status_code=303)


def _suggest_group(columns: list[str], rows: list[dict]) -> str:
    """The column that reads most like a status: few values, each repeated."""
    best, best_n = "", None
    for c in columns[1:]:
        vals = {r.get(c, "") for r in rows if r.get(c, "")}
        if len(vals) < 2 or (rows and len(vals) >= len(rows)):
            continue
        if best_n is None or len(vals) < best_n:
            best, best_n = c, len(vals)
    if not best and len(columns) > 1:
        best = columns[1]
    return best


def _candidates(conn):
    rows = conn.execute(
        "SELECT * FROM imported_pages WHERE status = 'new' ORDER BY kind, id"
    ).fetchall()
    pages, databases = [], []
    for r in rows:
        if r["kind"] == "database":
            payload = json.loads(r["payload"] or "{}")
            columns = payload.get("columns") or []
            data_rows = payload.get("rows") or []
            databases.append({
                "row": r,
                "columns": columns,
                "count": len(data_rows),
                "suggested": _suggest_group(columns, data_rows),
            })
        else:
            pages.append(r)
    return pages, databases


@router.get("")
def import_page(request: Request, conn=Depends(get_conn), msg: str = ""):
    pages, databases = _candidates(conn)
    return render(
        request,
        "import/notion.html",
        {"pages": pages, "databases": databases, "msg": msg},
    )


@router.post("/upload")
async def import_upload(
    request: Request, conn=Depends(get_conn), file: UploadFile = File(...)
):
    data = await file.read()
    rows = notion_import.parse_export(data)
    if not rows:
        return _redirect(
            "could not find pages or databases in that file. upload the"
            " markdown and csv export zip from notion."
        )
    with conn:
        conn.execute("DELETE FROM imported_pages WHERE status = 'new'")
        for r in rows:
            conn.execute(
                "INSERT INTO imported_pages (kind, title, digest, payload)"
                " VALUES (?, ?, ?, ?)",
                (r["kind"], r["title"], r["digest"], r["payload"]),
            )
    pages = sum(1 for r in rows if r["kind"] == "page")
    dbs = len(rows) - pages
    return _redirect(f"found {pages} pages and {dbs} databases. pick what moves in.")


@router.post("/act")
def import_act(
    request: Request,
    conn=Depends(get_conn),
    action: str = Form(...),
    page_ids: list[int] = Form([]),
):
    if not page_ids:
        return _redirect("nothing selected.")
    marks = ",".join("?" for _ in page_ids)
    rows = conn.execute(
        f"SELECT * FROM imported_pages WHERE status = 'new' AND id IN ({marks})",
        page_ids,
    ).fetchall()

    if action == "dismiss":
        with conn:
            conn.execute(
                f"UPDATE imported_pages SET status = 'dismissed' WHERE id IN ({marks})",
                page_ids,
            )
        return _redirect(f"dismissed {len(rows)}.")

    if action == "inbox":
        added = 0
        with conn:
            for r in rows:
                if r["kind"] == "database":
                    payload = json.loads(r["payload"] or "{}")
                    columns = payload.get("columns") or []
                    for data_row in payload.get("rows") or []:
                        title = data_row.get(columns[0], "") if columns else ""
                        if title:
                            conn.execute(
                                "INSERT INTO tasks (title, horizon, source)"
                                " VALUES (?, 'inbox', 'notion')",
                                (title[:500],),
                            )
                            added += 1
                else:
                    conn.execute(
                        "INSERT INTO tasks (title, horizon, source)"
                        " VALUES (?, 'inbox', 'notion')",
                        (r["title"][:500],),
                    )
                    added += 1
            conn.execute(
                f"UPDATE imported_pages SET status = 'used' WHERE id IN ({marks})",
                page_ids,
            )
        return _redirect(f"added {added} to the inbox.")

    return _redirect("nothing selected.")


@router.post("/{page_id}/board")
def make_board(
    request: Request,
    page_id: int,
    conn=Depends(get_conn),
    group_col: str = Form(""),
):
    r = conn.execute(
        "SELECT * FROM imported_pages WHERE id = ? AND kind = 'database'"
        " AND status = 'new'",
        (page_id,),
    ).fetchone()
    if r is None:
        return _redirect("that one is gone.")
    payload = json.loads(r["payload"] or "{}")
    columns = payload.get("columns") or []
    data_rows = payload.get("rows") or []
    if not columns:
        return _redirect("that database has no columns.")
    title_col = columns[0]
    if group_col not in columns:
        group_col = ""
    with conn:
        board_id = conn.execute(
            "INSERT INTO boards (name) VALUES (?)", (r["title"],)
        ).lastrowid
        buckets: dict[str, int] = {}
        counts: dict[int, int] = {}
        for data_row in data_rows:
            title = data_row.get(title_col, "")
            if not title:
                continue
            group = data_row.get(group_col, "") if group_col else ""
            group = group or "unsorted"
            if group not in buckets:
                buckets[group] = conn.execute(
                    "INSERT INTO buckets (board_id, name, position) VALUES (?, ?, ?)",
                    (board_id, group, len(buckets)),
                ).lastrowid
            b = buckets[group]
            conn.execute(
                "INSERT INTO cards (bucket_id, title, position) VALUES (?, ?, ?)",
                (b, title[:500], counts.get(b, 0)),
            )
            counts[b] = counts.get(b, 0) + 1
        conn.execute(
            "UPDATE imported_pages SET status = 'used' WHERE id = ?", (page_id,)
        )
    return RedirectResponse(f"/model/boards/{board_id}", status_code=303)

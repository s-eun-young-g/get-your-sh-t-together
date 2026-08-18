"""MODEL: mental-modeling boards with user-named buckets and cards."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response

from ..deps import get_conn, render, reindex

router = APIRouter(prefix="/model")


def _board_ctx(conn: sqlite3.Connection, board_id: int) -> dict:
    board = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    rows = conn.execute(
        "SELECT * FROM buckets WHERE board_id = ? ORDER BY position, id", (board_id,)
    ).fetchall()
    cards_by_bucket: dict[int, list] = {}
    for c in conn.execute(
        "SELECT c.* FROM cards c JOIN buckets b ON b.id = c.bucket_id"
        " WHERE b.board_id = ? ORDER BY c.position, c.id",
        (board_id,),
    ):
        cards_by_bucket.setdefault(c["bucket_id"], []).append(c)
    by_parent: dict = {}
    for r in rows:
        by_parent.setdefault(r["parent_id"], []).append(r)

    def build(parent_id):
        return [
            {
                "row": r,
                "cards": cards_by_bucket.get(r["id"], []),
                "children": build(r["id"]),
            }
            for r in by_parent.get(parent_id, [])
        ]

    tree = build(None)
    flat: list[dict] = []

    def walk(nodes, path):
        for n in nodes:
            p = path + [n["row"]["name"]]
            flat.append({"id": n["row"]["id"], "path": " / ".join(p)})
            walk(n["children"], p)

    walk(tree, [])
    return {"board": board, "tree": tree, "flat": flat}


@router.get("")
def boards_index(request: Request, conn=Depends(get_conn)):
    boards = conn.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM buckets k WHERE k.board_id = b.id) AS bucket_count"
        " FROM boards b WHERE archived_at IS NULL ORDER BY created_at DESC"
    ).fetchall()
    return render(request, "model/index.html", {"boards": boards})


@router.post("/boards")
def create_board(request: Request, conn=Depends(get_conn), name: str = Form(...)):
    name = name.strip() or "Untitled board"
    with conn:
        board_id = conn.execute("INSERT INTO boards (name) VALUES (?)", (name,)).lastrowid
    return Response(headers={"HX-Redirect": f"/model/boards/{board_id}"})


@router.get("/boards/{board_id}")
def board_page(request: Request, board_id: int, conn=Depends(get_conn)):
    return render(request, "model/board.html", _board_ctx(conn, board_id))


@router.post("/boards/{board_id}/buckets")
def add_bucket(
    request: Request,
    board_id: int,
    conn=Depends(get_conn),
    name: str = Form(...),
    parent_id: int = Form(0),
):
    name = name.strip()
    if name:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM buckets"
            " WHERE board_id = ? AND parent_id IS ?",
            (board_id, parent_id or None),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO buckets (board_id, name, position, parent_id)"
                " VALUES (?, ?, ?, ?)",
                (board_id, name, pos, parent_id or None),
            )
    return render(request, "model/_columns.html", _board_ctx(conn, board_id))


@router.post("/buckets/{bucket_id}/rename")
def rename_bucket(request: Request, bucket_id: int, conn=Depends(get_conn), name: str = Form(...)):
    b = conn.execute("SELECT board_id FROM buckets WHERE id = ?", (bucket_id,)).fetchone()
    if name.strip():
        with conn:
            conn.execute("UPDATE buckets SET name = ? WHERE id = ?", (name.strip(), bucket_id))
    return render(request, "model/_columns.html", _board_ctx(conn, b["board_id"]))


@router.post("/buckets/{bucket_id}/delete")
def delete_bucket(request: Request, bucket_id: int, conn=Depends(get_conn)):
    b = conn.execute("SELECT * FROM buckets WHERE id = ?", (bucket_id,)).fetchone()
    board_id = b["board_id"]
    error = ""
    has_children = conn.execute(
        "SELECT 1 FROM buckets WHERE parent_id = ?", (bucket_id,)
    ).fetchone()
    card_count = conn.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE bucket_id = ?", (bucket_id,)
    ).fetchone()["n"]
    if has_children:
        error = "this bucket has sub-buckets; delete or move those first."
    else:
        # Cards move up to the parent, or to the first other top-level bucket.
        target = b["parent_id"]
        if target is None:
            other = conn.execute(
                "SELECT id FROM buckets WHERE board_id = ? AND id <> ?"
                " AND parent_id IS NULL ORDER BY position, id",
                (board_id, bucket_id),
            ).fetchone()
            target = other["id"] if other else None
        if card_count and target is None:
            error = "its cards need somewhere to go; add another bucket first."
        else:
            with conn:
                if card_count:
                    base = conn.execute(
                        "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM cards"
                        " WHERE bucket_id = ?",
                        (target,),
                    ).fetchone()["p"]
                    for i, card in enumerate(
                        conn.execute(
                            "SELECT id FROM cards WHERE bucket_id = ?"
                            " ORDER BY position, id",
                            (bucket_id,),
                        ).fetchall()
                    ):
                        conn.execute(
                            "UPDATE cards SET bucket_id = ?, position = ? WHERE id = ?",
                            (target, base + i, card["id"]),
                        )
                conn.execute("DELETE FROM buckets WHERE id = ?", (bucket_id,))
    ctx = _board_ctx(conn, board_id)
    ctx["error"] = error
    return render(request, "model/_columns.html", ctx)


@router.post("/buckets/{bucket_id}/cards")
def add_card(request: Request, bucket_id: int, conn=Depends(get_conn), title: str = Form(...)):
    b = conn.execute("SELECT board_id FROM buckets WHERE id = ?", (bucket_id,)).fetchone()
    title = title.strip()
    if title:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM cards WHERE bucket_id = ?",
            (bucket_id,),
        ).fetchone()["p"]
        with conn:
            conn.execute(
                "INSERT INTO cards (bucket_id, title, position) VALUES (?, ?, ?)",
                (bucket_id, title, pos),
            )
    return render(request, "model/_columns.html", _board_ctx(conn, b["board_id"]))


@router.post("/cards/{card_id}/move")
def move_card(
    request: Request,
    card_id: int,
    conn=Depends(get_conn),
    bucket_id: int = Form(...),
):
    card = conn.execute("SELECT bucket_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    target = conn.execute("SELECT board_id FROM buckets WHERE id = ?", (bucket_id,)).fetchone()
    with conn:
        pos = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS p FROM cards WHERE bucket_id = ?",
            (bucket_id,),
        ).fetchone()["p"]
        conn.execute(
            "UPDATE cards SET bucket_id = ?, position = ? WHERE id = ?",
            (bucket_id, pos, card_id),
        )
        reindex(conn, "cards", "bucket_id", card["bucket_id"])
    return render(request, "model/_columns.html", _board_ctx(conn, target["board_id"]))


@router.post("/cards/{card_id}/delete")
def delete_card(request: Request, card_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT b.board_id FROM cards c JOIN buckets b ON b.id = c.bucket_id WHERE c.id = ?",
        (card_id,),
    ).fetchone()
    with conn:
        conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))
    return render(request, "model/_columns.html", _board_ctx(conn, row["board_id"]))


@router.post("/boards/{board_id}/notes")
def save_notes(request: Request, board_id: int, conn=Depends(get_conn), notes: str = Form("")):
    with conn:
        conn.execute("UPDATE boards SET notes = ? WHERE id = ?", (notes, board_id))
    return Response(status_code=204)


@router.post("/boards/{board_id}/delete")
def delete_board(request: Request, board_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute("DELETE FROM boards WHERE id = ?", (board_id,))
    return Response(headers={"HX-Redirect": "/model"})


@router.post("/boards/{board_id}/archive")
def archive_board(request: Request, board_id: int, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "UPDATE boards SET archived_at = datetime('now') WHERE id = ?", (board_id,)
        )
    return Response(headers={"HX-Redirect": "/model"})

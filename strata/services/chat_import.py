"""Parse a ChatGPT or Claude data export into (title, created, digest) rows.

Both products export a conversations.json (inside a zip). ChatGPT rows carry
title/create_time/mapping; Claude rows carry name/created_at/chat_messages.
Formats are undocumented and shift, so everything here is defensive: a
conversation we cannot read becomes a row with just its title, never a crash.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

DIGEST_CHARS = 240


def parse_export(data: bytes) -> list[dict]:
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = next(
                (n for n in zf.namelist() if n.endswith("conversations.json")), None
            )
            if name is None:
                return []
            data = zf.read(name)
    try:
        conversations = json.loads(data.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    if not isinstance(conversations, list):
        return []
    out = []
    for conv in conversations:
        if not isinstance(conv, dict):
            continue
        if conv.get("chat_messages") is not None or conv.get("name"):
            row = _parse_claude(conv)
        elif conv.get("title") or conv.get("mapping"):
            row = _parse_chatgpt(conv)
        else:
            continue
        out.append(row)
    out.sort(key=lambda c: c["created"] or "", reverse=True)
    return out


def _parse_chatgpt(conv: dict) -> dict:
    title = str(conv.get("title") or "").strip() or "Untitled chat"
    return {
        "title": title[:300],
        "created": _created(conv.get("create_time")),
        "digest": _first_user_message(conv.get("mapping")),
    }


def _parse_claude(conv: dict) -> dict:
    title = str(conv.get("name") or "").strip() or "Untitled chat"
    digest = ""
    messages = conv.get("chat_messages")
    if isinstance(messages, list):
        for m in messages:
            if isinstance(m, dict) and m.get("sender") == "human":
                digest = str(m.get("text") or "").strip()[:DIGEST_CHARS]
                if digest:
                    break
    created = None
    raw = conv.get("created_at")
    if isinstance(raw, str) and len(raw) >= 10:
        created = raw[:10]
    return {"title": title[:300], "created": created, "digest": digest}


def _created(create_time) -> str | None:
    try:
        return (
            datetime.fromtimestamp(float(create_time), tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d")
        )
    except (TypeError, ValueError):
        return None


def _first_user_message(mapping) -> str:
    if not isinstance(mapping, dict):
        return ""
    best_time, best_text = None, ""
    for node in mapping.values():
        msg = node.get("message") if isinstance(node, dict) else None
        if not isinstance(msg, dict):
            continue
        author = msg.get("author") or {}
        if author.get("role") != "user":
            continue
        content = msg.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        text = " ".join(p for p in parts if isinstance(p, str)).strip() if parts else ""
        if not text:
            continue
        t = msg.get("create_time") or 0
        if best_time is None or (t or 0) < best_time:
            best_time, best_text = t or 0, text
    return best_text[:DIGEST_CHARS]

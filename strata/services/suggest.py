"""Claude-backed mapping of imported chats onto the learn trees."""

from __future__ import annotations

import json
import logging
import sqlite3

log = logging.getLogger("strata.suggest")

MODEL = "claude-opus-5"

MAP_PROMPT = """A person tracks what they learn in dependency trees. Their tracks and items
(slug: title, done items marked [x]):

{tracks}

Below are titles and opening messages of ChatGPT conversations from their
learning folder. For each conversation that clearly maps onto this system,
emit one action:
- if it shows they already learned an existing item, mark it done
- if it covers ground the trees lack, propose a new item in the best track

Skip conversations that are ambiguous or not about learning. Respond with
ONLY a JSON array, no other text:
[{{"track_slug": "...", "kind": "done", "node_slug": "existing-slug"}},
 {{"track_slug": "...", "kind": "new", "title": "...", "summary": "one sentence",
   "prereq_slugs": ["existing-slug"]}}]

Conversations:
{chats}
"""

MAX_CHATS_PER_CALL = 40


def map_chats(api_key: str, tracks: list[dict], chats: list[sqlite3.Row]) -> list[dict]:
    """Map ChatGPT conversations onto the learn trees.

    tracks: [{slug, name, nodes: [Row]}]. Returns validated action dicts.
    """
    track_lines = []
    for t in tracks:
        track_lines.append(f"Track {t['slug']} ({t['name']}):")
        for n in t["nodes"]:
            track_lines.append(
                f"  - {'[x] ' if n['done_at'] else ''}{n['slug']}: {n['title']}"
            )
    chat_lines = [
        f"- {c['title']}" + (f" | starts: {c['digest']}" if c["digest"] else "")
        for c in chats[:MAX_CHATS_PER_CALL]
    ]
    prompt = MAP_PROMPT.format(tracks="\n".join(track_lines), chats="\n".join(chat_lines))
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key, timeout=60.0, max_retries=1)
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=8192,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return []
        text = next((b.text for b in response.content if b.type == "text"), "")
    except Exception:
        log.warning("chat mapping call failed", exc_info=True)
        return []
    return _parse_actions(text)


def _parse_actions(text: str) -> list[dict]:
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    out = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("track_slug"):
            continue
        kind = item.get("kind")
        if kind == "done" and item.get("node_slug"):
            out.append(
                {
                    "kind": "done",
                    "track_slug": str(item["track_slug"]),
                    "node_slug": str(item["node_slug"]),
                }
            )
        elif kind == "new" and str(item.get("title", "")).strip():
            out.append(
                {
                    "kind": "new",
                    "track_slug": str(item["track_slug"]),
                    "title": str(item["title"]).strip(),
                    "summary": str(item.get("summary", "")).strip(),
                    "prereq_slugs": [
                        str(s) for s in item.get("prereq_slugs", []) if isinstance(s, str)
                    ],
                }
            )
    return out


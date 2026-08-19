"""Parse a Notion workspace export (Markdown & CSV zip) into candidates.

Any Notion workspace can produce this export regardless of plan or org
policy: Settings > Export content > Markdown & CSV. Pages arrive as .md
files, databases as .csv. The format is undocumented and shifts, so parsing
is defensive: a file we cannot read is skipped, never a crash.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile

DIGEST_CHARS = 240
MAX_ROWS = 1000

# Notion suffixes every exported filename with a 32-hex page id.
_ID_SUFFIX = re.compile(r"\s+[0-9a-f]{32}(_all)?$")


def _clean_name(stem: str) -> str:
    return _ID_SUFFIX.sub("", stem).strip() or stem


def _walk_zip(data: bytes, depth: int = 0):
    """Yield (path, bytes) for every md/csv, recursing into nested part zips."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            if name.endswith("/"):
                continue
            lower = name.lower()
            try:
                if lower.endswith(".zip") and depth < 2:
                    yield from _walk_zip(zf.read(name), depth + 1)
                elif lower.endswith((".md", ".csv")):
                    yield name, zf.read(name)
            except Exception:
                continue


def _page(path: str, raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace")
    lines = text.splitlines()
    title = _clean_name(path.rsplit("/", 1)[-1][: -len(".md")])
    body_lines = lines
    if lines and lines[0].startswith("# "):
        title = lines[0][2:].strip() or title
        body_lines = lines[1:]
    body = " ".join(ln.strip() for ln in body_lines if ln.strip())
    return {"kind": "page", "title": title, "digest": body[:DIGEST_CHARS], "payload": ""}


def _database(path: str, raw: bytes) -> dict | None:
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        reader = csv.DictReader(io.StringIO(text))
        columns = [c for c in (reader.fieldnames or []) if c]
        rows = []
        for row in reader:
            rows.append({c: (row.get(c) or "").strip() for c in columns})
            if len(rows) >= MAX_ROWS:
                break
    except csv.Error:
        return None
    if not columns:
        return None
    digest = f"{len(rows)} rows: " + ", ".join(columns[:8])
    return {
        "kind": "database",
        "title": _clean_name(path.rsplit("/", 1)[-1][: -len(".csv")]),
        "digest": digest[:DIGEST_CHARS],
        "payload": json.dumps({"columns": columns, "rows": rows}),
    }


def parse_export(data: bytes) -> list[dict]:
    if data[:2] != b"PK":
        return []
    try:
        files = list(_walk_zip(data))
    except zipfile.BadZipFile:
        return []
    names = {n for n, _ in files}
    out = []
    for name, raw in files:
        lower = name.lower()
        try:
            if lower.endswith(".md"):
                item = _page(name, raw)
            else:
                # Newer exports ship x.csv plus x_all.csv with every column;
                # keep the richer _all twin and skip the narrow copy.
                if not lower.endswith("_all.csv") and name[:-4] + "_all.csv" in names:
                    continue
                item = _database(name, raw)
        except Exception:
            continue
        if item and item["title"]:
            out.append(item)
    return out

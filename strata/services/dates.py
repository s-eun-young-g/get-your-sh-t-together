"""Forgiving date parsing: type a date in any reasonable form, we infer it.

Accepted: 2026-09-01, 9/1, 9/1/26, sep 1, september 1 2026, 1 sep,
today, tomorrow, tmrw, in 3d / in 2w / in 1m, next week, friday, next friday.
Dates without a year resolve to the next future occurrence.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {}
for i, names in enumerate(
    [
        ("jan", "january"), ("feb", "february"), ("mar", "march"),
        ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
        ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
        ("nov", "november"), ("dec", "december"),
    ],
    start=1,
):
    for n in names:
        MONTHS[n] = i

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}


def _future(month: int, day: int, year: int | None, today: date) -> str | None:
    try:
        if year is not None:
            if year < 100:
                year += 2000
            return date(year, month, day).isoformat()
        d = date(today.year, month, day)
        if d < today:
            d = date(today.year + 1, month, day)
        return d.isoformat()
    except ValueError:
        return None


def parse_when(text: str, today: date | None = None) -> str | None:
    t = (text or "").strip().lower().rstrip(".")
    if not t:
        return None
    today = today or date.today()

    if t == "today":
        return today.isoformat()
    if t in ("tomorrow", "tmrw", "tom"):
        return (today + timedelta(days=1)).isoformat()
    if t in ("next week",):
        return (today + timedelta(days=7)).isoformat()
    if t in ("next month",):
        return (today + timedelta(days=30)).isoformat()

    m = re.fullmatch(r"(?:in\s+)?(\d+)\s*(d|days?|w|weeks?|mo|months?)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)[0] if not m.group(2).startswith("mo") else "mo"
        days = n * {"d": 1, "w": 7, "mo": 30}[unit]
        return (today + timedelta(days=days)).isoformat()

    m = re.fullmatch(r"(?:next\s+)?([a-z]+)", t)
    if m and m.group(1) in WEEKDAYS:
        ahead = (WEEKDAYS[m.group(1)] - today.weekday() - 1) % 7 + 1
        if t.startswith("next "):
            ahead += 7 if ahead <= 7 else 0
        return (today + timedelta(days=ahead)).isoformat()

    try:
        return date.fromisoformat(t).isoformat()
    except ValueError:
        pass

    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", t)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        return _future(month, day, year, today)

    m = re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", t)
    if m and m.group(1) in MONTHS:
        return _future(MONTHS[m.group(1)], int(m.group(2)), int(m.group(3)) if m.group(3) else None, today)

    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\.?(?:,?\s*(\d{4}))?", t)
    if m and m.group(2) in MONTHS:
        return _future(MONTHS[m.group(2)], int(m.group(1)), int(m.group(3)) if m.group(3) else None, today)

    return None

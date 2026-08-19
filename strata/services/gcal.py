"""Read-only Google Calendar pull via each calendar's secret ICS address.

Outbound-only like canvas sync: no OAuth, nothing to deploy. Gated on
GCAL_ICS_URL. Events are a mirror of the calendar, never user data, so they
live in an in-process cache that refetches when stale and keeps serving the
last good copy when the network is down.
"""

from __future__ import annotations

import logging
import time
import urllib.request
from datetime import date, datetime, timedelta

log = logging.getLogger("strata.gcal")

CACHE_TTL_SECONDS = 15 * 60
WINDOW_DAYS = 7

_cache: dict = {"at": 0.0, "events": []}


def fetch_ics(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read()


def _when_label(day: str) -> str:
    d = date.fromisoformat(day)
    offset = (d - date.today()).days
    if offset == 0:
        return "today"
    if offset == 1:
        return "tomorrow"
    return d.strftime("%a").lower()


def _window_events(data: bytes, start: date, end: date) -> list[dict]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(data)
    out = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev.get("DTSTART")
        if dtstart is None:
            continue
        dt = dtstart.dt
        title = str(ev.get("SUMMARY", "")).strip() or "(untitled)"
        if isinstance(dt, datetime):
            if dt.tzinfo is not None:
                dt = dt.astimezone()
            out.append({
                "day": dt.date().isoformat(),
                "minutes": dt.hour * 60 + dt.minute,
                "time": f"{dt.hour}:{dt.minute:02d}",
                "title": title,
            })
        else:
            out.append({
                "day": dt.isoformat(), "minutes": -1, "time": "", "title": title,
            })
    return out


def events(settings, fetch=None) -> list[dict]:
    """Events for the next WINDOW_DAYS across all configured calendars."""
    if not settings.gcal_enabled:
        return []
    if _cache["at"] and time.monotonic() - _cache["at"] < CACHE_TTL_SECONDS:
        return _cache["events"]
    fetch = fetch or fetch_ics
    start = date.today()
    collected: list[dict] = []
    try:
        for url in settings.gcal_ics_urls:
            collected += _window_events(
                fetch(url), start, start + timedelta(days=WINDOW_DAYS)
            )
    except Exception:
        log.exception("gcal fetch failed; serving the cached copy")
        _cache["at"] = time.monotonic()
        return _cache["events"]
    collected.sort(key=lambda e: (e["day"], e["minutes"]))
    for e in collected:
        e["when_label"] = _when_label(e["day"])
    _cache.update(at=time.monotonic(), events=collected)
    return collected


def today(settings, fetch=None) -> list[dict]:
    d = date.today().isoformat()
    return [e for e in events(settings, fetch) if e["day"] == d]

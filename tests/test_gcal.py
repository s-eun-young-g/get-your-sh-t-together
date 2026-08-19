from datetime import date, timedelta

from fastapi.testclient import TestClient

from strata.app import create_app
from strata.config import Settings
from strata.services import gcal


def _stamp(d: date, hhmm: str = "") -> str:
    return d.strftime("%Y%m%d") + (f"T{hhmm}00" if hhmm else "")


def _ics(today: date) -> bytes:
    # Floating local times so the expected labels are machine-independent.
    return "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Google Inc//Google Calendar//EN",
        "BEGIN:VEVENT",
        f"DTSTART:{_stamp(today, '0930')}",
        f"DTEND:{_stamp(today, '1000')}",
        "SUMMARY:therapy",
        "UID:one@test",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"DTSTART;VALUE=DATE:{_stamp(today + timedelta(days=2))}",
        f"DTEND;VALUE=DATE:{_stamp(today + timedelta(days=3))}",
        "SUMMARY:board retreat",
        "UID:two@test",
        "END:VEVENT",
        "BEGIN:VEVENT",
        f"DTSTART:{_stamp(today - timedelta(days=7), '1400')}",
        f"DTEND:{_stamp(today - timedelta(days=7), '1430')}",
        "RRULE:FREQ=WEEKLY",
        "SUMMARY:standup",
        "UID:three@test",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]).encode()


def _settings(tmp_path, url="https://calendar.google.com/private.ics"):
    return Settings(data_dir=tmp_path, secret="test-secret", gcal_ics_url=url)


def _reset_cache():
    gcal._cache.update(at=0.0, events=[])


def test_disabled_without_url(tmp_path):
    _reset_cache()
    s = Settings(data_dir=tmp_path, secret="test-secret")
    assert not s.gcal_enabled
    assert gcal.events(s) == []


def test_urls_split_on_commas(tmp_path):
    s = _settings(tmp_path, url="https://a/x.ics, https://b/y.ics")
    assert s.gcal_ics_urls == ["https://a/x.ics", "https://b/y.ics"]


def test_window_events_expand_and_label(tmp_path):
    _reset_cache()
    today = date.today()
    evs = gcal.events(_settings(tmp_path), fetch=lambda url: _ics(today))
    titles = [e["title"] for e in evs]
    assert "therapy" in titles and "board retreat" in titles
    assert "standup" in titles  # weekly recurrence expands into the window
    therapy = next(e for e in evs if e["title"] == "therapy")
    assert therapy["time"] == "9:30" and therapy["when_label"] == "today"
    retreat = next(e for e in evs if e["title"] == "board retreat")
    assert retreat["time"] == ""  # all-day carries no clock time
    assert evs == sorted(evs, key=lambda e: (e["day"], e["minutes"]))


def test_fetch_failure_serves_cache(tmp_path):
    _reset_cache()
    today = date.today()
    s = _settings(tmp_path)
    gcal.events(s, fetch=lambda url: _ics(today))
    gcal._cache["at"] = 0.0  # force a refetch

    def boom(url):
        raise OSError("network down")

    evs = gcal.events(s, fetch=boom)
    assert any(e["title"] == "therapy" for e in evs)


def test_events_render_on_home_and_life(tmp_path, monkeypatch):
    _reset_cache()
    today = date.today()
    monkeypatch.setattr(gcal, "fetch_ics", lambda url: _ics(today))
    with TestClient(create_app(_settings(tmp_path))) as c:
        home = c.get("/").text
        assert "therapy" in home and "9:30" in home
        assert "board retreat" not in home  # not today
        life = c.get("/life").text
        assert "on the calendar" in life
        assert "board retreat" in life and "standup" in life


def test_home_stays_quiet_when_disabled(client):
    _reset_cache()
    assert "on the calendar" not in client.get("/life").text

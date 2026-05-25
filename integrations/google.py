from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx

from config import settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_CALENDAR_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def get_auth_url() -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar.events",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    resp = httpx.post(_TOKEN_URL, data={
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> str:
    resp = httpx.post(_TOKEN_URL, data={
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def _parse_time(dt_str: str, all_day: bool) -> str:
    if all_day:
        return "all day"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        hkt = dt + timedelta(hours=8)  # UTC+8
        return hkt.strftime("%H:%M")
    except Exception:
        return dt_str


def _parse_item(item: dict) -> dict:
    start_info = item.get("start", {})
    end_info = item.get("end", {})
    all_day = "date" in start_info and "dateTime" not in start_info
    event_date = start_info.get("date") or start_info.get("dateTime", "")[:10]
    start_time = _parse_time(start_info.get("dateTime", start_info.get("date", "")), all_day)
    end_time = _parse_time(end_info.get("dateTime", end_info.get("date", "")), all_day)
    return {
        "id": item["id"],
        "date": event_date,
        "title": item.get("summary", "Untitled"),
        "time": f"{start_time}–{end_time}" if not all_day else "all day",
    }


def fetch_calendar_events(access_token: str, target_date: date) -> list[dict]:
    start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    resp = httpx.get(_CALENDAR_URL, headers={"Authorization": f"Bearer {access_token}"}, params={
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    })
    resp.raise_for_status()
    return [_parse_item(item) for item in resp.json().get("items", [])]


def get_events_for_user(user: dict, target_date: date) -> list[dict]:
    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        return []
    access_token = refresh_access_token(refresh_token)
    return fetch_calendar_events(access_token, target_date)


def fetch_calendar_events_range(access_token: str, start_date: date, end_date: date) -> list[dict]:
    start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
    end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=timezone.utc) + timedelta(days=1)
    resp = httpx.get(_CALENDAR_URL, headers={"Authorization": f"Bearer {access_token}"}, params={
        "timeMin": start.isoformat(),
        "timeMax": end.isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
    })
    resp.raise_for_status()
    return [_parse_item(item) for item in resp.json().get("items", [])]


def get_events_range_for_user(user: dict, start_date: date, end_date: date) -> list[dict]:
    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        return []
    access_token = refresh_access_token(refresh_token)
    return fetch_calendar_events_range(access_token, start_date, end_date)


def delete_calendar_event(access_token: str, event_id: str) -> None:
    resp = httpx.delete(
        f"{_CALENDAR_URL}/{event_id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()


def delete_event_for_user(user: dict, event_id: str) -> str:
    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        return "Google Calendar not connected."
    access_token = refresh_access_token(refresh_token)
    delete_calendar_event(access_token, event_id)
    return "Event deleted."


def create_calendar_event(
    access_token: str,
    title: str,
    event_date: str,
    start_time: str | None = None,
    end_time: str | None = None,
    notes: str | None = None,
) -> str:
    tz = "Asia/Hong_Kong"
    if start_time:
        start = {"dateTime": f"{event_date}T{start_time}:00+08:00", "timeZone": tz}
        if end_time:
            end = {"dateTime": f"{event_date}T{end_time}:00+08:00", "timeZone": tz}
        else:
            h, m = map(int, start_time.split(":"))
            end = {"dateTime": f"{event_date}T{(h + 1) % 24:02d}:{m:02d}:00+08:00", "timeZone": tz}
    else:
        next_day = (date.fromisoformat(event_date) + timedelta(days=1)).isoformat()
        start = {"date": event_date}
        end = {"date": next_day}

    body: dict = {"summary": title, "start": start, "end": end}
    if notes:
        body["description"] = notes

    resp = httpx.post(
        _CALENDAR_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json=body,
    )
    resp.raise_for_status()
    return resp.json().get("htmlLink", "")


def create_event_for_user(
    user: dict,
    title: str,
    event_date: str,
    start_time: str | None = None,
    end_time: str | None = None,
    notes: str | None = None,
) -> str:
    refresh_token = user.get("google_refresh_token")
    if not refresh_token:
        return "Google Calendar not connected."
    access_token = refresh_access_token(refresh_token)
    return create_calendar_event(access_token, title, event_date, start_time, end_time, notes)

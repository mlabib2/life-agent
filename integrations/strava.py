from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx

from config import settings

_AUTH_URL = "https://www.strava.com/oauth/authorize"
_TOKEN_URL = "https://www.strava.com/oauth/token"
_ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

GYM_SPORT_TYPES = {
    "WeightTraining", "Workout", "Crossfit", "RockClimbing",
    "Yoga", "Pilates", "Swim",
}


def get_auth_url() -> str:
    params = {
        "client_id": settings.strava_client_id,
        "redirect_uri": "http://localhost:8000/auth/strava/callback",
        "response_type": "code",
        "approval_prompt": "force",
        "scope": "activity:read_all",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    resp = httpx.post(_TOKEN_URL, data={
        "client_id": settings.strava_client_id,
        "client_secret": settings.strava_client_secret,
        "code": code,
        "grant_type": "authorization_code",
    })
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> str:
    resp = httpx.post(_TOKEN_URL, data={
        "client_id": settings.strava_client_id,
        "client_secret": settings.strava_client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_activities(access_token: str, since: datetime) -> list[dict]:
    resp = httpx.get(_ACTIVITIES_URL, headers={"Authorization": f"Bearer {access_token}"}, params={
        "after": int(since.timestamp()),
        "per_page": 30,
    })
    resp.raise_for_status()

    activities = []
    for item in resp.json():
        start = item.get("start_date_local", "")[:10]
        sport_type = item.get("sport_type", item.get("type", ""))
        activities.append({
            "id": item["id"],
            "name": item.get("name", "Activity"),
            "sport_type": sport_type,
            "date": start,
            "duration_min": round(item.get("moving_time", 0) / 60),
            "distance_km": round(item.get("distance", 0) / 1000, 2),
            "avg_hr": item.get("average_heartrate"),
            "calories": item.get("calories"),
            "is_gym": sport_type in GYM_SPORT_TYPES,
        })
    return activities


def get_activities_for_user(user: dict, since: datetime) -> list[dict]:
    refresh_token = user.get("strava_refresh_token")
    if not refresh_token:
        return []
    access_token = refresh_access_token(refresh_token)
    return fetch_activities(access_token, since)

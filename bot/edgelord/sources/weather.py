"""Game-time weather forecasts from Open-Meteo (no API key required).

nflverse carries observed temp and wind for games already played. For upcoming
games we need a forecast, and only for stadiums that are actually exposed --
a dome game gets no lookup at all.
"""

from __future__ import annotations

from datetime import date, datetime

import httpx

from .. import config
from .stadiums import Venue

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# Open-Meteo's forecast horizon; beyond this a request returns nothing useful.
MAX_FORECAST_DAYS = 16


def is_indoor(roof: str | None) -> bool:
    return (roof or "").lower() in config.INDOOR_ROOFS


def forecast(venue: Venue, kickoff: datetime, *, timeout: float = 15.0) -> dict | None:
    """Hourly forecast nearest to kickoff. Returns None if out of range or unreachable."""
    days_out = (kickoff.date() - date.today()).days
    if days_out < 0 or days_out > MAX_FORECAST_DAYS:
        return None

    params = {
        "latitude": venue.lat,
        "longitude": venue.lon,
        "hourly": "temperature_2m,precipitation_probability,precipitation,"
        "wind_speed_10m,wind_gusts_10m,relative_humidity_2m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": venue.tz,
        "forecast_days": min(MAX_FORECAST_DAYS, max(1, days_out + 2)),
    }
    try:
        r = httpx.get(FORECAST_URL, params=params, timeout=timeout)
        r.raise_for_status()
        hourly = r.json()["hourly"]
    except Exception:
        return None

    target = kickoff.strftime("%Y-%m-%dT%H:00")
    try:
        i = hourly["time"].index(target)
    except ValueError:
        return None

    def at(key):
        series = hourly.get(key) or []
        return series[i] if i < len(series) else None

    return {
        "source": "open-meteo forecast",
        "temp_f": at("temperature_2m"),
        "wind_mph": at("wind_speed_10m"),
        "wind_gust_mph": at("wind_gusts_10m"),
        "precip_probability_pct": at("precipitation_probability"),
        "precip_inches": at("precipitation"),
        "humidity_pct": at("relative_humidity_2m"),
    }


def for_game(game: dict, venue: Venue | None, kickoff: datetime | None) -> dict:
    """Weather block: observed if played, forecast if not, skipped if indoors.

    A venue's own roof wins when it declares one. On neutral-site games the
    schedule reports the nominal home team's roof -- the Melbourne Cricket
    Ground comes through as "dome" because SoFi is one -- which would skip the
    forecast for an open-air stadium on the other side of the world.
    """
    roof = (venue.roof if venue and venue.roof else None) or game.get("roof")
    if is_indoor(roof):
        return {"roof": roof, "indoor": True, "note": "climate controlled, weather not a factor"}

    block: dict = {"roof": roof, "indoor": False}

    # Already played -- nflverse has the observation.
    if game.get("home_score") is not None:
        block.update(
            {
                "source": "nflverse observed",
                "temp_f": game.get("temp"),
                "wind_mph": game.get("wind"),
            }
        )
        return block

    if venue and kickoff:
        fc = forecast(venue, kickoff)
        if fc:
            block.update(fc)
            return block

    block["note"] = "no forecast available yet"
    return block

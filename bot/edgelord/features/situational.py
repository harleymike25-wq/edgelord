"""Rest, travel and where a game sits in a team's schedule."""

from __future__ import annotations

from datetime import date

import polars as pl

from ..sources import stadiums
from ..config import parse_gameday

# nflverse reports rest in days since the previous game.
BYE_REST = 13
SHORT_WEEK_REST = 5


def kickoff_slot(weekday: str | None, gametime: str | None) -> str:
    """Bucket a kickoff into the slots that actually behave differently."""
    if not weekday:
        return "unknown"
    hour = None
    if gametime:
        try:
            hour = int(gametime.split(":")[0])
        except ValueError:
            hour = None

    if weekday == "Thursday":
        return "thursday_night"
    if weekday in ("Friday", "Saturday"):
        return f"{weekday.lower()}"
    if weekday == "Monday":
        return "monday_night"
    if weekday == "Sunday":
        if hour is None:
            return "sunday_unknown"
        if hour < 12:
            return "sunday_international"
        if hour < 15:
            return "sunday_early"
        if hour < 19:
            return "sunday_late"
        return "sunday_night"
    return weekday.lower()


def is_primetime(slot: str) -> bool:
    return slot in ("thursday_night", "sunday_night", "monday_night")


def _prior_games(games: pl.DataFrame, team: str, season: int, week: int) -> pl.DataFrame:
    """That team's games earlier in the season, most recent first."""
    return (
        games.filter(
            (pl.col("season") == season)
            & (pl.col("week") < week)
            & ((pl.col("home_team") == team) | (pl.col("away_team") == team))
        )
        .sort("week", descending=True)
    )


def _consecutive_road(games: pl.DataFrame, team: str, season: int, week: int) -> int:
    """How many road games in a row the team is on, counting this one."""
    streak = 1
    for row in _prior_games(games, team, season, week).to_dicts():
        if row["away_team"] == team:
            streak += 1
        else:
            break
    return streak


def _previous_slot(games: pl.DataFrame, team: str, season: int, week: int) -> str | None:
    prior = _prior_games(games, team, season, week).head(1).to_dicts()
    if not prior:
        return None
    return kickoff_slot(prior[0].get("weekday"), prior[0].get("gametime"))


def team_situation(
    games: pl.DataFrame, game: dict, team: str, *, is_home: bool
) -> dict:
    """Rest and travel picture for one side of one game."""
    season, week = game["season"], game["week"]
    rest = game["home_rest"] if is_home else game["away_rest"]
    slot = kickoff_slot(game.get("weekday"), game.get("gametime"))

    venue = stadiums.venue(
        game.get("stadium_id"),
        game.get("home_team"),
        stadium=game.get("stadium"),
        neutral=bool(game.get("location") and game["location"] != "Home"),
    )
    origin = stadiums.home_venue(team)

    travel_miles = tz_shift = altitude_change = None
    if venue and origin:
        travel_miles = round(stadiums.haversine_miles(origin, venue))
        gameday: date = parse_gameday(game["gameday"])
        tz_shift = stadiums.tz_shift_hours(origin, venue, gameday)
        altitude_change = venue.elevation_ft - origin.elevation_ft

    prev_slot = _previous_slot(games, team, season, week)

    return {
        "rest_days": rest,
        "off_bye": rest is not None and rest >= BYE_REST,
        "short_week": rest is not None and rest <= SHORT_WEEK_REST,
        "travel_miles": 0 if is_home else travel_miles,
        "timezone_shift_hours": 0.0 if is_home else tz_shift,
        "altitude_change_ft": 0 if is_home else altitude_change,
        "consecutive_road_games": 0 if is_home else _consecutive_road(games, team, season, week),
        "previous_game_slot": prev_slot,
        "off_primetime": is_primetime(prev_slot) if prev_slot else None,
    }


def game_situation(games: pl.DataFrame, game: dict) -> dict:
    home, away = game["home_team"], game["away_team"]
    slot = kickoff_slot(game.get("weekday"), game.get("gametime"))

    # A "home" game at a neutral site is not a home game.
    neutral = bool(game.get("location") and game["location"] != "Home")
    venue = stadiums.venue(
        game.get("stadium_id"), home, stadium=game.get("stadium"), neutral=neutral
    )

    return {
        "kickoff_slot": slot,
        "is_primetime": is_primetime(slot),
        "neutral_site": neutral,
        # Anything outside North America, by the venue's own time zone.
        "international": bool(
            venue and venue.tz.split("/")[0] not in ("America",)
        )
        or (venue is not None and venue.stadium_id in ("SAO00", "RIO00", "MEX00")),
        "venue": venue.name if venue else game.get("stadium"),
        "divisional": bool(game.get("div_game")),
        "same_conference": stadiums.conference(home) == stadiums.conference(away),
        "rest_edge_home": (
            (game["home_rest"] - game["away_rest"])
            if game.get("home_rest") is not None and game.get("away_rest") is not None
            else None
        ),
        "home": team_situation(games, game, home, is_home=not neutral),
        "away": team_situation(games, game, away, is_home=False),
    }

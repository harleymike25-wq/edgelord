"""Venue geography for travel, time-zone shift and altitude features.

Stadium ids occasionally change when a team moves into a new building, so
lookups fall back to the team's canonical home venue and ultimately return
None rather than raising -- a missing travel number is recorded as a data gap,
it should never take down a slate.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass
from datetime import date
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Venue:
    stadium_id: str
    name: str
    lat: float
    lon: float
    elevation_ft: int
    tz: str
    # Only set for neutral-site venues. nflverse inherits `roof` from the home
    # team's stadium on international games -- the Melbourne Cricket Ground is
    # reported as "dome" because SoFi is one -- so an explicit value here
    # overrides it. None means trust the schedule's value.
    roof: str | None = None


VENUES: dict[str, Venue] = {
    v.stadium_id: v
    for v in [
        Venue("PHO00", "State Farm Stadium", 33.5276, -112.2626, 1070, "America/Phoenix"),
        Venue("ATL97", "Mercedes-Benz Stadium", 33.7554, -84.4008, 1050, "America/New_York"),
        Venue("BAL00", "M&T Bank Stadium", 39.2780, -76.6227, 33, "America/New_York"),
        Venue("BUF00", "Highmark Stadium", 42.7738, -78.7870, 600, "America/New_York"),
        Venue("CAR00", "Bank of America Stadium", 35.2258, -80.8528, 725, "America/New_York"),
        Venue("CHI98", "Soldier Field", 41.8623, -87.6167, 597, "America/Chicago"),
        Venue("CIN00", "Paycor Stadium", 39.0955, -84.5161, 490, "America/New_York"),
        Venue("CLE00", "Huntington Bank Field", 41.5061, -81.6995, 581, "America/New_York"),
        Venue("DAL00", "AT&T Stadium", 32.7473, -97.0945, 550, "America/Chicago"),
        Venue("DEN00", "Empower Field at Mile High", 39.7439, -105.0201, 5280, "America/Denver"),
        Venue("DET00", "Ford Field", 42.3400, -83.0456, 600, "America/New_York"),
        Venue("GNB00", "Lambeau Field", 44.5013, -88.0622, 640, "America/Chicago"),
        Venue("HOU00", "NRG Stadium", 29.6847, -95.4107, 49, "America/Chicago"),
        Venue("IND00", "Lucas Oil Stadium", 39.7601, -86.1639, 715, "America/Indiana/Indianapolis"),
        Venue("JAX00", "EverBank Stadium", 30.3239, -81.6373, 16, "America/New_York"),
        Venue("KAN00", "GEHA Field at Arrowhead", 39.0489, -94.4839, 750, "America/Chicago"),
        Venue("LAX01", "SoFi Stadium", 33.9535, -118.3392, 100, "America/Los_Angeles"),
        Venue("VEG00", "Allegiant Stadium", 36.0909, -115.1833, 2030, "America/Los_Angeles"),
        Venue("MIA00", "Hard Rock Stadium", 25.9580, -80.2389, 8, "America/New_York"),
        Venue("MIN01", "U.S. Bank Stadium", 44.9738, -93.2578, 830, "America/Chicago"),
        Venue("BOS00", "Gillette Stadium", 42.0909, -71.2643, 289, "America/New_York"),
        Venue("NOR00", "Caesars Superdome", 29.9511, -90.0812, 3, "America/Chicago"),
        Venue("NYC01", "MetLife Stadium", 40.8135, -74.0745, 7, "America/New_York"),
        Venue("PHI00", "Lincoln Financial Field", 39.9008, -75.1675, 39, "America/New_York"),
        Venue("PIT00", "Acrisure Stadium", 40.4468, -80.0158, 730, "America/New_York"),
        Venue("SEA00", "Lumen Field", 47.5952, -122.3316, 20, "America/Los_Angeles"),
        Venue("SFO01", "Levi's Stadium", 37.4030, -121.9700, 26, "America/Los_Angeles"),
        Venue("TAM00", "Raymond James Stadium", 27.9759, -82.5033, 26, "America/New_York"),
        Venue("NAS00", "Nissan Stadium", 36.1665, -86.7713, 450, "America/Chicago"),
        Venue("WAS00", "Northwest Stadium", 38.9076, -76.8645, 200, "America/New_York"),
        # International venues. `roof` is set explicitly on all of these because
        # the schedule's value belongs to the nominal home team's stadium.
        Venue("LON00", "Wembley Stadium", 51.5560, -0.2795, 150, "Europe/London", "outdoors"),
        Venue("LON02", "Tottenham Hotspur Stadium", 51.6043, -0.0665, 100, "Europe/London", "outdoors"),
        Venue("GER00", "Allianz Arena", 48.2188, 11.6247, 1700, "Europe/Berlin", "outdoors"),
        Venue("SAO00", "Arena Corinthians", -23.5453, -46.4742, 2500, "America/Sao_Paulo", "outdoors"),
        Venue("MEX00", "Estadio Azteca", 19.3029, -99.1505, 7200, "America/Mexico_City", "outdoors"),
        Venue("MAD00", "Estadio Santiago Bernabeu", 40.4531, -3.6883, 2200, "Europe/Madrid", "closed"),
        Venue("DUB00", "Croke Park", 53.3607, -6.2512, 60, "Europe/Dublin", "outdoors"),
        Venue("MEL00", "Melbourne Cricket Ground", -37.8200, 144.9834, 100, "Australia/Melbourne", "outdoors"),
        Venue("RIO00", "Maracana Stadium", -22.9121, -43.2302, 30, "America/Sao_Paulo", "outdoors"),
        Venue("PAR00", "Stade de France", 48.9245, 2.3601, 130, "Europe/Paris", "outdoors"),
    ]
}

# Neutral-site lookup by the stadium *name* nflverse reports.
#
# For international games nflverse keeps the home team's `stadium_id`: the 2026
# Melbourne game carries LAX01 (SoFi Stadium) and the Rio game carries DAL00
# (AT&T Stadium). Resolving those by id yields a short domestic hop with no
# time-zone change for a flight to Australia or Brazil -- backwards on exactly
# the games where travel matters most. Neutral sites are matched on name.
NEUTRAL_VENUE_BY_NAME: dict[str, str] = {
    "melbourne cricket ground": "MEL00",
    "maracana stadium": "RIO00",
    "maracana": "RIO00",
    "stade de france": "PAR00",
    "tottenham hotspur stadium": "LON02",
    "tottenham stadium": "LON02",
    "wembley stadium": "LON00",
    "allianz arena": "GER00",
    "fc bayern munich stadium": "GER00",
    "arena corinthians": "SAO00",
    "estadio azteca": "MEX00",
    "estadio banorte": "MEX00",
    "bernabeu": "MAD00",
    "estadio santiago bernabeu": "MAD00",
    "santiago bernabeu": "MAD00",
    "croke park": "DUB00",
}


def _normalise(name: str) -> str:
    """Lowercase, strip punctuation, and fold accents.

    Sources disagree on diacritics -- nflverse writes "Maracana" while most
    other feeds write "Maracana" with a tilde -- so decompose and drop the
    combining marks rather than maintaining a key per spelling.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    keep = [c.lower() for c in folded if c.isalnum() or c.isspace()]
    return " ".join("".join(keep).split())


def venue_by_name(stadium: str | None) -> Venue | None:
    """Resolve a neutral-site venue from the name nflverse reports."""
    if not stadium:
        return None
    key = NEUTRAL_VENUE_BY_NAME.get(_normalise(stadium))
    return VENUES.get(key) if key else None

HOME_VENUE: dict[str, str] = {
    "ARI": "PHO00", "ATL": "ATL97", "BAL": "BAL00", "BUF": "BUF00",
    "CAR": "CAR00", "CHI": "CHI98", "CIN": "CIN00", "CLE": "CLE00",
    "DAL": "DAL00", "DEN": "DEN00", "DET": "DET00", "GB": "GNB00",
    "HOU": "HOU00", "IND": "IND00", "JAX": "JAX00", "KC": "KAN00",
    "LA": "LAX01", "LAC": "LAX01", "LV": "VEG00", "MIA": "MIA00",
    "MIN": "MIN01", "NE": "BOS00", "NO": "NOR00", "NYG": "NYC01",
    "NYJ": "NYC01", "PHI": "PHI00", "PIT": "PIT00", "SEA": "SEA00",
    "SF": "SFO01", "TB": "TAM00", "TEN": "NAS00", "WAS": "WAS00",
}

DIVISIONS: dict[str, str] = {
    "BUF": "AFC East", "MIA": "AFC East", "NE": "AFC East", "NYJ": "AFC East",
    "BAL": "AFC North", "CIN": "AFC North", "CLE": "AFC North", "PIT": "AFC North",
    "HOU": "AFC South", "IND": "AFC South", "JAX": "AFC South", "TEN": "AFC South",
    "DEN": "AFC West", "KC": "AFC West", "LAC": "AFC West", "LV": "AFC West",
    "DAL": "NFC East", "NYG": "NFC East", "PHI": "NFC East", "WAS": "NFC East",
    "CHI": "NFC North", "DET": "NFC North", "GB": "NFC North", "MIN": "NFC North",
    "ATL": "NFC South", "CAR": "NFC South", "NO": "NFC South", "TB": "NFC South",
    "ARI": "NFC West", "LA": "NFC West", "SF": "NFC West", "SEA": "NFC West",
}


def venue(
    stadium_id: str | None,
    fallback_team: str | None = None,
    *,
    stadium: str | None = None,
    neutral: bool = False,
) -> Venue | None:
    """Resolve the venue a game is actually played at.

    `neutral` must be set for games nflverse marks with a location other than
    "Home"; those carry the home team's stadium_id rather than the real one, so
    the name takes precedence.
    """
    if neutral:
        by_name = venue_by_name(stadium)
        if by_name:
            return by_name
    if stadium_id and stadium_id in VENUES:
        return VENUES[stadium_id]
    if fallback_team and fallback_team in HOME_VENUE:
        return VENUES.get(HOME_VENUE[fallback_team])
    return None


def home_venue(team: str) -> Venue | None:
    return VENUES.get(HOME_VENUE.get(team, ""))


def haversine_miles(a: Venue, b: Venue) -> float:
    r = 3958.8
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def tz_shift_hours(origin: Venue, destination: Venue, on: date) -> float:
    """Signed hour shift the travelling team's body clock takes.

    Positive means travelling east (losing hours), which is the direction the
    research consistently finds harder.
    """
    from datetime import datetime

    noon = datetime(on.year, on.month, on.day, 12)
    o = noon.replace(tzinfo=ZoneInfo(origin.tz)).utcoffset()
    d = noon.replace(tzinfo=ZoneInfo(destination.tz)).utcoffset()
    if o is None or d is None:
        return 0.0
    return (d.total_seconds() - o.total_seconds()) / 3600.0


def same_division(a: str, b: str) -> bool:
    return a in DIVISIONS and DIVISIONS.get(a) == DIVISIONS.get(b)


def conference(team: str) -> str | None:
    div = DIVISIONS.get(team)
    return div.split()[0] if div else None

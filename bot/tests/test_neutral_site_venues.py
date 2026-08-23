"""Neutral-site venue resolution.

nflverse gives international games the *home team's* `stadium_id`: the 2026
Melbourne game carries LAX01 (SoFi Stadium) and the Rio game carries DAL00
(AT&T Stadium). Resolving by id turns a flight to Australia into a 350-mile
hop with no time-zone change, silently and with no error -- on exactly the
games where travel is the biggest factor in the pack.

These tests pin the name-based resolution that fixes it.
"""

import datetime

import pytest

from edgelord.sources import stadiums


class TestNameResolution:
    def test_melbourne(self):
        v = stadiums.venue_by_name("Melbourne Cricket Ground")
        assert v is not None and v.stadium_id == "MEL00"

    def test_punctuation_and_case_are_ignored(self):
        assert stadiums.venue_by_name("MARACANÃ STADIUM.") is not None
        assert stadiums.venue_by_name("  stade   de   france  ") is not None

    def test_renamed_venues_map_to_the_same_place(self):
        """Sponsors rename stadiums; the geography does not move."""
        assert stadiums.venue_by_name("Estadio Banorte") == stadiums.venue_by_name(
            "Estadio Azteca"
        )
        assert stadiums.venue_by_name("FC Bayern Munich Stadium") == (
            stadiums.venue_by_name("Allianz Arena")
        )
        assert stadiums.venue_by_name("Bernabeu") == stadiums.venue_by_name(
            "Estadio Santiago Bernabeu"
        )

    def test_unknown_name_returns_none(self):
        assert stadiums.venue_by_name("Somewhere Not In The Table") is None

    def test_empty_input(self):
        assert stadiums.venue_by_name(None) is None
        assert stadiums.venue_by_name("") is None


class TestVenueDispatch:
    def test_neutral_prefers_name_over_the_misleading_id(self):
        # The real 2026 row: Melbourne game carrying SoFi Stadium's id.
        v = stadiums.venue("LAX01", "LA", stadium="Melbourne Cricket Ground", neutral=True)
        assert v.stadium_id == "MEL00"

    def test_home_game_still_uses_the_id(self):
        v = stadiums.venue("LAX01", "LA", stadium="SoFi Stadium", neutral=False)
        assert v.stadium_id == "LAX01"

    def test_neutral_with_unknown_name_falls_back_to_the_id(self):
        """Degrades to wrong-but-present rather than crashing; build.py flags it."""
        v = stadiums.venue("DAL00", "DAL", stadium="Some New Stadium", neutral=True)
        assert v.stadium_id == "DAL00"

    def test_unknown_id_falls_back_to_the_team(self):
        v = stadiums.venue("ZZZ99", "GB")
        assert v.stadium_id == "GNB00"


class TestTravelIsActuallyRight:
    """The numbers that would have been wrong, checked against reality."""

    def _miles(self, away, stadium_id, home, stadium):
        v = stadiums.venue(stadium_id, home, stadium=stadium, neutral=True)
        return round(stadiums.haversine_miles(stadiums.home_venue(away), v))

    def test_sf_to_melbourne_is_not_a_california_trip(self):
        miles = self._miles("SF", "LAX01", "LA", "Melbourne Cricket Ground")
        assert 7500 < miles < 8300, miles
        # The bug produced roughly this instead.
        assert miles > 1000

    def test_baltimore_to_rio(self):
        miles = self._miles("BAL", "DAL00", "DAL", "Maracana Stadium")
        assert 4500 < miles < 5100, miles

    def test_minnesota_to_mexico_city(self):
        miles = self._miles("MIN", "SFO01", "SF", "Estadio Banorte")
        assert 1600 < miles < 2000, miles


class TestTimezoneShift:
    def test_melbourne_is_a_huge_shift(self):
        v = stadiums.venue("LAX01", "LA", stadium="Melbourne Cricket Ground", neutral=True)
        shift = stadiums.tz_shift_hours(
            stadiums.home_venue("SF"), v, datetime.date(2026, 9, 10)
        )
        # Melbourne is ~17 hours ahead of Pacific in September.
        assert abs(shift) >= 16, shift

    def test_london_shift_is_moderate(self):
        v = stadiums.venue("JAX00", "JAX", stadium="Wembley Stadium", neutral=True)
        shift = stadiums.tz_shift_hours(
            stadiums.home_venue("HOU"), v, datetime.date(2026, 10, 18)
        )
        assert shift == pytest.approx(6.0)


class TestAllScheduledNeutralSitesResolve:
    """Every 2026 neutral site must be in the table, not just the ones tested."""

    KNOWN_2026 = [
        "Melbourne Cricket Ground",
        "Maracana Stadium",
        "Tottenham Hotspur Stadium",
        "Wembley Stadium",
        "Stade de France",
        "Bernabeu",
        "FC Bayern Munich Stadium",
        "Estadio Banorte",
    ]

    @pytest.mark.parametrize("name", KNOWN_2026)
    def test_resolves(self, name):
        assert stadiums.venue_by_name(name) is not None, name

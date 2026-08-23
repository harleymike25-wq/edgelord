"""The spread sign convention is the easiest thing here to get silently wrong.

The Odds API quotes the favourite with a negative point; nflverse quotes the
home team's line as positive when home is favoured. Everything downstream
(key numbers, movement direction, grading) assumes the nflverse convention, so
a flipped sign would corrupt results without ever raising an error.
"""

from edgelord.sources import odds

CAPTURED = "2026-09-10T15:00:00+00:00"

# Home favoured by 6.5: the API reports the home team at -6.5.
HOME_FAVOURED = {
    "id": "evt1",
    "commence_time": "2026-09-13T17:00:00Z",
    "home_team": "Tampa Bay Buccaneers",
    "away_team": "Dallas Cowboys",
    "bookmakers": [
        {
            "key": "draftkings",
            "last_update": "2026-09-10T14:58:00Z",
            "markets": [
                {
                    "key": "spreads",
                    "outcomes": [
                        {"name": "Tampa Bay Buccaneers", "price": -111, "point": -6.5},
                        {"name": "Dallas Cowboys", "price": -109, "point": 6.5},
                    ],
                },
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": -110, "point": 48.5},
                        {"name": "Under", "price": -110, "point": 48.5},
                    ],
                },
                {
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Tampa Bay Buccaneers", "price": -280},
                        {"name": "Dallas Cowboys", "price": 230},
                    ],
                },
            ],
        }
    ],
}


def test_home_favourite_becomes_positive():
    (row,) = odds.parse_event(HOME_FAVOURED, CAPTURED)
    # nflverse convention: positive spread_home means the home team is favoured.
    assert row["spread_home"] == 6.5
    assert row["home_team"] == "TB"
    assert row["away_team"] == "DAL"
    assert row["spread_home_price"] == -111
    assert row["spread_away_price"] == -109


def test_away_favourite_becomes_negative():
    event = {
        **HOME_FAVOURED,
        "bookmakers": [
            {
                "key": "fanduel",
                "last_update": "2026-09-10T14:59:00Z",
                "markets": [
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Tampa Bay Buccaneers", "price": -105, "point": 3.0},
                            {"name": "Dallas Cowboys", "price": -115, "point": -3.0},
                        ],
                    }
                ],
            }
        ],
    }
    (row,) = odds.parse_event(event, CAPTURED)
    assert row["spread_home"] == -3.0


def test_totals_and_moneyline():
    (row,) = odds.parse_event(HOME_FAVOURED, CAPTURED)
    assert row["total"] == 48.5
    assert row["over_price"] == -110
    assert row["under_price"] == -110
    assert row["ml_home"] == -280
    assert row["ml_away"] == 230


def test_one_row_per_book():
    event = {
        **HOME_FAVOURED,
        "bookmakers": HOME_FAVOURED["bookmakers"] * 3,
    }
    assert len(odds.parse_event(event, CAPTURED)) == 3


def test_unknown_team_falls_back_to_full_name():
    event = {**HOME_FAVOURED, "home_team": "Toronto Huskies"}
    (row,) = odds.parse_event(event, CAPTURED)
    assert row["home_team"] == "Toronto Huskies"

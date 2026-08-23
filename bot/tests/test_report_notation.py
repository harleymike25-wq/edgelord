"""Spread display notation.

The database stores a line as "the picked side is favoured by N", but books
display the inverse. Getting this backwards makes every spread on the report
read as its own opposite, which is the kind of error a reader would act on.
"""

from edgelord.report import _describe_pick


def row(**kw):
    base = {
        "pick_type": "spread", "pick_side": "CHI", "home_team": "CHI",
        "line_at_pick": None, "spread_line": None, "total_line": None,
    }
    base.update(kw)
    return base


def test_favourite_shows_as_laying_points():
    # BAL favoured by 14 -> a bettor sees BAL -14.
    assert _describe_pick(row(pick_side="BAL", home_team="BAL", line_at_pick=14.0)) == "BAL -14"


def test_underdog_shows_as_getting_points():
    # HOU favoured by -5.5, i.e. getting 5.5 -> HOU +5.5.
    assert _describe_pick(row(pick_side="HOU", home_team="HOU", line_at_pick=-5.5)) == "HOU +5.5"


def test_away_underdog():
    assert _describe_pick(row(pick_side="PIT", home_team="CHI", line_at_pick=-3.0)) == "PIT +3"


def test_pick_em():
    assert _describe_pick(row(line_at_pick=0.0)) == "CHI +0"


def test_falls_back_to_closing_line_for_home_side():
    # No snapshot; spread_line 6.5 means home is laying 6.5.
    assert _describe_pick(row(spread_line=6.5)) == "CHI -6.5"


def test_falls_back_to_closing_line_for_away_side():
    # Same game from the away side: PIT is getting 6.5.
    assert _describe_pick(
        row(pick_side="PIT", home_team="CHI", spread_line=6.5)
    ) == "PIT +6.5"


def test_totals_are_not_inverted():
    assert _describe_pick(row(pick_type="total", pick_side="over", line_at_pick=45.5)) == "Over 45.5"
    assert _describe_pick(row(pick_type="total", pick_side="under", line_at_pick=45.5)) == "Under 45.5"


def test_pass():
    assert _describe_pick(row(pick_type="pass", pick_side="none")) == "No play"

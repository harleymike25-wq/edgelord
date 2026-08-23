"""Grading maths.

A sign error here produces plausible-looking records that are quietly wrong,
so each convention gets an explicit case: a favourite that covers, a favourite
that wins but fails to cover, a push, and CLV in both directions.
"""

import pytest

from edgelord import track

HOME = "CHI"
AWAY = "PIT"


class TestSpreadGrading:
    def test_home_favourite_covers(self):
        # CHI laying 3, wins by 7.
        assert track._spread_grade(HOME, HOME, 3.0, 27, 20) == "win"

    def test_home_favourite_wins_but_fails_to_cover(self):
        # CHI laying 3, wins by 1. Won the game, lost the bet.
        assert track._spread_grade(HOME, HOME, 3.0, 21, 20) == "loss"

    def test_push_on_the_number(self):
        assert track._spread_grade(HOME, HOME, 3.0, 23, 20) == "push"

    def test_away_underdog_covers_while_losing(self):
        # PIT getting 3 (line -3 from PIT's view), loses by 1.
        assert track._spread_grade(AWAY, HOME, -3.0, 21, 20) == "win"

    def test_away_underdog_loses_by_more_than_the_number(self):
        assert track._spread_grade(AWAY, HOME, -3.0, 31, 20) == "loss"

    def test_away_favourite_covers(self):
        # PIT laying 6, wins by 10.
        assert track._spread_grade(AWAY, HOME, 6.0, 17, 27) == "win"


class TestTotalGrading:
    def test_over_hits(self):
        assert track._total_grade("over", 45.5, 27, 20) == "win"

    def test_over_misses(self):
        assert track._total_grade("over", 45.5, 17, 20) == "loss"

    def test_under_hits(self):
        assert track._total_grade("under", 45.5, 17, 20) == "win"

    def test_exact_total_pushes_both_ways(self):
        assert track._total_grade("over", 47.0, 27, 20) == "push"
        assert track._total_grade("under", 47.0, 27, 20) == "push"


class TestPayout:
    def test_standard_juice(self):
        assert track.payout(-110) == pytest.approx(0.909, abs=1e-3)

    def test_plus_money(self):
        assert track.payout(130) == pytest.approx(1.30)

    def test_missing_price_defaults_to_standard(self):
        assert track.payout(None) == track.payout(-110)


class TestCLV:
    def test_beating_the_close_as_underdog(self):
        # Took PIT +4 (line -4), market closed PIT +3 (spread_home 3).
        # We hold the better number.
        clv = track._clv("spread", AWAY, HOME, -4.0, 3.0, None)
        assert clv == pytest.approx(1.0)

    def test_losing_to_the_close_as_underdog(self):
        # Took PIT +3, market closed PIT +4. Worse number.
        clv = track._clv("spread", AWAY, HOME, -3.0, 4.0, None)
        assert clv == pytest.approx(-1.0)

    def test_beating_the_close_as_favourite(self):
        # Laid CHI -2.5 and it closed -3.5: we laid fewer points.
        clv = track._clv("spread", HOME, HOME, 2.5, 3.5, None)
        assert clv == pytest.approx(1.0)

    def test_over_beats_close_when_total_rises(self):
        # Took over 44, closed 46 -- our number is easier.
        assert track._clv("total", "over", HOME, 44.0, None, 46.0) == pytest.approx(2.0)

    def test_under_beats_close_when_total_falls(self):
        assert track._clv("total", "under", HOME, 46.0, None, 44.0) == pytest.approx(2.0)

    def test_no_line_gives_no_clv(self):
        assert track._clv("spread", HOME, HOME, None, 3.0, None) is None

    def test_pass_has_no_clv(self):
        assert track._clv("pass", "none", HOME, 3.0, 3.0, 45.0) is None

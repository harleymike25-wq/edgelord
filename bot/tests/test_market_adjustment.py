"""Turning the model's move off the line back into a home margin.

The model no longer projects a margin. It states how far it moves the market
number, and `derived_margin` reconstructs the margin the rest of the system
stores -- so this one function sits between the model and every downstream
consumer of `projected_margin`: grading, CLV, the post-mortem miss, the report.

That makes it exactly the kind of sign-sensitive arithmetic that has already
gone wrong once in this project. An inverted adjustment would not raise an
error; it would silently reverse which side every pick is arguing for and still
produce plausible numbers. So the sign is checked from both directions, on both
home and away favourites, and across zero.
"""

import pytest

from edgelord import predict

HOME = "BBB"
AWAY = "AAA"


def _pack(spread_home):
    """Only the market block matters here."""
    return {
        "game": {"game_id": "2026_01_AAA_BBB", "home_team": HOME, "away_team": AWAY},
        "market": {"current_spread_home": spread_home},
    }


def _result(adjustment):
    return {"market_adjustment": adjustment}


class TestSignConvention:
    """positive spread_home = home favoured; positive adjustment = toward home."""

    def test_zero_adjustment_reproduces_the_line(self):
        """The one case that must be exact: agreeing with the market."""
        assert predict.derived_margin(_pack(3.0), _result(0.0)) == 3.0

    def test_moving_toward_home_widens_a_home_favourite(self):
        assert predict.derived_margin(_pack(3.0), _result(2.0)) == 5.0

    def test_moving_away_from_home_narrows_a_home_favourite(self):
        assert predict.derived_margin(_pack(3.0), _result(-2.0)) == 1.0

    def test_moving_toward_home_narrows_an_away_favourite(self):
        # Away favoured by 6; a +2 move toward home makes it 4.
        assert predict.derived_margin(_pack(-6.0), _result(2.0)) == -4.0

    def test_moving_away_from_home_widens_an_away_favourite(self):
        assert predict.derived_margin(_pack(-6.0), _result(-2.0)) == -8.0

    def test_a_move_can_cross_zero_and_flip_the_favourite(self):
        """The model may disagree about who wins, not just by how much."""
        assert predict.derived_margin(_pack(2.0), _result(-5.0)) == -3.0

    def test_pickem_takes_the_adjustment_directly(self):
        assert predict.derived_margin(_pack(0.0), _result(3.5)) == 3.5


class TestNoMarketNumber:
    """A game with no line falls back to a pick'em baseline.

    Rare, but the field has to keep meaning the same thing or the post-mortem
    arithmetic reads a margin that was measured from a different zero.
    """

    def test_missing_spread_is_treated_as_a_pickem(self):
        assert predict.derived_margin(_pack(None), _result(4.0)) == 4.0

    def test_absent_market_block_is_treated_as_a_pickem(self):
        pack = {"game": {"home_team": HOME, "away_team": AWAY}}
        assert predict.derived_margin(pack, _result(-2.5)) == -2.5

    def test_null_market_block_is_treated_as_a_pickem(self):
        pack = {"game": {"home_team": HOME, "away_team": AWAY}, "market": None}
        assert predict.derived_margin(pack, _result(1.5)) == 1.5


class TestShapeOfTheOutput:
    def test_half_points_survive(self):
        assert predict.derived_margin(_pack(3.5), _result(-1.5)) == 2.0

    def test_result_is_rounded_not_truncated(self):
        assert predict.derived_margin(_pack(2.5), _result(0.25)) == 2.75

    def test_integer_inputs_are_accepted(self):
        """Structured output may hand back an int where a float is declared."""
        assert predict.derived_margin(_pack(3), _result(2)) == 5.0


class TestTheBiasItExistsToPrevent:
    """A compressed projection is now a stated move, not a silent default.

    Under the old free-floating format the model could return a margin nearer
    zero than the spread without ever saying it had moved the number. These
    pin the property that makes the compression visible: the distance from the
    market is the adjustment, and nothing else.
    """

    @pytest.mark.parametrize("spread", [-9.5, -3.0, 0.0, 3.0, 9.5])
    def test_the_move_is_exactly_the_distance_from_the_market(self, spread):
        for adjustment in (-3.5, -1.0, 0.0, 1.0, 3.5):
            margin = predict.derived_margin(_pack(spread), _result(adjustment))
            assert margin - spread == pytest.approx(adjustment)

    def test_agreeing_with_the_market_cannot_manufacture_dog_value(self):
        """A zero move leaves no gap for either side to be 'value'."""
        for spread in (-7.0, -1.5, 0.0, 1.5, 7.0):
            assert predict.derived_margin(_pack(spread), _result(0.0)) == spread


class TestSchemaContract:
    """The schema and the derivation have to agree on the field name."""

    def test_market_adjustment_is_required(self):
        assert "market_adjustment" in predict.RESPONSE_SCHEMA["required"]

    def test_projected_margin_is_no_longer_asked_of_the_model(self):
        assert "projected_margin" not in predict.RESPONSE_SCHEMA["properties"]
        assert "projected_margin" not in predict.RESPONSE_SCHEMA["required"]

    def test_projected_total_is_still_asked_for_directly(self):
        """Totals are unchanged -- only the spread carried the dog bias."""
        assert "projected_total" in predict.RESPONSE_SCHEMA["required"]

"""The best-bet rating, computed from the move off the line.

The model was asked to hold itself to this bar and did not: Week 2 of 2026 had
seven picks moving the number two points or more and none rated best_bet. The
rating is now arithmetic, which means a sign error would silently promote the
wrong picks -- so the edge is checked from both sides of the ball, and the
key-number rule on both the dog and the favourite.
"""

from edgelord import predict

HOME = "BBB"
AWAY = "AAA"


def _pack(spread_home=None, total=None, *, prior_weight=None, continuity=None):
    side = {}
    if prior_weight is not None:
        side["efficiency_provenance"] = {"prior_season_weight": prior_weight}
    if continuity is not None:
        side["roster_turnover"] = {"overall_continuity": continuity}
    return {
        "game": {"game_id": "2026_03_AAA_BBB", "home_team": HOME, "away_team": AWAY},
        "market": {"current_spread_home": spread_home, "current_total": total},
        "home": side,
        "away": {},
    }


def _spread(side, adjustment):
    return {"pick_type": "spread", "pick_side": side, "market_adjustment": adjustment}


def _total(side, projected):
    return {"pick_type": "total", "pick_side": side, "projected_total": projected}


def rate(pack, result):
    return predict.computed_conviction(pack, result)


class TestEdgeBar:
    def test_two_points_toward_home_is_a_best_bet(self):
        assert rate(_pack(9.5), _spread(HOME, 2.0)) == "best_bet"

    def test_two_points_toward_away_is_a_best_bet(self):
        # Negative adjustment moves toward the away side.
        assert rate(_pack(9.5), _spread(AWAY, -2.0)) == "best_bet"

    def test_move_against_the_picked_side_is_never_a_best_bet(self):
        # DAL/NYG: a pick whose own number argued for the other team.
        assert rate(_pack(9.5), _spread(AWAY, 2.5)) == "lean"
        assert rate(_pack(9.5), _spread(HOME, -2.5)) == "lean"

    def test_under_the_bar_is_a_lean(self):
        assert rate(_pack(9.5), _spread(HOME, 1.5)) == "lean"

    def test_bar_rises_when_figures_are_mostly_last_season(self):
        assert rate(_pack(9.5, prior_weight=0.6), _spread(HOME, 2.5)) == "lean"
        assert rate(_pack(9.5, prior_weight=0.6), _spread(HOME, 3.0)) == "best_bet"

    def test_bar_rises_on_low_roster_continuity(self):
        assert rate(_pack(9.5, continuity=0.65), _spread(HOME, 2.5)) == "lean"
        assert rate(_pack(9.5, continuity=0.75), _spread(HOME, 2.5)) == "best_bet"

    def test_no_line_is_a_lean(self):
        assert rate(_pack(None), _spread(HOME, 4.0)) == "lean"


class TestKeyNumbers:
    def test_dog_at_three_and_a_half_projected_inside_three(self):
        # Home favoured by 3.5; taking the away dog, moved 1 toward it -> -2.5.
        assert rate(_pack(3.5), _spread(AWAY, -1.0)) == "best_bet"

    def test_favourite_laying_two_and_a_half_projected_to_win_by_three(self):
        assert rate(_pack(2.5), _spread(HOME, 1.0)) == "best_bet"

    def test_away_favourite_through_seven(self):
        # Away favoured by 6.5 (spread_home -6.5); moved 1 toward away -> 7.5.
        assert rate(_pack(-6.5), _spread(AWAY, -1.0)) == "best_bet"

    def test_half_point_through_a_key_is_not_enough(self):
        assert rate(_pack(3.5), _spread(AWAY, -0.5)) == "lean"

    def test_a_point_that_crosses_nothing_is_a_lean(self):
        assert rate(_pack(4.5), _spread(HOME, 1.0)) == "lean"


class TestTotals:
    def test_under_two_below_is_a_best_bet(self):
        assert rate(_pack(3.0, 45.5), _total("under", 43.5)) == "best_bet"

    def test_over_projected_below_the_total_is_a_lean(self):
        assert rate(_pack(3.0, 45.5), _total("over", 43.0)) == "lean"

    def test_over_two_above_is_a_best_bet(self):
        assert rate(_pack(3.0, 45.5), _total("over", 47.5)) == "best_bet"

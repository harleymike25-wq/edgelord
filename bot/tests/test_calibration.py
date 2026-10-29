"""Learned factor corrections: shrunk toward no change, applied in code, and
fitted on the model's raw points rather than their own output."""

import random

from edgelord import calibration, shadow
from tests.test_shadow import AWAY, HOME, _out, _pack


def _games(n, true_worth=1.0, factor="team_strength", seed=1):
    """Games where `factor` is really worth `true_worth` times the model's points."""
    rng = random.Random(seed)
    data = []
    for _ in range(n):
        pts = {k: 0.0 for k in shadow.FACTOR_KEYS}
        pts[factor] = rng.uniform(-6, 6)
        pts["home_field"] = 1.5
        margin = true_worth * pts[factor] + 1.5 + rng.gauss(0, shadow.SIGMA)
        data.append({"game_id": "g", "margin": margin, "points": pts})
    return data


class TestFit:
    def test_no_games_means_no_change(self):
        c = calibration.fit([])
        assert c["n_games"] == 0
        assert set(c["multipliers"].values()) == {1.0}

    def test_a_week_barely_moves_a_factor(self):
        # Even if team strength is really worth half, 14 games cannot say so.
        m = calibration.fit(_games(14, true_worth=0.5))["multipliers"]["team_strength"]
        assert 0.8 < m <= 1.05

    def test_a_long_run_of_misses_does_move_it(self):
        m = calibration.fit(_games(3000, true_worth=0.5))["multipliers"]["team_strength"]
        assert 0.5 <= m < 0.75

    def test_unused_factor_stays_exactly_one(self):
        c = calibration.fit(_games(50))
        assert c["multipliers"]["weather"] == 1.0
        assert c["factors"]["weather"]["games"] == 0

    def test_correction_is_bounded(self):
        data = _games(5000, true_worth=0.0)
        for d in data:
            d["margin"] -= 10 * d["points"]["team_strength"]
        m = calibration.fit(data)["multipliers"]["team_strength"]
        assert m == calibration.FLOOR


class TestAssemble:
    def test_multipliers_scale_the_sum_and_raw_is_kept(self):
        out = _out(team_strength=4.0, home_field=2.0)
        calc = shadow.assemble(_pack(spread=3.0), out, {"projected_home": 5.0},
                               {"multipliers": {"team_strength": 0.5}, "n_games": 40})
        assert calc["raw_margin"] == 6.0
        assert calc["projected_margin"] == 4.0
        assert calc["raw_points"]["team_strength"] == 4.0
        assert calc["signed_points"]["team_strength"] == 2.0
        assert calc["calibration"]["n_games"] == 40

    def test_no_calibration_is_the_old_sum(self):
        calc = shadow.assemble(_pack(), _out(team_strength=4.0, home_field=2.0), None)
        assert calc["projected_margin"] == calc["raw_margin"] == 6.0

    def test_stored_pick_carries_raw_points_for_the_next_fit(self):
        pack = _pack(spread=3.0)
        out = _out(team_strength=-4.0, home_field=2.0)
        calc = shadow.assemble(pack, out, {"projected_home": 0.0},
                               {"multipliers": {"team_strength": 0.5}, "n_games": 40})
        pred = shadow.to_prediction(pack, out, calc)
        assert pred["factor_points"]["raw"]["team_strength"] == -4.0
        # Shown factors add up to the shown margin.
        assert pred["key_factors"][0] in ("Team strength: AAA +2", "Home field: BBB +2")


class TestReconstruct:
    def test_single_slight_factor_takes_the_exact_remainder(self):
        kf = ["Team strength: BBB +3", "Home field: BBB +1.5"]
        table = [
            {"factor": "Team strength", "favors": HOME, "weight": "decisive"},
            {"factor": "Home field", "favors": HOME, "weight": "moderate"},
            {"factor": "Rest and travel", "favors": AWAY, "weight": "slight"},
            {"factor": "Weather", "favors": "neither", "weight": "none"},
        ]
        raw = calibration.reconstruct(HOME, AWAY, 3.9, kf, table)
        assert raw["team_strength"] == 3.0 and raw["home_field"] == 1.5
        assert raw["rest_travel"] == -0.6
        assert raw["weather"] == 0.0
        assert round(sum(raw.values()), 2) == 3.9

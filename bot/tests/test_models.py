"""The computed models: Elo moves the right way, the QB value shrinks a thin
sample toward replacement, and the report card reads the line correctly."""

import polars as pl
import pytest

from edgelord.models import common, elo, qb


def _games(rows):
    base = {"game_type": "REG", "neutral": False, "home_rest": 7, "away_rest": 7,
            "spread_line": 0.0, "market_prob": None,
            "home_qb_id": None, "away_qb_id": None}
    out = []
    for i, r in enumerate(rows):
        g = {**base, "game_id": f"G{i}", "week": i + 1, **r}
        g["margin"] = None if g.get("hs") is None else g["hs"] - g["as"]
        out.append(g)
    return pl.DataFrame(out, infer_schema_length=None)


class TestElo:
    def test_winner_gains_and_projection_follows(self):
        g = _games([
            {"season": 2020, "home_team": "AAA", "away_team": "BBB", "hs": 30, "as": 10},
            {"season": 2020, "home_team": "BBB", "away_team": "AAA", "hs": None, "as": None},
        ])
        rep = elo.replay(g, elo.Params(hfa=0.0))
        assert rep["projected"][0] == 0.0
        # AAA won, so as the away side in game two it is projected to win.
        assert rep["projected"][1] < 0
        assert rep["elo_away"][1] > elo.MEAN > rep["elo_home"][1]

    def test_home_field_and_neutral_site(self):
        g = _games([
            {"season": 2020, "home_team": "AAA", "away_team": "BBB", "hs": None, "as": None},
            {"season": 2020, "home_team": "CCC", "away_team": "DDD", "hs": None, "as": None,
             "neutral": True},
        ])
        rep = elo.replay(g, elo.Params(hfa=40.0, elo_per_point=20.0))
        assert rep["projected"].to_list() == [2.0, 0.0]

    def test_offseason_pulls_back_toward_the_mean(self):
        g = _games([
            {"season": 2020, "home_team": "AAA", "away_team": "BBB", "hs": 40, "as": 0},
            {"season": 2021, "home_team": "AAA", "away_team": "BBB", "hs": None, "as": None},
        ])
        full = elo.replay(g, elo.Params(hfa=0.0, revert=0.0))
        half = elo.replay(g, elo.Params(hfa=0.0, revert=0.5))
        # Ratings are reported to one decimal.
        assert half["elo_home"][1] - elo.MEAN == pytest.approx(
            (full["elo_home"][1] - elo.MEAN) / 2, abs=0.1)


class TestQuarterback:
    def test_thin_sample_sits_near_replacement(self):
        st = qb._State(qb.Params(prior_dropbacks=200, replacement=-0.2))
        st.add("thin", 2020, 20, 20 * 0.4)
        st.add("thick", 2020, 600, 600 * 0.3)
        assert st.value("unknown") == pytest.approx(-0.2)
        assert st.value("thin") < -0.1
        assert st.value("thick") > 0.1

    def test_backup_start_moves_the_line_against_his_team(self):
        g = _games([
            {"season": 2020, "home_team": "AAA", "away_team": "BBB", "hs": 20, "as": 20,
             "home_qb_id": "star", "away_qb_id": "b1"},
            {"season": 2020, "home_team": "AAA", "away_team": "BBB", "hs": None, "as": None,
             "home_qb_id": "backup", "away_qb_id": "b1"},
        ])
        qbg = pl.DataFrame({"game_id": ["G0", "G0"], "passer_id": ["star", "b1"],
                            "dropbacks": [400, 400], "epa": [400 * 0.3, 0.0]})
        rep = qb.replay(g, qbg, qb.Params(team_alpha=1.0, scale=20.0), elo.Params(hfa=0.0))
        second = rep.row(1, named=True)
        assert second["qb_home_adj"] < 0
        assert second["projected"] < second["elo_projected"]


class TestReportCard:
    def test_line_favourite_and_model_scored_on_the_same_games(self):
        df = pl.DataFrame({
            "projected": [3.0, -3.0, 2.0, -1.0],
            "market": [3.0, 3.0, -2.0, -1.0],
            "market_prob": [None, None, None, None],
            "margin": [7, -3, 1, -10],
        }, schema_overrides={"market_prob": pl.Float64})
        card = common.report_card(df, 13.5)
        assert card["games"] == 4
        assert card["winners"]["model"]["accuracy"] == 1.0
        assert card["winners"]["line"]["accuracy"] == 0.5
        assert card["winners"]["disagreements"] == {
            "games": 2, "model_right": 2, "model_right_pct": 1.0}

    def test_moneyline_is_devigged(self):
        g = pl.DataFrame({"home_moneyline": [-200], "away_moneyline": [170]}).with_columns(
            common._no_vig("home_moneyline", "away_moneyline").alias("p"))
        assert 0.64 < g["p"][0] < 0.66

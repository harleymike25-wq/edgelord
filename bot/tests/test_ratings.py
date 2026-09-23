"""Power ratings from final scores.

The replay is only worth anything if a projection never sees its own result,
and the ratings are only readable if the signs match `spread_line` (positive =
home favoured). Both would fail silently -- a leaking replay just looks
brilliant -- so both are pinned here on synthetic seasons where the right
answer is known.
"""

import polars as pl
import pytest

from edgelord import ratings as R


def _games(rows):
    """rows: (season, week, home, away, home_score, away_score, spread, neutral)"""
    df = pl.DataFrame(
        [
            {
                "game_id": f"{s}_{w:02d}_{a}_{h}", "season": s, "week": w,
                "game_type": "REG", "gameday": f"{s}-09-{w:02d}",
                "location": "Neutral" if n else "Home",
                "home_team": h, "away_team": a, "home_score": hs, "away_score": as_,
                "spread_line": sp,
            }
            for s, w, h, a, hs, as_, sp, n in rows
        ],
        schema_overrides={"home_score": pl.Int64, "away_score": pl.Int64},
    )
    return df.with_columns(
        (pl.col("home_score") - pl.col("away_score")).alias("margin"),
        (pl.col("location") != "Neutral").cast(pl.Float64).alias("home_field"),
    )


P = R.Params(prior_weight=0.5, ridge=0.5, margin_cap=99.0, recency=1.0)


def _season(strong="AAA", weak="BBB", margin=10):
    """A plays B four times on neutral ground and always wins by `margin`."""
    return [(2025, w, strong, weak, 20 + margin, 20, 0.0, True) for w in range(1, 5)]


class TestSigns:
    def test_the_team_that_keeps_winning_rates_higher(self):
        r, _ = R.fit(_games(_season()), 2025, 5, P)
        assert r["AAA"] > r["BBB"]
        assert r["AAA"] + r["BBB"] == pytest.approx(0.0)

    def test_projection_is_a_home_margin(self):
        r, hfa = R.fit(_games(_season()), 2025, 5, P)
        # Strong team at home: positive, i.e. home favoured, as spread_line.
        assert R.project(r, hfa, "AAA", "BBB", neutral=True) > 0
        assert R.project(r, hfa, "BBB", "AAA", neutral=True) < 0

    def test_home_field_is_fitted_and_skipped_on_neutral_ground(self):
        # Equal teams; the home side always wins by 3.
        rows = [
            (2025, w, *(("AAA", "BBB") if w % 2 else ("BBB", "AAA")), 23, 20, 0.0, False)
            for w in range(1, 9)
        ]
        r, hfa = R.fit(_games(rows), 2025, 9, P)
        assert hfa == pytest.approx(3.0, abs=0.01)
        assert R.project(r, hfa, "AAA", "BBB", neutral=True) == pytest.approx(0.0, abs=0.01)

    def test_relocated_codes_are_one_franchise(self):
        assert R.RELOCATED["OAK"] == "LV" and R.RELOCATED["SD"] == "LAC"


class TestNoLeak:
    def test_a_week_is_fitted_only_on_earlier_weeks(self):
        rows = _season(margin=10) + [(2025, 5, "BBB", "AAA", 70, 0, 0.0, True)]
        before, _ = R.fit(_games(rows), 2025, 5, P)
        without, _ = R.fit(_games(_season(margin=10)), 2025, 5, P)
        assert before == pytest.approx(without)

    def test_replay_projection_ignores_its_own_result(self):
        rows = _season(margin=10) + [(2025, 5, "BBB", "AAA", 70, 0, 0.0, True)]
        rep = R.replay(_games(rows), [2025], P)
        wk5 = rep.filter(pl.col("week") == 5).row(0, named=True)
        # Projected from four A wins, so B at "home" is still the underdog
        # despite winning this game by 70.
        assert wk5["projected"] < 0

    def test_last_season_is_the_prior_for_week_one(self):
        rows = [(2024, w, "AAA", "BBB", 30, 20, 0.0, True) for w in range(1, 5)]
        r, _ = R.fit(_games(rows), 2025, 1, P)
        assert r["AAA"] > r["BBB"]


class TestEvaluate:
    def test_ats_bets_the_side_the_rating_prefers(self):
        # Model says home by 7, market home by 3, home wins by 10: a win.
        rep = pl.DataFrame({"projected": [7.0], "market": [3.0], "margin": [10]})
        ats = R.evaluate(rep)["ats"]["0+"]
        assert (ats["w"], ats["l"]) == (1, 0)

    def test_ats_loss_when_the_market_side_covers(self):
        # Model prefers the away side (+3 vs home -3 projection 0); home wins by 10.
        rep = pl.DataFrame({"projected": [0.0], "market": [3.0], "margin": [10]})
        ats = R.evaluate(rep)["ats"]["0+"]
        assert (ats["w"], ats["l"]) == (0, 1)

    def test_a_model_equal_to_the_market_gets_no_weight_and_no_bets(self):
        rep = pl.DataFrame({"projected": [3.0, -2.0], "market": [3.0, -2.0], "margin": [10, 1]})
        ev = R.evaluate(rep)
        assert ev["market_weight"]["beta"] == 0.0
        assert ev["ats"]["0+"]["games"] == 0

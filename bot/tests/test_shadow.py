"""The shadow predictor: the line never reaches the model, the margin is the
sum of the factors, and the tier needs the computed baseline to agree."""

import json

import pytest

from edgelord import config, db, shadow

HOME, AWAY = "BBB", "AAA"


def _pack(spread=3.0):
    return {
        "game": {"game_id": "2026_07_AAA_BBB", "home_team": HOME, "away_team": AWAY,
                 "gameday": "2026-10-25", "week": 7, "season": 2026},
        "market": {"current_spread_home": spread, "current_total": 44.5,
                   "moneyline_home": -160, "moneyline_away": 140},
        "situation": {"neutral_site": False, "home": {"rest_days": 7}, "away": {"rest_days": 7}},
        "weather": {"indoor": True},
        "matchup": {
            "unit_ratings": {"units": []},
            "head_to_head": {
                "meetings": 1, "BBB_su_wins": 1, "BBB_ats_covers": 1,
                "recent": [{"season": 2025, "score": "AAA 10 @ BBB 20", "spread_line": 3.5,
                            "winner": "BBB", "covered": "BBB"}],
            },
        },
        "home": {"splits": {"overall": {"record": "4-2", "ats": "4-2", "ats_pct": 0.667},
                            "as_favorite": {"record": "3-1"}}},
        "away": {"splits": {"overall": {"record": "2-4", "ats": "3-3", "ats_pct": 0.5}}},
    }


def _out(**points):
    """A model reply: points per factor, positive toward HOME, negative toward AWAY."""
    factors = {}
    for k in shadow.FACTOR_KEYS:
        v = points.get(k, 0.0)
        factors[k] = {"favors": HOME if v > 0 else AWAY if v < 0 else "neither",
                      "points": abs(v), "evidence": "solid", "reading": "x"}
    return {"factors": factors, "projected_total": 44.0, "headline": "h",
            "paragraph": "p", "baseline_disagreement": "agree"}


class TestBlindView:
    def test_nothing_priced_off_the_line_reaches_the_model(self):
        text = json.dumps(shadow.blind_view(_pack())).lower()
        for leak in ("spread", "moneyline", "ats", "covered", "as_favorite", "44.5"):
            assert leak not in text, leak
        # Straight-up results stay.
        assert "4-2" in text and "winner" in text

    def test_prompt_carries_no_line(self):
        prompt = shadow.build_prompt(_pack(), {"projected_home": 2.0, "home_win_prob": 0.56})
        assert "current_spread" not in prompt and "moneyline" not in prompt
        assert "checklist" in prompt.lower()


class TestAssemble:
    def test_margin_is_the_sum_of_the_factors(self):
        calc = shadow.assemble(_pack(), _out(team_strength=4.0, home_field=1.5,
                                             quarterback=-2.0), {"projected_home": 3.0})
        assert calc["projected_margin"] == pytest.approx(3.5)
        assert calc["winner"] == HOME
        assert 0.5 < calc["home_win_prob"] < 0.7

    def test_best_bet_needs_both_numbers_past_the_line(self):
        # Line BBB -3. Factors say BBB by 6 (edge 3), Elo says BBB by 4.5 (edge 1.5).
        calc = shadow.assemble(_pack(3.0), _out(team_strength=6.0), {"projected_home": 4.5})
        assert (calc["pick_side"], calc["edge"], calc["baseline_edge"], calc["tier"]) == (
            HOME, 3.0, 1.5, "best_bet")

    def test_elo_on_the_other_side_caps_it_at_coin_flip(self):
        calc = shadow.assemble(_pack(3.0), _out(team_strength=6.0), {"projected_home": 1.0})
        assert calc["baseline_edge"] == -2.0
        assert calc["tier"] == "coin_flip"

    def test_underdog_side_reads_from_the_dog(self):
        # Line BBB -3; factors say AAA by 1, Elo says BBB by 1: both on AAA +3.
        calc = shadow.assemble(_pack(3.0), _out(team_strength=-1.0), {"projected_home": 1.0})
        assert calc["pick_side"] == AWAY
        assert calc["edge"] == 4.0
        assert calc["baseline_edge"] == 2.0
        assert calc["tier"] == "best_bet"
        assert calc["winner"] == AWAY

    def test_negative_points_are_floored(self):
        out = _out(team_strength=2.0)
        out["factors"]["weather"] = {"favors": HOME, "points": -3, "evidence": "thin", "reading": "x"}
        assert shadow.assemble(_pack(), out, None)["projected_margin"] == 2.0


class TestReport:
    @pytest.fixture
    def conn(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
        db.init()
        c = db.connect()
        yield c
        c.close()

    def test_grades_shadow_beside_live(self, conn):
        conn.execute(
            "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, home_score, "
            "away_score, spread_line) VALUES ('G', 2026, 7, '2026-10-25', ?, ?, 17, 20, 3.0)", (HOME, AWAY))
        # Shadow took AAA +3 (line_home 3.0) and named AAA the winner.
        conn.execute(
            "INSERT INTO shadow_predictions (game_id, created_at, winner, line_home, "
            "pick_side, tier) VALUES ('G', 'now', ?, 3.0, ?, 'lean')", (AWAY, AWAY))
        conn.commit()
        rep = shadow.report(conn, 2026)
        assert rep["games"] == 1
        assert rep["shadow"]["winners"] == {"w": 1, "l": 0, "p": 0}
        assert rep["shadow"]["ats"] == {"w": 1, "l": 0, "p": 0}
        assert rep["shadow"]["dog"]["w"] == 1
        assert rep["market_favourite_winners"] == {"w": 0, "l": 1, "p": 0}


class TestOfficialPick:
    def test_pick_against_its_own_winner_says_so_plainly(self):
        # Line BBB -3; factors say BBB by 1: the pick is AAA +3 though BBB wins.
        pack = _pack(3.0)
        out = _out(team_strength=1.0)
        out["headline"] = "Bears edge it at home."
        calc = shadow.assemble(pack, out, {"projected_home": 0.5})
        res = shadow.to_prediction(pack, out, calc)
        assert res["pick_side"] == AWAY
        assert res["paragraph"].startswith(
            "Our number: BBB by 1. The market: BBB by 3. The pick: AAA +3.")
        assert res["headline"] == "Bears edge it at home, but closer than the market thinks: AAA +3"
        assert res["conviction"] == calc["tier"]
        assert 50 < res["confidence"] < 60

    def test_favourite_shows_minus_and_factors_rank_by_points(self):
        pack = _pack(3.0)
        out = _out(team_strength=4.0, home_field=1.5, quarterback=2.5)
        calc = shadow.assemble(pack, out, {"projected_home": 5.0})
        res = shadow.to_prediction(pack, out, calc)
        assert res["paragraph"].startswith("Our number: BBB by 8. The market: BBB by 3. The pick: BBB -3.")
        assert res["key_factors"][0] == "Team strength: BBB +4"
        assert [r["weight"] for r in res["decision_table"][:3]] == ["decisive", "strong", "moderate"]
        assert res["headline"] == "h"

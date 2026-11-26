"""The timing call and the total pick are both arithmetic on a line, so both are pinned.

A timing call with the sign backwards tells you to wait on the number you
should grab, and a total picked on the wrong comparison replaces a spread pick
that had the bigger edge.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from edgelord import config, db, early, shadow
from edgelord import predict as predictor
from edgelord.early import EASTERN

HOME, AWAY = "BBB", "AAA"
THURSDAY = datetime(2026, 11, 19, 12, 0, tzinfo=EASTERN)


def _pack(spread=3.0, total=44.5, move=None):
    movement = {"available": move is not None, "spread_move": move}
    return {
        "game": {"game_id": "2026_11_AAA_BBB", "home_team": HOME, "away_team": AWAY,
                 "gameday": "2026-11-22", "gametime_et": "13:00", "week": 11,
                 "season": 2026},
        "market": {"current_spread_home": spread, "current_total": total,
                   "movement": movement},
    }


def _call(spread, side, tier="lean", **kw):
    return early.recommend(_pack(spread, **kw), "spread", side, tier, now=THURSDAY)


class TestBetNow:
    def test_dog_holding_the_hook_on_three(self):
        t = _call(3.5, AWAY)                      # AAA +3.5
        assert t["action"] == early.BET_NOW
        assert "+3.5" in t["reason"]

    def test_dog_holding_the_hook_on_seven(self):
        assert _call(-7.5, HOME)["action"] == early.BET_NOW      # BBB +7.5

    def test_favourite_laying_under_three(self):
        t = _call(2.5, HOME)                      # BBB -2.5
        assert t["action"] == early.BET_NOW
        assert "-2.5" in t["reason"]

    def test_favourite_laying_under_seven(self):
        assert _call(-6.5, AWAY)["action"] == early.BET_NOW      # AAA -6.5

    def test_a_coin_flip_is_never_worth_betting_early(self):
        assert _call(3.5, AWAY, tier="coin_flip")["action"] == early.NO_RUSH

    def test_a_best_bet_qualifies(self):
        assert _call(3.5, AWAY, tier="best_bet")["action"] == early.BET_NOW


class TestWait:
    def test_favourite_a_half_point_past_three(self):
        t = _call(3.5, HOME)                      # BBB -3.5
        assert t["action"] == early.WAIT
        assert "-3.5" in t["reason"]

    def test_dog_a_half_point_short_of_three(self):
        assert _call(2.5, AWAY)["action"] == early.WAIT          # AAA +2.5

    def test_favourite_past_seven_and_dog_short_of_it(self):
        assert _call(7.5, HOME)["action"] == early.WAIT
        assert _call(6.5, AWAY)["action"] == early.WAIT

    def test_waiting_applies_to_coin_flips_too(self):
        assert _call(3.5, HOME, tier="coin_flip")["action"] == early.WAIT


class TestNoCall:
    @pytest.mark.parametrize("spread", [1.0, 4.5, 5.5, 9.5, 10.0, 3.0, 7.0])
    def test_numbers_away_from_the_hooks_are_no_rush(self, spread):
        assert _call(spread, HOME)["action"] == early.NO_RUSH
        assert _call(spread, AWAY)["action"] == early.NO_RUSH

    def test_totals_are_not_rated(self):
        t = early.recommend(_pack(), "total", "under", "lean", now=THURSDAY)
        assert t["action"] == early.NOT_RATED

    def test_too_close_to_kickoff(self):
        saturday_night = datetime(2026, 11, 21, 20, 0, tzinfo=EASTERN)
        t = early.recommend(_pack(3.5), "spread", AWAY, "lean", now=saturday_night)
        assert t["action"] == early.NOT_RATED

    def test_no_line(self):
        assert _call(None, HOME)["action"] == early.NOT_RATED

    def test_movement_is_reported_from_the_picks_side_and_never_used(self):
        # Home spread up a point: worse for a home pick, better for an away one.
        assert _call(4.5, HOME, move=1.0)["moved_since_open"] == 1.0
        assert _call(4.5, AWAY, move=1.0)["moved_since_open"] == -1.0
        assert _call(4.5, HOME, move=1.0)["action"] == early.NO_RUSH

    def test_hours_to_kickoff(self):
        assert early.hours_to_kickoff(_pack()["game"], THURSDAY) == 73.0


def _out(total=44.0, **points):
    factors = {}
    for k in shadow.FACTOR_KEYS:
        v = points.get(k, 0.0)
        factors[k] = {"favors": HOME if v > 0 else AWAY if v < 0 else "neither",
                      "points": abs(v), "evidence": "solid", "reading": "x"}
    return {"factors": factors, "projected_total": total, "headline": "Home wins it",
            "paragraph": "p", "baseline_disagreement": "agree"}


class TestTotalPick:
    def test_a_small_total_gap_stays_a_spread_pick(self):
        calc = shadow.assemble(_pack(3.0), _out(total=40.0, pass_game=5.0), None)
        assert calc["pick"]["type"] == "spread"
        assert calc["total_side"] == "under" and calc["total_edge"] == 4.5

    def test_a_big_total_gap_becomes_the_pick(self):
        calc = shadow.assemble(_pack(3.0), _out(total=36.5, pass_game=5.0), None)
        assert calc["pick"] == {"type": "total", "side": "under", "edge": 8.0, "tier": "lean"}

    def test_over(self):
        calc = shadow.assemble(_pack(3.0), _out(total=53.0, pass_game=3.5), None)
        assert calc["pick"]["side"] == "over"

    def test_the_spread_keeps_the_pick_when_its_edge_is_bigger(self):
        # Margin 12 against a line of 3 is 9 off; the total is 8 off.
        calc = shadow.assemble(_pack(3.0), _out(total=36.5, pass_game=12.0), None)
        assert calc["pick"]["type"] == "spread"

    def test_exactly_at_the_bar_counts(self):
        calc = shadow.assemble(_pack(3.0), _out(total=37.5, pass_game=4.0), None)
        assert calc["total_edge"] == shadow.TOTAL_PICK_EDGE
        assert calc["pick"]["type"] == "total"

    def test_a_total_is_never_a_best_bet(self):
        calc = shadow.assemble(_pack(3.0), _out(total=30.0, pass_game=4.0), None)
        assert calc["pick"]["tier"] == "lean"

    def test_the_spread_fields_still_describe_the_spread(self):
        """Corrections and replays read these; a total pick must not change them."""
        calc = shadow.assemble(_pack(3.0), _out(total=36.5, team_strength=3.0, pass_game=2.0), None)
        assert calc["pick_side"] == HOME and calc["edge"] == 2.0

    def test_no_total_line_means_a_spread_pick(self):
        calc = shadow.assemble(_pack(3.0, total=None), _out(total=20.0, pass_game=5.0), None)
        assert calc["pick"]["type"] == "spread" and calc["total_edge"] is None

    def test_the_write_up_names_the_total_and_keeps_the_spread_lean(self):
        pack = _pack(3.0)
        out = _out(total=36.5, pass_game=5.0)
        pred = shadow.to_prediction(pack, out, shadow.assemble(pack, out, None))
        assert (pred["pick_type"], pred["pick_side"], pred["conviction"]) == ("total", "under", "lean")
        assert pred["paragraph"].startswith(
            "Our total: 36.5. The market: 44.5. The pick: under 44.5.")
        assert "a lean to BBB -3" in pred["paragraph"]
        assert pred["headline"].endswith("The play is the under 44.5")
        # 8 points of edge on a 13.5-point game.
        assert pred["confidence"] == round(100 * shadow.win_prob(8.0))


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _stored(conn, game_id, timing, clv):
    home, away = game_id.split("_")[3], game_id.split("_")[2]
    conn.execute(
        "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, "
        "home_score, away_score) VALUES (?,2026,11,'2026-11-22',?,?,20,17)",
        (game_id, home, away))
    cur = conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, paragraph, timing) VALUES (?,'m','t','blind','spread',?,'p',?)",
        (game_id, home, json.dumps({"action": timing})))
    conn.execute(
        "INSERT INTO results (prediction_id, game_id, home_score, away_score, "
        "pick_result, profit_units, clv_points, graded_at) VALUES (?,?,20,17,'win',0,?,'t')",
        (cur.lastrowid, game_id, clv))


class TestStoredAndGraded:
    def test_a_total_pick_is_stored_with_its_line_and_timing(self, conn):
        pack = _pack(3.0)
        conn.execute(
            "INSERT INTO games (game_id, season, week, gameday, home_team, away_team) "
            "VALUES (?,2026,11,'2026-11-22',?,?)", (pack["game"]["game_id"], HOME, AWAY))
        out = {**_out(total=36.5, pass_game=5.0), "_model": "m"}
        calc = shadow.assemble(pack, out, None)
        result = shadow.to_prediction(pack, out, calc)
        result["timing"] = early.recommend(pack, "total", "under", "lean", now=THURSDAY)
        pid = predictor.store(conn, pack["game"]["game_id"], None, pack, result,
                              run_label="blind", conviction=calc["pick"]["tier"])
        row = conn.execute("SELECT * FROM predictions WHERE id = ?", (pid,)).fetchone()
        assert (row["pick_type"], row["pick_side"], row["line_at_pick"]) == ("total", "under", 44.5)
        assert row["conviction"] == "lean"
        assert json.loads(row["timing"])["action"] == early.NOT_RATED

    def test_report_reads_the_move_after_the_pick(self, conn):
        _stored(conn, "2026_11_AAA_BBB", "bet_now", 0.5)    # number got worse: right
        _stored(conn, "2026_11_CCC_DDD", "bet_now", 0.0)
        _stored(conn, "2026_11_EEE_FFF", "wait", -0.5)      # number got better: right
        rep = early.report(conn, 2026)
        assert rep["bet_now"] == {"picks": 2, "got_worse": 1, "got_better": 0,
                                  "unchanged": 1, "avg_move": 0.25}
        assert rep["wait"]["got_better"] == 1 and rep["wait"]["avg_move"] == -0.5
        assert rep["no_rush"]["picks"] == 0

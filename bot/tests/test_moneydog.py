"""The Moneydog: prices, the value calculation, the lock at kickoff, grading."""

import json
from datetime import datetime

import pytest

from edgelord import config, db, moneydog
from edgelord.recheck import EASTERN


class TestPrices:
    def test_even_projection_is_a_coin_flip(self):
        assert moneydog.win_prob(0) == pytest.approx(0.5)

    def test_projected_three_point_loser_wins_about_41_percent(self):
        assert moneydog.win_prob(-3) == pytest.approx(0.412, abs=0.005)

    def test_implied_probability_of_a_dog_and_a_favourite(self):
        assert moneydog.implied(150) == pytest.approx(0.4)
        assert moneydog.implied(-150) == pytest.approx(0.6)

    def test_fair_price_removes_the_vig(self):
        # +124 / -148 sums past 100%; the fair split must sum to exactly 1.
        assert moneydog.fair_implied(124, -148) + moneydog.fair_implied(-148, 124) == pytest.approx(1)

    def test_profit(self):
        assert moneydog.profit(180, "win") == pytest.approx(1.8)
        assert moneydog.profit(180, "loss") == -1.0
        assert moneydog.profit(180, "push") == 0.0


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _game(conn, gid, home, away, ml_home, ml_away, margin, *, day="2026-10-18", score=None):
    conn.execute(
        "INSERT INTO games (game_id, season, week, game_type, gameday, gametime, home_team, "
        "away_team, home_score, away_score) VALUES (?,2026,6,'REG',?,'13:00',?,?,?,?)",
        (gid, day, home, away, *(score or (None, None))),
    )
    pack = {"market": {"moneyline_home": ml_home, "moneyline_away": ml_away}}
    fid = conn.execute(
        "INSERT INTO features (game_id, built_at, payload) VALUES (?, 'x', ?)",
        (gid, json.dumps(pack)),
    ).lastrowid
    conn.execute(
        "INSERT INTO predictions (game_id, features_id, model, created_at, run_label, "
        "pick_type, pick_side, projected_margin, paragraph) "
        "VALUES (?,?,'m','x','manual','spread',?,?,'p')",
        (gid, fid, home, margin),
    )


BEFORE = datetime(2026, 10, 18, 10, 0, tzinfo=EASTERN)
AFTER = datetime(2026, 10, 18, 14, 0, tzinfo=EASTERN)


class TestSelection:
    def test_best_value_dog_in_range_is_chosen(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0)   # A +170, projected to lose by 3
        _game(conn, "2026_06_C_D", "D", "C", -160, 135, 6.0)   # C +135, projected to lose by 6
        md = moneydog.select(conn, 2026, 6, now=BEFORE)
        assert (md["team"], md["odds"]) == ("A", 170)

    def test_prices_outside_the_range_never_qualify(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -500, 400, 1.0)   # +400 long shot
        _game(conn, "2026_06_C_D", "D", "C", -115, 105, 0.0)   # +105 near pick'em
        assert moneydog.select(conn, 2026, 6, now=BEFORE) is None

    def test_locked_once_its_game_kicks_off(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0)
        moneydog.select(conn, 2026, 6, now=BEFORE)
        _game(conn, "2026_06_E_F", "F", "E", -130, 250, -2.0, day="2026-10-19")  # better, later
        assert moneydog.select(conn, 2026, 6, now=AFTER)["team"] == "A"

    def test_can_change_before_kickoff(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0)
        moneydog.select(conn, 2026, 6, now=BEFORE)
        _game(conn, "2026_06_E_F", "F", "E", -130, 250, -2.0)
        assert moneydog.select(conn, 2026, 6, now=BEFORE)["team"] == "E"

    def test_live_selection_never_uses_a_started_game(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0)
        assert moneydog.select(conn, 2026, 6, now=AFTER) is None


class TestGrading:
    def test_outright_win_pays_the_price(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0, score=(17, 20))
        moneydog.select(conn, 2026, 6, backfill=True)
        moneydog.grade(conn, 2026)
        rec = moneydog.record(conn, 2026)
        assert (rec["record"], rec["units"], rec["backfilled_weeks"]) == ("1-0", 1.7, [6])

    def test_loss_costs_a_unit(self, conn):
        _game(conn, "2026_06_A_B", "B", "A", -200, 170, 3.0, score=(24, 20))
        moneydog.select(conn, 2026, 6, backfill=True)
        moneydog.grade(conn, 2026)
        assert moneydog.record(conn, 2026)["units"] == -1.0

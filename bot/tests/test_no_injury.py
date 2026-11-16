"""The no-injury replay: same points, availability zeroed, graded on the pick's own line.

The replay is only worth showing if it reproduces the real picks exactly when
injuries had nothing to do with them, so most of this checks that it agrees.
"""

import json

import pytest

from edgelord import config, db, no_injury

FACTORS = ("team_strength", "quarterback", "availability", "pass_game", "run_game",
           "pressure", "form", "rest_travel", "weather", "home_field")


def _points(**raw):
    return {"raw": {k: raw.get(k, 0.0) for k in FACTORS}, "multipliers": None}


class TestReplay:
    def test_injuries_flip_a_close_pick(self):
        # LV +6.5: SEA by 5.2 only because availability gave LV 2 points.
        fp = _points(team_strength=-6.0, availability=2.0, home_field=1.25, form=-2.45)
        assert no_injury.replay(fp, -6.5, "LV", "SEA") == "SEA"

    def test_no_injury_points_means_the_same_side(self):
        fp = _points(team_strength=4.0, home_field=1.25)
        assert no_injury.replay(fp, 3.0, "NYG", "WAS") == "NYG"

    def test_corrections_are_applied_before_zeroing(self):
        # x1.2 on team strength takes 2.5 to 3.0, which beats a 2.5 line.
        fp = _points(team_strength=2.5, availability=-1.0)
        fp["multipliers"] = {"team_strength": 1.2}
        assert no_injury.replay(fp, 2.5, "GB", "MIN") == "GB"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _game(conn, gid, week, home, away, hs=None, as_=None):
    conn.execute(
        "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, home_score, away_score) "
        "VALUES (?,2026,?,'2026-11-15',?,?,?,?)",
        (gid, week, home, away, hs, as_),
    )


def _pick(conn, gid, side, line_at_pick, fp, superseded=None):
    conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, pick_side, "
        "line_at_pick, price_at_pick, factor_points, superseded_by, paragraph) "
        "VALUES (?, 'm', '2026-11-15', 'blind', 'spread', ?, ?, -110, ?, ?, '')",
        (gid, side, line_at_pick, json.dumps(fp), superseded),
    )


class TestCompare:
    def test_splits_hindsight_from_the_test(self, conn):
        # Week 10, hindsight: LV +6.5 on injuries, SEA won by 8. Replay takes SEA and wins.
        _game(conn, "2026_10_SEA_LV", 10, "LV", "SEA", 13, 21)
        _pick(conn, "2026_10_SEA_LV", "LV", -6.5,
              _points(team_strength=-6.0, availability=2.0, home_field=1.25, form=-2.45))
        # Week 11, the test: no injury points, both columns agree and win.
        _game(conn, "2026_11_WAS_NYG", 11, "NYG", "WAS", 24, 14)
        _pick(conn, "2026_11_WAS_NYG", "NYG", 3.0, _points(team_strength=4.0, home_field=1.25))

        out = no_injury.compare(conn, 2026)
        assert out["hindsight"]["as_made"]["record"] == "0-1"
        assert out["hindsight"]["no_injury"]["record"] == "1-0"
        assert out["hindsight"]["differ"] == 1
        assert out["test"]["as_made"]["record"] == "1-0"
        assert out["test"]["no_injury"]["record"] == "1-0"
        assert out["test"]["differ"] == 0
        assert out["test"]["no_injury"]["units"] == pytest.approx(0.91, abs=0.01)

    def test_superseded_picks_are_left_out(self, conn):
        _game(conn, "2026_11_WAS_NYG", 11, "NYG", "WAS", 24, 14)
        _pick(conn, "2026_11_WAS_NYG", "NYG", 3.0, _points(team_strength=4.0))
        _pick(conn, "2026_11_WAS_NYG", "WAS", -3.0, _points(team_strength=-4.0), superseded=1)
        assert no_injury.compare(conn, 2026)["test"]["games"] == 1

    def test_unplayed_disagreement_is_listed(self, conn):
        _game(conn, "2026_11_SEA_LV", 11, "LV", "SEA")
        _pick(conn, "2026_11_SEA_LV", "LV", -6.5,
              _points(team_strength=-6.0, availability=2.0, home_field=1.25, form=-2.45))
        out = no_injury.compare(conn, 2026)
        assert out["upcoming"] == [
            {"game_id": "2026_11_SEA_LV", "week": 11, "pick": "LV", "no_injury": "SEA"}
        ]
        assert out["test"]["games"] == 0

    def test_away_pick_line_is_turned_to_the_home_side(self, conn):
        # JAX -10 at BAL: line_at_pick +10 from JAX's side, so BAL's line is -10.
        _game(conn, "2026_09_JAX_BAL", 9, "BAL", "JAX", 10, 33)
        _pick(conn, "2026_09_JAX_BAL", "JAX", 10.0, _points(team_strength=-11.6))
        out = no_injury.compare(conn, 2026)["hindsight"]
        assert out["as_made"]["record"] == out["no_injury"]["record"] == "1-0"

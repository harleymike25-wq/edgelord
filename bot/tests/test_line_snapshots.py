"""Free line snapshots from nflverse.

Without a paid odds feed the schedule's own line is the source. Snapshotting it
on every run reconstructs the opening number, the movement path and closing
line value -- the things that otherwise need thirty books and a subscription.

What it cannot do is shop across books, so `best_available` stays thin and
book disagreement is always zero. These tests pin both the capability and the
limitation.
"""

import pytest

from edgelord import config, db, track
from edgelord.features import market


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


GAME = "2026_01_AAA_BBB"


def _game(conn, spread=3.5, total=44.5, home_score=None, away_score=None):
    conn.execute(
        "INSERT OR REPLACE INTO games (game_id, season, week, game_type, gameday, "
        "home_team, away_team, spread_line, total_line, home_score, away_score) "
        "VALUES (?,2026,1,'REG','2026-09-13','BBB','AAA',?,?,?,?)",
        (GAME, spread, total, home_score, away_score),
    )


def _snap(conn, at, spread, total=44.5):
    conn.execute(
        "INSERT INTO line_snapshots (game_id, odds_event_id, commence_time, "
        "home_team, away_team, book, captured_at, spread_home, total) "
        "VALUES (?,?, '2026-09-13T17:00', 'BBB','AAA','nflverse',?,?,?)",
        (GAME, GAME, at, spread, total),
    )


class TestMovementFromFreeLines:
    def test_single_snapshot_gives_an_opener(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 3.5)
        h = market.line_history(conn, GAME)
        assert h["available"] is True
        assert h["opening_spread_home"] == 3.5
        assert h["spread_move"] == 0

    def test_movement_across_snapshots(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 2.5)
        _snap(conn, "2026-09-11T12:00:00", 3.5)
        h = market.line_history(conn, GAME)
        assert h["opening_spread_home"] == 2.5
        assert h["current_spread_home"] == 3.5
        assert h["spread_move"] == 1.0
        assert h["key_numbers_crossed"] == [3]

    def test_move_toward_the_underdog_is_flagged(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 7.0)
        _snap(conn, "2026-09-11T12:00:00", 5.5)
        h = market.line_history(conn, GAME)
        assert h["spread_move_toward_underdog"] is True

    def test_single_source_means_no_book_disagreement(self, conn):
        """The honest limitation: one line, so no shopping signal."""
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 3.5)
        h = market.line_history(conn, GAME)
        assert h["book_spread_disagreement"] == 0.0
        assert h["books_latest"] == 1

    def test_public_percentage_stays_null(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 3.5)
        assert market.line_history(conn, GAME)["public_betting_pct"] is None


class TestClvWorksWithoutAPaidFeed:
    def test_beating_the_close(self, conn):
        # Picked the home side at 2.5; nflverse's closing line settled at 3.5.
        _game(conn, spread=3.5, home_score=27, away_score=20)
        conn.execute(
            "INSERT INTO predictions (game_id, model, created_at, run_label, "
            "pick_type, pick_side, line_at_pick, price_at_pick, confidence, "
            "projected_margin, projected_total, paragraph) VALUES "
            "(?,'m','2026-09-08T12:00:00','sunday','spread','BBB',2.5,-110,60,6.0,45.0,'p')",
            (GAME,),
        )
        assert track.grade(conn) == 1
        r = dict(conn.execute("SELECT * FROM results").fetchone())
        assert r["pick_result"] == "win"          # laid 2.5, won by 7
        assert r["clv_points"] == pytest.approx(1.0)  # held 2.5 against a 3.5 close


class TestRepredictFilterUsesFreeSnapshots:
    def test_key_number_crossing_triggers_a_repredict(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 2.5)
        conn.execute(
            "INSERT INTO predictions (game_id, model, created_at, run_label, "
            "pick_type, pick_side, paragraph) VALUES "
            "(?,'m','2026-09-08T13:00:00','sunday','spread','BBB','p')",
            (GAME,),
        )
        _snap(conn, "2026-09-11T12:00:00", 3.5)
        assert market.games_needing_repredict(conn, 2026, 1) == [GAME]

    def test_small_move_does_not(self, conn):
        _game(conn)
        _snap(conn, "2026-09-08T12:00:00", 3.5)
        conn.execute(
            "INSERT INTO predictions (game_id, model, created_at, run_label, "
            "pick_type, pick_side, paragraph) VALUES "
            "(?,'m','2026-09-08T13:00:00','sunday','spread','BBB','p')",
            (GAME,),
        )
        _snap(conn, "2026-09-11T12:00:00", 4.0)
        assert market.games_needing_repredict(conn, 2026, 1) == []

"""The predict -> play -> refresh -> grade chain.

The failure this guards against is silent and total: `grade` skips any game
whose `home_score` is still null, and only `sync_games` ever writes that
column. If the scheduled job forgets to refresh first, predictions accumulate
forever, nothing is ever scored, the record sits at 0-0 and CLV is never
computed -- with no error anywhere.
"""

import pytest

from edgelord import config, db, evidence, track


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


GAME = "2026_01_AAA_BBB"


def _scheduled_game(conn, spread=3.0, total=45.5):
    """A game that has been scheduled but not yet played."""
    conn.execute(
        "INSERT INTO games (game_id, season, week, game_type, gameday, home_team, "
        "away_team, spread_line, total_line) "
        "VALUES (?,2026,1,'REG','2026-09-13','BBB','AAA',?,?)",
        (GAME, spread, total),
    )


def _prediction(conn, side="BBB", line=2.5, conviction="best_bet"):
    conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, conviction, line_at_pick, price_at_pick, confidence, "
        "projected_margin, projected_total, paragraph) VALUES "
        "(?,'m','2026-09-13T10:00:00','sunday','spread',?,?,?,-110,60,6.0,44.0,'p')",
        (GAME, side, conviction, line),
    )


def _final_score(conn, home=27, away=20):
    """What `edgelord refresh` does: writes the final score in."""
    conn.execute(
        "UPDATE games SET home_score = ?, away_score = ? WHERE game_id = ?",
        (home, away, GAME),
    )


class TestTheChain:
    def test_prediction_is_stored_immediately(self, conn):
        _scheduled_game(conn)
        _prediction(conn)
        row = conn.execute(
            "SELECT pick_side, paragraph FROM predictions WHERE game_id = ?", (GAME,)
        ).fetchone()
        assert row["pick_side"] == "BBB"
        assert row["paragraph"]

    def test_nothing_grades_before_the_refresh(self, conn):
        """The bug: game played in reality, score not yet in the database."""
        _scheduled_game(conn)
        _prediction(conn)
        assert track.grade(conn) == 0
        assert track.record(conn, season=2026)["overall"]["record"] == "0-0"

    def test_grading_works_once_scores_land(self, conn):
        _scheduled_game(conn)
        _prediction(conn)
        _final_score(conn)                     # refresh writes the score
        assert track.grade(conn) == 1

        r = dict(conn.execute("SELECT * FROM results").fetchone())
        assert r["pick_result"] == "win"       # laid 2.5, won by 7
        assert r["profit_units"] == pytest.approx(0.909, abs=1e-3)
        assert r["clv_points"] == pytest.approx(0.5)  # held 2.5 against a 3.0 close

    def test_record_reflects_the_graded_result(self, conn):
        _scheduled_game(conn)
        _prediction(conn)
        _final_score(conn)
        track.grade(conn)

        overall = track.record(conn, season=2026)["overall"]
        assert overall["record"] == "1-0"
        assert overall["plays"] == 1
        assert overall["pending"] == 0
        assert overall["avg_clv"] == pytest.approx(0.5)

    def test_pending_counts_before_grading_and_clears_after(self, conn):
        _scheduled_game(conn)
        _prediction(conn)
        assert track.record(conn, season=2026)["overall"]["pending"] == 1
        _final_score(conn)
        track.grade(conn)
        assert track.record(conn, season=2026)["overall"]["pending"] == 0

    def test_evidence_sees_the_graded_best_bet(self, conn):
        _scheduled_game(conn)
        _prediction(conn, conviction="best_bet")
        _final_score(conn)
        track.grade(conn)

        a = evidence.assess(conn, season=2026)
        assert a["plays_decided"] == 1
        # One play is nowhere near enough to claim anything.
        assert a["verdict"] == "no signal yet"

    def test_evidence_ignores_leans(self, conn):
        """Leans are opinions the model would not have staked.

        Judging the record on them would measure something nobody bet.
        """
        _scheduled_game(conn)
        _prediction(conn, conviction="lean")
        _final_score(conn)
        track.grade(conn)

        assert evidence.assess(conn, season=2026)["plays_decided"] == 0
        # But it is still graded and still counted in the overall record.
        rec = track.record(conn, season=2026)
        assert rec["overall"]["record"] == "1-0"
        assert rec["best_bets"]["plays"] == 0

    def test_grading_is_idempotent(self, conn):
        """The job runs three times a week; re-grading must not double-count."""
        _scheduled_game(conn)
        _prediction(conn)
        _final_score(conn)
        track.grade(conn)
        track.grade(conn)
        track.grade(conn)
        assert conn.execute("SELECT COUNT(*) n FROM results").fetchone()["n"] == 1
        assert track.record(conn, season=2026)["overall"]["record"] == "1-0"

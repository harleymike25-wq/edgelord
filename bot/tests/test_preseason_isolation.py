"""Preseason odds must not be able to reach the record.

The games table holds only regular and postseason rows, so a preseason poll
stores snapshots with a null game_id. These tests pin down that those orphans
stay inert -- they cannot be graded, cannot enter a feature pack, and cannot
move the running record.
"""

import pytest

from edgelord import config, db, track
from edgelord.features import market
from edgelord.sources import odds


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _preseason_snapshot(conn, captured_at="2026-08-14T18:00:00+00:00"):
    """A preseason game: real teams, real line, but no matching scheduled game."""
    conn.execute(
        "INSERT INTO line_snapshots (game_id, odds_event_id, commence_time, "
        "home_team, away_team, book, captured_at, spread_home, total) "
        "VALUES (NULL, 'pre1', '2026-08-15T23:00:00Z', 'GB', 'CLE', 'draftkings', ?, 3.0, 38.5)",
        (captured_at,),
    )


def _regular_game_and_pick(conn):
    conn.execute(
        "INSERT INTO games (game_id, season, week, game_type, gameday, home_team, "
        "away_team, home_score, away_score, spread_line, total_line) "
        "VALUES ('2026_01_AAA_BBB',2026,1,'REG','2026-09-13','BBB','AAA',24,20,3.0,45.5)"
    )
    conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, line_at_pick, price_at_pick, confidence, projected_margin, "
        "projected_total, paragraph) VALUES "
        "('2026_01_AAA_BBB','m','2026-09-13T10:00:00','sunday','spread','BBB',3.0,-110,60,4.0,44.0,'p')"
    )


class TestPreseasonCannotReachTheRecord:
    def test_orphan_snapshot_is_stored_but_unlinked(self, conn):
        _preseason_snapshot(conn)
        row = conn.execute(
            "SELECT game_id, home_team FROM line_snapshots"
        ).fetchone()
        assert row["game_id"] is None
        assert row["home_team"] == "GB"

    def test_grading_ignores_orphans(self, conn):
        _preseason_snapshot(conn)
        _regular_game_and_pick(conn)
        # Only the real prediction grades; the orphan has nothing to grade.
        assert track.grade(conn) == 1
        assert conn.execute("SELECT COUNT(*) n FROM results").fetchone()["n"] == 1

    def test_record_is_unchanged_by_orphans(self, conn):
        _regular_game_and_pick(conn)
        track.grade(conn)
        before = track.record(conn, season=2026)["overall"]

        _preseason_snapshot(conn)
        track.grade(conn)
        after = track.record(conn, season=2026)["overall"]

        assert before == after
        assert after["record"] == "1-0"

    def test_orphans_do_not_enter_a_feature_pack(self, conn):
        """line_history keys on game_id, so a null-keyed row is invisible to it."""
        _preseason_snapshot(conn)
        _regular_game_and_pick(conn)
        history = market.line_history(conn, "2026_01_AAA_BBB")
        assert history["available"] is False

    def test_orphans_do_not_trigger_a_repredict(self, conn):
        _regular_game_and_pick(conn)
        _preseason_snapshot(conn)
        # The game already has a live prediction and no snapshots of its own,
        # so a preseason row nearby must not make it look like the line moved.
        assert market.games_needing_repredict(conn, 2026, 1) == []


class TestPurge:
    def test_purge_removes_only_unmatched(self, conn):
        _preseason_snapshot(conn)
        _regular_game_and_pick(conn)
        conn.execute(
            "INSERT INTO line_snapshots (game_id, odds_event_id, commence_time, "
            "home_team, away_team, book, captured_at, spread_home) VALUES "
            "('2026_01_AAA_BBB','evt2','2026-09-13T17:00:00Z','BBB','AAA','dk',"
            "'2026-09-12T10:00:00+00:00', 3.0)"
        )
        assert odds.purge_unmatched(conn) == 1
        remaining = conn.execute("SELECT game_id FROM line_snapshots").fetchall()
        assert [r["game_id"] for r in remaining] == ["2026_01_AAA_BBB"]

    def test_purge_on_empty_table_is_a_noop(self, conn):
        assert odds.purge_unmatched(conn) == 0

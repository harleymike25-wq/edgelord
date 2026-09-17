"""Which week the mirror keeps even when nobody has picked it.

The Firestore mirror skips games with no prediction and no result, because the
full schedule is 272 documents of nothing. The dashboard, though, opens on the
live week by date -- so if that week is unpicked *and* unmirrored, the landing
page 404s and the site reads as though the season has ended. The one exception
is therefore load-bearing, and the two-day grace period has to match
`run_task.ps1` or the two disagree about which week is live on a Monday.
"""

from datetime import date, timedelta

import pytest

from edgelord import config, db, sync


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _game(conn, *, week, gameday, gametime="13:00", team="AAA"):
    conn.execute(
        "INSERT INTO games (game_id, season, week, game_type, gameday, gametime, "
        "home_team, away_team) VALUES (?,2026,?,'REG',?,?,?,'ZZZ')",
        (f"2026_{week:02d}_{team}_ZZZ", week, gameday, gametime, team),
    )


def _day(offset: int) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


class TestLiveWeek:
    def test_the_week_kicking_off_next_is_live(self, conn):
        _game(conn, week=2, gameday=_day(1))
        _game(conn, week=3, gameday=_day(8))
        assert sync._live_week(conn, 2026) == 2

    def test_a_week_finished_yesterday_is_still_live(self, conn):
        """Monday belongs to the slate that just played, not the next one."""
        _game(conn, week=2, gameday=_day(-1))
        _game(conn, week=3, gameday=_day(6))
        assert sync._live_week(conn, 2026) == 2

    def test_a_week_three_days_gone_has_handed_over(self, conn):
        _game(conn, week=2, gameday=_day(-3))
        _game(conn, week=3, gameday=_day(4))
        assert sync._live_week(conn, 2026) == 3

    def test_kickoff_time_breaks_a_same_day_tie(self, conn):
        # A Thursday nightcap belonging to week 3 must not outrank the week 2
        # game earlier the same day.
        _game(conn, week=3, gameday=_day(2), gametime="20:15", team="CCC")
        _game(conn, week=2, gameday=_day(2), gametime="13:00", team="BBB")
        assert sync._live_week(conn, 2026) == 2

    def test_no_games_left_is_none(self, conn):
        _game(conn, week=18, gameday=_day(-30))
        assert sync._live_week(conn, 2026) is None

    def test_another_season_does_not_leak(self, conn):
        _game(conn, week=2, gameday=_day(1))
        assert sync._live_week(conn, 2025) is None

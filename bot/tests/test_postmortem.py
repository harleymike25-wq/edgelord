"""Miss arithmetic, and the two things it exists to catch.

The first is sign error. A post-mortem that gets the direction of the line
wrong does not merely report a wrong number -- it reaches the opposite verdict,
excusing a bet that had no edge as bad luck. So every field that carries a sign
is checked from both sides of the number: a favourite that failed to cover, a
dog that lost outright, an over and an under.

The second is the backtest leak. Backtests predict games that had already
finished, so letting one reach the record inflates it with a replay nobody
staked. `grade` scores them deliberately; `record` must not count them.
"""

import pytest

from edgelord import config, db, postmortem, sync, track

HOME = "BBB"
AWAY = "AAA"


def _row(**over):
    """A losing prediction joined to its result and its game."""
    row = {
        "pick_type": "spread",
        "pick_side": HOME,
        "home_team": HOME,
        "away_team": AWAY,
        "home_score": 21,
        "away_score": 20,
        "line_at_pick": 3.0,
        "spread_line": 3.0,
        "total_line": 45.5,
        "projected_margin": 6.0,
        "projected_total": 44.0,
        "confidence": 60,
        "conviction": "best_bet",
        "clv_points": 0.0,
        "profit_units": -1.0,
        "decision_table": "[]",
        "key_factors": "[]",
    }
    row.update(over)
    return row


class TestSpreadMiss:
    def test_home_favourite_that_failed_to_cover(self):
        # BBB laid 3 and won by 1, projecting 6.
        m = postmortem.compute_miss(_row())
        assert m["actual_margin"] == 1
        assert m["projected_margin"] == 6.0
        assert m["points_short"] == pytest.approx(2.0)
        assert m["severity"] == "near_miss"
        assert m["underdog"] is False
        assert m["projected_edge"] == pytest.approx(3.0)
        assert m["projection_error"] == pytest.approx(5.0)
        assert m["contradicted_own_projection"] is False

    def test_away_underdog_that_lost_outright(self):
        # AAA getting 3, lost by 11. Projection had it losing by 1.
        m = postmortem.compute_miss(
            _row(pick_side=AWAY, line_at_pick=-3.0, home_score=31, away_score=20,
                 projected_margin=1.0)
        )
        assert m["actual_margin"] == -11
        assert m["projected_margin"] == pytest.approx(-1.0)
        assert m["points_short"] == pytest.approx(8.0)
        assert m["severity"] == "decisive"
        assert m["underdog"] is True
        assert m["projected_edge"] == pytest.approx(2.0)
        assert m["projection_error"] == pytest.approx(10.0)
        assert m["contradicted_own_projection"] is False

    def test_away_pick_falls_back_to_the_inverted_closing_line(self):
        """No captured line, so the nflverse number is flipped for an away pick."""
        m = postmortem.compute_miss(
            _row(pick_side=AWAY, line_at_pick=None, spread_line=3.0,
                 home_score=31, away_score=20)
        )
        assert m["line"] == pytest.approx(-3.0)
        assert m["points_short"] == pytest.approx(8.0)

    def test_no_number_to_grade_against(self):
        m = postmortem.compute_miss(_row(line_at_pick=None, spread_line=None))
        assert m["line"] is None
        assert m["points_short"] is None
        assert m["severity"] is None
        assert m["contradicted_own_projection"] is None


class TestTotalMiss:
    def test_over_that_missed(self):
        m = postmortem.compute_miss(
            _row(pick_type="total", pick_side="over", line_at_pick=45.5,
                 home_score=17, away_score=20, projected_total=49.0)
        )
        assert m["actual_total"] == 37
        assert m["points_short"] == pytest.approx(8.5)
        assert m["severity"] == "decisive"
        assert m["underdog"] is None
        assert m["projected_edge"] == pytest.approx(3.5)
        assert m["projection_error"] == pytest.approx(12.0)

    def test_under_that_missed_narrowly(self):
        m = postmortem.compute_miss(
            _row(pick_type="total", pick_side="under", line_at_pick=45.5,
                 home_score=27, away_score=20, projected_total=42.0)
        )
        assert m["actual_total"] == 47
        assert m["points_short"] == pytest.approx(1.5)
        assert m["severity"] == "near_miss"
        # An under's edge runs the other way: the projection must sit below the
        # number. Getting this backwards would read a good bet as a bad one.
        assert m["projected_edge"] == pytest.approx(3.5)
        assert m["projection_error"] == pytest.approx(-5.0)


class TestContradictedOwnProjection:
    """The flag that stops a no-edge bet being written off as variance.

    The real case: the write-up argued for the away side "plus the field goal"
    while that side was laying three, so the projection sat 3.5 points the wrong
    way and the pick could not have been right even had it cashed.
    """

    def test_sign_error_on_the_line_is_caught(self):
        m = postmortem.compute_miss(
            _row(pick_side=AWAY, line_at_pick=3.0, home_score=28, away_score=20,
                 projected_margin=0.5)
        )
        assert m["projected_margin"] == pytest.approx(-0.5)
        assert m["projected_edge"] == pytest.approx(-3.5)
        assert m["contradicted_own_projection"] is True
        assert m["points_short"] == pytest.approx(11.0)
        assert m["severity"] == "decisive"

    def test_zero_edge_is_still_no_edge(self):
        m = postmortem.compute_miss(_row(line_at_pick=3.0, projected_margin=3.0))
        assert m["projected_edge"] == pytest.approx(0.0)
        assert m["contradicted_own_projection"] is True

    def test_unknown_without_a_projection(self):
        m = postmortem.compute_miss(_row(projected_margin=None))
        assert m["projected_edge"] is None
        assert m["contradicted_own_projection"] is None

    def test_an_under_can_contradict_itself_too(self):
        # Took the under 40 while projecting 44: the projection says over.
        m = postmortem.compute_miss(
            _row(pick_type="total", pick_side="under", line_at_pick=40.0,
                 projected_total=44.0, home_score=27, away_score=20)
        )
        assert m["projected_edge"] == pytest.approx(-4.0)
        assert m["contradicted_own_projection"] is True


class TestSeverity:
    """Bands, at the boundaries. A -1.00 unit loss is one number for a
    half-point miss and a three-touchdown one; only the second is evidence."""

    @pytest.mark.parametrize(
        "points_short,expected",
        [
            (0.5, "photo_finish"),
            (1.0, "photo_finish"),
            (1.5, "near_miss"),
            (3.0, "near_miss"),
            (3.5, "clear"),
            (7.0, "clear"),
            (7.5, "decisive"),
            (14.0, "decisive"),
            (14.5, "blowout"),
            (28.0, "blowout"),
        ],
    )
    def test_bands(self, points_short, expected):
        assert postmortem._severity(points_short) == expected


class TestFactorSplit:
    def test_rows_are_sorted_into_wrong_and_outvoted(self):
        table = [
            {"factor": "a", "reading": "r", "favors": HOME, "weight": "slight"},
            {"factor": "b", "reading": "r", "favors": HOME, "weight": "decisive"},
            {"factor": "c", "reading": "r", "favors": AWAY, "weight": "moderate"},
            {"factor": "d", "reading": "r", "favors": AWAY, "weight": "strong"},
        ]
        split = postmortem._factor_split(table, HOME)

        # Favoured the side that lost, so they argued for a losing pick.
        assert [r["factor"] for r in split["argued_for_pick"]] == ["b", "a"]
        # Favoured the other side and were overruled. These are the ones to read.
        assert [r["factor"] for r in split["argued_against_pick"]] == ["d", "c"]
        assert split["heaviest_wrong"]["factor"] == "b"
        assert split["heaviest_right"]["factor"] == "d"

    def test_neutral_and_weightless_rows_carry_no_side(self):
        table = [
            {"factor": "a", "reading": "r", "favors": "neither", "weight": "strong"},
            {"factor": "b", "reading": "r", "favors": HOME, "weight": "none"},
        ]
        split = postmortem._factor_split(table, HOME)
        assert [r["factor"] for r in split["carried_no_side"]] == ["a", "b"]
        assert split["heaviest_wrong"] is None
        assert split["heaviest_right"] is None

    def test_an_empty_table_is_not_an_error(self):
        split = postmortem._factor_split([], HOME)
        assert split["argued_for_pick"] == []
        assert split["heaviest_wrong"] is None

    def test_malformed_decision_table_json_is_survivable(self):
        m = postmortem.compute_miss(_row(decision_table="{not json"))
        assert m["factors"]["argued_for_pick"] == []


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


GAME = "2026_01_AAA_BBB"


def _played_game(conn):
    conn.execute(
        "INSERT INTO games (game_id, season, week, game_type, gameday, home_team, "
        "away_team, spread_line, total_line, home_score, away_score) "
        "VALUES (?,2026,1,'REG','2026-09-13',?,?,3.0,45.5,27,20)",
        (GAME, HOME, AWAY),
    )


def _prediction(conn, *, run_label, side=HOME, line=2.5):
    conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, conviction, line_at_pick, price_at_pick, confidence, "
        "projected_margin, projected_total, paragraph) VALUES "
        "(?,'m','2026-09-13T10:00:00',?,'spread',?,'best_bet',?,-110,60,6.0,44.0,'p')",
        (GAME, run_label, side, line),
    )


class TestBacktestsStayOutOfTheRecord:
    """A backtest predicts a game that already finished.

    `grade` scores them on purpose -- that is how a replay is evaluated -- so
    the record is the only thing standing between a favourable replay and a
    win rate that describes money nobody risked.
    """

    def test_a_graded_backtest_does_not_reach_the_record(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="sunday")
        _prediction(conn, run_label="backtest")
        assert track.grade(conn) == 2      # both are graded

        overall = track.record(conn, season=2026)["overall"]
        assert overall["record"] == "1-0"  # only one was staked
        assert overall["plays"] == 1

    def test_a_backtest_cannot_move_the_clv_trend(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="backtest", line=-6.0)
        track.grade(conn)

        assert sync._clv_series(conn, 2026) == []

    def test_the_live_pick_alone_drives_the_trend(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="sunday")
        _prediction(conn, run_label="backtest", line=-6.0)
        track.grade(conn)

        series = sync._clv_series(conn, 2026)
        assert len(series) == 1
        assert series[0]["plays"] == 1
        assert series[0]["avg_clv"] == pytest.approx(0.5)


class TestLosingPicks:
    def test_only_losses_are_returned(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="sunday")          # BBB -2.5, won by 7
        track.grade(conn)
        assert postmortem.losing_picks(conn, season=2026) == []

    def test_a_loss_is_picked_up_with_what_it_needs(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="sunday", side=AWAY, line=-2.5)
        track.grade(conn)

        losses = postmortem.losing_picks(conn, season=2026)
        assert len(losses) == 1
        m = postmortem.compute_miss(dict(losses[0]))
        assert m["pick_side"] == AWAY
        assert m["points_short"] == pytest.approx(4.5)

    def test_backtest_losses_are_not_post_mortemed(self, conn):
        _played_game(conn)
        _prediction(conn, run_label="backtest", side=AWAY, line=-2.5)
        track.grade(conn)
        assert postmortem.losing_picks(conn, season=2026) == []

"""Spend guard and re-predict filter.

These two are the difference between a $12 season and a $200 one, so each
branch gets an explicit case rather than being trusted to the happy path.
"""

import pytest

from edgelord import config, db, predict
from edgelord.features import market


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _usage(inp, out):
    return {"input_tokens": inp, "output_tokens": out}


class TestPricing:
    def test_fable_is_the_expensive_one(self):
        assert config.price_of("claude-fable-5") == (10.0, 50.0)

    def test_opus_tier(self):
        assert config.price_of("claude-opus-4-8") == (5.0, 25.0)

    def test_dated_model_id_still_resolves(self):
        assert config.price_of("claude-haiku-4-5-20251001") == (1.0, 5.0)

    def test_unknown_model_falls_back_to_opus_not_free(self):
        # Guessing zero would silently disable the budget guard.
        assert config.price_of("claude-something-new") == (5.0, 25.0)

    def test_cost_maths(self):
        # 4k in, 2k out on Fable: 0.004*10 + 0.002*50 = 0.14
        assert config.cost_usd("claude-fable-5", 4000, 2000) == pytest.approx(0.14)

    def test_output_dominates_on_fable(self):
        """Output is priced 5x input, which is why effort matters more than pack size.

        Ten thousand output tokens costs 3.4x what ten thousand input tokens
        does -- so trimming the feature pack saves far less than lowering
        effort, and thinking tokens are billed as output.
        """
        inp_heavy = config.cost_usd("claude-fable-5", 10_000, 1_000)  # $0.15
        out_heavy = config.cost_usd("claude-fable-5", 1_000, 10_000)  # $0.51
        assert out_heavy > inp_heavy * 3


class TestBudgetGuard:
    def test_passes_when_empty(self, conn):
        assert predict.check_budget(conn, budget=10.0) == 0.0

    def test_accumulates_spend(self, conn):
        predict._record(conn, "g1", "sunday", "claude-fable-5", _usage(4000, 2000))
        predict._record(conn, "g2", "sunday", "claude-fable-5", _usage(4000, 2000))
        assert predict.month_spend(conn) == pytest.approx(0.28)

    def test_blocks_at_the_ceiling(self, conn):
        predict._record(conn, "g1", "sunday", "claude-fable-5", _usage(400_000, 200_000))
        with pytest.raises(predict.BudgetExceeded):
            predict.check_budget(conn, budget=10.0)

    def test_ceiling_is_inclusive(self, conn):
        # Exactly at the ceiling must stop, not squeeze one more call through.
        predict._record(conn, "g1", "sunday", "claude-fable-5", _usage(0, 200_000))
        assert predict.month_spend(conn) == pytest.approx(10.0)
        with pytest.raises(predict.BudgetExceeded):
            predict.check_budget(conn, budget=10.0)

    def test_previous_month_does_not_count(self, conn):
        conn.execute(
            "INSERT INTO api_usage (called_at, model, input_tokens, output_tokens, cost_usd) "
            "VALUES ('2020-01-15T12:00:00', 'claude-fable-5', 0, 0, 999.0)"
        )
        conn.commit()
        assert predict.month_spend(conn) == 0.0
        predict.check_budget(conn, budget=10.0)


class TestKeyNumberCrossing:
    def test_crossing_three(self):
        assert market.crossed_key_number(2.5, 3.5) is True

    def test_moving_without_crossing(self):
        assert market.crossed_key_number(3.5, 4.0) is False

    def test_landing_on_a_major_key_number_qualifies(self):
        # 3.5 -> 3.0 passes through nothing, but it takes the hook away from a
        # pick argued on having it. Previously skipped; that is the bug this
        # pins. Symmetric, because leaving 3 changes the premise just as much.
        assert market.crossed_key_number(3.5, 3.0) is True
        assert market.crossed_key_number(3.0, 3.5) is True
        assert market.crossed_key_number(7.5, 7.0) is True

    def test_touching_a_minor_key_number_is_not_enough(self):
        # 4 is a key number but a thin one. Letting it trigger on touch would
        # qualify almost every half-point move and defeat the filter.
        assert market.crossed_key_number(3.5, 4.0) is False
        assert market.crossed_key_number(6.0, 6.5) is False

    def test_no_movement(self):
        assert market.crossed_key_number(3.0, 3.0) is False

    def test_sign_flip_uses_magnitude(self):
        # -2.5 to +3.5 is a two-point move through 3 in magnitude terms.
        assert market.crossed_key_number(-2.5, 3.5) is True

    def test_missing_snapshot_is_not_a_crossing(self):
        assert market.crossed_key_number(None, 3.5) is False
        assert market.crossed_key_number(3.5, None) is False

    def test_big_move_crosses_several(self):
        assert market.crossed_key_number(2.5, 7.5) is True


class TestRepredictFilter:
    def _game(self, conn, game_id="2026_01_AAA_BBB"):
        conn.execute(
            "INSERT INTO games (game_id, season, week, gameday, home_team, away_team) "
            "VALUES (?,2026,1,'2026-09-13','BBB','AAA')",
            (game_id,),
        )
        return game_id

    def _snapshot(self, conn, game_id, at, spread):
        conn.execute(
            "INSERT INTO line_snapshots (game_id, odds_event_id, commence_time, "
            "home_team, away_team, book, captured_at, spread_home) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (game_id, "evt", "2026-09-13T17:00", "BBB", "AAA", "dk", at, spread),
        )

    def _prediction(self, conn, game_id, at):
        conn.execute(
            "INSERT INTO predictions (game_id, model, created_at, run_label, "
            "pick_type, pick_side, paragraph) "
            "VALUES (?,'m',?,'sunday','spread','BBB','p')",
            (game_id, at),
        )

    def test_unpredicted_game_always_qualifies(self, conn):
        g = self._game(conn)
        assert market.games_needing_repredict(conn, 2026, 1) == [g]

    def test_predicted_and_unmoved_is_skipped(self, conn):
        g = self._game(conn)
        self._snapshot(conn, g, "2026-09-10T10:00:00", 3.5)
        self._prediction(conn, g, "2026-09-10T11:00:00")
        self._snapshot(conn, g, "2026-09-11T10:00:00", 4.0)
        assert market.games_needing_repredict(conn, 2026, 1) == []

    def test_predicted_then_crossed_qualifies(self, conn):
        g = self._game(conn)
        self._snapshot(conn, g, "2026-09-10T10:00:00", 2.5)
        self._prediction(conn, g, "2026-09-10T11:00:00")
        self._snapshot(conn, g, "2026-09-11T10:00:00", 3.5)
        assert market.games_needing_repredict(conn, 2026, 1) == [g]

    def test_no_snapshots_means_no_evidence_so_skip(self, conn):
        g = self._game(conn)
        self._prediction(conn, g, "2026-09-10T11:00:00")
        assert market.games_needing_repredict(conn, 2026, 1) == []

    def test_backtest_predictions_do_not_count_as_live(self, conn):
        g = self._game(conn)
        conn.execute(
            "INSERT INTO predictions (game_id, model, created_at, run_label, "
            "pick_type, pick_side, paragraph) "
            "VALUES (?,'m','2026-09-10T11:00:00','backtest','spread','BBB','p')",
            (g,),
        )
        assert market.games_needing_repredict(conn, 2026, 1) == [g]


class TestPlayedGamesAreNotRepredicted:
    def _game(self, conn, game_id, home_score=None):
        conn.execute(
            "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, "
            "home_score, away_score) VALUES (?,2026,1,'2026-09-13','BBB','AAA',?,?)",
            (game_id, home_score, None if home_score is None else 10),
        )

    def test_finished_games_are_split_out_in_order(self, conn):
        from edgelord.features.build import split_played

        self._game(conn, "g1")
        self._game(conn, "g2", home_score=13)
        self._game(conn, "g3")
        assert split_played(conn, ["g1", "g2", "g3"]) == (["g1", "g3"], ["g2"])

    def test_empty_selection(self, conn):
        from edgelord.features.build import split_played

        assert split_played(conn, []) == ([], [])

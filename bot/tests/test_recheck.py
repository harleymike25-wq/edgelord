"""What makes a live pick stale enough to flag, and what the cap lets through.

Every flag is a candidate for a paid rerun, so the detector is tested as much
for what it ignores (practice churn, bench players, small total moves) as for
what it catches (the Week 5 CLE, LAC and BAL changes).
"""

from datetime import datetime

import pytest

from edgelord import config, db, recheck
from edgelord.recheck import EASTERN


def _pack(spread=3.0, total=44.5, home_inj=(), away_inj=(), home_qb="Home QB",
          away_qb="Away QB", away_situation=None):
    return {
        "game": {"home_team": "ATL", "away_team": "BAL"},
        "market": {"current_spread_home": spread, "current_total": total},
        "home": {"quarterback": home_qb, "injuries": list(home_inj)},
        "away": {
            "quarterback": away_qb,
            "quarterback_situation": away_situation,
            "injuries": list(away_inj),
        },
    }


def _inj(player, status, position="WR", starter=True, snap=0.9):
    return {"player": player, "status": status, "position": position,
            "starter": starter, "snap_pct_prior": snap}


class TestInjuryChanges:
    def test_starter_ruled_out_is_flagged(self):
        old = _pack(away_inj=[_inj("Zay Flowers", "Limited Participation in Practice")])
        new = _pack(away_inj=[_inj("Zay Flowers", "Out")])
        assert recheck.injury_changes(old, new) == [
            "BAL WR Zay Flowers: Limited Participation in Practice -> Out"
        ]

    def test_starter_appearing_out_on_a_report_that_did_not_exist_is_flagged(self):
        # Week 5: whole teams had no report at pick time.
        new = _pack(home_inj=[_inj("Derwin James", "Out", position="S")])
        assert recheck.injury_changes(_pack(), new) == [
            "ATL S Derwin James: not listed -> Out"
        ]

    def test_expected_quarterback_change_is_flagged(self):
        old = _pack(away_situation={"expected_starter": "Lamar Jackson"})
        new = _pack(away_situation={"expected_starter": "Tyler Huntley"})
        assert "BAL expected QB Lamar Jackson -> Tyler Huntley" in recheck.injury_changes(old, new)

    def test_starting_quarterback_status_change_is_flagged(self):
        old = _pack(away_qb="Dillon Gabriel", away_inj=[_inj("Dillon Gabriel", "Full Participation in Practice", position="QB")])
        new = _pack(away_qb="Dillon Gabriel", away_inj=[_inj("Dillon Gabriel", "Questionable", position="QB")])
        assert recheck.injury_changes(old, new) == [
            "BAL QB Dillon Gabriel: Full Participation in Practice -> Questionable"
        ]

    def test_backup_quarterback_is_ignored(self):
        # DEN/LAC Week 5: Lance went Doubtful; Herbert started every snap.
        backup = dict(position="QB", starter=False, snap=0)
        old = _pack(home_qb="Justin Herbert")
        new = _pack(home_qb="Justin Herbert", home_inj=[_inj("Trey Lance", "Doubtful", **backup)])
        assert recheck.injury_changes(old, new) == []

    def test_backup_who_becomes_the_expected_starter_is_flagged(self):
        old = _pack(away_situation={"expected_starter": "Lamar Jackson"},
                    away_inj=[_inj("Lamar Jackson", "Did Not Participate In Practice", position="QB")])
        new = _pack(away_situation={"expected_starter": "Tyler Huntley"},
                    away_inj=[_inj("Lamar Jackson", "Out", position="QB")])
        assert recheck.injury_changes(old, new) == [
            "BAL expected QB Lamar Jackson -> Tyler Huntley",
            "BAL QB Lamar Jackson: Did Not Participate In Practice -> Out",
        ]

    def test_practice_churn_alone_is_ignored(self):
        old = _pack(home_inj=[_inj("A", "Did Not Participate In Practice")])
        new = _pack(home_inj=[_inj("A", "Limited Participation in Practice")])
        assert recheck.injury_changes(old, new) == []

    def test_starter_moving_between_available_and_questionable_is_ignored(self):
        old = _pack(home_inj=[_inj("A", "Full Participation in Practice")])
        new = _pack(home_inj=[_inj("A", "Questionable")])
        assert recheck.injury_changes(old, new) == []

    def test_bench_player_ruled_out_is_ignored(self):
        new = _pack(home_inj=[_inj("Backup", "Out", starter=False, snap=0.2)])
        assert recheck.injury_changes(_pack(), new) == []

    def test_doubtful_counts_as_out(self):
        old = _pack(home_inj=[_inj("A", "Out")])
        new = _pack(home_inj=[_inj("A", "Doubtful")])
        assert recheck.injury_changes(old, new) == []


class TestLineChanges:
    def test_spread_landing_on_three_is_flagged(self):
        assert recheck.line_changes(_pack(spread=2.5), _pack(spread=3.0), "spread")

    def test_spread_crossing_seven_is_flagged(self):
        assert recheck.line_changes(_pack(spread=-7.5), _pack(spread=-6.5), "spread")

    def test_a_move_between_key_numbers_is_ignored(self):
        assert recheck.line_changes(_pack(spread=8.5), _pack(spread=9.5), "spread") == []

    def test_total_move_counts_only_for_total_picks(self):
        old, new = _pack(total=44.5), _pack(total=42.5)
        assert recheck.line_changes(old, new, "total") == ["total 44.5 -> 42.5"]
        assert recheck.line_changes(old, new, "spread") == []

    def test_one_point_total_move_is_ignored(self):
        assert recheck.line_changes(_pack(total=44.5), _pack(total=43.5), "total") == []


class TestKickoff:
    GAME = {"gameday": "2026-10-11", "gametime": "13:00"}

    def test_before_kickoff(self):
        assert not recheck.kicked_off(self.GAME, datetime(2026, 10, 11, 11, 45, tzinfo=EASTERN))

    def test_after_kickoff_is_never_repicked(self):
        assert recheck.kicked_off(self.GAME, datetime(2026, 10, 11, 14, 50, tzinfo=EASTERN))

    def test_missing_time_is_not_treated_as_started(self):
        assert not recheck.kicked_off({"gameday": "2026-10-11", "gametime": None})


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _usage(conn, game_id, label, cost):
    conn.execute(
        "INSERT INTO api_usage (called_at, game_id, run_label, model, input_tokens, "
        "output_tokens, cost_usd) VALUES ('2026-10-11T12:00:00',?,?,'m',1,1,?)",
        (game_id, label, cost),
    )


class TestSpend:
    def test_week_spend_counts_only_this_weeks_rechecks(self, conn):
        _usage(conn, "2026_05_BAL_ATL", "recheck", 0.12)
        _usage(conn, "2026_05_IND_PIT", "recheck", 0.11)
        _usage(conn, "2026_05_IND_PIT", "manual", 0.50)       # a manual run
        _usage(conn, "2026_06_BAL_ATL", "recheck", 0.40)       # next week
        _usage(conn, "2026_05_LV_NE", "postmortem", 0.03)
        assert recheck.week_spend(conn, 2026, 5) == pytest.approx(0.23)

    def test_estimate_takes_the_dearest_recent_prediction(self, conn):
        _usage(conn, "g", "sunday", 0.09)
        _usage(conn, "g", "recheck", 0.13)
        _usage(conn, "g", "postmortem", 0.90)                   # not a prediction
        assert recheck.call_estimate(conn) == pytest.approx(0.13)

    def test_estimate_has_a_default_with_no_history(self, conn):
        assert recheck.call_estimate(conn) == pytest.approx(0.12)



class TestRunRespectsTheCap:
    """`recheck --run` is what the scheduler calls unattended."""

    @pytest.fixture()
    def calls(self, conn, monkeypatch):
        from edgelord import cli
        from edgelord.features import build

        flagged = [
            {"game_id": f"2026_05_G{i}", "prediction_id": i, "reasons": ["x"], "pack": {}}
            for i in range(3)
        ]
        made = []

        def fake_predict(conn, builder, game_id, **kw):
            made.append(game_id)
            _usage(conn, game_id, "recheck", 0.12)
            return {"_cost_usd": 0.12}

        monkeypatch.setattr(cli, "refresh_lines", lambda conn, season: {})
        monkeypatch.setattr(build, "FeatureBuilder", lambda seasons: None)
        monkeypatch.setattr(recheck, "detect", lambda *a, **k: flagged)
        monkeypatch.setattr(recheck, "store_flags", lambda *a, **k: None)
        monkeypatch.setattr(recheck, "call_estimate", lambda conn: 0.12)
        monkeypatch.setattr(cli, "predict_one", fake_predict)
        return made

    def _run(self, **kw):
        import argparse
        from edgelord import cli
        args = argparse.Namespace(season=2026, week=5, run=True, cap=None, allow=None)
        for k, v in kw.items():
            setattr(args, k, v)
        cli.cmd_recheck(args)

    def test_zero_cap_calls_no_model(self, calls, monkeypatch):
        monkeypatch.setattr(config, "RECHECK_WEEKLY_USD", 0.0)
        self._run()
        assert calls == []

    def test_cap_stops_before_the_call_that_would_exceed_it(self, calls):
        self._run(cap=0.30)
        assert len(calls) == 2           # 0.12 + 0.12 = 0.24; a third would be 0.36

    def test_flag_only_without_run(self, calls):
        self._run(run=False, cap=5.0)
        assert calls == []

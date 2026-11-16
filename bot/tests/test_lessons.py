"""The habit tags are arithmetic on stored factor points, so they are tested as such.

A tag that fires on the wrong picks would send a correct factor to be cut, and
a bar that reads 'act' on a handful of games is the noise-chasing this module
exists to prevent.
"""

from __future__ import annotations

import json

import pytest

from edgelord import config, db, evidence, lessons
from edgelord.features import market
from edgelord.shadow import FACTOR_KEYS, expected_starters


def _points(**kw) -> dict:
    return {"raw": {k: float(kw.get(k, 0.0)) for k in FACTOR_KEYS}, "multipliers": None}


def _thin_pack(dropbacks=46):
    return {"home": {"quarterback_situation": {
        "expected_starter": "Backup",
        "candidates": [
            {"player": "Starter", "form_this_season": {"dropbacks": 300}},
            {"player": "Backup", "form_this_season": {"dropbacks": dropbacks}},
        ]}}, "away": {}}


class TestTowardPick:
    def test_home_pick_keeps_the_sign(self):
        assert lessons.toward_pick(_points(team_strength=3), True)["team_strength"] == 3

    def test_away_pick_flips_it(self):
        assert lessons.toward_pick(_points(team_strength=3), False)["team_strength"] == -3

    def test_corrections_are_applied(self):
        fp = {"raw": {"team_strength": 2.0}, "multipliers": {"team_strength": 1.5}}
        assert lessons.toward_pick(fp, True)["team_strength"] == 3.0


class TestTags:
    def test_injuries_overriding_strength(self):
        # Away pick: strength says home by 3, injuries say away by 2.
        pts = lessons.toward_pick(_points(team_strength=3, availability=-2), False)
        tags = lessons.tags_for(pts, {})
        assert "injuries_over_strength" in tags
        assert "against_team_strength" in tags

    def test_injuries_with_strength_is_not_the_habit(self):
        pts = lessons.toward_pick(_points(team_strength=3, availability=2), True)
        assert lessons.tags_for(pts, {}) == []

    def test_small_injury_points_do_not_count(self):
        pts = lessons.toward_pick(_points(team_strength=3, availability=-0.5), False)
        assert "injuries_over_strength" not in lessons.tags_for(pts, {})

    def test_thin_quarterback_read(self):
        pts = lessons.toward_pick(_points(team_strength=2, quarterback=1.5), True)
        assert lessons.tags_for(pts, _thin_pack()) == ["thin_quarterback_read"]

    def test_quarterback_read_on_a_full_sample_is_not_thin(self):
        pts = lessons.toward_pick(_points(team_strength=2, quarterback=1.5), True)
        assert lessons.tags_for(pts, _thin_pack(dropbacks=250)) == []

    def test_no_quarterback_situation_is_not_thin(self):
        pts = lessons.toward_pick(_points(quarterback=3), True)
        assert "thin_quarterback_read" not in lessons.tags_for(pts, {"home": {}, "away": {}})

    def test_a_backup_with_no_snaps_at_all_is_thin(self):
        pack = {"home": {"quarterback_situation": {
            "expected_starter": "Rookie",
            "candidates": [{"player": "Rookie", "form_this_season": None}]}}}
        assert lessons.thin_quarterback(pack)

    def test_matchup_points_are_summed(self):
        pts = lessons.toward_pick(
            _points(team_strength=-2, pass_game=0.5, run_game=0.3, pressure=0.4), True)
        assert "matchup_over_strength" in lessons.tags_for(pts, {})


class TestHowPlayed:
    def test_outplayed(self):
        box = {"edge_epa_per_play_ex_turnovers": -0.2, "edge_success_rate": -0.06}
        assert lessons.how_played(box) == "outplayed"

    def test_won_the_snaps(self):
        box = {"edge_epa_per_play_ex_turnovers": 0.19, "edge_success_rate": 0.05}
        assert lessons.how_played(box) == "won_snaps"

    def test_mixed_is_even(self):
        box = {"edge_epa_per_play_ex_turnovers": 0.19, "edge_success_rate": -0.05}
        assert lessons.how_played(box) == "even"

    def test_no_play_by_play(self):
        assert lessons.how_played(None) is None


class TestTheBar:
    def test_a_handful_of_losses_is_too_few(self):
        v = lessons.verdict({"wins": 0, "losses": 9, "pushes": 0})
        assert v["verdict"] == "too few"
        assert v["needs"] == 11

    def test_a_coin_flip_holds(self):
        assert lessons.verdict({"wins": 11, "losses": 12, "pushes": 0})["verdict"] == "hold"

    def test_a_real_losing_habit_acts(self):
        v = lessons.verdict({"wins": 6, "losses": 16, "pushes": 0})
        assert v["verdict"] == "act"
        assert v["p_value"] < lessons.P_BAR

    def test_a_winning_habit_never_acts(self):
        assert lessons.verdict({"wins": 18, "losses": 4, "pushes": 0})["verdict"] == "hold"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _graded(conn, game_id, week, side, result, points, *, label="blind", conviction="lean"):
    home, away = game_id.split("_")[3], game_id.split("_")[2]
    conn.execute(
        "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, "
        "home_score, away_score) VALUES (?,2026,?,'2026-11-22',?,?,20,17)",
        (game_id, week, home, away),
    )
    cur = conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, conviction, line_at_pick, paragraph, factor_points) "
        "VALUES (?,'m','2026-11-20T10:00:00',?,'spread',?,?,1.0,'p',?)",
        (game_id, label, side, conviction, json.dumps(points)),
    )
    conn.execute(
        "INSERT INTO results (prediction_id, game_id, home_score, away_score, "
        "pick_result, profit_units, graded_at) VALUES (?,?,20,17,?,0,'t')",
        (cur.lastrowid, game_id, result),
    )


class TestTally:
    def test_wins_and_losses_both_count_and_weeks_split(self, conn):
        habit = _points(team_strength=3, availability=-2)       # away pick
        _graded(conn, "2026_09_AAA_BBB", 9, "AAA", "loss", habit)
        _graded(conn, "2026_11_CCC_DDD", 11, "CCC", "win", habit)
        _graded(conn, "2026_11_EEE_FFF", 11, "FFF", "loss", _points(team_strength=3))
        out = lessons.tally(conn, 2026)

        assert out["hindsight"]["tags"]["injuries_over_strength"]["record"] == "0-1"
        assert out["hindsight"]["tags"]["injuries_over_strength"]["verdict"] == "hindsight"
        test = out["test"]
        assert test["picks"] == 2
        assert test["tags"]["injuries_over_strength"]["record"] == "1-0"
        assert test["tags"]["injuries_over_strength"]["verdict"] == "too few"
        assert test["factors"]["team_strength"]["leaned_on"]["record"] == "0-1"
        assert test["factors"]["team_strength"]["went_against"]["record"] == "1-0"

    def test_only_standing_blind_picks(self, conn):
        _graded(conn, "2026_11_AAA_BBB", 11, "BBB", "win", _points(team_strength=3),
                label="sunday")
        assert lessons.tally(conn, 2026)["test"]["picks"] == 0


class TestBacktestsStayOutOfTheVerdict:
    """The 2026-11-16 audit: three graded backtest best bets were in the verdict."""

    def test_a_backtest_best_bet_is_not_a_decided_play(self, conn):
        _graded(conn, "2026_11_AAA_BBB", 11, "BBB", "win", _points(),
                label="backtest", conviction="best_bet")
        assert evidence.assess(conn, season=2026)["plays_decided"] == 0

    def test_a_live_best_bet_still_is(self, conn):
        _graded(conn, "2026_11_AAA_BBB", 11, "BBB", "win", _points(),
                conviction="best_bet")
        assert evidence.assess(conn, season=2026)["plays_decided"] == 1


class TestExpectedStarters:
    def test_reads_the_id_from_a_quarterback_situation(self):
        pack = {"game": {"game_id": "G"},
                "home": {"quarterback_situation": {"expected_starter_id": "00-1"}},
                "away": {"quarterback_situation": None}}
        assert expected_starters([pack]) == {"G": {"home": "00-1"}}

    def test_a_settled_game_names_nobody(self):
        assert expected_starters([{"game": {"game_id": "G"}, "home": {}, "away": {}}]) == {}

    def test_the_model_never_sees_the_id(self):
        from edgelord.predict import model_view
        pack = {"home": {"quarterback_situation": {
            "expected_starter": "Drew Lock", "expected_starter_id": "00-1"}}, "away": {}}
        seen = model_view(pack)["home"]["quarterback_situation"]
        assert seen == {"expected_starter": "Drew Lock"}
        # The stored pack keeps it.
        assert pack["home"]["quarterback_situation"]["expected_starter_id"] == "00-1"


class TestSnapshotTimeZones:
    """Snapshots are stamped UTC, picks local. They must compare as instants."""

    def _setup(self, conn, snaps):
        conn.execute(
            "INSERT INTO games (game_id, season, week, gameday, home_team, away_team) "
            "VALUES ('G',2026,1,'2026-09-13','BBB','AAA')")
        for at, spread in snaps:
            conn.execute(
                "INSERT INTO line_snapshots (game_id, odds_event_id, commence_time, "
                "home_team, away_team, book, captured_at, spread_home) "
                "VALUES ('G','evt','t','BBB','AAA','nflverse',?,?)", (at, spread))

    def test_offsets_are_compared_as_instants(self, conn):
        # 15:00 UTC is before 12:00 at UTC-5 (17:00 UTC), though "15" sorts after "12".
        self._setup(conn, [("2026-09-10T09:00:00+00:00", 2.5),
                           ("2026-09-10T15:00:00+00:00", 3.5)])
        assert market._consensus_at(conn, "G", "2026-09-10T12:00:00-05:00") == 3.5

    def test_a_later_snapshot_is_not_the_line_at_the_pick(self, conn):
        self._setup(conn, [("2026-09-10T09:00:00+00:00", 2.5),
                           ("2026-09-10T18:00:00+00:00", 3.5)])
        assert market._consensus_at(conn, "G", "2026-09-10T12:00:00-05:00") == 2.5
        assert market._consensus_at(conn, "G", None) == 3.5


class TestQuarterbackBaselineStarters:
    """Who the baseline thinks is starting a game that has not been played."""

    def _replay(self, upcoming_qb, starters=None):
        import polars as pl
        from edgelord.models import qb

        def game(gid, week, home_qb, margin):
            return {"game_id": gid, "season": 2026, "week": week, "game_type": "REG",
                    "home_team": "AAA", "away_team": "BBB", "margin": margin,
                    "spread_line": None, "market_prob": None, "neutral": False,
                    "home_rest": 7, "away_rest": 7,
                    "home_qb_id": home_qb, "away_qb_id": "opp"}

        games = pl.DataFrame(
            [game(f"g{w}", w, "star", 7) for w in range(1, 9)]
            + [game("next", 9, upcoming_qb, None)],
            infer_schema_length=None,
        )
        # The star is far better than replacement; the backup has never played.
        qbg = pl.DataFrame(
            [{"game_id": f"g{w}", "passer_id": "star", "dropbacks": 40, "epa": 12.0}
             for w in range(1, 9)]
            + [{"game_id": f"g{w}", "passer_id": "opp", "dropbacks": 40, "epa": 0.0}
               for w in range(1, 9)]
        )
        rep = qb.replay(games, qbg, starters=starters)
        return rep.filter(pl.col("game_id") == "next")["qb_home_adj"][0]

    def test_no_starter_named_assumes_last_weeks(self):
        assert self._replay(None) == pytest.approx(self._replay("star"))

    def test_an_expected_backup_moves_the_baseline(self):
        # A backup who has never played is valued at replacement level, well
        # below the starter the team's results were built on.
        backup = self._replay(None, {"next": {"home": "backup"}})
        assert backup < self._replay(None) - 0.1

    def test_the_schedules_own_starter_wins_over_the_packs(self):
        with_schedule = self._replay("star", {"next": {"home": "backup"}})
        assert with_schedule == pytest.approx(self._replay("star"))

"""Player-level form.

The point of this module is the case where team efficiency and player form
disagree -- a quarterback whose season line looks fine while the last month
does not. The usage floors matter just as much: without them a backup's three
efficient carries outrank a starter's two hundred.
"""

import polars as pl
import pytest

from edgelord.features import players

COLS = [
    "season", "week", "season_type", "posteam", "game_id", "qb_dropback",
    "pass", "rush", "epa", "success", "cpoe", "sack", "interception",
    "pass_touchdown", "air_yards", "yards_gained",
    "passer_player_id", "passer_player_name",
    "rusher_player_id", "rusher_player_name",
    "receiver_player_id", "receiver_player_name",
]


def _pbp(rows):
    return pl.DataFrame(rows, schema=COLS, orient="row")


def _dropback(week, qb, epa, cpoe=0.0, game=None, success=1, sack=0):
    return (
        2025, week, "REG", "AAA", game or f"g{week}", 1,
        1, 0, epa, success, cpoe, sack, 0, 0, 8.0, 10.0,
        f"id_{qb}", qb, None, None, None, None,
    )


def _carry(week, rb, epa, game=None):
    return (
        2025, week, "REG", "AAA", game or f"g{week}", 0,
        0, 1, epa, 1, None, 0, 0, 0, None, 4.0,
        None, None, f"id_{rb}", rb, None, None,
    )


class TestQuarterback:
    def test_identifies_the_primary_passer_by_volume(self):
        rows = [_dropback(w, "Starter", 0.1) for w in range(1, 11)] * 4
        rows += [_dropback(1, "Backup", 0.9)] * 5
        qb = players.quarterback(_pbp(rows), "AAA", 2025, 12)
        assert qb["player"] == "Starter"

    def test_backup_below_the_floor_is_ignored(self):
        """Five efficient dropbacks must not outrank a season of starts."""
        rows = [_dropback(w, "Starter", 0.05) for w in range(1, 11)] * 4
        rows += [_dropback(1, "Backup", 2.0)] * 5
        qb = players.quarterback(_pbp(rows), "AAA", 2025, 12)
        assert qb["player"] == "Starter"
        assert qb["epa_per_dropback"] == pytest.approx(0.05, abs=1e-3)

    def test_returns_none_when_nobody_clears_the_floor(self):
        rows = [_dropback(1, "Backup", 0.5)] * 5
        assert players.quarterback(_pbp(rows), "AAA", 2025, 12) is None

    def test_respects_the_as_of_week(self):
        """Week 6 must not see week 8 -- this is the backtest leak guard."""
        rows = [_dropback(w, "QB", 0.1) for w in range(1, 6)] * 8
        rows += [_dropback(8, "QB", -5.0)] * 40
        qb = players.quarterback(_pbp(rows), "AAA", 2025, 6)
        assert qb["epa_per_dropback"] > 0

    def test_recent_window_can_diverge_from_the_season(self):
        early = [_dropback(w, "QB", 0.30) for w in range(1, 7)] * 8
        late = [_dropback(w, "QB", -0.30) for w in range(7, 11)] * 10
        df = _pbp(early + late)

        season = players.quarterback(df, "AAA", 2025, 11)
        recent = players.quarterback(df, "AAA", 2025, 11, last_n_weeks=4)
        assert season["epa_per_dropback"] > recent["epa_per_dropback"]
        assert recent["epa_per_dropback"] < 0

    def test_counts_touchdowns_and_interceptions(self):
        rows = [_dropback(w, "QB", 0.1) for w in range(1, 11)] * 4
        df = _pbp(rows)
        qb = players.quarterback(df, "AAA", 2025, 12)
        assert qb["dropbacks"] == 40
        assert qb["sack_rate"] == 0.0


class TestSkillPlayers:
    def test_ranks_by_usage_not_efficiency(self):
        rows = [_carry(w, "Workhorse", 0.01) for w in range(1, 11)] * 5
        rows += [_carry(1, "Scatback", 3.0)] * 25
        out = players.skill_players(_pbp(rows), "AAA", 2025, 12)
        assert out["rushers"][0]["player"] == "Workhorse"

    def test_below_the_carry_floor_is_excluded(self):
        rows = [_carry(w, "Workhorse", 0.01) for w in range(1, 11)] * 5
        rows += [_carry(1, "Fullback", 1.0)] * 3
        out = players.skill_players(_pbp(rows), "AAA", 2025, 12)
        assert [r["player"] for r in out["rushers"]] == ["Workhorse"]

    def test_caps_the_list(self):
        rows = []
        for i in range(6):
            rows += [_carry(w, f"RB{i}", 0.1) for w in range(1, 6)] * 5
        out = players.skill_players(_pbp(rows), "AAA", 2025, 12)
        assert len(out["rushers"]) <= players.TOP_SKILL_PLAYERS


class TestProfile:
    def test_empty_input_yields_empty_profile(self):
        assert players.profile(_pbp([]), "AAA", 2025, 1) == {}

    def test_week_one_has_nothing_to_report(self):
        rows = [_dropback(w, "QB", 0.1) for w in range(1, 11)] * 4
        assert players.profile(_pbp(rows), "AAA", 2025, 1) == {}

    def test_carries_both_windows_when_available(self):
        rows = [_dropback(w, "QB", 0.1) for w in range(1, 11)] * 6
        out = players.profile(_pbp(rows), "AAA", 2025, 11)
        assert "quarterback_season" in out
        assert "quarterback_last_5" in out

    def test_other_teams_are_excluded(self):
        rows = [_dropback(w, "QB", 0.1) for w in range(1, 11)] * 4
        out = players.profile(_pbp(rows), "ZZZ", 2025, 11)
        assert out == {}

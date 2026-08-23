"""Roster continuity, depth charts and injury weighting.

Every bug found building this module produced a plausible-looking number that
was wrong -- a team silently dropped by an abbreviation mismatch, continuity
understated by a null-heavy join key, notable departures never firing because
the threshold used the wrong denominator. Each of those gets a test here.
"""

import polars as pl
import pytest

from edgelord.features import context, roster


def _snaps(rows):
    """rows: (team, pfr_id, player, position, off_snaps, def_snaps, off_pct, def_pct)"""
    return pl.DataFrame(
        rows,
        schema=[
            "team", "pfr_player_id", "player", "position",
            "offense_snaps", "defense_snaps", "offense_pct", "defense_pct",
        ],
        orient="row",
    )


def _roster(rows):
    return pl.DataFrame(rows, schema=["team", "gsis_id"], orient="row")


def _players(rows):
    return pl.DataFrame(rows, schema=["pfr_id", "gsis_id"], orient="row")


class TestTeamAliases:
    def test_arizona_reconciles(self):
        """Rosters say AZ, snap counts say ARI. Unmapped, Arizona vanishes."""
        snaps = _snaps([("ARI", "P1", "Starter", "QB", 1000, 0, 0.95, 0.0)])
        ros = _roster([("AZ", "G1")])
        out = roster.continuity(snaps, ros, _players([("P1", "G1")]))
        assert "ARI" in out
        assert out["ARI"]["offense_continuity"] == 1.0

    def test_other_known_aliases(self):
        for alias, canonical in [("WSH", "WAS"), ("LAR", "LA"), ("JAC", "JAX")]:
            assert roster.TEAM_ALIASES[alias] == canonical


class TestCrosswalkJoin:
    def test_matches_through_gsis_not_pfr(self):
        """Roster pfr_id is ~1/3 null; the join must not depend on it."""
        snaps = _snaps([("NE", "P1", "Keeper", "WR", 900, 0, 0.9, 0.0)])
        ros = _roster([("NE", "G1")])
        out = roster.continuity(snaps, ros, _players([("P1", "G1")]))
        assert out["NE"]["offense_continuity"] == 1.0

    def test_player_who_left_is_not_retained(self):
        snaps = _snaps([("NE", "P1", "Leaver", "WR", 900, 0, 0.9, 0.0)])
        ros = _roster([("MIA", "G1")])
        out = roster.continuity(snaps, ros, _players([("P1", "G1")]))
        assert out["NE"]["offense_continuity"] == 0.0
        assert out["NE"]["departures"][0]["now"] == "MIA"

    def test_unsigned_player_reads_as_off_a_roster(self):
        snaps = _snaps([
            ("NE", "P1", "Retiree", "WR", 900, 0, 0.9, 0.0),
            ("NE", "P2", "Keeper", "TE", 900, 0, 0.9, 0.0),
        ])
        ros = _roster([("NE", "G2")])  # only the keeper is still signed
        cross = _players([("P1", "G1"), ("P2", "G2")])
        out = roster.continuity(snaps, ros, cross)
        assert out["NE"]["departures"][0]["now"] == "not on a roster"

    def test_empty_current_roster_yields_nothing_rather_than_zero(self):
        """No roster means unknown, not 'everyone left'."""
        snaps = _snaps([("NE", "P1", "Someone", "WR", 900, 0, 0.9, 0.0)])
        assert roster.continuity(snaps, _roster([]), _players([("P1", "G1")])) == {}


class TestSnapWeighting:
    def test_continuity_weights_by_snaps_not_headcount(self):
        """Losing one 1000-snap starter outweighs keeping three scrubs."""
        snaps = _snaps([
            ("NE", "P1", "Starter", "QB", 1000, 0, 0.98, 0.0),
            ("NE", "P2", "Scrub1", "WR", 20, 0, 0.02, 0.0),
            ("NE", "P3", "Scrub2", "WR", 20, 0, 0.02, 0.0),
            ("NE", "P4", "Scrub3", "WR", 20, 0, 0.02, 0.0),
        ])
        ros = _roster([("NE", "G2"), ("NE", "G3"), ("NE", "G4")])  # starter gone
        cross = _players([("P1", "G1"), ("P2", "G2"), ("P3", "G3"), ("P4", "G4")])
        out = roster.continuity(snaps, ros, cross)
        # 60 of 1060 snaps retained, not 3 of 4 players.
        assert out["NE"]["offense_continuity"] == pytest.approx(0.057, abs=0.01)

    def test_notable_threshold_uses_player_share_of_team_plays(self):
        """A starter is ~98% of team plays but under 10% of summed roster snaps.

        Measured against the summed denominator the starter scores 0.08 and
        never crosses the notable threshold, which is the bug this pins.
        """
        snaps = _snaps([
            ("NE", "P1", "Starter", "QB", 1000, 0, 0.98, 0.0),
            *[
                ("NE", f"P{i}", f"Sub{i}", "WR", 500, 0, 0.45, 0.0)
                for i in range(2, 12)
            ],
        ])
        # Everyone re-signs except the starter.
        ros = _roster([("NE", f"G{i}") for i in range(2, 12)])
        cross = _players([(f"P{i}", f"G{i}") for i in range(1, 12)])
        out = roster.continuity(snaps, ros, cross)
        assert [d["player"] for d in out["NE"]["departures"]] == ["Starter"]


class TestCarryover:
    def test_high_continuity_keeps_full_carryover(self):
        assert roster.carryover_for(0.90, 0.6) == 0.6

    def test_low_continuity_halves_it(self):
        assert roster.carryover_for(0.40, 0.6) == pytest.approx(0.3)

    def test_midrange_interpolates(self):
        v = roster.carryover_for(0.70, 0.6)
        assert 0.3 < v < 0.6

    def test_unknown_continuity_is_neutral(self):
        assert roster.carryover_for(None, 0.6) == 0.6


class TestDepthChart:
    def _depth(self, rows):
        return pl.DataFrame(
            rows, schema=["dt", "team", "player_name", "pos_abb", "pos_rank"],
            orient="row",
        )

    def test_uses_only_the_latest_chart(self):
        d = self._depth([
            ("2026-08-01", "SEA", "Old Starter", "QB", 1),
            ("2026-08-23", "SEA", "New Starter", "QB", 1),
        ])
        assert roster.depth_chart(d, "SEA")["quarterback"] == "New Starter"

    def test_groups_by_position_in_rank_order(self):
        d = self._depth([
            ("2026-08-23", "SEA", "QB2", "QB", 2),
            ("2026-08-23", "SEA", "QB1", "QB", 1),
        ])
        assert roster.depth_chart(d, "SEA")["by_position"]["QB"] == ["QB1", "QB2"]

    def test_respects_team_aliases(self):
        d = self._depth([("2026-08-23", "AZ", "Starter", "QB", 1)])
        assert roster.depth_chart(d, "ARI")["quarterback"] == "Starter"

    def test_empty_input(self):
        assert roster.depth_chart(pl.DataFrame(), "SEA") == {}


class TestInjuryWeighting:
    def _injuries(self, rows):
        return pl.DataFrame(
            rows,
            schema=[
                "season", "week", "team", "gsis_id", "position", "full_name",
                "report_status", "practice_status", "report_primary_injury",
                "practice_primary_injury",
            ],
            orient="row",
        )

    def test_starter_and_scrub_are_distinguishable(self):
        inj = self._injuries([
            (2025, 12, "NYJ", "G1", "DE", "Starter", "Questionable", None, "Quad", None),
            (2025, 12, "NYJ", "G2", "RB", "Scrub", "Questionable", None, "Hamstring", None),
        ])
        usage = {"G1": {"snap_pct": 0.655}, "G2": {"snap_pct": 0.005}}
        out = context.injury_report(inj, "NYJ", 2025, 12, usage=usage)
        assert out[0]["player"] == "Starter"      # heavier usage sorts first
        assert out[0]["starter"] is True
        assert out[1]["starter"] is False

    def test_out_outranks_questionable_regardless_of_usage(self):
        inj = self._injuries([
            (2025, 12, "NYJ", "G1", "DE", "BigQ", "Questionable", None, "Quad", None),
            (2025, 12, "NYJ", "G2", "RB", "SmallOut", "Out", None, "Hamstring", None),
        ])
        usage = {"G1": {"snap_pct": 0.95}, "G2": {"snap_pct": 0.10}}
        out = context.injury_report(inj, "NYJ", 2025, 12, usage=usage)
        assert out[0]["player"] == "SmallOut"

    def test_missing_usage_is_not_treated_as_a_scrub(self):
        inj = self._injuries([
            (2025, 12, "NYJ", "G9", "CB", "Rookie", "Out", None, "Concussion", None),
        ])
        out = context.injury_report(inj, "NYJ", 2025, 12, usage={})
        assert out[0]["snap_pct_prior"] is None
        assert out[0]["starter"] is False

    def test_works_without_usage_at_all(self):
        inj = self._injuries([
            (2025, 12, "NYJ", "G1", "DE", "Someone", "Out", None, "Quad", None),
        ])
        assert context.injury_report(inj, "NYJ", 2025, 12)[0]["player"] == "Someone"

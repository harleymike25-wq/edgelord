"""Unit-versus-unit ratings.

Sign conventions are the whole risk here. `edge` is offence minus what the
defence allows, so positive must always favour the offence -- and pressure runs
the other way, because a pass rush beating a protection is an edge to the
defence. Getting either backwards would invert the read on every game without
raising anything.
"""

import pytest

from edgelord.features import matchup


def _eff(off_epa, def_epa, **kw):
    """Minimal split-efficiency block."""
    off = {
        "epa_adj": off_epa, "success_rate": kw.get("off_success", 0.45),
        "explosive_rate": kw.get("off_explosive", 0.12),
        "rz_td_pct": kw.get("off_rz", 0.55), "third_down_rate": kw.get("off_third", 0.40),
        "pressure_rate": kw.get("protection", 0.15),
        "plays_per_game": kw.get("off_pace", 62.0),
    }
    dfn = {
        "epa_adj": def_epa, "success_rate": kw.get("def_success", 0.45),
        "explosive_rate": kw.get("def_explosive", 0.12),
        "rz_td_pct": kw.get("def_rz", 0.55), "third_down_rate": kw.get("def_third", 0.40),
        "pressure_rate": kw.get("pass_rush", 0.15),
        "plays_per_game": kw.get("def_pace", 62.0),
    }
    return {"offense": off, "defense": dfn}


class TestSignConvention:
    """EPA ratings combine by addition, not subtraction.

    Both sides are centred on zero by the opponent adjustment, so an offence at
    +0.05 facing a defence allowing -0.05 is a league-average matchup. Getting
    this backwards scores an elite defence as help to the opponent.
    """

    def test_good_offence_versus_bad_defence_favours_the_offence(self):
        r = matchup.ratings("HOME", "AWAY", _eff(0.15, 0.0), _eff(0.0, 0.10))
        unit = r["units"][0]                      # HOME offence vs AWAY defence
        assert unit["epa_per_play"]["projected"] == pytest.approx(0.25)
        assert unit["verdict"] == "clear edge to the offense"

    def test_average_offence_versus_elite_defence_favours_the_defence(self):
        # AWAY defence allows -0.12: elite. HOME offence is average.
        r = matchup.ratings("HOME", "AWAY", _eff(0.01, 0.0), _eff(0.0, -0.12))
        unit = r["units"][0]
        assert unit["epa_per_play"]["projected"] == pytest.approx(-0.11)
        assert unit["verdict"] == "clear edge to the defense"

    def test_good_offence_and_good_defence_cancel_to_average(self):
        """The case a subtraction gets exactly wrong."""
        r = matchup.ratings("HOME", "AWAY", _eff(0.10, 0.0), _eff(0.0, -0.10))
        unit = r["units"][0]
        assert unit["epa_per_play"]["projected"] == pytest.approx(0.0)
        assert unit["verdict"] == "roughly even"

    def test_evenly_matched_reads_as_even(self):
        r = matchup.ratings("HOME", "AWAY", _eff(0.02, 0.0), _eff(0.0, 0.01))
        assert r["units"][0]["verdict"] == "roughly even"

    def test_rate_metrics_use_a_league_baseline(self):
        """Rates sit around ~0.45, not zero, so the baseline must be subtracted."""
        r = matchup.ratings(
            "HOME", "AWAY",
            _eff(0.0, 0.0, off_success=0.50),   # good offence
            _eff(0.0, 0.0, def_success=0.45),   # average defence
        )
        s = r["units"][0]["success_rate"]
        assert s["league_avg"] == pytest.approx(0.45)
        assert s["projected"] == pytest.approx(0.50)   # 0.50 + (0.45 - 0.45)
        assert s["edge"] == pytest.approx(0.05)

    def test_pressure_runs_the_other_way(self):
        """A pass rush beating a protection is an edge to the DEFENCE."""
        r = matchup.ratings(
            "HOME", "AWAY",
            _eff(0.0, 0.0, protection=0.12),   # home line allows little pressure
            _eff(0.0, 0.0, pass_rush=0.22),    # away rush generates a lot
        )
        pr = r["units"][0]["pressure"]
        assert pr["defense_generates"] == 0.22
        assert pr["offense_allows"] == 0.12
        assert pr["edge_to_defense"] == pytest.approx(0.10)


class TestBothPairings:
    def test_produces_one_unit_per_side(self):
        r = matchup.ratings("HOME", "AWAY", _eff(0.1, 0.0), _eff(0.0, 0.1))
        assert len(r["units"]) == 2
        assert r["units"][0]["matchup"] == "HOME offense vs AWAY defense"
        assert r["units"][1]["matchup"] == "AWAY offense vs HOME defense"

    def test_a_team_can_be_strong_on_one_side_and_not_the_other(self):
        """The case a single team rating hides."""
        home = _eff(0.01, -0.12)   # mediocre offence, excellent defence
        away = _eff(0.01, 0.01)    # average both ways
        r = matchup.ratings("HOME", "AWAY", home, away)
        # HOME offence vs AWAY's average defence: nothing special.
        assert r["units"][0]["verdict"] == "roughly even"
        # AWAY's average offence into HOME's elite defence: the defence wins.
        assert r["units"][1]["verdict"] == "clear edge to the defense"
        assert r["units"][1]["epa_per_play"]["projected"] == pytest.approx(-0.11)


class TestBiggestMismatch:
    def test_picks_the_larger_gap(self):
        home = _eff(0.02, -0.15)   # elite defence
        away = _eff(0.01, 0.01)
        out = matchup.ratings("HOME", "AWAY", home, away)["biggest_mismatch"]
        assert "AWAY offense vs HOME defense" in out
        assert "defense" in out

    def test_ignores_pressure_when_ranking(self):
        """The headline mismatch is decided on EPA, not on pass rush."""
        home = _eff(0.01, 0.01, protection=0.30)
        away = _eff(0.01, 0.01, pass_rush=0.10)
        assert "no unit mismatch stands out" in (
            matchup.ratings("HOME", "AWAY", home, away)["biggest_mismatch"]
        )

    def test_says_so_when_nothing_stands_out(self):
        r = matchup.ratings("HOME", "AWAY", _eff(0.01, 0.0), _eff(0.0, 0.01))
        assert "no unit mismatch stands out" in r["biggest_mismatch"]


class TestMissingData:
    def test_empty_blocks_do_not_raise(self):
        r = matchup.ratings("HOME", "AWAY", {}, {})
        assert r["units"][0] == {"matchup": "HOME offense vs AWAY defense"}
        assert r["biggest_mismatch"] is None

    def test_partial_metrics_are_skipped_not_faked(self):
        home = {"offense": {"epa_adj": 0.1}, "defense": {"epa_adj": 0.0}}
        away = {"offense": {"epa_adj": 0.0}, "defense": {"epa_adj": 0.0}}
        unit = matchup.ratings("HOME", "AWAY", home, away)["units"][0]
        assert "epa_per_play" in unit
        assert "success_rate" not in unit
        assert "pressure" not in unit

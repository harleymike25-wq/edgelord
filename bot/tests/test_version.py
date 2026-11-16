"""The version stamp is what lets the record be read one predictor at a time.

The first test here is the guard: it fails whenever the recipe changes without
a new named entry in `version.VERSIONS`. That is on purpose. If it fails, do
not paste the new fingerprint in to make it pass -- decide whether the change
was meant, and if it was, give it a name and a line saying what changed.
"""

from __future__ import annotations

import pytest

from edgelord import config, db, shadow, track, version


def test_the_current_recipe_is_a_named_version():
    fp = version.fingerprint()
    assert fp in version.VERSIONS, (
        f"the predictor's recipe changed (fingerprint {fp}) without a new entry in "
        "edgelord/version.py VERSIONS. If the change is deliberate, add it there "
        "with a name and what changed, and note it in VERIFIED.md."
    )


def test_a_threshold_change_is_a_different_version(monkeypatch):
    before = version.fingerprint()
    monkeypatch.setattr(shadow, "TOTAL_PICK_EDGE", 4.0)
    assert version.fingerprint() != before
    assert version.name() == "unregistered"


def test_a_prompt_change_is_a_different_version(monkeypatch):
    before = version.fingerprint()
    monkeypatch.setattr(shadow, "SYSTEM_PROMPT", shadow.SYSTEM_PROMPT + " Be bold.")
    assert version.fingerprint() != before


def test_the_machines_effort_setting_does_not_change_the_fingerprint(monkeypatch):
    before = version.fingerprint()
    monkeypatch.setattr(config, "PREDICT_EFFORT", "max")
    assert version.fingerprint() == before


def test_stamp_carries_model_and_effort_and_shortens_to_the_name():
    s = version.stamp("claude-opus-5-5", "medium")
    assert s.endswith(" claude-opus-5-5 medium")
    assert version.short(s) == version.name()
    assert version.short(None) == "unstamped"
    assert version.short("v3 computed tiers+reconstructed") == "v3 computed tiers"


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        yield c


def _pick(conn, game_id, week, result, stamp=None, label="blind"):
    home, away = game_id.split("_")[3], game_id.split("_")[2]
    conn.execute(
        "INSERT INTO games (game_id, season, week, gameday, home_team, away_team, "
        "home_score, away_score) VALUES (?,2026,?,'2026-11-22',?,?,20,17)",
        (game_id, week, home, away))
    cur = conn.execute(
        "INSERT INTO predictions (game_id, model, created_at, run_label, pick_type, "
        "pick_side, paragraph, predictor_version) VALUES (?,'m','t',?,'spread',?,'p',?)",
        (game_id, label, home, stamp))
    conn.execute(
        "INSERT INTO results (prediction_id, game_id, home_score, away_score, "
        "pick_result, profit_units, graded_at) VALUES (?,?,20,17,?,?,'t')",
        (cur.lastrowid, game_id, result, 0.91 if result == "win" else -1.0))
    return cur.lastrowid


class TestRecordByVersion:
    def test_each_version_gets_its_own_line(self, conn):
        _pick(conn, "2026_10_AAA_BBB", 10, "loss", "v6 blind with corrections+reconstructed")
        _pick(conn, "2026_11_CCC_DDD", 11, "win", version.stamp("m", "medium"))
        _pick(conn, "2026_11_EEE_FFF", 11, "win", version.stamp("m", "medium"))
        by = track.record(conn, season=2026)["by_version"]
        assert list(by) == ["v6 blind with corrections", version.name()]
        assert by["v6 blind with corrections"]["record"] == "0-1"
        assert by[version.name()]["record"] == "2-0"

    def test_no_picks_is_an_empty_table_not_a_missing_one(self, conn):
        assert track.record(conn, season=2026)["by_version"] == {}


class TestBackfill:
    def test_names_by_week_and_only_fills_blanks(self, conn):
        old = _pick(conn, "2026_03_AAA_BBB", 3, "win")
        kept = _pick(conn, "2026_09_CCC_DDD", 9, "win", "already+stamped")
        later = _pick(conn, "2026_11_EEE_FFF", 11, "win")
        test = _pick(conn, "2026_02_GGG_HHH", 2, "win", label="backtest")
        assert version.backfill(conn) == 1

        def stamp(pid):
            return conn.execute(
                "SELECT predictor_version FROM predictions WHERE id = ?", (pid,)
            ).fetchone()[0]

        assert stamp(old) == "v3 computed tiers+reconstructed"
        assert stamp(kept) == "already+stamped"
        assert stamp(later) is None        # after stamping began: nothing to guess
        assert stamp(test) is None         # backtests are never part of the record


def test_a_stored_blind_pick_carries_the_stamp(conn):
    from edgelord import predict as predictor
    pack = {"game": {"game_id": "2026_11_AAA_BBB", "home_team": "BBB", "away_team": "AAA"},
            "market": {"current_spread_home": 3.0, "current_total": 44.5}}
    factors = {k: {"favors": "neither", "points": 0, "evidence": "solid", "reading": "x"}
               for k in shadow.FACTOR_KEYS}
    out = {"factors": factors, "projected_total": 44.0, "headline": "h",
           "paragraph": "p", "baseline_disagreement": "agree", "_model": "m"}
    result = shadow.to_prediction(pack, out, shadow.assemble(pack, out, None))
    result["predictor_version"] = version.stamp("m", "medium")
    pid = predictor.store(conn, "2026_11_AAA_BBB", None, pack, result, run_label="blind",
                          conviction="coin_flip")
    row = conn.execute("SELECT predictor_version FROM predictions WHERE id = ?", (pid,)).fetchone()
    assert row[0] == f"{version.name()}+{version.fingerprint()} m medium"

"""`predict` snapshots the line before anything reads one.

The market block reads `line_snapshots`, not `games.spread_line`. On
2026-09-24 a manual `refresh` then `predict` priced ATL/GB off a week-old 6.5
while the real line was 4.5, and the pick was paid for before anyone noticed.
Nothing raised: the pack was well-formed, just wrong. So the order is pinned
here -- lines first, then game selection, then packs -- with every expensive
or networked piece stubbed out. No model calls.
"""

import pytest

from edgelord import cli, config, db
from edgelord import predict as predictor
from edgelord.features import build, market

GAME = "2026_03_AAA_BBB"


@pytest.fixture()
def calls(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    db.init()
    with db.session() as c:
        c.execute(
            "INSERT INTO games (game_id, season, week, game_type, gameday, home_team, "
            "away_team, spread_line, total_line) "
            "VALUES (?,2026,3,'REG','2026-09-24','BBB','AAA',4.5,42.5)",
            (GAME,),
        )

    order: list[str] = []

    monkeypatch.setattr(cli, "refresh_lines", lambda conn, season: order.append("lines") or {})

    class FakeBuilder:
        def __init__(self, seasons):
            pass

        def build(self, conn, game_id):
            order.append(f"build {game_id}")
            return {"game": {"game_id": game_id}}

    monkeypatch.setattr(build, "FeatureBuilder", FakeBuilder)
    monkeypatch.setattr(build, "slate_game_ids", lambda conn, s, w: (order.append("select") or [GAME]))
    monkeypatch.setattr(
        market, "games_needing_repredict", lambda conn, s, w: (order.append("select moved") or [GAME])
    )
    monkeypatch.setattr(predictor, "build_prompt", lambda pack: "")

    def boom(*a, **k):
        raise AssertionError("dry run must never call the model")

    monkeypatch.setattr(predictor, "predict", boom)
    return order


def _run(*argv):
    args = cli.build_parser().parse_args(["predict", *argv, "--dry-run"])
    return args.func(args)


def test_single_game_snapshots_before_building(calls):
    assert _run("--game", GAME, "--label", "thursday") == 0
    assert calls == ["lines", f"build {GAME}"]


def test_slate_snapshots_before_selecting(calls):
    assert _run("--season", "2026", "--week", "3", "--label", "sunday") == 0
    assert calls == ["lines", "select", f"build {GAME}"]


def test_only_moved_selects_on_the_fresh_line(calls):
    # --only-moved chooses games by line movement, so the snapshot must come
    # before the selection, not just before the build.
    assert _run("--season", "2026", "--week", "3", "--label", "thursday", "--only-moved") == 0
    assert calls == ["lines", "select moved", f"build {GAME}"]


def test_backtests_do_not_touch_live_lines(calls):
    assert _run("--game", GAME, "--label", "backtest") == 0
    assert "lines" not in calls

"""A pre-registered test of an EPA-based rating against the closing line.

The score-based rating in `edgelord/ratings.py` lost to the line on 2022-2025
(VERIFIED.md, 2026-09-23). Final scores are the public result everyone prices,
so the open question is whether play-level efficiency -- EPA per play, opponent
adjusted -- carries something the line does not. If it does, it is the number
to hand the model as a source of conviction. If not, it is not.

THE RULES, written and committed before any of this was run. Nothing below is
changed after seeing a result.

1. One rating, no grid. Team strength before a week is the bot's own
   `blended_team_metrics` (current season blended with last season regressed
   toward average): net = off_epa_adj - def_epa_adj, per play.
2. Points: projected home margin = hfa * (not neutral) + scale * (net_home -
   net_away). `hfa` and `scale` are the only fitted numbers, fit once by least
   squares against the final margin on 2017-2021 regular-season games. Fit on
   accuracy against the game, never on the ATS record.
3. Holdout: 2022-2025 regular season, closing nflverse spreads, looked at once.
4. PASS requires BOTH:
   a. market weight: regressing the line's miss on the rating's disagreement
      gives beta > 0 with beta at least 2 standard errors above zero, i.e. the
      rating knows something the line has not priced; and
   b. betting the rating's side where it is 2+ points off the line wins at
      least 52.4% (break-even at -110) with one-sided p < 0.05.
5. Reported either way: RMSE/MAE against the margin next to the line's, ATS at
   every threshold, and the share of disagreements that took the underdog.

Only on a PASS does the rating go into the prediction pack. No model calls,
no cost.

    .venv/Scripts/python.exe scripts/epa_rating_test.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from edgelord import ratings as R
from edgelord.features.efficiency import blended_team_metrics
from edgelord.sources import nflverse

TUNE = range(2017, 2022)
HOLDOUT = range(2022, 2026)
BREAKEVEN = 110 / 210
MIN_EDGE = 2.0

PBP_COLS = [
    "season", "week", "season_type", "game_id", "play_id", "home_team", "away_team",
    "posteam", "defteam", "pass", "rush", "qb_kneel", "qb_spike", "qb_dropback",
    "yards_gained", "epa", "success", "down", "sack", "qb_hit", "series_success",
    "fixed_drive", "drive_inside20", "fixed_drive_result", "score_differential",
    "qtr", "game_seconds_remaining", "pass_oe",
]
TEAM_COLS = ("home_team", "away_team", "posteam", "defteam")


def load_pbp() -> pl.DataFrame:
    frames = []
    for y in range(2016, 2026):
        lf = pl.scan_parquet(nflverse._cache_path("pbp", y))
        have = lf.collect_schema().names()
        frames.append(lf.select([c for c in PBP_COLS if c in have]).collect())
    pbp = pl.concat(frames, how="diagonal_relaxed")
    # One series per franchise across relocations, matching the schedule.
    return pbp.with_columns([pl.col(c).replace(R.RELOCATED) for c in TEAM_COLS])


def net_by_week(pbp: pl.DataFrame, games: pl.DataFrame) -> dict:
    """(season, week) -> {team: net EPA per play} as of before that week."""
    empty_ftn = pl.DataFrame()
    out = {}
    keys = games.select("season", "week").unique().sort("season", "week").iter_rows()
    for season, week in keys:
        table, _ = blended_team_metrics(pbp, empty_ftn, season, week)
        if table.is_empty() or "off_epa_adj" not in table.columns:
            continue
        out[(season, week)] = {
            t: o - d
            for t, o, d in table.select("team", "off_epa_adj", "def_epa_adj").iter_rows()
            if o is not None and d is not None
        }
    return out


def frame(games: pl.DataFrame, nets: dict) -> pl.DataFrame:
    rows = []
    for g in games.iter_rows(named=True):
        n = nets.get((g["season"], g["week"]), {})
        h, a = n.get(g["home_team"]), n.get(g["away_team"])
        if h is None or a is None:
            continue
        rows.append({
            "game_id": g["game_id"], "season": g["season"], "week": g["week"],
            "diff": h - a, "home_field": g["home_field"],
            "market": g["spread_line"], "margin": g["margin"],
        })
    return pl.DataFrame(rows)


def fit(df: pl.DataFrame) -> tuple[float, float]:
    X = np.column_stack([df["home_field"].to_numpy(), df["diff"].to_numpy()])
    coef, *_ = np.linalg.lstsq(X, df["margin"].to_numpy(), rcond=None)
    return float(coef[0]), float(coef[1])


def _p_one_sided(w: int, n: int) -> float:
    if not n:
        return 1.0
    z = (w - n * 0.5) / math.sqrt(n * 0.25)
    return 0.5 * math.erfc(z / math.sqrt(2))


def main() -> None:
    games = R.load_games(2025).filter(
        (pl.col("game_type") == "REG")
        & pl.col("margin").is_not_null()
        & pl.col("spread_line").is_not_null()
        & pl.col("season").is_between(TUNE.start, HOLDOUT.stop - 1)
    )
    print("building weekly EPA ratings ...")
    nets = net_by_week(load_pbp(), games)
    df = frame(games, nets)

    tune = df.filter(pl.col("season").is_in(list(TUNE)))
    hfa, scale = fit(tune)
    print(f"fit on {TUNE.start}-{TUNE.stop - 1} ({tune.height} games): "
          f"hfa {hfa:.2f}, scale {scale:.1f} pts per EPA/play\n")

    hold = df.filter(pl.col("season").is_in(list(HOLDOUT))).with_columns(
        (pl.lit(hfa) * pl.col("home_field") + pl.lit(scale) * pl.col("diff"))
        .round(2).alias("projected")
    )
    ev = R.evaluate(hold)

    print(f"HOLDOUT {HOLDOUT.start}-{HOLDOUT.stop - 1}: {ev['games']} games")
    print(f"  RMSE vs margin   rating {ev['model']['rmse']}   line {ev['market']['rmse']}")
    print(f"  MAE  vs margin   rating {ev['model']['mae']}   line {ev['market']['mae']}")
    mw = ev["market_weight"]
    print(f"  market weight    beta {mw['beta']} (se {mw['se']})")
    print(f"  mean |disagreement| {ev['mean_abs_disagreement']} pts, "
          f"took the dog in {ev['dog_share']:.0%}")
    for k, v in ev["ats"].items():
        n = v["w"] + v["l"]
        print(f"  ATS {k:>3} pts off  {v['w']}-{v['l']}-{v['p']}  "
              f"{v['win_pct']:.1%}  p={_p_one_sided(v['w'], n):.3f}  {v['units']:+.1f}u")

    a = mw["beta"] > 0 and mw["se"] and mw["beta"] >= 2 * mw["se"]
    two = ev["ats"][f"{MIN_EDGE:g}+"]
    b = (two["win_pct"] or 0) >= BREAKEVEN and _p_one_sided(two["w"], two["w"] + two["l"]) < 0.05
    print(f"\n  (a) market weight >= 2 se above zero: {'yes' if a else 'no'}")
    print(f"  (b) {MIN_EDGE:g}+ pts off wins >= 52.4% at p < 0.05: {'yes' if b else 'no'}")
    print(f"\nVERDICT: {'PASS' if a and b else 'FAIL'}")


if __name__ == "__main__":
    main()

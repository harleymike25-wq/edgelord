"""Does "fade the team whose record outruns its points" cover the spread?

The luck/regression factor is the heaviest-weighted input in the LLM's decision
tables (avg 2.27 of 4, pointing at the picked side 22 times to 8). This checks
the thesis on its own, against closing lines, over every regular-season game
2016-2025 -- using the bot's own definitions from `features.regression`, and
only results from before each kickoff.

For each game: take each team's Pythagorean delta (win% minus Pythagorean
win%; positive = the record flatters them) and one-score win%, then bet the
side the thesis prefers -- the team whose record is *less* flattering -- at the
closing spread. Every threshold is reported; none was chosen by looking.

Weeks 1-4 use last season's full-year figures, which is what the pack leans on
early; from Week 5 the current season's. No model calls, no cost.

    .venv/Scripts/python.exe scripts/backtest_regression_thesis.py
"""

from __future__ import annotations

import math

import polars as pl

from edgelord import ratings
from edgelord.features import regression

SEASONS = range(2016, 2026)
EARLY_WEEKS = 4           # use last season's figures through this week
MIN_ONE_SCORE_GAMES = 3
BREAKEVEN = 110 / 210


def _snapshot(games: pl.DataFrame, season: int, week: int) -> dict:
    if week <= EARLY_WEEKS:
        tbl = regression.records(games, season - 1, 99)
    else:
        tbl = regression.records(games, season, week)
    return {r["team"]: r for r in tbl.iter_rows(named=True)} if tbl.height else {}


def rows(games: pl.DataFrame) -> pl.DataFrame:
    out = []
    target = games.filter(
        pl.col("season").is_in(list(SEASONS))
        & (pl.col("game_type") == "REG")
        & pl.col("margin").is_not_null()
        & pl.col("spread_line").is_not_null()
    )
    for (season, week), wk in target.group_by(["season", "week"], maintain_order=True):
        snap = _snapshot(games, season, week)
        for g in wk.iter_rows(named=True):
            h, a = snap.get(g["home_team"]), snap.get(g["away_team"])
            if not h or not a:
                continue
            ok = (h["one_score_games"] or 0) >= MIN_ONE_SCORE_GAMES and (
                a["one_score_games"] or 0
            ) >= MIN_ONE_SCORE_GAMES
            out.append({
                "season": season, "week": week,
                "early": week <= EARLY_WEEKS,
                # Home-minus-away: positive means the HOME record is the lucky one.
                "pyth_diff": h["pythagorean_delta"] - a["pythagorean_delta"],
                "onescore_diff": (h["one_score_win_pct"] - a["one_score_win_pct"]) if ok else None,
                # Home margin against the closing line; > 0 means home covered.
                "home_cover": g["margin"] - g["spread_line"],
            })
    return pl.DataFrame(out)


def fade(df: pl.DataFrame, col: str, threshold: float) -> dict:
    """Bet against the luckier side whenever the gap is at least `threshold`."""
    sub = df.filter(pl.col(col).is_not_null() & (pl.col(col).abs() >= threshold))
    # Fading the lucky home side means backing away: win when home fails to cover.
    res = -(sub[col].sign() * sub["home_cover"].sign())
    w, l = int((res > 0).sum()), int((res < 0).sum())
    n = w + l
    pct = w / n if n else float("nan")
    se = math.sqrt(0.25 / n) if n else float("nan")
    return {
        "games": n, "w": w, "l": l, "win_pct": pct,
        "z_vs_50": (pct - 0.5) / se if n else float("nan"),
        "units": w * 100 / 110 - l,
    }


def report(df: pl.DataFrame, col: str, thresholds, label: str) -> None:
    print(f"\n{label}")
    print(f"  {'gap >=':>7} {'games':>6} {'record':>11} {'win%':>6} {'z vs 50%':>9} {'units':>8}")
    for t in thresholds:
        r = fade(df, col, t)
        if not r["games"]:
            continue
        print(
            f"  {t:>7.2f} {r['games']:>6} {r['w']:>5}-{r['l']:<5} "
            f"{r['win_pct']:>6.1%} {r['z_vs_50']:>+9.2f} {r['units']:>+8.1f}"
        )


def main() -> None:
    games = ratings.load_games(2025)
    df = rows(games)
    pyth_t = (0.0, 0.05, 0.10, 0.15, 0.20, 0.30)
    one_t = (0.0, 0.25, 0.40, 0.50)

    print(f"{df.height} games, {SEASONS.start}-{SEASONS.stop - 1}. "
          f"Break-even at -110 is {BREAKEVEN:.1%}.")
    report(df, "pyth_diff", pyth_t, "Fade the Pythagorean overachiever -- all weeks")
    report(df.filter(~pl.col("early")), "pyth_diff", pyth_t, "  ...Week 5 on (this season's figures)")
    report(df.filter(pl.col("early")), "pyth_diff", pyth_t, "  ...Weeks 1-4 (last season's figures)")
    report(df, "onescore_diff", one_t, "Fade the better one-score record -- all weeks")
    for lo, hi in ((2016, 2020), (2021, 2025)):
        report(
            df.filter(pl.col("season").is_between(lo, hi)), "pyth_diff", (0.0, 0.10, 0.20),
            f"Pythagorean fade, {lo}-{hi}",
        )


if __name__ == "__main__":
    main()

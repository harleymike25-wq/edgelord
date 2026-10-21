"""What every computed model shares: the games, win probability, the report card.

A model's output is a frame with one row per game:

    game_id, season, week, home_team, away_team, projected, margin, market,
    market_prob

`projected` is the model's home margin, `margin` the actual one, `market` the
closing spread (positive = home favoured) and `market_prob` the closing
moneyline's no-vig home win probability where there was one.

The report card asks two separate questions, because they have different
answers:

1. Does it pick WINNERS? Straight-up accuracy, Brier score and log loss, next
   to the closing line's own straight-up record on the same games. A model can
   be good at this and still useless for betting, since the favourite usually
   wins and the line knows who the favourite is.
2. Does it beat the SPREAD? The market-weight regression and ATS record from
   `edgelord.ratings.evaluate` -- the test every number so far has failed.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from ..ratings import RELOCATED, evaluate as vs_line
from ..sources import nflverse

FIRST_SEASON = 2002
TUNE_SEASONS = range(2017, 2022)
HOLDOUT_SEASONS = range(2022, 2026)

# One game's margin against a good projection has a standard deviation of
# about 13.5 points; each model refits its own on the tuning seasons.
DEFAULT_SIGMA = 13.5


def load_games(through_season: int, *, refresh: bool = False) -> pl.DataFrame:
    """Every game from 2002 on, one series per franchise, sorted by kickoff."""
    df = nflverse.schedules(range(FIRST_SEASON, through_season + 1), refresh=refresh)
    return (
        df.select(
            "game_id", "season", "week", "game_type", "gameday", "gametime",
            "location",
            pl.col("home_team").replace(RELOCATED),
            pl.col("away_team").replace(RELOCATED),
            "home_score", "away_score", "spread_line",
            "home_moneyline", "away_moneyline", "home_rest", "away_rest",
            "home_qb_id", "away_qb_id", "home_qb_name", "away_qb_name",
        )
        .with_columns(
            (pl.col("home_score") - pl.col("away_score")).alias("margin"),
            (pl.col("location") == "Neutral").alias("neutral"),
            _no_vig("home_moneyline", "away_moneyline").alias("market_prob"),
        )
        .sort("season", "gameday", "gametime", "game_id")
    )


def _implied(col: str) -> pl.Expr:
    ml = pl.col(col).cast(pl.Float64)
    return pl.when(ml < 0).then(-ml / (-ml + 100)).otherwise(100 / (ml + 100))


def _no_vig(home: str, away: str) -> pl.Expr:
    h, a = _implied(home), _implied(away)
    return h / (h + a)


def win_prob(margin: float | np.ndarray, sigma: float = DEFAULT_SIGMA):
    """P(home wins) from a projected home margin, normal around the projection."""
    z = np.asarray(margin, dtype=float) / (sigma * math.sqrt(2))
    return 0.5 * (1 + np.vectorize(math.erf)(z)) if np.ndim(z) else 0.5 * (1 + math.erf(float(z)))


def fit_sigma(df: pl.DataFrame) -> float:
    """The sigma that minimises log loss of `projected` on decided games."""
    d = df.drop_nulls(["projected", "margin"]).filter(pl.col("margin") != 0)
    if d.is_empty():
        return DEFAULT_SIGMA
    proj = d["projected"].to_numpy()
    won = (d["margin"].to_numpy() > 0).astype(float)
    best = min(
        np.arange(9.0, 18.01, 0.25),
        key=lambda s: _log_loss(win_prob(proj, s), won),
    )
    return float(best)


def _log_loss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def _straight_up(pick_home: np.ndarray, prob: np.ndarray, home_won: np.ndarray) -> dict:
    return {
        "accuracy": round(float((pick_home == home_won).mean()), 4),
        "brier": round(float(((prob - home_won) ** 2).mean()), 4),
        "log_loss": round(_log_loss(prob, home_won), 4),
    }


def report_card(df: pl.DataFrame, sigma: float) -> dict:
    """Winners first, then the spread, each beside the closing line."""
    d = df.drop_nulls(["projected", "margin", "market"]).filter(pl.col("margin") != 0)
    if d.is_empty():
        return {"games": 0}
    proj = d["projected"].to_numpy()
    mkt = d["market"].to_numpy()
    home_won = (d["margin"].to_numpy() > 0).astype(float)

    model_prob = win_prob(proj, sigma)
    # The line's own straight-up view: the moneyline where there is one, else
    # the spread through the same normal curve. A pick'em spread falls back to
    # the moneyline's side, then to the home team.
    ml = d["market_prob"].to_numpy().astype(float)
    line_prob = np.where(np.isnan(ml), win_prob(mkt, DEFAULT_SIGMA), ml)

    return {
        "games": d.height,
        "sigma": sigma,
        "winners": {
            "model": _straight_up((proj > 0) | ((proj == 0) & (model_prob >= 0.5)),
                                  model_prob, home_won),
            "line": _straight_up(line_prob >= 0.5, line_prob, home_won),
            # Games where the model and the line name different winners, and
            # how often the model was the one that was right.
            "disagreements": _disagreements(proj > 0, line_prob >= 0.5, home_won),
        },
        # Ties are pushes against a spread, not missing games, so the spread
        # half keeps them.
        "spread": vs_line(df.drop_nulls(["projected", "margin", "market"])),
    }


def _disagreements(model_home: np.ndarray, line_home: np.ndarray, home_won: np.ndarray) -> dict:
    split = model_home != line_home
    n = int(split.sum())
    right = int((model_home[split] == home_won[split]).sum())
    return {"games": n, "model_right": right,
            "model_right_pct": round(right / n, 4) if n else None}

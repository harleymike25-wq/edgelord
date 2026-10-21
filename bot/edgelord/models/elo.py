"""Elo ratings from final scores, in the style FiveThirtyEight ran for the NFL.

Every team starts at 1505. Before each game the home side gets a home-field
bump and a team coming off a bye gets a rest bump. The rating gap becomes a
win probability through the usual logistic curve and a point spread at
`elo_per_point` Elo to the point. After the game both ratings move by

    k * mov_mult * (result - expected)

where `mov_mult` grows with the log of the margin and shrinks when the
favourite wins big, so a rout by the better team teaches less than an upset.
Between seasons every rating is pulled part of the way back to 1505.

Differences from the least-squares rating in `edgelord.ratings`: Elo is
updated one game at a time and never refits history, it carries information
from 2002 forward, and it knows about rest. It is a different kind of model
looking at the same scores, which is the point of having both.

Parameters are tuned on 2017-2021 on margin error; 2022 onward is the holdout.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import polars as pl

from . import common

MEAN = 1505.0


@dataclass(frozen=True)
class Params:
    """Defaults are the `tune()` winner on 2017-2021 (RMSE 13.604 vs the margin).

    The surface is flat: the top twenty settings sit within 0.01 of each other,
    so these are a representative point rather than a sharp optimum. Home field
    came out at 25 Elo (1.25 points), well under the old 48, and the bye bump
    added nothing.
    """
    k: float = 20.0
    hfa: float = 25.0           # Elo points; 1.25 points of spread at 20/pt
    revert: float = 0.5         # share of the gap to 1505 erased each offseason
    bye: float = 0.0            # Elo points for a team coming off a bye
    elo_per_point: float = 20.0


DEFAULT = Params()


def _mov_mult(mov: float, winner_diff: float) -> float:
    return math.log(max(abs(mov), 1) + 1) * 2.2 / (winner_diff * 0.001 + 2.2)


def _pregame_diff(p: Params, rh: float, ra: float, g: dict) -> float:
    """Home Elo advantage before kickoff, with home field and rest."""
    diff = rh - ra
    if not g["neutral"]:
        diff += p.hfa
    # A bye shows up as 13+ days of rest; the schedule's rest columns count
    # days since the team's last game.
    if (g["home_rest"] or 7) >= 13:
        diff += p.bye
    if (g["away_rest"] or 7) >= 13:
        diff -= p.bye
    return diff


def replay(games: pl.DataFrame, p: Params = DEFAULT, *,
           on_game=None) -> pl.DataFrame:
    """Walk every game in kickoff order; project each before updating on it.

    `on_game(g, diff, ratings)` is called before each game is applied, so a
    model built on top of Elo (see `qb`) can read the pregame state.
    """
    ratings: dict[str, float] = {}
    season_of: dict[str, int] = {}
    out = []
    for g in games.iter_rows(named=True):
        h, a, season = g["home_team"], g["away_team"], g["season"]
        for t in (h, a):
            r = ratings.get(t, MEAN)
            if season_of.get(t) is not None and season_of[t] != season:
                r = MEAN + (r - MEAN) * (1 - p.revert)
            ratings[t] = r
            season_of[t] = season

        diff = _pregame_diff(p, ratings[h], ratings[a], g)
        if on_game:
            on_game(g, diff, ratings)
        out.append({
            "game_id": g["game_id"], "season": season, "week": g["week"],
            "game_type": g["game_type"],
            "home_team": h, "away_team": a,
            "projected": round(diff / p.elo_per_point, 2),
            "elo_home": round(ratings[h], 1), "elo_away": round(ratings[a], 1),
            "margin": g["margin"], "market": g["spread_line"],
            "market_prob": g["market_prob"],
        })

        if g["margin"] is None:
            continue
        expected = 1 / (1 + 10 ** (-diff / 400))
        m = g["margin"]
        result = 1.0 if m > 0 else 0.0 if m < 0 else 0.5
        winner_diff = diff if m > 0 else -diff if m < 0 else 0.0
        shift = p.k * _mov_mult(m, winner_diff) * (result - expected)
        ratings[h] += shift
        ratings[a] -= shift
    return pl.DataFrame(out, infer_schema_length=None)


def regular(rep: pl.DataFrame, seasons) -> pl.DataFrame:
    return rep.filter(
        pl.col("season").is_in(list(seasons)) & (pl.col("game_type") == "REG")
    )


def tune(games: pl.DataFrame) -> tuple[Params, list[dict]]:
    """Grid on 2017-2021 only, scored on RMSE against the margin, never ATS."""
    grid = []
    for k in (15.0, 20.0, 25.0, 30.0):
        for hfa in (15.0, 20.0, 25.0, 30.0, 40.0, 48.0):
            for revert in (0.25, 1 / 3, 0.5):
                for bye in (0.0, 25.0):
                    rep = replay(games, Params(k, hfa, revert, bye))
                    d = regular(rep, common.TUNE_SEASONS).drop_nulls(["projected", "margin"])
                    # The spread scale only rescales `projected`, so it is
                    # searched without replaying.
                    for epp in (20.0, 25.0, 30.0, 35.0):
                        proj = d["projected"].to_numpy() * 25.0 / epp
                        err = d["margin"].to_numpy() - proj
                        grid.append({**asdict(Params(k, hfa, revert, bye, epp)),
                                     "rmse": round(float((err ** 2).mean() ** 0.5), 3)})
    grid.sort(key=lambda r: r["rmse"])
    b = grid[0]
    return Params(b["k"], b["hfa"], b["revert"], b["bye"], b["elo_per_point"]), grid

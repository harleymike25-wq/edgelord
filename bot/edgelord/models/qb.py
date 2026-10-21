"""Elo adjusted for who is actually starting at quarterback.

A team rating built from scores is blind to a quarterback change until the new
starter has played enough games to drag it -- by which time the market moved
weeks ago. This model keeps a value for every quarterback and adjusts the Elo
projection when a team starts someone better or worse than the quarterbacks
its rating was built on:

    projected = elo_projected + scale * (adj_home - adj_away)
    adj       = value(today's starter) - team's recent starter value

A quarterback's value is EPA per dropback, decayed so recent games count more,
and shrunk toward replacement level by `prior_dropbacks` of imaginary
replacement play -- so a backup with forty dropbacks is valued near
replacement, not at whatever his forty dropbacks happened to show. A team's
recent starter value is a moving average over its games, which is what the
team's Elo has absorbed.

Starters come from the schedule's `home_qb_id`/`away_qb_id`: in a replay that
is who actually started, which is nearly always known before kickoff. A game
with no listed starter (an upcoming one) uses the team's last starter.

Values come from play-by-play, cached from 2016, so 2016 is burn-in and
nothing is scored before 2017.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import polars as pl

from . import common, elo
from ..ratings import RELOCATED
from ..sources import nflverse

PBP_FIRST = 2016


@dataclass(frozen=True)
class Params:
    """Chosen from `tune()` on 2017-2021 (RMSE 13.447 vs Elo alone at 13.604).

    The top six settings sit within 0.003 of each other; this is a middle
    point of that plateau rather than its best cell (100 dropbacks scored
    13.445). In-season decay came out at none -- every dropback this season
    counts the same -- with the summer still discounting last year.
    """
    prior_dropbacks: float = 200.0
    replacement: float = -0.25   # EPA per dropback of an unknown quarterback
    decay: float = 1.0           # weight kept per game the quarterback plays
    offseason: float = 0.7       # extra weight kept across a summer
    team_alpha: float = 0.1      # moving-average step for a team's starter value
    scale: float = 19.7          # points per EPA/dropback of starter difference


DEFAULT = Params()


def qb_games(through_season: int) -> pl.DataFrame:
    """Dropbacks and EPA by quarterback by game, from cached play-by-play."""
    frames = []
    for y in range(PBP_FIRST, through_season + 1):
        try:
            lf = pl.scan_parquet(nflverse._cache_path("pbp", y))
        except FileNotFoundError:
            continue
        frames.append(
            lf.filter((pl.col("qb_dropback") == 1) & pl.col("passer_id").is_not_null()
                      & pl.col("epa").is_not_null())
            .group_by("game_id", "passer_id")
            .agg(pl.len().alias("dropbacks"), pl.col("epa").sum().alias("epa"))
            .collect()
        )
    return pl.concat(frames) if frames else pl.DataFrame(
        schema={"game_id": pl.String, "passer_id": pl.String,
                "dropbacks": pl.UInt32, "epa": pl.Float64})


class _State:
    def __init__(self, p: Params):
        self.p = p
        self.wepa: dict[str, float] = {}
        self.wdb: dict[str, float] = {}
        self.season: dict[str, int] = {}
        self.team_value: dict[str, float] = {}
        self.last_starter: dict[str, str] = {}

    def value(self, qb: str | None) -> float:
        p = self.p
        if qb is None:
            return p.replacement
        return ((self.wepa.get(qb, 0.0) + p.replacement * p.prior_dropbacks)
                / (self.wdb.get(qb, 0.0) + p.prior_dropbacks))

    def add(self, qb: str, season: int, dropbacks: float, epa: float) -> None:
        p = self.p
        keep = p.decay
        if self.season.get(qb) is not None and self.season[qb] != season:
            keep *= p.offseason
        self.wepa[qb] = self.wepa.get(qb, 0.0) * keep + epa
        self.wdb[qb] = self.wdb.get(qb, 0.0) * keep + dropbacks
        self.season[qb] = season


def replay(games: pl.DataFrame, qbg: pl.DataFrame, p: Params = DEFAULT,
           ep: elo.Params = elo.DEFAULT) -> pl.DataFrame:
    """Elo's replay with each game's quarterback adjustment beside it."""
    by_game: dict[str, list[tuple]] = {}
    for gid, qb, db, e in qbg.iter_rows():
        by_game.setdefault(gid, []).append((qb, db, e))

    st = _State(p)
    adj_rows: list[dict] = []

    def on_game(g, _diff, _ratings):
        adjs, starters = {}, {}
        for side in ("home", "away"):
            team = g[f"{side}_team"]
            qb = g[f"{side}_qb_id"] or st.last_starter.get(team)
            v = st.value(qb)
            adjs[side] = v - st.team_value.get(team, v)
            starters[team] = qb
        adj_rows.append({"game_id": g["game_id"], "qb_home_adj": adjs["home"],
                         "qb_away_adj": adjs["away"]})
        # Fold this game's dropbacks into every passer's value, after the
        # pregame read above.
        for passer, db, e in by_game.get(g["game_id"], ()):
            st.add(passer, g["season"], db, e)
        # The team's baseline moves toward its starter's value as it now
        # stands. Using the pregame value instead would freeze a quarterback's
        # early, replacement-level estimate into the baseline, and his own
        # later starts would then read as an upgrade.
        if g["margin"] is None:
            return
        for team, qb_id in starters.items():
            v = st.value(qb_id)
            team_v = st.team_value.get(team, v)
            st.team_value[team] = team_v + p.team_alpha * (v - team_v)
            if qb_id:
                st.last_starter[team] = qb_id

    base = elo.replay(games, ep, on_game=on_game)
    adj = pl.DataFrame(adj_rows)
    return (
        base.join(adj, on="game_id", how="left")
        .with_columns((pl.col("qb_home_adj") - pl.col("qb_away_adj")).alias("qb_diff"))
        .with_columns(
            pl.col("projected").alias("elo_projected"),
            (pl.col("projected") + p.scale * pl.col("qb_diff")).round(2).alias("projected"),
        )
    )


def fit_scale(rep: pl.DataFrame) -> float:
    """Least-squares points per EPA/dropback on the tuning seasons."""
    d = elo.regular(rep, common.TUNE_SEASONS).drop_nulls(["margin", "elo_projected", "qb_diff"])
    x = d["qb_diff"].to_numpy()
    y = (d["margin"] - d["elo_projected"]).to_numpy()
    return float((x * y).sum() / (x * x).sum()) if (x * x).sum() else 0.0


def tune(games: pl.DataFrame, qbg: pl.DataFrame) -> tuple[Params, list[dict]]:
    """Grid on 2017-2021 only, scale refit at each point, scored on RMSE."""
    grid = []
    for prior in (100.0, 200.0, 400.0):
        for repl in (-0.30, -0.25, -0.20, -0.10, 0.0):
            for decay in (0.95, 0.98, 0.99, 1.0):
                for alpha in (0.05, 0.1, 0.25):
                    p = Params(prior, repl, decay, 0.7, alpha, 0.0)
                    rep = replay(games, qbg, p)
                    scale = fit_scale(rep)
                    d = elo.regular(rep, common.TUNE_SEASONS).drop_nulls(
                        ["margin", "elo_projected", "qb_diff"])
                    err = (d["margin"] - d["elo_projected"] - scale * d["qb_diff"]).to_numpy()
                    grid.append({**asdict(p), "scale": round(scale, 1),
                                 "rmse": round(float(np.sqrt((err ** 2).mean())), 3)})
    grid.sort(key=lambda r: r["rmse"])
    b = grid[0]
    return Params(**{k: b[k] for k in asdict(DEFAULT)}), grid

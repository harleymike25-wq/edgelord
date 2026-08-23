"""Regression indicators -- the four flags that say a record is fragile.

Turnover margin, one-score game record, Pythagorean expectation and opponent
field goal percentage all mean-revert hard year to year and even within a
season. A team outrunning its point differential on the back of these is a
different proposition than one that earned its record.
"""

from __future__ import annotations

import polars as pl

# The NFL-calibrated Pythagorean exponent.
PYTHAG_EXPONENT = 2.37
ONE_SCORE_MARGIN = 8


def _played(games: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    return games.filter(
        (pl.col("season") == season)
        & (pl.col("week") < through_week)
        & (pl.col("game_type") == "REG")
        & pl.col("home_score").is_not_null()
    )


def _long_form(played: pl.DataFrame) -> pl.DataFrame:
    """One row per team per game, from that team's point of view."""
    home = played.select(
        pl.col("home_team").alias("team"),
        pl.col("away_team").alias("opponent"),
        pl.col("home_score").alias("pf"),
        pl.col("away_score").alias("pa"),
    )
    away = played.select(
        pl.col("away_team").alias("team"),
        pl.col("home_team").alias("opponent"),
        pl.col("away_score").alias("pf"),
        pl.col("home_score").alias("pa"),
    )
    return pl.concat([home, away]).with_columns(
        (pl.col("pf") - pl.col("pa")).alias("margin")
    )


def records(games: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    """Record, point differential, Pythagorean expectation and one-score splits."""
    played = _played(games, season, through_week)
    if played.is_empty():
        return pl.DataFrame({"team": []})

    long = _long_form(played)
    agg = long.group_by("team").agg(
        pl.len().alias("gp"),
        (pl.col("margin") > 0).sum().alias("wins"),
        (pl.col("margin") < 0).sum().alias("losses"),
        (pl.col("margin") == 0).sum().alias("ties"),
        pl.col("pf").sum().alias("points_for"),
        pl.col("pa").sum().alias("points_against"),
        pl.col("margin").mean().alias("point_diff_per_game"),
        # One-score games: the coin-flip bucket.
        ((pl.col("margin").abs() <= ONE_SCORE_MARGIN) & (pl.col("margin") > 0))
        .sum()
        .alias("one_score_wins"),
        ((pl.col("margin").abs() <= ONE_SCORE_MARGIN) & (pl.col("margin") < 0))
        .sum()
        .alias("one_score_losses"),
    )

    pf = pl.col("points_for").cast(pl.Float64)
    pa = pl.col("points_against").cast(pl.Float64)
    pyth = pf**PYTHAG_EXPONENT / (pf**PYTHAG_EXPONENT + pa**PYTHAG_EXPONENT)

    return agg.with_columns(
        (pl.col("wins") / pl.col("gp")).alias("win_pct"),
        pyth.alias("pythagorean_win_pct"),
        (pl.col("one_score_wins") + pl.col("one_score_losses")).alias("one_score_games"),
    ).with_columns(
        # Positive means the record flatters the team relative to its scoring.
        (pl.col("win_pct") - pl.col("pythagorean_win_pct")).alias("pythagorean_delta"),
        pl.when(pl.col("one_score_games") > 0)
        .then(pl.col("one_score_wins") / pl.col("one_score_games"))
        .otherwise(None)
        .alias("one_score_win_pct"),
    )


def turnovers(pbp: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    """Giveaways, takeaways and margin."""
    scoped = pbp.filter(
        (pl.col("season") == season)
        & (pl.col("week") < through_week)
        & (pl.col("season_type") == "REG")
        & pl.col("posteam").is_not_null()
    ).with_columns(
        (
            (pl.col("interception") == 1).cast(pl.Int32)
            + (pl.col("fumble_lost") == 1).cast(pl.Int32)
        ).alias("to")
    )
    if scoped.is_empty():
        return pl.DataFrame({"team": []})

    give = (
        scoped.group_by("posteam")
        .agg(pl.col("to").sum().alias("giveaways"), pl.col("game_id").n_unique().alias("gp"))
        .rename({"posteam": "team"})
    )
    take = (
        scoped.group_by("defteam")
        .agg(pl.col("to").sum().alias("takeaways"))
        .rename({"defteam": "team"})
    )
    return (
        give.join(take, on="team", how="full", coalesce=True)
        .with_columns((pl.col("takeaways") - pl.col("giveaways")).alias("turnover_margin"))
        .with_columns(
            (pl.col("turnover_margin") / pl.col("gp")).alias("turnover_margin_per_game")
        )
    )


def field_goals(pbp: pl.DataFrame, season: int, through_week: int) -> pl.DataFrame:
    """Own and opponent field goal percentage.

    Opponent FG% is almost pure noise -- a defence has very little control over
    whether the other team's kicker is hitting, so an extreme number here is a
    regression flag rather than a skill signal.
    """
    fg = pbp.filter(
        (pl.col("season") == season)
        & (pl.col("week") < through_week)
        & (pl.col("season_type") == "REG")
        & pl.col("field_goal_result").is_not_null()
        & pl.col("posteam").is_not_null()
    ).with_columns((pl.col("field_goal_result") == "made").cast(pl.Float64).alias("made"))

    if fg.is_empty():
        return pl.DataFrame({"team": []})

    own = (
        fg.group_by("posteam")
        .agg(pl.col("made").mean().alias("own_fg_pct"), pl.len().alias("own_fg_att"))
        .rename({"posteam": "team"})
    )
    opp = (
        fg.group_by("defteam")
        .agg(pl.col("made").mean().alias("opp_fg_pct"), pl.len().alias("opp_fg_att"))
        .rename({"defteam": "team"})
    )
    return own.join(opp, on="team", how="full", coalesce=True)


def table(
    games: pl.DataFrame, pbp: pl.DataFrame, season: int, through_week: int
) -> pl.DataFrame:
    out = records(games, season, through_week)
    if out.is_empty():
        return out
    for extra in (
        turnovers(pbp, season, through_week),
        field_goals(pbp, season, through_week),
    ):
        if not extra.is_empty():
            out = out.join(extra.drop("gp", strict=False), on="team", how="left")
    return out

"""Team efficiency metrics derived from play-by-play.

Everything here is "as of" a given week: `scope()` trims the play-by-play to
weeks strictly before the game being predicted, so a backtest can never see a
result it would not have had at the time.

Raw rates are reported alongside a first-order opponent adjustment (a team's
number minus the average its opponents allowed, re-centred on the league mean),
because raw EPA over eight games is heavily schedule-dependent.
"""

from __future__ import annotations

import polars as pl

# Explosive play thresholds, the conventional ones.
EXPLOSIVE_PASS_YDS = 15
EXPLOSIVE_RUSH_YDS = 10
# A blitz is five or more rushers.
BLITZ_RUSHERS = 5


def scope(
    pbp: pl.DataFrame,
    season: int,
    through_week: int,
    *,
    last_n_weeks: int | None = None,
    regular_only: bool = True,
) -> pl.DataFrame:
    """Plays available before kickoff of `through_week`."""
    df = pbp.filter((pl.col("season") == season) & (pl.col("week") < through_week))
    if regular_only:
        df = df.filter(pl.col("season_type") == "REG")
    if last_n_weeks:
        df = df.filter(pl.col("week") >= through_week - last_n_weeks)
    return df


def _scrimmage(df: pl.DataFrame) -> pl.DataFrame:
    """Offensive snaps only: no special teams, kneels or spikes."""
    return df.filter(
        ((pl.col("pass") == 1) | (pl.col("rush") == 1))
        & (pl.col("qb_kneel") == 0)
        & (pl.col("qb_spike") == 0)
        & pl.col("posteam").is_not_null()
    )


_EXPLOSIVE = (
    ((pl.col("pass") == 1) & (pl.col("yards_gained") >= EXPLOSIVE_PASS_YDS))
    | ((pl.col("rush") == 1) & (pl.col("yards_gained") >= EXPLOSIVE_RUSH_YDS))
).cast(pl.Float64)

_AGGS = [
    pl.col("epa").mean().alias("epa_play"),
    pl.col("success").mean().alias("success_rate"),
    _EXPLOSIVE.mean().alias("explosive_rate"),
    pl.col("epa").filter(pl.col("down").is_in([1, 2])).mean().alias("early_down_epa"),
    pl.col("epa").filter(pl.col("pass") == 1).mean().alias("pass_epa"),
    pl.col("epa").filter(pl.col("rush") == 1).mean().alias("rush_epa"),
    pl.len().alias("plays"),
    pl.col("game_id").n_unique().alias("games"),
    # Pressure: sacks and hits per dropback.
    (
        pl.when(pl.col("qb_dropback") == 1)
        .then(((pl.col("sack") == 1) | (pl.col("qb_hit") == 1)).cast(pl.Float64))
        .otherwise(None)
    )
    .mean()
    .alias("pressure_rate"),
    (
        pl.when(pl.col("qb_dropback") == 1)
        .then((pl.col("sack") == 1).cast(pl.Float64))
        .otherwise(None)
    )
    .mean()
    .alias("sack_rate"),
    (
        pl.when(pl.col("down") == 3)
        .then(pl.col("series_success").cast(pl.Float64))
        .otherwise(None)
    )
    .mean()
    .alias("third_down_rate"),
]


def _side(df: pl.DataFrame, team_col: str, prefix: str) -> pl.DataFrame:
    out = df.group_by(team_col).agg(_AGGS).rename({team_col: "team"})
    out = out.with_columns((pl.col("plays") / pl.col("games")).alias("plays_per_game"))
    rename = {
        c: f"{prefix}_{c}" for c in out.columns if c not in ("team", "games")
    }
    return out.rename(rename)


def red_zone(df: pl.DataFrame) -> pl.DataFrame:
    """Red zone TD rate, scored per drive that reached the 20."""
    drives = (
        df.filter(pl.col("posteam").is_not_null() & pl.col("fixed_drive").is_not_null())
        .group_by("game_id", "fixed_drive", "posteam", "defteam")
        .agg(
            pl.col("drive_inside20").max().alias("inside20"),
            pl.col("fixed_drive_result").drop_nulls().first().alias("result"),
        )
        .filter(pl.col("inside20") == 1)
        .with_columns((pl.col("result") == "Touchdown").cast(pl.Float64).alias("td"))
    )
    off = drives.group_by("posteam").agg(
        pl.col("td").mean().alias("off_rz_td_pct"),
        pl.len().alias("off_rz_trips"),
    ).rename({"posteam": "team"})
    dfn = drives.group_by("defteam").agg(
        pl.col("td").mean().alias("def_rz_td_pct"),
        pl.len().alias("def_rz_trips"),
    ).rename({"defteam": "team"})
    return off.join(dfn, on="team", how="full", coalesce=True)


def pace(df: pl.DataFrame) -> pl.DataFrame:
    """Seconds per snap in neutral game states (within one score, first three quarters).

    Trailing teams hurry and leading teams stall, so pace measured across all
    situations mostly re-measures the scoreboard.
    """
    neutral = _scrimmage(df).filter(
        (pl.col("score_differential").abs() <= 8) & (pl.col("qtr") <= 3)
    )
    elapsed = (
        neutral.sort("game_id", "fixed_drive", "play_id")
        .with_columns(
            (
                pl.col("game_seconds_remaining").shift(1)
                - pl.col("game_seconds_remaining")
            )
            .over("game_id", "fixed_drive")
            .alias("sec")
        )
        .filter(pl.col("sec").is_between(1, 60))
    )
    return (
        elapsed.group_by("posteam")
        .agg(pl.col("sec").median().alias("sec_per_play"))
        .rename({"posteam": "team"})
    )


def proe(df: pl.DataFrame) -> pl.DataFrame:
    """Pass rate over expected -- the cleanest read on a coach's aggression."""
    return (
        _scrimmage(df)
        .filter(pl.col("pass_oe").is_not_null() & (pl.col("qtr") <= 3))
        .group_by("posteam")
        .agg(pl.col("pass_oe").mean().alias("proe"))
        .rename({"posteam": "team"})
    )


def blitz_rates(pbp_scoped: pl.DataFrame, ftn: pl.DataFrame) -> pl.DataFrame:
    """Blitz rate generated and faced, from FTN charting (2022+)."""
    if ftn.is_empty():
        return pl.DataFrame({"team": [], "def_blitz_rate": [], "off_blitz_faced": []})

    # pbp stores play_id as a float, FTN as an int -- align before joining.
    keys = pbp_scoped.select(
        "game_id", pl.col("play_id").cast(pl.Int64), "posteam", "defteam"
    )
    charting = ftn.select(
        "nflverse_game_id",
        pl.col("nflverse_play_id").cast(pl.Int64),
        "n_pass_rushers",
    )
    joined = keys.join(
        charting,
        left_on=["game_id", "play_id"],
        right_on=["nflverse_game_id", "nflverse_play_id"],
        how="inner",
    ).filter(pl.col("n_pass_rushers").is_not_null())

    if joined.is_empty():
        return pl.DataFrame({"team": [], "def_blitz_rate": [], "off_blitz_faced": []})

    joined = joined.with_columns(
        (pl.col("n_pass_rushers") >= BLITZ_RUSHERS).cast(pl.Float64).alias("blitz")
    )
    d = (
        joined.group_by("defteam")
        .agg(pl.col("blitz").mean().alias("def_blitz_rate"))
        .rename({"defteam": "team"})
    )
    o = (
        joined.group_by("posteam")
        .agg(pl.col("blitz").mean().alias("off_blitz_faced"))
        .rename({"posteam": "team"})
    )
    return d.join(o, on="team", how="full", coalesce=True)


def _opponent_adjust(table: pl.DataFrame, schedule: pl.DataFrame) -> pl.DataFrame:
    """Subtract what a team's opponents allowed on average, re-centred league-wide.

    First order only -- no iteration to convergence. Enough to stop a team that
    played four bottom-five defences from looking elite.
    """
    for raw, opp_col, out in (
        ("off_epa_play", "def_epa_play", "off_epa_adj"),
        ("def_epa_play", "off_epa_play", "def_epa_adj"),
        ("off_success_rate", "def_success_rate", "off_success_adj"),
        ("def_success_rate", "off_success_rate", "def_success_adj"),
    ):
        if raw not in table.columns or opp_col not in table.columns:
            continue
        league = table[opp_col].mean()
        opp_strength = (
            schedule.join(
                table.select("team", pl.col(opp_col).alias("_opp")),
                left_on="opponent",
                right_on="team",
                how="left",
            )
            .group_by("team")
            .agg(pl.col("_opp").mean().alias("_opp_avg"))
        )
        table = table.join(opp_strength, on="team", how="left").with_columns(
            (pl.col(raw) - (pl.col("_opp_avg") - league)).alias(out)
        ).drop("_opp_avg")
    return table


def _schedule_faced(df: pl.DataFrame) -> pl.DataFrame:
    """Long form team/opponent pairs for every game in scope."""
    games = df.select("game_id", "home_team", "away_team").unique()
    home = games.select(
        pl.col("home_team").alias("team"), pl.col("away_team").alias("opponent")
    )
    away = games.select(
        pl.col("away_team").alias("team"), pl.col("home_team").alias("opponent")
    )
    return pl.concat([home, away])


def team_metrics(
    pbp: pl.DataFrame,
    ftn: pl.DataFrame,
    season: int,
    through_week: int,
    *,
    last_n_weeks: int | None = None,
) -> pl.DataFrame:
    """One row per team with offensive and defensive efficiency as of a week."""
    scoped = scope(pbp, season, through_week, last_n_weeks=last_n_weeks)
    if scoped.is_empty():
        return pl.DataFrame({"team": []})

    plays = _scrimmage(scoped)
    table = _side(plays, "posteam", "off").join(
        _side(plays, "defteam", "def").drop("games"), on="team", how="full", coalesce=True
    )
    for extra in (red_zone(scoped), pace(scoped), proe(scoped), blitz_rates(plays, ftn)):
        if not extra.is_empty():
            table = table.join(extra, on="team", how="left")

    return _opponent_adjust(table, _schedule_faced(scoped))


# How much of a team's prior-season efficiency carries into the next year.
# Year-over-year correlation for team EPA sits around 0.5-0.65, so the prior is
# pulled most of the way toward league average before use -- carrying it over
# untouched would treat a 2025 outlier as a 2026 fact.
PRIOR_CARRYOVER = 0.6

# Prior-season data is worth roughly this many current-season games. At six,
# week 1 leans entirely on the prior, week 7 is an even split, and by week 13
# the current season carries about two thirds.
PRIOR_WEIGHT_GAMES = 6

# Past this many played games the prior adds noise rather than information.
PRIOR_CUTOFF_GAMES = 12


def _regress_to_mean(table: pl.DataFrame, factor: float) -> pl.DataFrame:
    """Pull every rate column toward the league average by `1 - factor`."""
    out = table
    for col in table.columns:
        if col == "team" or table[col].dtype not in (pl.Float64, pl.Float32):
            continue
        mean = table[col].mean()
        if mean is None:
            continue
        out = out.with_columns(
            (pl.lit(mean) + (pl.col(col) - pl.lit(mean)) * factor).alias(col)
        )
    return out


def blended_team_metrics(
    pbp: pl.DataFrame,
    ftn: pl.DataFrame,
    season: int,
    through_week: int,
    *,
    last_n_weeks: int | None = None,
) -> tuple[pl.DataFrame, float]:
    """Current-season efficiency, backfilled with the prior season early on.

    In week 1 there is no current-season data at all, so a pack built from it
    alone leaves the model with nothing but the market line -- which is exactly
    what it then defers to, and why every early-season pick comes back a pass.

    Blending fixes that without pretending last year's team is this year's:
    prior-season rates are regressed toward league average first, then weighted
    against current-season data by how many games have actually been played.

    Returns the table plus the weight given to current-season data, so the pack
    can state plainly how much of what the model is reading is last year's.
    """
    current = team_metrics(pbp, ftn, season, through_week, last_n_weeks=last_n_weeks)
    games_played = max(0, through_week - 1)

    if games_played >= PRIOR_CUTOFF_GAMES:
        return current, 1.0

    prior = team_metrics(pbp, ftn, season - 1, 99)
    if prior.is_empty():
        return current, 1.0
    prior = _regress_to_mean(prior, PRIOR_CARRYOVER)

    weight = games_played / (games_played + PRIOR_WEIGHT_GAMES)
    if current.is_empty() or "team" not in current.columns or current.height == 0:
        return prior, 0.0

    rate_cols = [
        c
        for c in current.columns
        if c != "team"
        and c in prior.columns
        and current[c].dtype in (pl.Float64, pl.Float32)
    ]
    joined = current.join(
        prior.select(["team", *rate_cols]), on="team", how="left", suffix="_prior"
    )
    for c in rate_cols:
        joined = joined.with_columns(
            pl.when(pl.col(f"{c}_prior").is_null())
            .then(pl.col(c))
            .otherwise(pl.col(c) * weight + pl.col(f"{c}_prior") * (1 - weight))
            .alias(c)
        )
    return joined.drop([f"{c}_prior" for c in rate_cols]), round(weight, 3)

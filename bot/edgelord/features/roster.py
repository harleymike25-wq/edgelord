"""Offseason roster turnover.

Blending prior-season efficiency into early-week packs assumes last year's team
resembles this year's. Often it does not: a team can return 85% of its snaps or
45% of them, and the blend should not treat those alike.

Continuity is measured the way it actually matters -- weighted by 2025 snaps
rather than by headcount. Losing a backup guard and losing a 1,100-snap
quarterback are not the same event, and a roster count cannot tell them apart.

Joining the two datasets needs care. Snap counts key on `pfr_player_id`, and
while rosters do carry `pfr_id`, roughly a third of it is null -- a returning
player without a Pro Football Reference page would be counted as departed,
understating continuity for every team. Roster `gsis_id` is fully populated, so
the join goes through the players table as a crosswalk instead.

Team abbreviations also disagree between the two feeds (rosters say "AZ", snap
counts say "ARI"), which silently drops a team entirely if left unnormalised.
"""

from __future__ import annotations

import polars as pl

# nflverse is not internally consistent about these. Mapping to the schedule's
# spelling, which is what the rest of the project uses.
TEAM_ALIASES = {
    "AZ": "ARI",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "LAR": "LA",
    "SL": "LA",
    "SD": "LAC",
    "OAK": "LV",
    "WSH": "WAS",
    "JAC": "JAX",
}


def _normalise_team(col: str) -> pl.Expr:
    return pl.col(col).replace(TEAM_ALIASES).alias(col)

# A departure or arrival worth naming rather than folding into the percentage,
# measured as the player's own share of team plays (snap_counts' offense_pct),
# not their share of the roster's summed snaps -- no single player reaches even
# 10% of the latter, so a threshold set against it never fires.
NOTABLE_SNAP_PCT = 0.55
NOTABLE_LIST_LIMIT = 6

# Continuity below this is a materially different team; above it, broadly the
# same one. Used to scale how much prior-season efficiency is trusted.
LOW_CONTINUITY = 0.55
HIGH_CONTINUITY = 0.85


def _team_snap_totals(snaps: pl.DataFrame) -> pl.DataFrame:
    """Per player per team: total snaps, and their own share of team plays.

    Two different denominators, deliberately. `off_snaps` feeds the
    snap-weighted continuity percentage, where summing across the roster is
    correct. `off_pct` is the player's share of the team's plays, which is what
    decides whether a departure is worth naming.
    """
    return snaps.group_by("team", "pfr_player_id", "player", "position").agg(
        pl.col("offense_snaps").sum().alias("off_snaps"),
        pl.col("defense_snaps").sum().alias("def_snaps"),
        pl.col("offense_pct").mean().alias("off_pct"),
        pl.col("defense_pct").mean().alias("def_pct"),
    )


def continuity(
    snaps_prior: pl.DataFrame,
    roster_current: pl.DataFrame,
    players: pl.DataFrame,
) -> dict[str, dict]:
    """Snap-weighted roster continuity per team, plus who left and who arrived.

    `players` is the nflverse players table, used only as a pfr_id -> gsis_id
    crosswalk so the roster can be matched on its fully populated id.

    Returns a dict keyed by team abbreviation. A team missing from either input
    simply does not appear, rather than being reported as zero continuity.
    """
    if snaps_prior.is_empty() or roster_current.is_empty() or players.is_empty():
        return {}

    snaps_prior = snaps_prior.with_columns(_normalise_team("team"))
    roster_current = roster_current.with_columns(_normalise_team("team"))

    per_player = _team_snap_totals(snaps_prior)

    # pfr_id -> gsis_id. Roster pfr_id is ~1/3 null; gsis_id is complete.
    crosswalk = (
        players.filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .select(pl.col("pfr_id").alias("pfr_player_id"), "gsis_id")
        .unique(subset=["pfr_player_id"])
    )
    per_player = per_player.join(crosswalk, on="pfr_player_id", how="left")

    current = (
        roster_current.filter(pl.col("gsis_id").is_not_null())
        .select("gsis_id", pl.col("team").alias("now_team"))
        .unique(subset=["gsis_id"])
    )
    joined = per_player.join(current, on="gsis_id", how="left").with_columns(
        (pl.col("now_team") == pl.col("team")).fill_null(False).alias("retained")
    )

    out: dict[str, dict] = {}
    for team in sorted(joined["team"].unique().to_list()):
        rows = joined.filter(pl.col("team") == team)
        kept = rows.filter(pl.col("retained"))

        def share(frame: pl.DataFrame, col: str, total_col: str) -> float | None:
            total = rows[total_col].sum()
            return round(frame[col].sum() / total, 3) if total else None

        notable = (pl.col("off_pct") >= NOTABLE_SNAP_PCT) | (
            pl.col("def_pct") >= NOTABLE_SNAP_PCT
        )
        by_usage = pl.max_horizontal(
            pl.col("off_pct").fill_null(0), pl.col("def_pct").fill_null(0)
        )

        departures = [
            {
                "player": r["player"],
                "position": r["position"],
                "snap_pct_2025": round(max(r["off_pct"] or 0, r["def_pct"] or 0), 3),
                "side": "offense" if (r["off_pct"] or 0) >= (r["def_pct"] or 0) else "defense",
                "now": r["now_team"] or "not on a roster",
            }
            for r in rows.filter(~pl.col("retained") & notable)
            .sort(by_usage, descending=True)
            .head(NOTABLE_LIST_LIMIT)
            .to_dicts()
        ]

        # Players now here who logged real snaps elsewhere last season.
        arrivals = [
            {
                "player": r["player"],
                "position": r["position"],
                "from": r["team"],
                "snap_pct_2025": round(max(r["off_pct"] or 0, r["def_pct"] or 0), 3),
                "side": "offense" if (r["off_pct"] or 0) >= (r["def_pct"] or 0) else "defense",
            }
            for r in joined.filter(
                (pl.col("now_team") == team) & (pl.col("team") != team) & notable
            )
            .sort(by_usage, descending=True)
            .head(NOTABLE_LIST_LIMIT)
            .to_dicts()
        ]

        off_cont = share(kept, "off_snaps", "off_snaps")
        def_cont = share(kept, "def_snaps", "def_snaps")
        overall = (
            round((off_cont + def_cont) / 2, 3)
            if off_cont is not None and def_cont is not None
            else off_cont if off_cont is not None else def_cont
        )

        out[team] = {
            "offense_continuity": off_cont,
            "defense_continuity": def_cont,
            "overall_continuity": overall,
            "departures": departures,
            "arrivals": arrivals,
        }
    return out


def usage_by_gsis(
    snaps: pl.DataFrame, players: pl.DataFrame
) -> dict[str, dict]:
    """gsis_id -> how much that player actually played last season.

    Injury reports key on gsis_id but say nothing about whether the player is a
    starter. Without that, "Questionable: J. Smith, CB" is unreadable -- it
    could be a shutdown corner or a special-teamer. This supplies the snap
    share so the model can tell the difference.
    """
    if snaps.is_empty() or players.is_empty():
        return {}

    crosswalk = (
        players.filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .select(pl.col("pfr_id").alias("pfr_player_id"), "gsis_id")
        .unique(subset=["pfr_player_id"])
    )
    agg = (
        snaps.group_by("pfr_player_id")
        .agg(
            pl.col("offense_pct").mean().alias("off_pct"),
            pl.col("defense_pct").mean().alias("def_pct"),
            pl.len().alias("games"),
        )
        .join(crosswalk, on="pfr_player_id", how="inner")
    )
    return {
        r["gsis_id"]: {
            "snap_pct": round(max(r["off_pct"] or 0, r["def_pct"] or 0), 3),
            "games": r["games"],
        }
        for r in agg.to_dicts()
    }


def depth_chart(depth: pl.DataFrame, team: str, *, top_n: int = 2) -> dict:
    """Current listed starters by position, from the most recent chart.

    Depth charts carry a timestamp and are refreshed through the week, so only
    the latest snapshot is used -- an older one would describe a lineup that
    has since changed.
    """
    if depth.is_empty():
        return {}
    latest = depth.filter(pl.col("dt") == depth["dt"].max()).with_columns(
        _normalise_team("team")
    )
    rows = latest.filter(
        (pl.col("team") == team) & (pl.col("pos_rank") <= top_n)
    ).sort("pos_abb", "pos_rank")
    if rows.is_empty():
        return {}

    out: dict[str, list[str]] = {}
    for r in rows.to_dicts():
        out.setdefault(r["pos_abb"], []).append(r["player_name"])
    return {
        "as_of": str(latest["dt"].max())[:10],
        "by_position": out,
        "quarterback": (out.get("QB") or [None])[0],
    }


def carryover_for(overall_continuity: float | None, base: float) -> float:
    """Scale prior-season carryover by how much of the roster actually returned.

    A team returning 85%+ of its snaps keeps the full carryover; one returning
    under 55% has its prior-season numbers pulled substantially further toward
    league average, because they describe a team that no longer exists.
    """
    if overall_continuity is None:
        return base
    if overall_continuity >= HIGH_CONTINUITY:
        return base
    if overall_continuity <= LOW_CONTINUITY:
        return base * 0.5
    # Linear between the two thresholds.
    span = (overall_continuity - LOW_CONTINUITY) / (HIGH_CONTINUITY - LOW_CONTINUITY)
    return base * (0.5 + 0.5 * span)

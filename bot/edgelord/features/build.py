"""Assemble the single JSON pack that gets handed to the model for one game.

Loading play-by-play is the expensive step, so a builder is constructed once per
slate and reused across every game in it.

Anything unavailable is emitted as an explicit null and recorded in `data_gaps`.
The model is instructed to reason around gaps rather than fill them in, which
only works if the gaps are actually stated.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import polars as pl

from .. import config
from ..sources import nflverse, stadiums, weather
from . import (
    context,
    efficiency,
    market,
    matchup,
    players,
    regression,
    roster,
    situational,
)

# Recency window used alongside season-to-date numbers.
RECENT_WEEKS = 5

# How many seasons of schedules to load for head-to-head history. Cheap: a
# season of schedules is ~285 rows against ~50,000 for play-by-play.
H2H_SEASONS = 10
# Positions whose absence actually moves a line.
KEY_POSITIONS = ("QB", "RB", "WR", "TE", "T", "G", "C", "DE", "DT", "LB", "CB", "S", "K")

EASTERN = ZoneInfo("America/New_York")


def _jsonable(obj):
    """Polars and numpy scalars do not survive json.dumps untouched."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) else round(obj, 4)
    if hasattr(obj, "item"):
        try:
            return _jsonable(obj.item())
        except Exception:
            return str(obj)
    return obj


def _split_sides(row: dict) -> dict:
    """Turn off_/def_ prefixed columns into two nested blocks."""
    off = {k[4:]: v for k, v in row.items() if k.startswith("off_")}
    dfn = {k[4:]: v for k, v in row.items() if k.startswith("def_")}
    rest = {
        k: v
        for k, v in row.items()
        if not k.startswith(("off_", "def_")) and k != "team"
    }
    return {"offense": off, "defense": dfn, **rest}


def _continuity_reading(overall: float | None) -> str | None:
    """Plain-language guidance so the number is not read in isolation."""
    if overall is None:
        return None
    if overall >= roster.HIGH_CONTINUITY:
        return (
            "largely the same team; prior-season figures are reasonably "
            "descriptive"
        )
    if overall <= roster.LOW_CONTINUITY:
        return (
            "substantially rebuilt; prior-season figures describe a roster that "
            "no longer exists and should carry little weight"
        )
    return "meaningful turnover; discount prior-season figures accordingly"


def _row_for(table: pl.DataFrame, team: str) -> dict:
    if table.is_empty() or "team" not in table.columns:
        return {}
    hit = table.filter(pl.col("team") == team)
    return hit.to_dicts()[0] if hit.height else {}


def kickoff_datetime(game: dict) -> datetime | None:
    """Kickoff in the venue's local time. nflverse stores gametime as Eastern."""
    gameday, gametime = game.get("gameday"), game.get("gametime")
    if not gameday or not gametime:
        return None
    try:
        naive = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    eastern = naive.replace(tzinfo=EASTERN)
    venue = stadiums.venue(
        game.get("stadium_id"),
        game.get("home_team"),
        stadium=game.get("stadium"),
        neutral=bool(game.get("location") and game["location"] != "Home"),
    )
    if not venue:
        return eastern.replace(tzinfo=None)
    return eastern.astimezone(ZoneInfo(venue.tz)).replace(tzinfo=None)


class FeatureBuilder:
    """Holds the season data in memory so a whole slate can be built cheaply."""

    def __init__(self, seasons: list[int], *, refresh: bool = False):
        self.seasons = sorted(seasons)

        # Play-by-play is the expensive pull (~50k rows a season) so it stays
        # on the narrow window the efficiency metrics need. Schedules are ~285
        # rows a season, which makes a decade of them essentially free -- and a
        # head-to-head history two seasons deep is barely a history at all.
        self.pbp = nflverse.pbp(self.seasons, refresh=refresh)
        self.injuries = nflverse.injuries(self.seasons, refresh=refresh)
        self.ftn = nflverse.ftn_charting(self.seasons, refresh=refresh)

        newest = self.seasons[-1]
        history = list(range(newest - H2H_SEASONS + 1, newest + 1))
        self.schedules = nflverse.schedules(history, refresh=refresh)
        self._eff_cache: dict = {}
        self._reg_cache: dict = {}
        self._continuity: dict | None = None
        self._usage: dict | None = None
        self._depth = None

    def _roster_inputs(self, season: int):
        """Snap counts, current roster and the id crosswalk, loaded once."""
        return (
            nflverse.snap_counts([season - 1]),
            nflverse.rosters([season]),
            nflverse.players(),
        )

    def continuity(self, season: int) -> dict:
        """Snap-weighted roster turnover from the prior offseason."""
        if self._continuity is None:
            try:
                self._continuity = roster.continuity(*self._roster_inputs(season))
            except Exception:
                self._continuity = {}
        return self._continuity

    def usage(self, season: int) -> dict:
        """gsis_id -> snap share, so injuries can be read by importance."""
        if self._usage is None:
            try:
                snaps, _, players = self._roster_inputs(season)
                self._usage = roster.usage_by_gsis(snaps, players)
            except Exception:
                self._usage = {}
        return self._usage

    def depth(self, season: int):
        """Latest depth chart, refreshed through the week."""
        if self._depth is None:
            try:
                self._depth = nflverse.depth_charts(season)
            except Exception:
                self._depth = pl.DataFrame()
        return self._depth

    def _efficiency(self, season: int, week: int, last_n: int | None):
        """Returns (table, current_season_weight)."""
        key = (season, week, last_n)
        if key not in self._eff_cache:
            self._eff_cache[key] = efficiency.blended_team_metrics(
                self.pbp, self.ftn, season, week, last_n_weeks=last_n
            )
        return self._eff_cache[key]

    def _regression(self, season: int, week: int) -> pl.DataFrame:
        key = (season, week)
        if key not in self._reg_cache:
            self._reg_cache[key] = regression.table(self.schedules, self.pbp, season, week)
        return self._reg_cache[key]

    def _team_block(self, game: dict, team: str, gaps: list[str]) -> dict:
        season, week = game["season"], game["week"]
        side = "home" if team == game["home_team"] else "away"

        season_table, blend_weight = self._efficiency(season, week, None)
        recent_table, _ = self._efficiency(season, week, RECENT_WEEKS)
        season_eff = _row_for(season_table, team)
        recent_eff = _row_for(recent_table, team)
        reg = _row_for(self._regression(season, week), team)

        if not season_eff:
            gaps.append(f"{team}: no efficiency data yet (week {week} of {season})")
        if not reg:
            # Early weeks have no current-season record at all, so the prior
            # season's is supplied separately rather than left blank.
            gaps.append(f"{team}: no results yet in {season}")

        injuries = context.injury_report(
            self.injuries,
            team,
            season,
            week,
            positions=KEY_POSITIONS,
            usage=self.usage(season),
        )
        if not injuries:
            gaps.append(f"{team}: no injury report rows for week {week}")

        # Checked before every game, not only while the prior season is being
        # blended in: rosters keep changing mid-season through trades, waivers
        # and injured reserve.
        depth = roster.depth_chart(self.depth(season), team)
        cont = self.continuity(season).get(team, {})

        block = {
            "team": team,
            "coach": game.get(f"{side}_coach"),
            "quarterback": depth.get("quarterback") or game.get(f"{side}_qb"),
            "division": stadiums.DIVISIONS.get(team),
            "efficiency_season": _split_sides(season_eff) if season_eff else None,
            f"efficiency_last_{RECENT_WEEKS}": _split_sides(recent_eff) if recent_eff else None,
            "regression_indicators": reg or None,
            "splits": context.team_splits(self.schedules, team, season, week),
            "coaching": context.coaching_profile(self.pbp, team, season, week),
            "injuries": injuries,
            "depth_chart": depth or None,
        }

        # Who is actually producing the offence, and whether they still are.
        # Team efficiency hides a quarterback who has fallen apart in a month.
        form = players.profile(self.pbp, team, season, week, recent_weeks=RECENT_WEEKS)
        if form:
            block["player_form"] = form
        elif week > 1:
            gaps.append(f"{team}: no player-level data yet in {season}")

        if cont:
            block["roster_turnover"] = {**cont, "reading": _continuity_reading(
                cont.get("overall_continuity")
            )}

        # State the provenance rather than passing blended numbers off as
        # current-season fact. The model is told how much of what it is reading
        # is last year's and that the prior has been regressed to the mean.
        if blend_weight < 1.0:
            block["efficiency_provenance"] = {
                "current_season_weight": blend_weight,
                "prior_season_weight": round(1 - blend_weight, 3),
                "prior_season": season - 1,
                "note": (
                    f"{round((1 - blend_weight) * 100)}% of the efficiency figures "
                    f"above come from {season - 1}, regressed toward league average "
                    "before use. See roster_turnover for how much of that team "
                    "actually returned -- the lower the continuity, the less those "
                    "figures describe the team playing this week."
                ),
            }
            prior_reg = _row_for(self._regression(season - 1, 99), team)
            if prior_reg:
                block["prior_season_record"] = prior_reg

        return block

    def build(self, conn, game_id: str, *, include_result: bool = False) -> dict:
        """Assemble the pack.

        `include_result` defaults to False and must stay that way for anything
        the model sees: the games table holds final scores for completed games,
        and handing those over would let a backtest read the answer instead of
        predicting it.
        """
        row = conn.execute("SELECT * FROM games WHERE game_id = ?", (game_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown game_id {game_id!r}")
        game = dict(row)
        gaps: list[str] = []

        home, away = game["home_team"], game["away_team"]
        neutral = bool(game.get("location") and game["location"] != "Home")
        venue = stadiums.venue(
            game.get("stadium_id"), home, stadium=game.get("stadium"), neutral=neutral
        )
        if venue is None:
            gaps.append(
                f"unknown venue {game.get('stadium')!r} ({game.get('stadium_id')!r}): "
                "no travel, altitude or weather data"
            )
        elif neutral and venue.stadium_id == game.get("stadium_id"):
            # Name lookup missed and we fell back to the home team's stadium --
            # travel numbers would be wrong rather than merely absent.
            gaps.append(
                f"neutral-site venue {game.get('stadium')!r} not in the venue table; "
                "travel and time-zone figures fall back to the home stadium and "
                "should be ignored"
            )

        kickoff = kickoff_datetime(game)
        wx = weather.for_game(game, venue, kickoff)
        if not wx.get("indoor") and wx.get("temp_f") is None:
            gaps.append("no weather observation or forecast available")

        mkt = market.block(conn, game)
        if not mkt["movement"].get("available"):
            gaps.append(
                "no stored line snapshots: opening line, line movement and "
                "movement direction are unavailable for this game"
            )

        ref = context.referee_profile(self.schedules, self.pbp, game.get("referee"))
        if ref is None:
            gaps.append("referee not yet announced")

        home_block = self._team_block(game, home, gaps)
        away_block = self._team_block(game, away, gaps)

        h2h = context.head_to_head(self.schedules, home, away, game["season"], game["week"])
        if not h2h["meetings"]:
            gaps.append(
                f"no {home}-{away} meetings within the loaded seasons "
                f"({self.seasons[0]}-{self.seasons[-1]}); head-to-head history is "
                "unavailable rather than nonexistent"
            )

        pack = {
            "game": {
                "game_id": game_id,
                "season": game["season"],
                "week": game["week"],
                "game_type": game["game_type"],
                "kickoff_local": kickoff.strftime("%Y-%m-%d %H:%M") if kickoff else None,
                "gameday": game["gameday"],
                "weekday": game["weekday"],
                "gametime_et": game["gametime"],
                "home_team": home,
                "away_team": away,
                "stadium": game.get("stadium"),
            },
            "market": mkt,
            "situation": situational.game_situation(self.schedules, game),
            "weather": wx,
            "officiating": ref,
            "matchup": {
                **context.divisional_context(home, away),
                # Unit against unit, computed rather than left for the model to
                # difference across two separate team blocks.
                "unit_ratings": matchup.ratings(
                    home,
                    away,
                    home_block.get("efficiency_season") or {},
                    away_block.get("efficiency_season") or {},
                ),
                "head_to_head": h2h,
            },
            "home": home_block,
            "away": away_block,
            "data_gaps": gaps,
        }

        if include_result and game["home_score"] is not None:
            pack["game"]["final_score"] = {
                "home": game["home_score"],
                "away": game["away_score"],
            }
        return _jsonable(pack)

    def store(self, conn, game_id: str, pack: dict) -> int:
        cur = conn.execute(
            "INSERT INTO features (game_id, built_at, payload, data_gaps) VALUES (?,?,?,?)",
            (
                game_id,
                datetime.now().isoformat(timespec="seconds"),
                json.dumps(pack, separators=(",", ":")),
                json.dumps(pack.get("data_gaps", [])),
            ),
        )
        return cur.lastrowid


def split_played(conn, game_ids: list[str]) -> tuple[list[str], list[str]]:
    """Split game ids into (unplayed, played), preserving order.

    A live pick on a finished game supersedes the pick that was graded, and
    grading only counts unsuperseded rows -- so the record would silently swap
    a real outcome for a pick written after the score was known.
    """
    if not game_ids:
        return [], []
    marks = ",".join("?" * len(game_ids))
    played = {
        r["game_id"]
        for r in conn.execute(
            f"SELECT game_id FROM games WHERE home_score IS NOT NULL "
            f"AND game_id IN ({marks})",
            game_ids,
        )
    }
    return (
        [g for g in game_ids if g not in played],
        [g for g in game_ids if g in played],
    )


def slate_game_ids(conn, season: int, week: int) -> list[str]:
    rows = conn.execute(
        "SELECT game_id FROM games WHERE season = ? AND week = ? ORDER BY gameday, gametime",
        (season, week),
    ).fetchall()
    return [r["game_id"] for r in rows]

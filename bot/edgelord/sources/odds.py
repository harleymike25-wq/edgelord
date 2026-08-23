"""The Odds API client.

The free tier allows 500 credits a month and a request costs
`markets x regions` credits, so one poll of spreads/totals/moneyline across US
books is 3. Polling every six hours is ~360 a month, which leaves headroom for
the extra Thursday and Monday passes. `check_budget` refuses to spend past the
configured ceiling rather than letting a runaway loop burn the month's quota.

Snapshots are the whole point: the API only ever returns the *current* number,
so the opening line and everything derived from line movement exists only
because we stored every poll.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .. import config

BASE = "https://api.the-odds-api.com/v4"
SPORT = "americanfootball_nfl"
DEFAULT_MARKETS = ("spreads", "totals", "h2h")
DEFAULT_REGIONS = ("us",)

# The Odds API uses full club names; nflverse uses these abbreviations.
TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


class BudgetExceeded(RuntimeError):
    pass


def credits_used_this_month(conn) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(credits_used), 0) n FROM odds_api_usage "
        "WHERE captured_at >= date('now','start of month')"
    ).fetchone()
    return int(row["n"] or 0)


def check_budget(conn, cost: int, *, budget: int | None = None) -> tuple[int, int]:
    """Raise before spending if this call would breach the monthly ceiling."""
    budget = budget if budget is not None else config.ODDS_MONTHLY_BUDGET
    used = credits_used_this_month(conn)
    if used + cost > budget:
        raise BudgetExceeded(
            f"poll would cost {cost} credits; {used}/{budget} already used this month"
        )
    return used, budget


def fetch(
    markets: tuple[str, ...] = DEFAULT_MARKETS,
    regions: tuple[str, ...] = DEFAULT_REGIONS,
    *,
    timeout: float = 30.0,
) -> tuple[list[dict], dict]:
    """Current odds for every upcoming NFL game, plus quota headers."""
    params = {
        "apiKey": config.odds_key(),
        "regions": ",".join(regions),
        "markets": ",".join(markets),
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    r = httpx.get(f"{BASE}/sports/{SPORT}/odds", params=params, timeout=timeout)
    r.raise_for_status()
    quota = {
        "used": r.headers.get("x-requests-used"),
        "remaining": r.headers.get("x-requests-remaining"),
        "last_cost": r.headers.get("x-requests-last"),
    }
    return r.json(), quota


def _outcomes(market: dict) -> dict[str, dict]:
    return {o["name"]: o for o in market.get("outcomes", [])}


def parse_event(event: dict, captured_at: str) -> list[dict]:
    """Flatten one event into one row per bookmaker."""
    home_name, away_name = event.get("home_team"), event.get("away_team")
    home, away = TEAM_ABBR.get(home_name), TEAM_ABBR.get(away_name)
    rows = []

    for book in event.get("bookmakers", []):
        markets = {m["key"]: m for m in book.get("markets", [])}
        row = {
            "odds_event_id": event["id"],
            "commence_time": event["commence_time"],
            "home_team": home or home_name,
            "away_team": away or away_name,
            "book": book["key"],
            "captured_at": captured_at,
            "book_update": book.get("last_update"),
            "spread_home": None, "spread_home_price": None, "spread_away_price": None,
            "total": None, "over_price": None, "under_price": None,
            "ml_home": None, "ml_away": None,
        }

        if "spreads" in markets:
            o = _outcomes(markets["spreads"])
            if home_name in o:
                # The Odds API quotes the home handicap as -3.5 when home is
                # favoured; nflverse quotes the same game as +3.5. Flip it so
                # everything downstream shares one convention.
                row["spread_home"] = -o[home_name].get("point") if o[home_name].get("point") is not None else None
                row["spread_home_price"] = o[home_name].get("price")
            if away_name in o:
                row["spread_away_price"] = o[away_name].get("price")

        if "totals" in markets:
            o = _outcomes(markets["totals"])
            if "Over" in o:
                row["total"] = o["Over"].get("point")
                row["over_price"] = o["Over"].get("price")
            if "Under" in o:
                row["under_price"] = o["Under"].get("price")

        if "h2h" in markets:
            o = _outcomes(markets["h2h"])
            if home_name in o:
                row["ml_home"] = o[home_name].get("price")
            if away_name in o:
                row["ml_away"] = o[away_name].get("price")

        rows.append(row)
    return rows


def match_game_id(conn, row: dict) -> str | None:
    """Tie an odds event to an nflverse game_id via teams and kickoff date."""
    try:
        kickoff = datetime.fromisoformat(row["commence_time"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    day = kickoff.astimezone(timezone.utc).date().isoformat()

    hit = conn.execute(
        "SELECT game_id FROM games WHERE home_team = ? AND away_team = ? "
        "AND ABS(julianday(gameday) - julianday(?)) <= 1 LIMIT 1",
        (row["home_team"], row["away_team"], day),
    ).fetchone()
    return hit["game_id"] if hit else None


COLUMNS = [
    "game_id", "odds_event_id", "commence_time", "home_team", "away_team", "book",
    "captured_at", "book_update", "spread_home", "spread_home_price",
    "spread_away_price", "total", "over_price", "under_price", "ml_home", "ml_away",
]


def poll(
    conn,
    *,
    markets=DEFAULT_MARKETS,
    regions=DEFAULT_REGIONS,
    budget=None,
    dry_run: bool = False,
) -> dict:
    """One poll: fetch, match to games, store every book's numbers.

    `dry_run` still costs a credit (the request is made) but writes nothing --
    it is the way to confirm auth, parsing and the sign convention against live
    odds without putting a single row in the database.
    """
    cost = len(markets) * len(regions)
    used, ceiling = check_budget(conn, cost, budget=budget)

    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events, quota = fetch(markets, regions)

    rows, unmatched, sample = [], 0, []
    for event in events:
        for row in parse_event(event, captured_at):
            row["game_id"] = match_game_id(conn, row)
            if row["game_id"] is None:
                unmatched += 1
            if len(sample) < 8:
                sample.append(
                    {
                        "matchup": f"{row['away_team']} at {row['home_team']}",
                        "kickoff": row["commence_time"],
                        "book": row["book"],
                        "spread_home": row["spread_home"],
                        "total": row["total"],
                        "game_id": row["game_id"],
                    }
                )
            rows.append(tuple(row[c] for c in COLUMNS))

    if rows and not dry_run:
        conn.executemany(
            f"INSERT OR IGNORE INTO line_snapshots ({', '.join(COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in COLUMNS)})",
            rows,
        )

    spent = int(quota["last_cost"] or cost)
    # Credit accounting is recorded even on a dry run -- the request was made
    # and the provider charged for it, so pretending otherwise would drift the
    # budget guard out of sync with reality.
    conn.execute(
        "INSERT INTO odds_api_usage (captured_at, endpoint, credits_used, "
        "credits_remaining, events_returned) VALUES (?,?,?,?,?)",
        (captured_at, f"odds:{','.join(markets)}{':dry' if dry_run else ''}", spent,
         int(quota["remaining"]) if quota["remaining"] else None, len(events)),
    )

    return {
        "captured_at": captured_at,
        "dry_run": dry_run,
        "events": len(events),
        "rows": len(rows) if not dry_run else 0,
        "rows_would_write": len(rows) if dry_run else None,
        "unmatched_rows": unmatched,
        "credits_spent": spent,
        "credits_remaining_provider": quota["remaining"],
        "credits_used_this_month": used + spent,
        "monthly_budget": ceiling,
        "sample": sample,
    }


def purge_unmatched(conn) -> int:
    """Delete snapshots that never matched a scheduled game.

    Preseason events land here: the games table only holds regular and
    postseason rows, so a preseason poll stores orphans with a null game_id.
    They are inert -- every downstream query joins on game_id -- but this
    clears them out if you want a clean slate before week one.
    """
    cur = conn.execute("DELETE FROM line_snapshots WHERE game_id IS NULL")
    return cur.rowcount

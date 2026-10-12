"""Which live picks were made on information that has since changed.

The Week 5 picks were made on a Thursday, before most injury reports existed,
and nothing looked at them again: two losses went to kickoff with a quarterback
whose status had changed after the pick. This compares the pack each live pick
was built from against a fresh one and names what moved. It costs nothing --
spending a model call on a flagged game is the caller's decision.

What counts as a change is deliberately narrow, because every flag is a
candidate for a paid rerun:

- the spread crossing a key number (or a total moving 1.5+ on a total pick),
  measured against the number the pick itself saw, not a snapshot lookup;
- the expected starting quarterback changing;
- the expected starter's own game status changing;
- a starter (or a 50%+ snap player) moving into or out of Out/Doubtful.

Backup quarterbacks do not count. A rule that flagged any quarterback would
have rerun DEN/LAC because Trey Lance went Doubtful while Herbert started.

Practice-participation churn on its own does not count. It moves every day and
a rerun on each would cost a slate a week.
"""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from .features import market

EASTERN = ZoneInfo("America/New_York")
TOTAL_MOVE = 1.5
SNAP_SHARE = 0.5
GONE = {"out", "doubtful"}


def kicked_off(game: dict, now: datetime | None = None) -> bool:
    """True once kickoff has passed. nflverse stores gametime as Eastern."""
    try:
        ko = datetime.strptime(f"{game['gameday']} {game['gametime']}", "%Y-%m-%d %H:%M")
    except (KeyError, TypeError, ValueError):
        return False
    now = now or datetime.now(EASTERN)
    return now >= ko.replace(tzinfo=EASTERN)


def _availability(status: str | None) -> str:
    s = (status or "").strip().lower()
    if s in GONE:
        return "out"
    if s == "questionable":
        return "questionable"
    return "available"


def _players(pack: dict, side: str) -> dict[str, dict]:
    return {
        p["player"]: p
        for p in (pack.get(side) or {}).get("injuries") or []
        if isinstance(p, dict) and p.get("player")
    }


def _expected_qb(pack: dict, side: str) -> str | None:
    block = pack.get(side) or {}
    sit = block.get("quarterback_situation") or {}
    qb = sit.get("expected_starter") or block.get("quarterback")
    if isinstance(qb, dict):
        qb = qb.get("name")
    return qb


def _is_qb(p: dict) -> bool:
    return (p.get("position") or "").upper() == "QB"


def _matters(p: dict, starting_qbs: set[str]) -> bool:
    if _is_qb(p):
        return p.get("player") in starting_qbs
    return bool(p.get("starter")) or (p.get("snap_pct_prior") or 0) >= SNAP_SHARE


def injury_changes(old: dict, new: dict) -> list[str]:
    reasons = []
    for side in ("home", "away"):
        team = (new.get("game") or {}).get(f"{side}_team") or side
        before, after = _expected_qb(old, side), _expected_qb(new, side)
        if before and after and before != after:
            reasons.append(f"{team} expected QB {before} -> {after}")

        starting_qbs = {q for q in (before, after) if q}
        o, n = _players(old, side), _players(new, side)
        for name in sorted(set(o) | set(n)):
            p = n.get(name) or o[name]
            if not _matters(p, starting_qbs):
                continue
            a = _availability((o.get(name) or {}).get("status"))
            b = _availability((n.get(name) or {}).get("status"))
            if a == b:
                continue
            if _is_qb(p) or "out" in (a, b):
                was = (o.get(name) or {}).get("status") or "not listed"
                now = (n.get(name) or {}).get("status") or "not listed"
                reasons.append(f"{team} {p.get('position') or ''} {name}: {was} -> {now}".replace("  ", " "))
    return reasons


def line_changes(old: dict, new: dict, pick_type: str | None) -> list[str]:
    om, nm = old.get("market") or {}, new.get("market") or {}
    reasons = []
    s0, s1 = om.get("current_spread_home"), nm.get("current_spread_home")
    if market.crossed_key_number(s0, s1):
        reasons.append(f"spread {s0:+g} -> {s1:+g} (home), crossed a key number")
    t0, t1 = om.get("current_total"), nm.get("current_total")
    if pick_type == "total" and t0 is not None and t1 is not None and abs(t1 - t0) >= TOTAL_MOVE:
        reasons.append(f"total {t0:g} -> {t1:g}")
    return reasons


def live_picks(conn, season: int, week: int) -> list[dict]:
    """Every game of the week with its live pick (or None) and kickoff fields."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT g.game_id, g.gameday, g.gametime, g.home_score, "
            "  p.id AS prediction_id, p.pick_type, f.payload "
            "FROM games g "
            "LEFT JOIN predictions p ON p.game_id = g.game_id "
            "  AND p.superseded_by IS NULL AND p.run_label != 'backtest' "
            "LEFT JOIN features f ON f.id = p.features_id "
            "WHERE g.season = ? AND g.week = ? ORDER BY g.gameday, g.gametime",
            (season, week),
        ).fetchall()
    ]


def detect(conn, builder, season: int, week: int, *, now: datetime | None = None) -> list[dict]:
    """Games that need a (re)pick, each with its reasons and the fresh pack."""
    out = []
    for g in live_picks(conn, season, week):
        if g["home_score"] is not None or kicked_off(g, now):
            continue
        new = builder.build(conn, g["game_id"])
        if g["prediction_id"] is None:
            out.append({**g, "pack": new, "reasons": ["no pick yet"]})
            continue
        old = json.loads(g["payload"]) if g["payload"] else {}
        reasons = line_changes(old, new, g["pick_type"]) + injury_changes(old, new)
        if reasons:
            out.append({**g, "pack": new, "reasons": reasons})
    return out


def store_flags(conn, season: int, week: int, flagged: list[dict]) -> None:
    """Replace the week's open flags with this check's findings."""
    conn.execute(
        "DELETE FROM recheck_flags WHERE game_id IN "
        "(SELECT game_id FROM games WHERE season = ? AND week = ?)",
        (season, week),
    )
    now = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO recheck_flags (game_id, prediction_id, checked_at, reasons) "
        "VALUES (?,?,?,?)",
        [(f["game_id"], f["prediction_id"], now, json.dumps(f["reasons"])) for f in flagged],
    )



def week_spend(conn, season: int, week: int) -> float:
    """Model spend already made by scheduled rechecks for this week."""
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_usage "
        "WHERE run_label = 'recheck' AND game_id LIKE ?",
        (f"{season}_{week:02d}_%",),
    ).fetchone()
    return float(row[0])


def call_estimate(conn, default: float = 0.12) -> float:
    """Expected cost of one prediction: the dearest of the last ten live calls."""
    rows = conn.execute(
        "SELECT cost_usd FROM api_usage WHERE run_label NOT IN ('postmortem', 'backtest') "
        "ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return max([r[0] for r in rows if r[0]] or [default])

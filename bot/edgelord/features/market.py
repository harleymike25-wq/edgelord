"""Market features derived from our own line snapshots.

Key numbers matter because NFL margins pile up on specific values: roughly one
game in seven lands on exactly 3 and one in seventeen on exactly 7. Buying or
selling across those numbers is worth far more than the same half point
anywhere else, so the pack reports where the current line sits relative to them.

On reverse line movement: true RLM is defined against public ticket share, and
no free source publishes that. What is computed here is line movement *direction
and magnitude* -- specifically whether the number moved toward the underdog,
which correlates with but is not identical to RLM. It is named accordingly so
the model is not told something stronger than the data supports.
"""

from __future__ import annotations

import statistics
from datetime import datetime

# Ordered by how much probability mass sits on them.
KEY_NUMBERS = [3, 7, 6, 10, 4, 14]
# A move this size or larger is worth remarking on.
NOTABLE_MOVE = 1.0
STEAM_MOVE = 1.5


def key_number_context(spread: float | None) -> dict | None:
    """Where a spread sits relative to the numbers that actually matter."""
    if spread is None:
        return None
    mag = abs(spread)
    nearest = min(KEY_NUMBERS, key=lambda k: (abs(mag - k), KEY_NUMBERS.index(k)))
    return {
        "spread_magnitude": mag,
        "on_key_number": any(abs(mag - k) < 1e-9 for k in KEY_NUMBERS),
        "nearest_key_number": nearest,
        "distance_to_key": round(mag - nearest, 1),
        "just_past_3": 3 < mag <= 3.5,
        "just_past_7": 7 < mag <= 7.5,
        "inside_3": mag < 3,
    }


def _consensus(rows: list[dict], field: str) -> float | None:
    vals = [r[field] for r in rows if r.get(field) is not None]
    return round(statistics.median(vals), 2) if vals else None


def _crossings(series: list[float]) -> list[int]:
    """Key numbers the line crossed over the life of the market."""
    if len(series) < 2:
        return []
    lo, hi = min(map(abs, series)), max(map(abs, series))
    return [k for k in sorted(KEY_NUMBERS) if lo < k < hi]


def line_history(conn, game_id: str) -> dict:
    """Reconstruct the open-to-current path from stored snapshots."""
    rows = conn.execute(
        "SELECT captured_at, book, spread_home, spread_home_price, total, "
        "over_price, under_price, ml_home, ml_away "
        "FROM line_snapshots WHERE game_id = ? ORDER BY captured_at",
        (game_id,),
    ).fetchall()

    if not rows:
        return {
            "available": False,
            "note": "no line snapshots stored for this game; only the nflverse "
            "closing line is known",
        }

    by_time: dict[str, list[dict]] = {}
    for r in rows:
        by_time.setdefault(r["captured_at"], []).append(dict(r))

    stamps = sorted(by_time)
    path = [
        {
            "captured_at": t,
            "books": len(by_time[t]),
            "spread_home": _consensus(by_time[t], "spread_home"),
            "total": _consensus(by_time[t], "total"),
        }
        for t in stamps
    ]
    spreads = [p["spread_home"] for p in path if p["spread_home"] is not None]
    totals = [p["total"] for p in path if p["total"] is not None]

    opener, current = (spreads[0], spreads[-1]) if spreads else (None, None)
    t_open, t_current = (totals[0], totals[-1]) if totals else (None, None)
    move = round(current - opener, 2) if opener is not None and current is not None else None

    # Book disagreement at the latest timestamp -- a wide range means the market
    # has not settled and there may be a better number available somewhere.
    latest = by_time[stamps[-1]]
    latest_spreads = [r["spread_home"] for r in latest if r["spread_home"] is not None]
    spread_range = (
        round(max(latest_spreads) - min(latest_spreads), 2) if len(latest_spreads) > 1 else 0.0
    )

    toward_dog = None
    if move is not None and opener is not None and opener != 0:
        # opener > 0 means home favoured; the line moving down favours the dog.
        toward_dog = (move < 0) if opener > 0 else (move > 0)

    return {
        "available": True,
        "first_seen": stamps[0],
        "last_seen": stamps[-1],
        "snapshots": len(stamps),
        "books_latest": len(latest),
        "opening_spread_home": opener,
        "current_spread_home": current,
        "spread_move": move,
        "spread_move_toward_underdog": toward_dog,
        "notable_move": move is not None and abs(move) >= NOTABLE_MOVE,
        "steam_move": move is not None and abs(move) >= STEAM_MOVE,
        "key_numbers_crossed": _crossings(spreads),
        "opening_total": t_open,
        "current_total": t_current,
        "total_move": round(t_current - t_open, 2) if t_open is not None and t_current is not None else None,
        "book_spread_disagreement": spread_range,
        "public_betting_pct": None,
        "public_betting_note": "no free source publishes ticket/handle splits; "
        "reverse line movement cannot be confirmed, only movement direction",
        "path": path[-12:],
    }


def best_available(conn, game_id: str) -> dict:
    """The best number on offer per side at the most recent poll."""
    row = conn.execute(
        "SELECT MAX(captured_at) t FROM line_snapshots WHERE game_id = ?", (game_id,)
    ).fetchone()
    if not row or not row["t"]:
        return {}

    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT book, spread_home, spread_home_price, spread_away_price, total, "
            "over_price, under_price, ml_home, ml_away FROM line_snapshots "
            "WHERE game_id = ? AND captured_at = ?",
            (game_id, row["t"]),
        ).fetchall()
    ]
    if not rows:
        return {}

    def pick(field, best):
        cand = [r for r in rows if r.get(field) is not None]
        return best(cand, key=lambda r: r[field]) if cand else None

    best_home = pick("spread_home", max)
    best_away = pick("spread_home", min)
    best_over = pick("total", min)
    best_under = pick("total", max)

    return {
        "as_of": row["t"],
        "best_home_spread": (
            {"book": best_home["book"], "line": best_home["spread_home"],
             "price": best_home["spread_home_price"]} if best_home else None
        ),
        "best_away_spread": (
            {"book": best_away["book"], "line": -best_away["spread_home"],
             "price": best_away["spread_away_price"]} if best_away else None
        ),
        "best_over": ({"book": best_over["book"], "line": best_over["total"],
                       "price": best_over["over_price"]} if best_over else None),
        "best_under": ({"book": best_under["book"], "line": best_under["total"],
                        "price": best_under["under_price"]} if best_under else None),
    }


def _consensus_at(conn, game_id: str, at: str | None) -> float | None:
    """Consensus home spread at a point in time, or the latest if `at` is None."""
    if at is None:
        row = conn.execute(
            "SELECT MAX(captured_at) t FROM line_snapshots WHERE game_id = ?",
            (game_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT MAX(captured_at) t FROM line_snapshots "
            "WHERE game_id = ? AND captured_at <= ?",
            (game_id, at),
        ).fetchone()
    if not row or not row["t"]:
        return None
    rows = [
        dict(r)
        for r in conn.execute(
            "SELECT spread_home FROM line_snapshots "
            "WHERE game_id = ? AND captured_at = ?",
            (game_id, row["t"]),
        ).fetchall()
    ]
    return _consensus(rows, "spread_home")


def crossed_key_number(before: float | None, after: float | None) -> bool:
    """True when a key number sits strictly between two spreads."""
    if before is None or after is None or before == after:
        return False
    lo, hi = sorted((abs(before), abs(after)))
    return any(lo < k < hi for k in KEY_NUMBERS)


def games_needing_repredict(conn, season: int, week: int) -> list[str]:
    """Games worth spending another model call on.

    Re-predicting a whole slate on every midweek run triples the bill for very
    little -- most numbers barely move, and a pick at 3.5 rarely changes because
    the line ticked to 3.5 the other way. A game qualifies only if it has no
    live prediction yet, or its number has crossed a key number since the last.
    """
    rows = conn.execute(
        "SELECT g.game_id, "
        "  (SELECT MAX(p.created_at) FROM predictions p "
        "    WHERE p.game_id = g.game_id AND p.superseded_by IS NULL "
        "      AND p.run_label != 'backtest') AS last_pred "
        "FROM games g WHERE g.season = ? AND g.week = ? "
        "ORDER BY g.gameday, g.gametime",
        (season, week),
    ).fetchall()

    out = []
    for r in rows:
        if r["last_pred"] is None:
            out.append(r["game_id"])
            continue
        before = _consensus_at(conn, r["game_id"], r["last_pred"])
        after = _consensus_at(conn, r["game_id"], None)
        if crossed_key_number(before, after):
            out.append(r["game_id"])
    return out


def block(conn, game: dict) -> dict:
    """Full market picture for one game."""
    history = line_history(conn, game["game_id"])
    current = history.get("current_spread_home")
    if current is None:
        current = game.get("spread_line")
    current_total = history.get("current_total") or game.get("total_line")

    return {
        "nflverse_closing_spread_home": game.get("spread_line"),
        "nflverse_closing_total": game.get("total_line"),
        "current_spread_home": current,
        "current_total": current_total,
        "moneyline_home": game.get("home_moneyline"),
        "moneyline_away": game.get("away_moneyline"),
        "key_numbers": key_number_context(current),
        "movement": history,
        "best_available": best_available(conn, game["game_id"]),
    }

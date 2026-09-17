"""Every measured input behind a pick, as renderable tables.

The write-up argues a case and names the two or three figures that support
it. This is the rest: the same numbers the model was handed, laid out so a
reader can check the argument against them rather than take it on trust.

Both report formats build from the same table list, so the markdown and the
HTML cannot drift apart -- a factor added here appears in both or neither.
"""

from __future__ import annotations

from typing import Any

# A table is either a key/value block ("kv") or a header/rows grid ("grid").
Table = dict[str, Any]


def _pct(v: Any, digits: int = 1) -> str:
    return "—" if v is None else f"{float(v) * 100:.{digits}f}%"


def _num(v: Any, digits: int = 3) -> str:
    return "—" if v is None else f"{float(v):.{digits}f}"


def _signed(v: Any, digits: int = 2) -> str:
    if v is None:
        return "—"
    return f"{float(v):+.{digits}f}"


def _int(v: Any) -> str:
    return "—" if v is None else f"{int(v):,}"


def _conditions(pack: dict) -> Table | None:
    wx = pack.get("weather") or {}
    sit = pack.get("situation") or {}
    rows: list[tuple[str, str]] = []

    if wx.get("indoor"):
        rows.append(("Roof", f"{wx.get('roof') or 'indoor'} — weather not a factor"))
    elif wx.get("temp_f") is not None:
        rows.append(("Temperature", f"{_num(wx.get('temp_f'), 0)}°F"))
        gust = wx.get("wind_gust_mph")
        wind = f"{_num(wx.get('wind_mph'), 0)} mph"
        if gust:
            wind += f", gusting {_num(gust, 0)}"
        rows.append(("Wind", wind))
        rows.append(
            (
                "Precipitation",
                f"{_num(wx.get('precip_probability_pct'), 0)}% chance, "
                f"{_num(wx.get('precip_inches'), 2)} in",
            )
        )
        rows.append(("Humidity", f"{_num(wx.get('humidity_pct'), 0)}%"))
        rows.append(("Source", str(wx.get("source") or "—")))
    else:
        rows.append(("Weather", str(wx.get("note") or "not available")))

    if sit:
        home, away = sit.get("home") or {}, sit.get("away") or {}
        rows.append(
            (
                "Rest",
                f"{_num(home.get('rest_days'), 0)} days home / "
                f"{_num(away.get('rest_days'), 0)} days away",
            )
        )
        rows.append(("Road travel", f"{_int(away.get('travel_miles'))} miles"))
        rows.append(
            ("Time-zone shift", f"{_signed(away.get('timezone_shift_hours'), 0)} hours")
        )
        rows.append(
            ("Altitude change", f"{_signed(away.get('altitude_change_ft'), 0)} ft")
        )
        slot = sit.get("kickoff_slot") or "—"
        if sit.get("divisional"):
            slot += " · divisional"
        if sit.get("neutral_site"):
            slot += " · neutral site"
        rows.append(("Slot", slot))

    return {"title": "Conditions", "kind": "kv", "rows": rows} if rows else None


def _market(pack: dict) -> Table | None:
    mkt = pack.get("market") or {}
    if not mkt:
        return None

    keys = mkt.get("key_numbers") or {}
    mv = mkt.get("movement") or {}
    rows = [
        ("Current spread (home)", _signed(mkt.get("current_spread_home"), 1)),
        ("Current total", _num(mkt.get("current_total"), 1)),
        (
            "Moneyline",
            f"home {mkt.get('moneyline_home') or '—'} / "
            f"away {mkt.get('moneyline_away') or '—'}",
        ),
        ("Nearest key number", str(keys.get("nearest_key_number") or "—")),
        ("On a key number", "yes" if keys.get("on_key_number") else "no"),
        ("Distance to key", _num(keys.get("distance_to_key"), 1)),
    ]

    if mv.get("available"):
        rows += [
            ("Opening spread", _signed(mv.get("opening_spread_home"), 1)),
            ("Spread move", _signed(mv.get("spread_move"), 1)),
            (
                "Move direction",
                "toward the underdog"
                if mv.get("spread_move_toward_underdog")
                else "toward the favourite",
            ),
            ("Total move", _signed(mv.get("total_move"), 1)),
            ("Key numbers crossed", str(mv.get("key_numbers_crossed") or "none")),
            ("Snapshots", str(mv.get("snapshots") or "—")),
            ("First seen", str(mv.get("first_seen") or "—")),
            ("Last seen", str(mv.get("last_seen") or "—")),
        ]
    else:
        rows.append(("Line movement", "no snapshot history"))

    return {"title": "Market", "kind": "kv", "rows": rows}


PRIOR_ROWS: list[tuple[str, str, str]] = [
    ("Record", "record", "raw"),
    ("Points for / against", "points", "raw"),
    ("Point diff / game", "point_diff_per_game", "signed1"),
    ("Win %", "win_pct", "pct"),
    ("Pythagorean win %", "pythagorean_win_pct", "pct"),
    ("Pythagorean delta", "pythagorean_delta", "signed3"),
    ("One-score record", "one_score", "raw"),
    ("Turnover margin", "turnover_margin", "signed0"),
    ("Own FG %", "own_fg_pct", "pct0"),
    ("Opponent FG %", "opp_fg_pct", "pct0"),
]


def _prior_cell(rec: dict, key: str, fmt: str) -> str:
    if key == "record":
        ties = f"-{rec.get('ties')}" if rec.get("ties") else ""
        return f"{rec.get('wins')}-{rec.get('losses')}{ties}"
    if key == "points":
        return f"{rec.get('points_for')} / {rec.get('points_against')}"
    if key == "one_score":
        return f"{rec.get('one_score_wins')}-{rec.get('one_score_losses')}"
    v = rec.get(key)
    return {
        "pct": lambda: _pct(v, 1),
        "pct0": lambda: _pct(v, 0),
        "signed0": lambda: _signed(v, 0),
        "signed1": lambda: _signed(v, 1),
        "signed3": lambda: _signed(v, 3),
    }[fmt]()


def _prior_season(pack: dict, away: str, home: str) -> Table | None:
    a = (pack.get("away") or {}).get("prior_season_record")
    h = (pack.get("home") or {}).get("prior_season_record")
    if not a and not h:
        return None

    rows = [
        [
            label,
            _prior_cell(a, key, fmt) if a else "—",
            _prior_cell(h, key, fmt) if h else "—",
        ]
        for label, key, fmt in PRIOR_ROWS
    ]
    return {
        "title": "Prior season profile",
        "kind": "grid",
        "headers": ["", away, home],
        "rows": rows,
        "note": (
            "Pythagorean delta is win rate minus what the points scored and "
            "allowed support. A positive figure means the record flatters the "
            "team, and that gap historically does not repeat."
        ),
    }


EFF_ROWS: list[tuple[str, str, str]] = [
    ("EPA / play", "epa_play", "num"),
    ("EPA / play (adjusted)", "epa_adj", "num"),
    ("Success rate", "success_rate", "pct"),
    ("Success rate (adjusted)", "success_adj", "pct"),
    ("Explosive rate", "explosive_rate", "pct"),
    ("Early-down EPA", "early_down_epa", "num"),
    ("Pass EPA", "pass_epa", "num"),
    ("Rush EPA", "rush_epa", "num"),
    ("Third-down rate", "third_down_rate", "pct"),
    ("Red-zone TD %", "rz_td_pct", "pct"),
    ("Pressure rate", "pressure_rate", "pct"),
    ("Sack rate", "sack_rate", "pct"),
    ("Plays / game", "plays_per_game", "num1"),
]


def _eff_cell(blk: dict | None, key: str, fmt: str) -> str:
    if not blk:
        return "—"
    v = blk.get(key)
    if fmt == "pct":
        return _pct(v, 1)
    if fmt == "num1":
        return _num(v, 1)
    return _num(v, 3)


def _efficiency(pack: dict, away: str, home: str, side: str) -> Table | None:
    a = ((pack.get("away") or {}).get("efficiency_season") or {}).get(side)
    h = ((pack.get("home") or {}).get("efficiency_season") or {}).get(side)
    if not a and not h:
        return None

    rows = [
        [label, _eff_cell(a, key, fmt), _eff_cell(h, key, fmt)]
        for label, key, fmt in EFF_ROWS
    ]
    return {
        "title": f"{side.capitalize()} efficiency, prior season",
        "kind": "grid",
        "headers": ["", away, home],
        "rows": rows,
    }


UNIT_ROWS: list[tuple[str, str]] = [
    ("EPA / play", "epa_per_play"),
    ("Success rate", "success_rate"),
    ("Explosive rate", "explosive_rate"),
    ("Red zone TD%", "red_zone_td_pct"),
    ("Third down", "third_down_rate"),
]


def _unit_pairings(pack: dict) -> list[Table]:
    ratings = (pack.get("matchup") or {}).get("unit_ratings") or {}
    out: list[Table] = []
    for unit in ratings.get("units") or []:
        rows = []
        for label, key in UNIT_ROWS:
            cell = unit.get(key) or {}
            fmt = (
                (lambda v: _num(v, 3))
                if key == "epa_per_play"
                else (lambda v: _pct(v, 1))
            )
            rows.append(
                [
                    label,
                    fmt(cell.get("offense")),
                    fmt(cell.get("defense_allows")),
                    fmt(cell.get("league_avg")),
                    f"{fmt(cell.get('projected'))} ({fmt(cell.get('edge'))})",
                ]
            )

        # Pressure and pace are measured per pairing but do not share the
        # offense/defense/league columns, so they ride as their own rows.
        pr = unit.get("pressure") or {}
        if pr:
            rows.append(
                [
                    "Pressure",
                    _pct(pr.get("offense_allows"), 1),
                    _pct(pr.get("defense_generates"), 1),
                    "—",
                    _pct(pr.get("edge_to_defense"), 1) + " to defense",
                ]
            )
        pace = unit.get("plays_per_game") or {}
        if pace:
            rows.append(
                [
                    "Plays / game",
                    _num(pace.get("offense"), 1),
                    _num(pace.get("defense_faces"), 1),
                    "—",
                    "—",
                ]
            )

        title = unit.get("matchup") or "Unit matchup"
        if unit.get("verdict"):
            title += f" — {unit['verdict']}"
        out.append(
            {
                "title": title,
                "kind": "grid",
                "headers": ["", "Offense", "D allows", "Lg avg", "Projected (edge)"],
                "rows": rows,
            }
        )

    if ratings.get("note"):
        out.append(
            {"title": "Unit read", "kind": "kv", "rows": [("Note", ratings["note"])]}
        )
    return out


def _designation(inj: dict) -> str:
    # The builder falls back to the practice status when a player carries no
    # game designation, so a status equal to the practice value means "none".
    status = inj.get("status")
    if not status or status == inj.get("practice"):
        return "no designation"
    return str(status)


def _injuries(pack: dict, side: str, team: str) -> Table | None:
    inj = (pack.get(side) or {}).get("injuries")
    if inj is None:
        return None
    if not inj:
        return {
            "title": f"{team} injury report",
            "kind": "kv",
            "rows": [("Report", "no listed players")],
        }
    rows = [
        [
            i.get("player") or "—",
            i.get("position") or "—",
            _designation(i),
            i.get("injury") or "—",
            i.get("practice") or "—",
            _pct(i.get("snap_pct_prior"), 0),
            "yes" if i.get("starter") else "",
        ]
        for i in inj
    ]
    return {
        "title": f"{team} injury report",
        "kind": "grid",
        "headers": ["Player", "Pos", "Game status", "Injury", "Practice", "Prior snaps", "Starter"],
        "rows": rows,
    }


def _turnover(pack: dict, side: str, team: str) -> Table | None:
    rt = (pack.get(side) or {}).get("roster_turnover")
    if not rt:
        return None

    rows = []
    for d in rt.get("departures") or []:
        rows.append(
            [
                d.get("player") or "—",
                d.get("position") or "—",
                _pct(d.get("snap_pct_2025"), 0),
                f"out → {d.get('now') or 'not on a roster'}",
            ]
        )
    for a in rt.get("arrivals") or []:
        rows.append(
            [
                a.get("player") or "—",
                a.get("position") or "—",
                _pct(a.get("snap_pct_2025"), 0),
                f"in ← {a.get('from') or '—'}",
            ]
        )
    if not rows:
        return None

    cont = (
        f"{_pct(rt.get('overall_continuity'), 0)} of snaps returning "
        f"(offense {_pct(rt.get('offense_continuity'), 0)}, "
        f"defense {_pct(rt.get('defense_continuity'), 0)})"
    )
    return {
        "title": f"{team} roster turnover — {cont}",
        "kind": "grid",
        "headers": ["Player", "Pos", "Prior snaps", "Move"],
        "rows": rows,
        "note": rt.get("reading"),
    }


def build(pack: dict, away: str, home: str) -> list[Table]:
    """Every measured input, ordered from context down to detail."""
    tables: list[Table | None] = [
        _conditions(pack),
        _market(pack),
        _injuries(pack, "away", away),
        _injuries(pack, "home", home),
        _prior_season(pack, away, home),
        _efficiency(pack, away, home, "offense"),
        _efficiency(pack, away, home, "defense"),
    ]
    tables += _unit_pairings(pack)
    tables += [_turnover(pack, "away", away), _turnover(pack, "home", home)]
    return [t for t in tables if t]

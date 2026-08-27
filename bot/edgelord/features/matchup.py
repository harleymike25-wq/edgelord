"""Unit-versus-unit ratings.

The pack already carries each team's offence and defence. What it did not carry
is the pairing, which is the thing a game actually turns on: this offence
against that defence, not both teams described in isolation.

Left to infer it, the model has to hold eight numbers across two blocks in
its head and difference them correctly. Computing it here makes the mismatches
explicit and stops the arithmetic being done in prose.

League baselines matter for reading the numbers. A defence allowing +0.02
EPA/play is not "bad" in the abstract -- it is roughly average, and only means
something next to the offence it is facing.
"""

from __future__ import annotations

# (metric key, output label). The defensive column is always what that unit
# ALLOWS, so a lower number is the better defence on every one of these.
#
# Combining them needs care, and getting it wrong inverts the read on a game.
# Both ratings are expressed against a league baseline, so the projection is:
#
#     expected = offence + (defence_allows - league_average)
#
# EPA is already centred on zero by the opponent adjustment, so its league
# average is 0 and the term collapses to a simple sum: an offence at +0.05
# facing a defence allowing -0.05 projects to a league-average 0.00. Subtracting
# instead would read that as a +0.10 edge to the offence, which is backwards --
# it would score an elite defence as help to the opponent.
#
# Rate metrics sit around their own league averages (success ~0.45, red zone TD
# ~0.55), so they need that baseline supplied rather than assumed.
PAIRS = [
    ("epa_adj", "epa_per_play"),
    ("success_rate", "success_rate"),
    ("explosive_rate", "explosive_rate"),
    ("rz_td_pct", "red_zone_td_pct"),
    ("third_down_rate", "third_down_rate"),
]

# Fallbacks when league means are not supplied. EPA is centred by construction.
DEFAULT_LEAGUE = {
    "epa_per_play": 0.0,
    "success_rate": 0.45,
    "explosive_rate": 0.12,
    "red_zone_td_pct": 0.55,
    "third_down_rate": 0.40,
}

# An advantage smaller than this is not worth calling a mismatch.
NOTABLE_EPA_GAP = 0.06


def _num(block: dict | None, key: str) -> float | None:
    if not block:
        return None
    v = block.get(key)
    return v if isinstance(v, (int, float)) else None


def _unit(
    offence: dict | None,
    defence: dict | None,
    label: str,
    league: dict | None = None,
) -> dict:
    """One side of the ball: an offence against the defence it will face."""
    out: dict = {"matchup": label}
    baseline = {**DEFAULT_LEAGUE, **(league or {})}

    for key, name in PAIRS:
        o, d = _num(offence, key), _num(defence, key)
        if o is None or d is None:
            continue
        avg = baseline.get(name, 0.0)
        projected = o + (d - avg)
        out[name] = {
            "offense": round(o, 4),
            "defense_allows": round(d, 4),
            "league_avg": round(avg, 4),
            # What this offence projects to do against this defence.
            "projected": round(projected, 4),
            # Relative to league average. Positive favours the offence.
            "edge": round(projected - avg, 4),
        }

    # Pressure is the one pairing that crosses over: the pass rush a defence
    # generates against the pressure that offence has been allowing.
    rush = _num(defence, "pressure_rate")
    allowed = _num(offence, "pressure_rate")
    if rush is not None and allowed is not None:
        out["pressure"] = {
            "defense_generates": round(rush, 4),
            "offense_allows": round(allowed, 4),
            # Positive means the pass rush is stronger than the protection.
            "edge_to_defense": round(rush - allowed, 4),
        }

    # Pace, which sets how many possessions the game gets.
    o_pace, d_pace = _num(offence, "plays_per_game"), _num(defence, "plays_per_game")
    if o_pace is not None and d_pace is not None:
        out["plays_per_game"] = {"offense": round(o_pace, 1), "defense_faces": round(d_pace, 1)}

    epa = out.get("epa_per_play", {}).get("edge")
    if epa is not None:
        out["verdict"] = (
            "clear edge to the offense" if epa >= NOTABLE_EPA_GAP
            else "clear edge to the defense" if epa <= -NOTABLE_EPA_GAP
            else "roughly even"
        )
    return out


def _biggest(units: list[dict]) -> str | None:
    """The single largest unit mismatch, for the model to lead with."""
    ranked = [
        (abs(u.get("epa_per_play", {}).get("edge") or 0), u)
        for u in units
        if u.get("epa_per_play")
    ]
    if not ranked:
        return None
    gap, unit = max(ranked, key=lambda x: x[0])
    if gap < NOTABLE_EPA_GAP:
        return "no unit mismatch stands out; the game projects close on efficiency"
    edge = unit["epa_per_play"]["edge"]
    side = "offense" if edge > 0 else "defense"
    return f"{unit['matchup']}: {gap:.3f} EPA/play advantage to the {side}"


def ratings(home_team: str, away_team: str, home_eff: dict, away_eff: dict) -> dict:
    """Both unit pairings for a game, plus the standout mismatch.

    `home_eff` / `away_eff` are the split efficiency blocks with `offense` and
    `defense` keys. EPA figures use the opponent-adjusted values where present,
    since raw EPA over a partial season is heavily schedule-dependent.
    """
    home_o = (home_eff or {}).get("offense")
    home_d = (home_eff or {}).get("defense")
    away_o = (away_eff or {}).get("offense")
    away_d = (away_eff or {}).get("defense")

    units = [
        _unit(home_o, away_d, f"{home_team} offense vs {away_team} defense"),
        _unit(away_o, home_d, f"{away_team} offense vs {home_team} defense"),
    ]
    return {
        "units": units,
        "biggest_mismatch": _biggest(units),
        "note": (
            "EPA figures are opponent-adjusted. `edge` is offense minus what the "
            "defense allows, so positive favours the offense. A defence allowing "
            "around 0.00 EPA/play is roughly league average, not bad."
        ),
    }

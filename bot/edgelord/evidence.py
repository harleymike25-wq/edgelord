"""How much the record itself should be believed.

The model rates its confidence per game. This does the same job one level up:
given the plays graded so far, how much evidence is there that any edge exists
at all?

The uncomfortable arithmetic that drives everything here: at -110 you need to
win 52.38% of spread bets to break even. Distinguishing a genuine 55% bettor
from a lucky 52.4% one takes on the order of two thousand plays -- roughly
seven NFL seasons. Any verdict from a single season is provisional, and saying
so plainly is more useful than a number that implies otherwise.

Pure standard library: no scipy, so the binomial tail is summed exactly and
the intervals use closed forms.
"""

from __future__ import annotations

import math

# Break-even win rate at standard -110 juice: 110 / (110 + 100).
BREAKEVEN = 110 / 210
# 95% two-sided, and 5% one-sided, normal deviates.
Z_95 = 1.959963985
Z_90_ONE_SIDED = 1.6448536
Z_POWER_80 = 0.8416212

# The edge worth powering for. 55% ATS is a strong, realistic long-run result;
# anything much above it is fantasy, anything below is hard to separate from
# the break-even point at all.
TARGET_EDGE = 0.55


def wilson_interval(wins: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval -- behaves sanely at small n, unlike normal approx."""
    if n == 0:
        return (0.0, 1.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def binomial_tail(wins: int, n: int, p: float) -> float:
    """P(X >= wins) for X ~ Binomial(n, p). Exact sum; n here is small."""
    if n == 0:
        return 1.0
    if wins <= 0:
        return 1.0
    return sum(
        math.comb(n, i) * (p**i) * ((1 - p) ** (n - i)) for i in range(wins, n + 1)
    )


def plays_to_detect(edge: float = TARGET_EDGE, p0: float = BREAKEVEN) -> int:
    """Sample size to separate `edge` from break-even at 95%/80% power."""
    if edge <= p0:
        return 0
    numerator = Z_90_ONE_SIDED * math.sqrt(p0 * (1 - p0)) + Z_POWER_80 * math.sqrt(
        edge * (1 - edge)
    )
    return math.ceil((numerator / (edge - p0)) ** 2)


def _clv_evidence(clvs: list[float]) -> dict:
    """Is average closing line value meaningfully above zero?

    CLV converges far faster than win rate -- it is measured on every play
    rather than only on the ones that resolve -- so it is the first place a
    real edge becomes visible.
    """
    n = len(clvs)
    if n < 2:
        return {"plays": n, "mean": None, "significant": False,
                "note": "too few graded plays to assess"}
    mean = sum(clvs) / n
    var = sum((c - mean) ** 2 for c in clvs) / (n - 1)
    stderr = math.sqrt(var / n) if var > 0 else 0.0
    z = mean / stderr if stderr > 0 else 0.0
    return {
        "plays": n,
        "mean": round(mean, 3),
        "stderr": round(stderr, 3),
        "z": round(z, 2),
        "positive_rate": round(sum(c > 0 for c in clvs) / n, 3),
        "significant": bool(stderr > 0 and z > Z_90_ONE_SIDED),
    }


def _discrimination(rows: list[dict]) -> dict:
    """Do the model's higher-confidence picks actually win more often?

    Absolute calibration is not the right test -- a stated confidence of 70
    cannot mean a 70% ATS win rate, since that rate is not achievable. What
    matters is ordering: if the top half by confidence does not beat the
    bottom half, the per-game number carries no information.
    """
    scored = [r for r in rows if r["confidence"] is not None
              and r["pick_result"] in ("win", "loss")]
    if len(scored) < 20:
        return {"plays": len(scored), "measurable": False,
                "note": "need at least 20 decided plays"}

    scored.sort(key=lambda r: r["confidence"])
    mid = len(scored) // 2
    low, high = scored[:mid], scored[mid:]

    def rate(group):
        w = sum(r["pick_result"] == "win" for r in group)
        return w / len(group) if group else 0.0

    lo_rate, hi_rate = rate(low), rate(high)
    return {
        "plays": len(scored),
        "measurable": True,
        "low_half_win_pct": round(lo_rate, 3),
        "high_half_win_pct": round(hi_rate, 3),
        "spread": round(hi_rate - lo_rate, 3),
        "informative": hi_rate > lo_rate,
    }


def _verdict(score: float) -> str:
    if score < 25:
        return "no signal yet"
    if score < 45:
        return "early, unproven"
    if score < 70:
        return "promising"
    return "established"


def assess(conn, *, season: int | None = None) -> dict:
    """Overall confidence in the record, with the reasoning made explicit."""
    # Judged on best bets only. Leans are recorded opinions the model would not
    # have staked, so folding them in would measure something nobody bet.
    sql = (
        "SELECT p.confidence, p.pick_type, r.pick_result, r.profit_units, r.clv_points "
        "FROM results r JOIN predictions p ON p.id = r.prediction_id "
        "JOIN games g ON g.game_id = r.game_id "
        "WHERE p.superseded_by IS NULL AND p.pick_type != 'pass' "
        "AND p.conviction = 'best_bet'"
    )
    params: tuple = ()
    if season is not None:
        sql += " AND g.season = ?"
        params = (season,)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    wins = sum(r["pick_result"] == "win" for r in rows)
    losses = sum(r["pick_result"] == "loss" for r in rows)
    decided = wins + losses
    clvs = [r["clv_points"] for r in rows if r["clv_points"] is not None]

    clv = _clv_evidence(clvs)
    disc = _discrimination(rows)
    lo, hi = wilson_interval(wins, decided)
    p_value = binomial_tail(wins, decided, BREAKEVEN) if decided else 1.0
    needed = plays_to_detect()

    reasons: list[str] = []
    score = 0.0

    # Sample size dominates. Everything else is noise until this is real.
    sample_pts = min(40.0, decided / needed * 40) if needed else 0.0
    score += sample_pts
    if decided < 100:
        reasons.append(
            f"{decided} decided plays is far too few to conclude anything; "
            f"separating a {TARGET_EDGE:.0%} bettor from break-even takes about "
            f"{needed:,}"
        )
    elif decided < needed:
        reasons.append(
            f"{decided} of roughly {needed:,} plays needed to confirm a "
            f"{TARGET_EDGE:.0%} edge"
        )
    else:
        reasons.append(f"{decided:,} plays is a sufficient sample")

    # CLV is the leading indicator and carries the most weight after sample size.
    if clv.get("mean") is not None:
        if clv["significant"] and clv["mean"] > 0:
            score += 35
            reasons.append(
                f"average CLV of {clv['mean']:+.2f} points is significantly "
                f"above zero (z={clv['z']}), the strongest early sign of a real edge"
            )
        elif clv["mean"] > 0:
            score += 12
            reasons.append(
                f"average CLV {clv['mean']:+.2f} is positive but not yet "
                "statistically distinguishable from zero"
            )
        else:
            reasons.append(
                f"average CLV {clv['mean']:+.2f} is at or below zero: the model "
                "is tracking the market rather than beating it"
            )
    else:
        reasons.append(
            "no closing line value recorded yet, so the leading indicator is unavailable"
        )

    # Win rate significance, deliberately worth less than CLV at small n.
    if decided:
        if p_value < 0.05:
            score += 15
            reasons.append(
                f"win rate {wins / decided:.1%} beats the {BREAKEVEN:.2%} "
                f"break-even at p={p_value:.3f}"
            )
        else:
            reasons.append(
                f"win rate {wins / decided:.1%} is not statistically above the "
                f"{BREAKEVEN:.2%} break-even (p={p_value:.2f}); the 95% interval "
                f"runs {lo:.1%} to {hi:.1%}"
            )

    if disc.get("measurable"):
        if disc["informative"]:
            score += 10
            reasons.append(
                f"higher-confidence picks win more often "
                f"({disc['high_half_win_pct']:.1%} vs {disc['low_half_win_pct']:.1%}), "
                "so the per-game confidence carries information"
            )
        else:
            reasons.append(
                f"higher-confidence picks do not win more often "
                f"({disc['high_half_win_pct']:.1%} vs {disc['low_half_win_pct']:.1%}); "
                "treat the per-game confidence as decorative for now"
            )

    score = round(min(100.0, score), 1)
    return {
        "verdict": _verdict(score),
        "score": score,
        "plays_decided": decided,
        "record": f"{wins}-{losses}",
        "win_pct": round(wins / decided, 4) if decided else None,
        "breakeven_pct": round(BREAKEVEN, 4),
        "win_pct_95_interval": [round(lo, 4), round(hi, 4)],
        "p_value_vs_breakeven": round(p_value, 4),
        "plays_needed_for_confidence": needed,
        "units": round(sum(r["profit_units"] or 0 for r in rows), 2),
        "clv": clv,
        "discrimination": disc,
        "reasons": reasons,
    }

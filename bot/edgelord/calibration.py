"""Learned corrections to the blind predictor's factor points.

The blind predictor has the model score ten factors in points and code adds
them up. Graded games show whether a factor's points tracked real margins:
if "team strength" keeps getting 3 points and the games keep landing nearer
zero, it is worth less than the model thinks. This learns one multiplier per
factor from those games and applies it when the points are summed.

It is the only place results feed back into a prediction, and it does so in
numbers, never in the prompt. The model scores every game exactly as before;
what it has been getting wrong is corrected in code where the correction can
be read, unit-tested and switched off. Post-mortem prose still never reaches a
prompt -- see README.md, Post-mortems.

Small samples teach noise, so every multiplier is pulled toward 1.0 (no
change). The pull is a ridge penalty: a prior that a factor is worth what the
model says, give or take PRIOR_SD, against game noise of SIGMA points. With a
week of games the multipliers barely move; a factor needs a season of
consistent misses before its correction is large.
"""

from __future__ import annotations

import json
import re

import numpy as np

from .shadow import CHECKLIST, FACTOR_KEYS, SIGMA

# How far a factor's true worth is believed to stray from the model's points,
# as a multiplier, before any games are seen. 0.25 says "x0.75 to x1.25 is
# plausible, x0.5 is a stretch".
PRIOR_SD = 0.25
RIDGE = (SIGMA / PRIOR_SD) ** 2

# A learned multiplier is never allowed past these, whatever the games say.
FLOOR, CEILING = 0.5, 1.5

LABEL_TO_KEY = {label: k for k, label, _ in CHECKLIST}


def samples(conn) -> list[dict]:
    """Every standing blind pick on a finished game, with its raw factor points.

    Raw points are the model's own, before any correction: multipliers are
    learned against what the model says, so they must never be fitted on
    their own output.
    """
    rows = conn.execute(
        """
        SELECT p.game_id, p.factor_points, g.home_score - g.away_score AS margin
        FROM predictions p JOIN games g ON g.game_id = p.game_id
        WHERE p.run_label = 'blind' AND p.superseded_by IS NULL
          AND p.factor_points IS NOT NULL AND g.home_score IS NOT NULL
        ORDER BY g.gameday, p.game_id
        """
    ).fetchall()
    out = []
    for r in rows:
        raw = json.loads(r["factor_points"]).get("raw") or {}
        out.append({"game_id": r["game_id"], "margin": float(r["margin"]),
                    "points": {k: float(raw.get(k) or 0.0) for k in FACTOR_KEYS}})
    return out


def fit(data: list[dict]) -> dict:
    """One multiplier per factor, shrunk toward 1.0.

    Minimises squared error on the actual margin plus RIDGE * (m - 1)^2 per
    factor, which is the posterior mean under a normal prior centred on the
    model's own points. A factor that never carried points has nothing to
    learn from and stays at exactly 1.0.
    """
    n = len(data)
    if not n:
        return {"n_games": 0, "multipliers": {k: 1.0 for k in FACTOR_KEYS}, "factors": {},
                "rmse_raw": None, "rmse_calibrated": None}

    S = np.array([[d["points"][k] for k in FACTOR_KEYS] for d in data])
    y = np.array([d["margin"] for d in data])
    resid = y - S.sum(axis=1)
    delta = np.linalg.solve(S.T @ S + RIDGE * np.eye(len(FACTOR_KEYS)), S.T @ resid)
    mult = np.clip(1.0 + delta, FLOOR, CEILING)

    factors = {}
    for i, k in enumerate(FACTOR_KEYS):
        col = S[:, i]
        used = col != 0
        factors[k] = {
            "games": int(used.sum()),
            "avg_points": round(float(np.abs(col[used]).mean()), 2) if used.any() else 0.0,
            "multiplier": round(float(mult[i]), 3),
        }

    def rmse(pred):
        return round(float(np.sqrt(np.mean((y - pred) ** 2))), 2)

    return {
        "n_games": n,
        "multipliers": {k: factors[k]["multiplier"] for k in FACTOR_KEYS},
        "factors": factors,
        # In-sample, so the calibrated figure flatters itself. Shown to make a
        # large gap visible, not as proof the correction works.
        "rmse_raw": rmse(S.sum(axis=1)),
        "rmse_calibrated": rmse(S @ mult),
    }


def current(conn) -> dict:
    """The corrections as they stand: what the next blind pick will use."""
    return fit(samples(conn))


# --- picks made before factor points were stored -------------------------------

_KEY_FACTOR = re.compile(r"^(?P<label>.+): (?P<team>[A-Z]{2,3}) \+(?P<pts>[\d.]+)$")


def reconstruct(home: str, away: str, margin: float, key_factors: list[str],
                decision_table: list[dict]) -> dict[str, float]:
    """Signed per-factor points for a blind pick stored before 2026-10-29.

    Those picks kept the top five factors' points (to 0.1) in `key_factors`
    and only a weight band for the rest. Every factor outside the top five was
    "slight" -- under a point -- and the margin is the exact sum, so the
    remainder is shared equally among them, signed by the side each favoured.
    Close enough for a correction that a week of games barely moves.
    """
    raw = {k: 0.0 for k in FACTOR_KEYS}
    seen = set()
    for s in key_factors:
        m = _KEY_FACTOR.match(s)
        if not m:
            continue
        key = LABEL_TO_KEY[m["label"]]
        raw[key] = float(m["pts"]) * (1 if m["team"] == home else -1)
        seen.add(key)

    rest = [(LABEL_TO_KEY[d["factor"]], 1 if d["favors"] == home else -1)
            for d in decision_table
            if d.get("weight") != "none" and d.get("favors") in (home, away)
            and LABEL_TO_KEY.get(d["factor"]) not in seen]
    if rest:
        residual = margin - sum(raw.values())
        net = sum(sign for _, sign in rest)
        each = residual / net if net else 0.0
        # A share outside the "slight" band means rounding or mixed signs
        # broke the arithmetic; fall back to the middle of the band.
        if not 0 < each < 1:
            each = 0.5
        for key, sign in rest:
            raw[key] = round(each * sign, 3)
    return raw


def backfill(conn) -> int:
    """Store reconstructed raw points on blind picks that predate the column."""
    rows = conn.execute(
        """
        SELECT p.id, p.projected_margin, p.key_factors, p.decision_table,
               g.home_team, g.away_team
        FROM predictions p JOIN games g ON g.game_id = p.game_id
        WHERE p.run_label = 'blind' AND p.factor_points IS NULL
        """
    ).fetchall()
    for r in rows:
        raw = reconstruct(r["home_team"], r["away_team"], r["projected_margin"],
                          json.loads(r["key_factors"] or "[]"),
                          json.loads(r["decision_table"] or "[]"))
        conn.execute(
            "UPDATE predictions SET factor_points = ? WHERE id = ?",
            (json.dumps({"raw": raw, "multipliers": None, "n_games": 0,
                         "source": "reconstructed"}), r["id"]),
        )
    return len(rows)

import { Fragment } from "react";

import type { MissSeverity, MissVerdict, PostMortem } from "@/lib/types";

const VERDICT_LABELS: Record<MissVerdict, string> = {
  thesis_wrong: "The reasoning was wrong",
  thesis_right_variance: "The reasoning held; the game went the other way",
  bad_input: "The reasoning followed a misleading input",
  data_gap: "Decided by something missing from the pack",
};

const SEVERITY_LABELS: Record<MissSeverity, string> = {
  photo_finish: "a point or less",
  near_miss: "inside a key number",
  clear: "a clear miss",
  decisive: "the wrong side",
  blowout: "not close",
};

function num(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

function signedNum(n: number): string {
  return `${n > 0 ? "+" : ""}${num(n)}`;
}

/**
 * Why a losing pick lost. Rendered under the write-up rather than beside it,
 * because it is a correction to that argument and needs to be read after it.
 *
 * `thesis_right_variance` is styled as calmly as the others on purpose: a loss
 * that was genuinely variance is not a failure to be flagged, and colouring it
 * like one would push the reader toward the exact overreaction this is meant
 * to prevent.
 */
export function PostMortemPanel({ pm }: { pm: PostMortem }) {
  const m = pm.miss;
  const variance = pm.verdict === "thesis_right_variance";
  const rows: [string, string][] = [];

  rows.push([
    "Final",
    `${m.home_team} ${m.home_score}, ${m.away_team} ${m.away_score}`,
  ]);

  if (m.pick_type === "spread" && m.actual_margin != null) {
    rows.push(
      m.projected_margin != null && m.projection_error != null
        ? [
            "Projected vs actual",
            `${m.pick_side} ${signedNum(m.projected_margin)} projected, ` +
              `${signedNum(m.actual_margin)} actual ` +
              `(off by ${num(Math.abs(m.projection_error))})`,
          ]
        : ["Actual margin", `${m.pick_side} ${signedNum(m.actual_margin)}`],
    );
  } else if (m.actual_total != null) {
    rows.push(
      m.projected_total != null && m.projection_error != null
        ? [
            "Projected vs actual",
            `${num(m.projected_total)} projected, ${num(m.actual_total)} actual ` +
              `(off by ${num(Math.abs(m.projection_error))})`,
          ]
        : ["Actual total", num(m.actual_total)],
    );
  }

  if (m.points_short != null) {
    const label = m.severity ? SEVERITY_LABELS[m.severity] : null;
    rows.push([
      "Against the number",
      `lost by ${num(m.points_short)}${label ? ` — ${label}` : ""}`,
    ]);
  }

  if (m.projected_edge != null) {
    rows.push(["Edge it claimed", `${signedNum(m.projected_edge)} pts`]);
  }

  const wrong = m.factors?.heaviest_wrong;
  const right = m.factors?.heaviest_right;

  return (
    <div className={`postmortem${variance ? " variance" : ""}`}>
      <h3 className="section">Why this lost</h3>

      {pm.verdict && (
        <p className="verdict">{VERDICT_LABELS[pm.verdict] ?? pm.verdict}</p>
      )}

      {m.contradicted_own_projection && (
        <p className="warn">
          No edge by its own arithmetic — the pick needed a result its own
          projection did not forecast.
        </p>
      )}

      <dl className="kv">
        {rows.map(([k, v]) => (
          <Fragment key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </Fragment>
        ))}

        {wrong && (
          <>
            <dt>Heaviest factor that was wrong</dt>
            <dd>
              {wrong.factor} <span className="w">({wrong.weight})</span>
              <br />
              <span className="reading">{wrong.reading}</span>
            </dd>
          </>
        )}
        {right && (
          <>
            <dt>Heaviest factor it outvoted</dt>
            <dd>
              {right.factor} <span className="w">({right.weight})</span>
              <br />
              <span className="reading">{right.reading}</span>
            </dd>
          </>
        )}
      </dl>

      {pm.explanation && (
        <div className="explanation">
          {pm.explanation.split(/\n\s*\n/).map((para, i) => (
            <p key={i}>{para.trim()}</p>
          ))}
        </div>
      )}

      {pm.lesson && (
        <p className="lesson">
          <span className="k">Lesson</span>
          {pm.lesson}
        </p>
      )}
    </div>
  );
}

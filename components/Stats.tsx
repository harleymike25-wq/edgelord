import Link from "next/link";

import { pct, units } from "@/lib/format";
import type { Evidence, Summary, WeeklyPoint } from "@/lib/types";

const tone = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : n > 0 ? "pos" : n < 0 ? "neg" : "";

/**
 * Both records side by side: best bets are what would have been staked, all
 * picks include every lean. Record and units only -- plays is the record's
 * sum, ROI is units over plays, there are no passes by design, and CLV is not
 * measurable until a second line source exists.
 */
export function RecordRow({
  best,
  all,
  href,
}: {
  best: Summary;
  all: Summary;
  href?: string;
}) {
  const pending = all.pending ?? 0;
  const body = (
    <div className="records">
      <RecordTile label="Best bets" s={best} primary />
      <RecordTile label="All picks" s={all} />
      {pending > 0 && <div className="records-pending">{pending} pending</div>}
    </div>
  );
  return href ? (
    <Link href={href} className="strip-link">
      {body}
    </Link>
  ) : (
    body
  );
}

function RecordTile({ label, s, primary = false }: { label: string; s: Summary; primary?: boolean }) {
  return (
    <div className={`record-tile ${primary ? "primary" : ""}`}>
      <div className="k">{label}</div>
      <div className="v">
        {s.record || "0-0"}
        <span className={`u ${tone(s.units)}`}>{units(s.units)}</span>
      </div>
    </div>
  );
}

/**
 * The verdict on the record, shown with it rather than buried.
 *
 * A 44-29 record reads like an edge and usually is not one. Putting the
 * sample-size caveat next to the number is the only way the number stays
 * honest.
 */
export function EvidenceBadge({ e }: { e: Evidence }) {
  const tone =
    e.score >= 70 ? "strong" : e.score >= 45 ? "moderate" : e.score >= 25 ? "weak" : "none";

  const headline =
    e.win_pct !== null
      ? `${(e.win_pct * 100).toFixed(1)}% over ${e.plays_decided} plays · ` +
        `95% confidence it's really between ` +
        `${(e.win_pct_95_interval[0] * 100).toFixed(1)}% and ` +
        `${(e.win_pct_95_interval[1] * 100).toFixed(1)}%`
      : "nothing graded yet";

  return (
    <details className={`evidence ${tone}`}>
      <summary>
        <span className="verdict">{e.verdict}</span>
        <span className="headline">{headline}</span>
      </summary>
      <ul>
        {e.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </details>
  );
}

export function SummaryTable({
  rows,
  label,
}: {
  rows: Record<string, Summary>;
  label: string;
}) {
  const entries = Object.entries(rows);
  if (!entries.length) return null;
  return (
    <table>
      <thead>
        <tr>
          <th>{label}</th>
          <th>Record</th>
          <th>Win%</th>
          <th>Units</th>
          <th>ROI</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([name, s]) => (
          <tr key={name}>
            <td>{name}</td>
            <td>{s.record}</td>
            <td>{pct(s.win_pct)}</td>
            <td className={s.units > 0 ? "pos" : s.units < 0 ? "neg" : ""}>
              {units(s.units)}
            </td>
            <td className={(s.roi ?? 0) > 0 ? "pos" : (s.roi ?? 0) < 0 ? "neg" : ""}>
              {pct(s.roi)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * Confidence tracking: does a higher stated confidence actually win more?
 *
 * This is the only question worth asking of the per-game number. Absolute
 * calibration is not — a confidence of 70 cannot mean a 70% ATS win rate,
 * because that rate is not achievable against a spread. What matters is
 * ordering, so the buckets are shown alongside an explicit verdict on whether
 * the signal carries information at all.
 */
export function ConfidenceTracking({
  buckets,
  discrimination,
}: {
  buckets: Record<string, Summary>;
  discrimination?: Evidence["discrimination"];
}) {
  const entries = Object.entries(buckets);
  if (!entries.length) {
    return (
      <p className="note">
        Nothing graded yet. Once picks resolve, this shows whether the
        higher-confidence ones actually win more often than the low ones.
      </p>
    );
  }

  const best = Math.max(...entries.map(([, s]) => s.win_pct ?? 0));

  return (
    <>
      <table>
        <thead>
          <tr>
            <th>Confidence</th>
            <th>Record</th>
            <th>Win%</th>
            <th>Units</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([name, s]) => (
            <tr key={name}>
              <td>
                <span className="bucket">{name}</span>
              </td>
              <td>{s.record}</td>
              <td>
                <span className="bar">
                  <i style={{ width: `${((s.win_pct ?? 0) / (best || 1)) * 100}%` }} />
                </span>
                {pct(s.win_pct)}
              </td>
              <td className={s.units > 0 ? "pos" : s.units < 0 ? "neg" : ""}>
                {units(s.units)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {discrimination?.measurable ? (
        <p className={`verdict-line ${discrimination.informative ? "good" : "bad"}`}>
          {discrimination.informative
            ? `The signal works so far: the top half by confidence wins ${pct(
                discrimination.high_half_win_pct,
              )} against ${pct(discrimination.low_half_win_pct)} for the bottom half.`
            : `The signal is not working: the top half by confidence wins ${pct(
                discrimination.high_half_win_pct,
              )} against ${pct(
                discrimination.low_half_win_pct,
              )} for the bottom half. Treat the per-game number as decorative until that gap opens up.`}
        </p>
      ) : (
        <p className="note">
          At least 20 decided plays are needed before the confidence signal can
          be judged either way.
        </p>
      )}
    </>
  );
}

/**
 * Cumulative units by week. Hand-drawn SVG rather than a charting dependency --
 * it is one polyline and a zero axis.
 */
export function UnitsTrend({ weekly }: { weekly: WeeklyPoint[] }) {
  if (weekly.length < 2) return null;

  // Kept close to 3:1 so the chart stays legible when it scales down to a
  // phone; a wider viewBox collapses to a sliver at 375px.
  const w = 600;
  const h = 190;
  const pad = 26;

  let running = 0;
  const pts = weekly.map((p) => {
    running += p.units;
    return { week: p.week, cum: running };
  });

  const ys = pts.map((p) => p.cum).concat(0);
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const span = hi - lo || 1;

  const x = (i: number) => pad + (i * (w - pad * 2)) / Math.max(1, pts.length - 1);
  const y = (v: number) => h - pad - ((v - lo) / span) * (h - pad * 2);

  const line = pts.map((p, i) => `${x(i)},${y(p.cum)}`).join(" ");
  const last = pts[pts.length - 1];

  return (
    // A fixed height against a wide viewBox leaves dead space once
    // preserveAspectRatio scales the drawing to the container width, so let the
    // aspect ratio set the height instead.
    <svg viewBox={`0 0 ${w} ${h}`} role="img"
         style={{ width: "100%", height: "auto", display: "block" }}
         aria-label={`Cumulative units through week ${last.week}: ${last.cum.toFixed(2)}`}>
      <line x1={pad} x2={w - pad} y1={y(0)} y2={y(0)}
            stroke="#3a424b" strokeWidth="1" strokeDasharray="3 3" />
      <polyline points={line} fill="none" strokeWidth="2"
                stroke={last.cum >= 0 ? "#4ade80" : "#f87171"} />
      {pts.map((p, i) => (
        <circle key={p.week} cx={x(i)} cy={y(p.cum)} r="2.5"
                fill={last.cum >= 0 ? "#4ade80" : "#f87171"} />
      ))}
      <text x={pad} y={y(0) - 6} fill="#6b7280" fontSize="11">0u</text>
      <text x={w - pad} y={y(last.cum) - 8} fill="#939aa4" fontSize="11" textAnchor="end">
        {last.cum >= 0 ? "+" : ""}{last.cum.toFixed(2)}u
      </text>
    </svg>
  );
}

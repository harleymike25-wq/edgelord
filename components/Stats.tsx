import Link from "next/link";

import { clv, COIN_FLIP_EDGE, pct, units } from "@/lib/format";
import type { Evidence, Game, Summary } from "@/lib/types";

const tone = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : n > 0 ? "pos" : n < 0 ? "neg" : "";

/**
 * Both records side by side: best bets are what would have been staked, all
 * picks include every lean. Closing line value sits beside them because it is
 * the better test of skill: a record can be luck for a season, but beating the
 * closing number consistently rarely is.
 */
/** A tier with nothing graded yet still shows, as 0-0: that is its record. */
const EMPTY: Summary = {
  plays: 0,
  passes: 0,
  record: "0-0",
  win_pct: null,
  units: 0,
  roi: null,
  avg_clv: null,
  clv_positive_pct: null,
};

/** One tile per conviction tier, then the season as a whole. */
export function RecordRow({
  tiers,
  all,
}: {
  tiers: Record<string, Summary>;
  all: Summary;
}) {
  const pending = all.pending ?? 0;
  return (
    <>
      <div className="records tiers">
        <RecordTile label="Best bets" s={tiers.best_bet ?? EMPTY} primary />
        <RecordTile label="Leans" s={tiers.lean ?? EMPTY} />
        <RecordTile label="Coin flips" s={tiers.coin_flip ?? EMPTY} />
      </div>
      <div className="records">
        <RecordTile label="All picks" s={all} />
        <ClvTile s={all} />
        {pending > 0 && <div className="records-pending">{pending} pending</div>}
      </div>
    </>
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

/** Average points beaten by against the close, and how often it was positive. */
function ClvTile({ s }: { s: Summary }) {
  return (
    <div className="record-tile">
      <div className="k">Closing line value</div>
      <div className="v">
        {s.avg_clv === null ? "—" : `${clv(s.avg_clv)} pts`}
        <span className="u">
          {s.clv_positive_pct === null ? "" : `${pct(s.clv_positive_pct)} beat the close`}
        </span>
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

/** Database keys as a reader would say them. */
const ROW_LABELS: Record<string, string> = {
  spread: "Spreads",
  total: "Over/unders",
  best_bet: "Best bets",
  lean: "Leans",
  coin_flip: "Coin flips",
};

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
    <table className="ratings">
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
            <td>{ROW_LABELS[name] ?? name}</td>
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

type Tally = { w: number; l: number; p: number; u: number; clv: number; clvN: number };

function tally(): Tally {
  return { w: 0, l: 0, p: 0, u: 0, clv: 0, clvN: 0 };
}

function add(t: Tally, result: string, profit: number, clvPoints?: number | null) {
  if (result === "win") t.w++;
  else if (result === "loss") t.l++;
  else t.p++;
  t.u += profit;
  if (clvPoints !== null && clvPoints !== undefined) {
    t.clv += clvPoints;
    t.clvN++;
  }
}

function avgClv(t: Tally): string {
  return t.clvN ? clv(t.clv / t.clvN) : "—";
}

function rec(t: Tally): string {
  return t.w + t.l + t.p ? `${t.w}-${t.l}${t.p ? `-${t.p}` : ""}` : "—";
}

/**
 * Record week by week, newest first, from the graded games themselves. Best
 * bets get their own column because they are the record that counts; the
 * running total shows the season's shape without needing the chart.
 */
export function WeeklyRecord({ games }: { games: Game[] }) {
  const weeks = new Map<number, { all: Tally; best: Tally }>();
  for (const g of games) {
    const r = g.result;
    if (!r || !g.prediction || g.prediction.pick_type === "pass") continue;
    const row = weeks.get(g.week) ?? { all: tally(), best: tally() };
    add(row.all, r.pick_result, r.profit_units, r.clv_points);
    if (g.prediction.conviction === "best_bet") add(row.best, r.pick_result, r.profit_units);
    weeks.set(g.week, row);
  }
  if (!weeks.size) return null;

  let running = 0;
  const rows = [...weeks.entries()]
    .sort(([a], [b]) => a - b)
    .map(([week, t]) => {
      running += t.all.u;
      return { week, ...t, running };
    })
    .reverse();

  const cls = (n: number) => (n > 0 ? "pos" : n < 0 ? "neg" : "");

  return (
    <table className="ratings">
      <thead>
        <tr>
          <th>Week</th>
          <th>Record</th>
          <th>Units</th>
          <th>CLV</th>
          <th>Best bets</th>
          <th>Season</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.week}>
            <td>
              <Link href={`/week/${r.week}`}>Week {r.week}</Link>
            </td>
            <td>{rec(r.all)}</td>
            <td className={cls(r.all.u)}>{units(r.all.u)}</td>
            <td className={cls(r.all.clvN ? r.all.clv / r.all.clvN : 0)}>{avgClv(r.all)}</td>
            <td className={r.best.w + r.best.l + r.best.p ? cls(r.best.u) : "dim"}>
              {rec(r.best)}
            </td>
            <td className={cls(r.running)}>{units(r.running)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const SPREAD_BANDS: { label: string; lo: number; hi: number }[] = [
  { label: "Under 3", lo: 0, hi: 2.5 },
  { label: "3 to 6.5", lo: 3, hi: 6.5 },
  { label: "7 to 9.5", lo: 7, hi: 9.5 },
  { label: "10+", lo: 10, hi: Infinity },
];

/**
 * Spread picks by the size of the number and by which side was taken.
 *
 * Split both ways because the bot's known habit lives in the corner of this
 * table: it takes the underdog on big spreads. Size alone would average that
 * away. `line_at_pick` is stored from the picked side: positive = favourite.
 */
export function SpreadRecord({ games }: { games: Game[] }) {
  const rows = SPREAD_BANDS.map((b) => ({ ...b, fav: tally(), dog: tally(), all: tally() }));
  for (const g of games) {
    const p = g.prediction;
    const r = g.result;
    if (!r || !p || p.pick_type !== "spread" || p.line_at_pick === null) continue;
    const size = Math.abs(p.line_at_pick);
    const row = rows.find((b) => size >= b.lo && size <= b.hi) ?? rows[rows.length - 1];
    add(row.all, r.pick_result, r.profit_units);
    if (p.line_at_pick > 0) add(row.fav, r.pick_result, r.profit_units);
    else if (p.line_at_pick < 0) add(row.dog, r.pick_result, r.profit_units);
  }
  const shown = rows.filter((r) => r.all.w + r.all.l + r.all.p > 0);
  if (!shown.length) return null;

  const cls = (t: Tally) => (t.w + t.l + t.p === 0 ? "dim" : t.u > 0 ? "pos" : t.u < 0 ? "neg" : "");
  const cell = (t: Tally) =>
    t.w + t.l + t.p ? (
      <>
        <span className="cell-rec">{rec(t)}</span>
        <span className="cell-u">{units(t.u)}</span>
      </>
    ) : (
      "—"
    );

  return (
    <table className="ratings stacked">
      <thead>
        <tr>
          <th>Spread</th>
          <th>Favourite</th>
          <th>Underdog</th>
          <th>All</th>
        </tr>
      </thead>
      <tbody>
        {shown.map((r) => (
          <tr key={r.label}>
            <td>{r.label}</td>
            <td className={cls(r.fav)}>{cell(r.fav)}</td>
            <td className={cls(r.dog)}>{cell(r.dog)}</td>
            <td className={cls(r.all)}>{cell(r.all)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const EDGE_BANDS: { label: string; lo: number; hi: number }[] = [
  { label: `Under ${COIN_FLIP_EDGE} pt (coin flip)`, lo: -Infinity, hi: COIN_FLIP_EDGE - 0.01 },
  { label: `${COIN_FLIP_EDGE} to 2.5 pts`, lo: COIN_FLIP_EDGE - 0.01, hi: 2.5 },
  { label: "3+ pts", lo: 2.5, hi: Infinity },
];

/**
 * Record by how far the projection beat the line.
 *
 * If the model knows something the market does not, bigger edges should win
 * more. Through Week 5 of 2026 they did not: a point or less went 31-21,
 * 3+ points 2-2.
 * This table keeps that question in front of the record rather than behind it.
 */
export function EdgeRecord({ games }: { games: Game[] }) {
  const rows = EDGE_BANDS.map((b) => ({ ...b, t: tally(), picks: 0 }));
  for (const g of games) {
    const p = g.prediction;
    if (!p || p.edge === null || p.edge === undefined) continue;
    const row = rows.find((b) => p.edge! > b.lo && p.edge! <= b.hi) ?? rows[rows.length - 1];
    row.picks++;
    if (g.result) add(row.t, g.result.pick_result, g.result.profit_units, g.result.clv_points);
  }
  if (!rows.some((r) => r.picks)) return null;

  const cls = (n: number) => (n > 0 ? "pos" : n < 0 ? "neg" : "");
  return (
    <table className="ratings">
      <thead>
        <tr>
          <th>Edge</th>
          <th>Picks</th>
          <th>Record</th>
          <th>Win%</th>
          <th>Units</th>
          <th>CLV</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const decided = r.t.w + r.t.l;
          return (
            <tr key={r.label}>
              <td>{r.label}</td>
              <td>{r.picks}</td>
              <td>{rec(r.t)}</td>
              <td>{decided ? pct(r.t.w / decided) : "—"}</td>
              <td className={cls(r.t.u)}>{units(r.t.u)}</td>
              <td className={cls(r.t.clvN ? r.t.clv / r.t.clvN : 0)}>{avgClv(r.t)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

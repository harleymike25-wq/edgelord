import type {
  DecisionRow,
  Factors,
  PriorSeasonRecord,
  RosterMove,
  RosterTurnover,
  Situation,
  Weather,
} from "@/lib/types";

/**
 * Every input the pick was built on, shown whether or not the write-up
 * mentioned it.
 *
 * The prose names two or three factors because that is what an argument is
 * for. Checking the argument needs the rest: all the departures rather than
 * the convenient ones, both teams rather than the side being sold, and the
 * conditions even when they turn out not to matter. A factor absent from the
 * table is absent from the model; a factor absent from the paragraph only
 * means it did not make the cut.
 */

function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

function num(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

function signed(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const s = Math.abs(v).toFixed(digits);
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}`;
}

function Conditions({ wx, sit }: { wx?: Weather | null; sit?: Situation | null }) {
  if (!wx && !sit) return null;

  return (
    <div className="factor-block">
      <h4>Conditions</h4>
      <dl className="factor-grid">
        {wx?.indoor ? (
          <>
            <dt>Roof</dt>
            <dd>{wx.roof ?? "indoor"} — weather not a factor</dd>
          </>
        ) : wx && wx.temp_f !== null && wx.temp_f !== undefined ? (
          <>
            <dt>Temperature</dt>
            <dd>{num(wx.temp_f, 0)}°F</dd>
            <dt>Wind</dt>
            <dd>
              {num(wx.wind_mph, 0)} mph
              {wx.wind_gust_mph ? `, gusting ${num(wx.wind_gust_mph, 0)}` : ""}
            </dd>
            <dt>Precipitation</dt>
            <dd>
              {num(wx.precip_probability_pct, 0)}% chance
              {wx.precip_inches ? `, ${num(wx.precip_inches, 2)}"` : ""}
            </dd>
            {wx.humidity_pct !== null && wx.humidity_pct !== undefined && (
              <>
                <dt>Humidity</dt>
                <dd>{num(wx.humidity_pct, 0)}%</dd>
              </>
            )}
          </>
        ) : (
          <>
            <dt>Weather</dt>
            <dd className="dim">{wx?.note ?? "not available"}</dd>
          </>
        )}

        {sit && (
          <>
            <dt>Rest</dt>
            <dd>
              {num(sit.home.rest_days, 0)} days home / {num(sit.away.rest_days, 0)} days away
            </dd>
            <dt>Travel</dt>
            <dd>
              {sit.away.travel_miles
                ? `${sit.away.travel_miles.toLocaleString()} mi, ${signed(
                    sit.away.timezone_shift_hours,
                    0,
                  )} timezones for the road team`
                : "no meaningful travel"}
            </dd>
            <dt>Slot</dt>
            <dd>
              {sit.kickoff_slot ?? "—"}
              {sit.divisional ? " · divisional" : ""}
              {sit.neutral_site ? " · neutral site" : ""}
            </dd>
          </>
        )}
      </dl>
    </div>
  );
}

/** Rows where a high number means the record overstates the team. */
const PRIOR_ROWS: Array<{
  label: string;
  get: (r: PriorSeasonRecord) => string;
  /** Flag the side whose figure is the louder regression signal. */
  flag?: (r: PriorSeasonRecord) => boolean;
}> = [
  {
    label: "Record",
    get: (r) => `${r.wins}-${r.losses}${r.ties ? `-${r.ties}` : ""}`,
  },
  { label: "Points for / against", get: (r) => `${r.points_for} / ${r.points_against}` },
  { label: "Point diff / game", get: (r) => signed(r.point_diff_per_game, 1) },
  { label: "Win %", get: (r) => pct(r.win_pct, 1) },
  { label: "Pythagorean win %", get: (r) => pct(r.pythagorean_win_pct, 1) },
  {
    label: "Pythagorean delta",
    get: (r) => signed(r.pythagorean_delta, 3),
    // Past +0.10 the record is meaningfully ahead of the scoring behind it.
    flag: (r) => (r.pythagorean_delta ?? 0) >= 0.08,
  },
  {
    label: "One-score record",
    get: (r) => `${r.one_score_wins}-${r.one_score_losses}`,
    flag: (r) =>
      r.one_score_wins + r.one_score_losses >= 6 &&
      r.one_score_wins / (r.one_score_wins + r.one_score_losses) >= 0.65,
  },
  { label: "Turnover margin", get: (r) => signed(r.turnover_margin, 0) },
  {
    label: "Field goal % (own / opp)",
    get: (r) => `${pct(r.own_fg_pct, 0)} / ${pct(r.opp_fg_pct, 0)}`,
  },
];

function PriorSeason({
  away,
  home,
  awayTeam,
  homeTeam,
}: {
  away?: PriorSeasonRecord | null;
  home?: PriorSeasonRecord | null;
  awayTeam: string;
  homeTeam: string;
}) {
  if (!away && !home) return null;

  return (
    <div className="factor-block">
      <h4>Prior season profile</h4>
      <table className="matchup">
        <thead>
          <tr>
            <th></th>
            <th>{awayTeam}</th>
            <th>{homeTeam}</th>
          </tr>
        </thead>
        <tbody>
          {PRIOR_ROWS.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              <td className={away && row.flag?.(away) ? "neg" : ""}>
                {away ? row.get(away) : "—"}
              </td>
              <td className={home && row.flag?.(home) ? "neg" : ""}>
                {home ? row.get(home) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="factor-note">
        Pythagorean delta is win rate minus what the points scored and allowed
        support. Highlighted figures are the ones that historically do not
        repeat — a record built on them tends to come back toward the scoring.
      </p>
    </div>
  );
}

function MoveList({ moves, kind }: { moves: RosterMove[]; kind: "out" | "in" }) {
  if (!moves.length) {
    return <p className="factor-note">None above the notable-snap threshold.</p>;
  }

  return (
    <table className="matchup roster">
      <thead>
        <tr>
          <th>{kind === "out" ? "Out" : "In"}</th>
          <th>Pos</th>
          <th>2025 snaps</th>
          <th>{kind === "out" ? "To" : "From"}</th>
        </tr>
      </thead>
      <tbody>
        {moves.map((m, i) => (
          <tr key={`${m.player}-${m.from ?? m.now ?? i}`}>
            <th scope="row">{m.player}</th>
            <td>{m.position ?? "—"}</td>
            <td>{pct(m.snap_pct_2025, 0)}</td>
            <td>{(kind === "out" ? m.now : m.from) ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TeamTurnover({ team, rt }: { team: string; rt: RosterTurnover }) {
  return (
    <div className="turnover-team">
      <div className="pairing-head">
        <span className="pairing-name">{team}</span>
        <span className="pairing-verdict">
          {pct(rt.overall_continuity, 0)} of snaps returning
        </span>
      </div>
      <p className="factor-note">
        Offense {pct(rt.offense_continuity, 0)} · defense {pct(rt.defense_continuity, 0)}
        {rt.reading ? ` — ${rt.reading}` : ""}
      </p>
      <MoveList moves={rt.departures} kind="out" />
      <MoveList moves={rt.arrivals} kind="in" />
    </div>
  );
}

/** Weight ordering, loudest first, so the table reads top-down by influence. */
const WEIGHT_RANK: Record<DecisionRow["weight"], number> = {
  decisive: 0,
  strong: 1,
  moderate: 2,
  slight: 3,
  none: 4,
};

export function DecisionTable({
  rows,
  pickSide,
}: {
  rows: DecisionRow[];
  pickSide: string | null;
}) {
  if (!rows.length) return null;

  const sorted = [...rows].sort(
    (a, b) => WEIGHT_RANK[a.weight] - WEIGHT_RANK[b.weight],
  );
  const against = sorted.filter(
    (r) => r.favors !== "neither" && pickSide && r.favors !== pickSide,
  ).length;

  return (
    <div className="factor-block">
      <h3 className="section">How the pick was reached</h3>
      <table className="matchup decision">
        <thead>
          <tr>
            <th>Factor</th>
            <th>Reading</th>
            <th>Favors</th>
            <th>Weight</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const tone =
              r.favors === "neither"
                ? "dim"
                : pickSide && r.favors === pickSide
                  ? "pos"
                  : "neg";
            return (
              <tr key={`${r.factor}-${r.favors}`}>
                <th scope="row">{r.factor}</th>
                <td className="reading">{r.reading}</td>
                <td className={tone}>{r.favors}</td>
                <td className={`weight w-${r.weight}`}>{r.weight}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="factor-note">
        {against > 0
          ? `${against} of ${sorted.length} factors argue against the side taken. `
          : "Every factor with a direction points the same way, which on a coin-flip game is worth a second look. "}
        Rows marked &ldquo;none&rdquo; were considered and found not to matter.
      </p>
    </div>
  );
}

export function FactorPanel({
  factors,
  homeTeam,
  awayTeam,
}: {
  factors: Factors;
  homeTeam: string;
  awayTeam: string;
}) {
  const awayRt = factors.away?.roster_turnover;
  const homeRt = factors.home?.roster_turnover;

  return (
    <div className="factor-panel">
      <h3 className="section">All factors</h3>

      <Conditions wx={factors.weather} sit={factors.situation} />

      <PriorSeason
        away={factors.away?.prior_season_record}
        home={factors.home?.prior_season_record}
        awayTeam={awayTeam}
        homeTeam={homeTeam}
      />

      {(awayRt || homeRt) && (
        <div className="factor-block">
          <h4>Offseason roster turnover</h4>
          <div className="turnover-grid">
            {awayRt && <TeamTurnover team={awayTeam} rt={awayRt} />}
            {homeRt && <TeamTurnover team={homeTeam} rt={homeRt} />}
          </div>
          <p className="factor-note">
            A player traded during 2025 appears once per team he logged notable
            snaps for, so the same name can show twice with different clubs.
          </p>
        </div>
      )}
    </div>
  );
}

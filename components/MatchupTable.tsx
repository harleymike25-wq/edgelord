import type { HeadToHead, UnitMetric, UnitPairing, UnitRatings } from "@/lib/types";

/** Metrics shown, in the order they matter for reading a matchup. */
const ROWS: Array<[keyof UnitPairing, string, "epa" | "pct"]> = [
  ["epa_per_play", "EPA / play", "epa"],
  ["success_rate", "Success rate", "pct"],
  ["explosive_rate", "Explosive rate", "pct"],
  ["red_zone_td_pct", "Red zone TD%", "pct"],
  ["third_down_rate", "Third down", "pct"],
];

function fmt(v: number, kind: "epa" | "pct"): string {
  return kind === "epa" ? v.toFixed(3) : `${(v * 100).toFixed(1)}%`;
}

function signed(v: number, kind: "epa" | "pct"): string {
  const s = kind === "epa" ? Math.abs(v).toFixed(3) : `${(Math.abs(v) * 100).toFixed(1)}%`;
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${s}`;
}

function Pairing({ unit }: { unit: UnitPairing }) {
  const tone =
    unit.verdict === "clear edge to the offense"
      ? "pos"
      : unit.verdict === "clear edge to the defense"
        ? "neg"
        : "";

  return (
    <div className="pairing">
      <div className="pairing-head">
        <span className="pairing-name">{unit.matchup}</span>
        {unit.verdict && <span className={`pairing-verdict ${tone}`}>{unit.verdict}</span>}
      </div>

      <table className="matchup">
        <thead>
          <tr>
            <th></th>
            <th>Offense</th>
            <th>D allows</th>
            <th>Lg avg</th>
            <th>Projected</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([key, label, kind]) => {
            const m = unit[key] as UnitMetric | undefined;
            if (!m) return null;
            // Edge is relative to league average and always favours the
            // offense when positive, on every metric here.
            const cls = m.edge > 0.001 ? "pos" : m.edge < -0.001 ? "neg" : "";
            return (
              <tr key={label}>
                <td>{label}</td>
                <td>{fmt(m.offense, kind)}</td>
                <td>{fmt(m.defense_allows, kind)}</td>
                <td className="dim">{fmt(m.league_avg, kind)}</td>
                <td className={cls}>
                  {fmt(m.projected, kind)}
                  <span className="edge"> ({signed(m.edge, kind)})</span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {(unit.pressure || unit.plays_per_game) && (
        <div className="pairing-extra">
          {unit.pressure && (
            <span>
              Pass rush {(unit.pressure.defense_generates * 100).toFixed(1)}% vs
              protection allowing {(unit.pressure.offense_allows * 100).toFixed(1)}%
              {unit.pressure.edge_to_defense > 0.01 && (
                <strong className="neg"> — rush wins</strong>
              )}
            </span>
          )}
          {unit.plays_per_game && (
            <span>
              Pace {unit.plays_per_game.offense.toFixed(1)} plays/gm vs{" "}
              {unit.plays_per_game.defense_faces.toFixed(1)} faced
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function MatchupTables({ ratings }: { ratings: UnitRatings }) {
  if (!ratings?.units?.length) return null;
  return (
    <>
      <h3 className="section">Unit matchups</h3>
      {ratings.biggest_mismatch && (
        <p className="mismatch">{ratings.biggest_mismatch}</p>
      )}
      {ratings.units.map((u) => (
        <Pairing key={u.matchup} unit={u} />
      ))}
      <p className="note">
        Projected is what that offense should do against that defense, against a
        league baseline. Positive favors the offense on every row. A defense
        allowing roughly the league average is average, not bad.
      </p>
    </>
  );
}

export function HeadToHeadTable({ h2h }: { h2h: HeadToHead }) {
  if (!h2h?.recent?.length) return null;
  return (
    <>
      <h3 className="section">Past meetings</h3>
      <table className="matchup h2h">
        <thead>
          <tr>
            <th>Season</th>
            <th>Result</th>
            <th>Line</th>
            <th>Covered</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {h2h.recent.map((m) => (
            <tr key={`${m.season}-${m.week}`}>
              <td>
                {m.season} <span className="dim">wk {m.week}</span>
              </td>
              <td>{m.score}</td>
              <td className="dim">
                {m.spread_line === null ? "—" : `${m.at} ${(-m.spread_line).toFixed(1)}`}
              </td>
              <td>{m.covered}</td>
              <td className="dim">
                {m.total ?? "—"}
                {m.total_line != null && (
                  <span className="edge"> / {m.total_line}</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

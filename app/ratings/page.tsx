import Link from "next/link";

import { Masthead } from "@/components/Chrome";
import { loadRatings, loadSeason } from "@/lib/data";
import type { RatingsEvaluation } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Win rate needed to break even at -110. */
const BREAKEVEN = 110 / 210;

/** A home margin as a betting line: the favourite, laying the points. */
function asLine(home: string, away: string, margin: number | null): string {
  if (margin === null) return "—";
  const m = Math.round(margin * 2) / 2;
  if (m === 0) return "Pick";
  return m > 0 ? `${home} −${m.toFixed(1)}` : `${away} −${(-m).toFixed(1)}`;
}

function signed(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(digits)}`;
}

/**
 * Whether the replay found anything. Judged on accuracy and on the weight the
 * rating earns next to the line -- not on the ATS record, which is the noisiest
 * of the three and the easiest to be fooled by.
 */
function beatsMarket(ev: RatingsEvaluation): boolean {
  const mw = ev.market_weight;
  if (!ev.model || !ev.market || !mw || mw.se === null) return false;
  return ev.model.rmse < ev.market.rmse || mw.beta > 2 * mw.se;
}

export default async function RatingsPage() {
  const season = await loadSeason();
  const ratings = season ? await loadRatings(season.season) : null;

  if (!season || !ratings) {
    return (
      <>
        {season && <Masthead payload={season} />}
        <Link href="/" className="back">
          ← Slate
        </Link>
        <div className="empty">
          <p>No power ratings yet.</p>
          <p>
            They are computed from final scores with no model call. Run{" "}
            <code>edgelord sync</code> to write them.
          </p>
        </div>
      </>
    );
  }

  const r = ratings.replay;
  const all = r.ats?.["0+"];
  const good = beatsMarket(r);
  const [t0, t1] = ratings.test_seasons;
  const [u0, u1] = ratings.tuned_on;

  return (
    <>
      <Masthead payload={season} />
      <Link href="/" className="back">
        ← Slate
      </Link>

      <h3 className="section">Power ratings — before Week {ratings.week}</h3>

      {/* The verdict comes first. A table of projected spreads next to the
          market reads as a list of bets whether or not it is one. */}
      {r.model && r.market && all && (
        <p className={`verdict-line ${good ? "good" : "bad"}`}>
          {good ? (
            <>
              Across {r.games.toLocaleString()} games from {t0}–{t1}, these
              ratings were more accurate than the closing line.
            </>
          ) : (
            <>
              <strong>These ratings do not beat the market.</strong> Replayed
              over {r.games.toLocaleString()} games from {t0}–{t1}, they missed
              the final margin by more than the closing line did (RMSE{" "}
              {r.model.rmse} vs {r.market.rmse}), and taking their side every
              week went {all.w}-{all.l}-{all.p}, {signed(all.units)} units. Read
              them as a summary of who has been winning, not as picks.
            </>
          )}
        </p>
      )}

      <div className="strip">
        <div className="stat">
          <div className="k">Replay games</div>
          <div className="v">{r.games.toLocaleString()}</div>
        </div>
        <div className="stat">
          <div className="k">RMSE rating / line</div>
          <div className="v">
            {r.model?.rmse} / {r.market?.rmse}
          </div>
        </div>
        <div className="stat">
          <div className="k">Weight vs line</div>
          <div className={`v ${good ? "pos" : "neg"}`}>
            {signed(r.market_weight?.beta, 2)}
          </div>
        </div>
        <div className="stat">
          <div className="k">ATS, every game</div>
          <div className={`v ${(all?.units ?? 0) > 0 ? "pos" : "neg"}`}>
            {all ? `${all.w}-${all.l}-${all.p}` : "—"}
          </div>
        </div>
      </div>

      <h3 className="section">Week {ratings.week}: rating vs market</h3>
      <table className="ratings">
        <thead>
          <tr>
            <th>Game</th>
            <th>Ratings say</th>
            <th>Market</th>
            <th>Gap</th>
          </tr>
        </thead>
        <tbody>
          {ratings.slate.map((g) => {
            const gap =
              g.projected !== null && g.market !== null ? g.projected - g.market : null;
            return (
              <tr key={g.game_id}>
                <td>
                  <Link href={`/game/${g.game_id}`}>
                    {g.away_team} @ {g.home_team}
                  </Link>
                </td>
                <td>{asLine(g.home_team, g.away_team, g.projected)}</td>
                <td>{asLine(g.home_team, g.away_team, g.market)}</td>
                <td className="dim">
                  {gap === null ? "—" : `${Math.abs(gap).toFixed(1)} pts`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h3 className="section">Rankings</h3>
      <table className="ratings">
        <thead>
          <tr>
            <th>#</th>
            <th>Team</th>
            <th>Rating</th>
            <th>Last week</th>
          </tr>
        </thead>
        <tbody>
          {ratings.teams.map((t) => (
            <tr key={t.team}>
              <td className="dim">{t.rank}</td>
              <td>{t.team}</td>
              <td>{signed(t.rating)}</td>
              <td className={t.change === null ? "dim" : t.change > 0 ? "pos" : t.change < 0 ? "neg" : "dim"}>
                {signed(t.change)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {r.ats && (
        <>
          <h3 className="section">
            Replay by disagreement, {t0}–{t1}
          </h3>
          <table className="ratings">
            <thead>
              <tr>
                <th>Gap to line</th>
                <th>Games</th>
                <th>Record</th>
                <th>Win %</th>
                <th>Units</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.ats).map(([k, a]) => (
                <tr key={k}>
                  <td>{k === "0+" ? "Any" : `${k.replace("+", "")}+ pts`}</td>
                  <td>{a.games}</td>
                  <td>
                    {a.w}-{a.l}-{a.p}
                  </td>
                  <td>{a.win_pct === null ? "—" : `${(a.win_pct * 100).toFixed(1)}%`}</td>
                  <td className={a.units > 0 ? "pos" : "neg"}>{signed(a.units)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="note">
            {Object.values(r.ats).every((a) => (a.win_pct ?? 0) < BREAKEVEN)
              ? "A bigger gap to the line is not a stronger bet here: no row clears the 52.4% it takes to beat the vig at −110."
              : "52.4% is break-even at −110. A row above it on a few hundred games is well inside what luck produces; the RMSE and weight above are the better test."}
          </p>
        </>
      )}

      <p className="note">
        A rating is points better than an average team on a neutral field; home
        field is fitted at {signed(ratings.home_field)}. Each week is fitted by
        weighted least squares on final margins from every earlier game this
        season, plus last season&rsquo;s at {ratings.params.prior_weight}×
        weight, with margins capped at {ratings.params.margin_cap} and a pull
        toward average. Settings were chosen on {u0}–{u1} and judged only on{" "}
        {t0}–{t1}, which the tuning never saw; no projection is fitted on its
        own result. Computed from nflverse scores, with no model calls.
      </p>
    </>
  );
}

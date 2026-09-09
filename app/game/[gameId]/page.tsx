import Link from "next/link";
import { notFound } from "next/navigation";

import { Masthead, SyntheticBanner } from "@/components/Chrome";
import { DecisionTable, FactorPanel } from "@/components/Factors";
import { ConvictionTag, PickBadge } from "@/components/GameCard";
import { HeadToHeadTable, MatchupTables } from "@/components/MatchupTable";
import {
  clv,
  finalScore,
  kickoff,
  signed,
  units,
} from "@/lib/format";
import { findGame, loadSeason } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function GamePage({
  params,
}: {
  params: Promise<{ gameId: string }>;
}) {
  const { gameId } = await params;
  const payload = await loadSeason();
  if (!payload) notFound();

  const game = findGame(payload.games, decodeURIComponent(gameId));
  if (!game) notFound();

  const p = game.prediction;
  const r = game.result;
  const score = finalScore(game);

  return (
    <>
      <Masthead payload={payload} />
      <Link href={`/week/${game.week}`} className="back">
        ← Week {game.week}
      </Link>
      <SyntheticBanner payload={payload} />

      <div className="detail">
        <h2>
          {game.away_team} at {game.home_team}
        </h2>
        <p className="generated">
          {kickoff(game)} · {game.stadium}
          {game.roof ? ` · ${game.roof}` : ""}
        </p>

        <p>
          <ConvictionTag conviction={p?.conviction} />
          <PickBadge game={game} />
        </p>

        {p ? (
          <>
            {p.headline && <p className="headline">{p.headline}</p>}

            {/* Rendered as separate paragraphs. One unbroken block with figures
                buried mid-sentence is exactly what this replaces. */}
            <div className="analysis">
              {p.paragraph.split(/\n\s*\n/).map((para, i) => (
                <p key={i}>{para.trim()}</p>
              ))}
            </div>

            <dl className="kv">
              <dt>Confidence</dt>
              <dd>{p.confidence}</dd>

              <dt>Projected</dt>
              <dd>
                {game.home_team} {signed(p.projected_margin)} · total{" "}
                {p.projected_total.toFixed(1)}
              </dd>

              {/* Only a played game has a closing line. Before kickoff this
                  field is the current consensus, and calling it "closing" makes
                  the page assert something it cannot know yet -- which is also
                  why CLV reads 0.0 on ungraded picks. */}
              <dt>{game.final ? "Closing line" : "Current line"}</dt>
              <dd>
                {game.closing_spread_home === null
                  ? "—"
                  : `${game.home_team} ${signed(-game.closing_spread_home)}`}
                {game.closing_total !== null && ` · O/U ${game.closing_total}`}
                <span className="source">
                  {game.final ? " · nflverse" : " · nflverse consensus, not a book"}
                </span>
              </dd>

              {score && (
                <>
                  <dt>Final</dt>
                  <dd>{score}</dd>
                </>
              )}

              {r && (
                <>
                  <dt>Result</dt>
                  <dd>
                    {r.pick_result} · {units(r.profit_units)}
                  </dd>
                  <dt>CLV</dt>
                  <dd>{clv(r.clv_points)} pts</dd>
                </>
              )}

              <dt>Referee</dt>
              <dd>{game.referee ?? "—"}</dd>

              <dt>Coaches</dt>
              <dd>
                {game.away_coach} / {game.home_coach}
              </dd>

              <dt>Run</dt>
              <dd>
                {p.run_label} · {new Date(p.created_at).toLocaleString("en-US", {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </dd>

              <dt>Model</dt>
              <dd>{p.model}</dd>
            </dl>

            {game.unit_ratings && <MatchupTables ratings={game.unit_ratings} />}
            {game.head_to_head && <HeadToHeadTable h2h={game.head_to_head} />}
            {p.decision_table && p.decision_table.length > 0 && (
              <DecisionTable rows={p.decision_table} pickSide={p.pick_side} />
            )}
            {game.factors && (
              <FactorPanel
                factors={game.factors}
                homeTeam={game.home_team}
                awayTeam={game.away_team}
              />
            )}

            {p.key_factors.length > 0 && (
              <div className="factors">
                {p.key_factors.map((f) => (
                  <span key={f}>{f}</span>
                ))}
              </div>
            )}

            {p.data_gaps.length > 0 && (
              <div className="gaps">
                <h3 className="section">
                  Data gaps at prediction time ({p.data_gaps.length})
                </h3>
                <ul>
                  {p.data_gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <div className="empty">
            <p>No prediction stored for this game.</p>
          </div>
        )}
      </div>
    </>
  );
}

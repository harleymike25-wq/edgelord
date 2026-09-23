import Link from "next/link";

import {
  describePick,
  finalScore,
  kickoff,
  units,
} from "@/lib/format";
import type { Game } from "@/lib/types";

export function PickBadge({ game }: { game: Game }) {
  const p = game.prediction;
  const label = describePick(game, p);
  // Once graded, the badge carries the outcome rather than the conviction.
  const tone = game.result
    ? game.result.pick_result
    : !p
      ? "none"
      : p.conviction === "best_bet"
        ? "best"
        : p.conviction === "pass" || p.pick_type === "pass"
          ? "pass"
          : "lean";
  return <span className={`pick ${tone}`}>{label}</span>;
}

/** Only best bets get a badge -- a marker on everything marks nothing. */
export function ConvictionTag({ conviction }: { conviction?: string }) {
  if (conviction !== "best_bet") return null;
  return <span className="best-bet">BEST BET</span>;
}

export function GameCard({ game }: { game: Game }) {
  const p = game.prediction;
  const score = finalScore(game);

  return (
    <Link href={`/game/${game.game_id}`} className="card">
      <div className="top">
        <div>
          <div className="matchup">
            {game.away_team} at {game.home_team}
          </div>
          <div className="when">
            {kickoff(game)}
            {game.divisional ? " · divisional" : ""}
          </div>
        </div>
        <div>
          <ConvictionTag conviction={p?.conviction} />
          <PickBadge game={game} />
          {game.result && (
            <div className="conf">{units(game.result.profit_units)}</div>
          )}
        </div>
      </div>

      {/* The headline if we have one, otherwise fall back to the opening of
          the write-up. Older predictions predate the headline field. */}
      {p && (
        <p className="excerpt">
          {p.headline || truncate(firstParagraph(p.paragraph), 190)}
        </p>
      )}

      {score && <div className="scoreline">Final {score}</div>}
    </Link>
  );
}

function firstParagraph(s: string): string {
  return s.split(/\n\s*\n/)[0];
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  const cut = s.slice(0, n);
  return `${cut.slice(0, cut.lastIndexOf(" "))}…`;
}

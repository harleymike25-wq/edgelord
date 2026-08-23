import Link from "next/link";

import {
  HIGH_CONFIDENCE,
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
    : p?.conviction === "best_bet"
      ? "best"
      : p?.conviction === "pass" || p?.pick_type === "pass"
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
          {/* Shown on leans too: a lean at 30 is a different statement from a
              lean at 55, and both are worth tracking. */}
          {p && (
            <div className="conf">
              <ConfidenceDots value={p.confidence} muted={p.pick_type === "pass"} />
              <span className={p.confidence >= HIGH_CONFIDENCE ? "high" : ""}>
                {p.confidence}
              </span>
              {game.result && ` · ${units(game.result.profit_units)}`}
            </div>
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

/**
 * Five dots for a 1-100 confidence, so the level reads at a glance without
 * implying more precision than the number carries.
 */
export function ConfidenceDots({
  value,
  muted = false,
}: {
  value: number;
  muted?: boolean;
}) {
  // 50 is a coin flip; the scale that matters runs from there to ~75.
  const filled = Math.max(0, Math.min(5, Math.round((value - 40) / 7)));
  return (
    <span className={`dots ${muted ? "muted" : ""}`} aria-label={`confidence ${value}`}>
      {[0, 1, 2, 3, 4].map((i) => (
        <i key={i} className={i < filled ? "on" : ""} />
      ))}
    </span>
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

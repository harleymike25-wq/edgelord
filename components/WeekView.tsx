import { Masthead, SyntheticBanner, WeekNav } from "@/components/Chrome";
import { GameCard } from "@/components/GameCard";
import { GlossaryLink } from "@/components/Glossary";
import { gamesForWeek, predictedWeeks } from "@/lib/data";
import type { SeasonPayload } from "@/lib/types";

/**
 * One week's slate. Rendered by `/week/[week]` and, for the newest week with
 * picks, by `/` itself -- so home never redirects and never goes stale.
 */
export function WeekView({ payload, week: n }: { payload: SeasonPayload; week: number }) {
  const games = gamesForWeek(payload.games, n);
  const weeks = predictedWeeks(payload.games);
  const picks = games.filter((g) => g.prediction).length;
  const best = games.filter((g) => g.prediction?.conviction === "best_bet").length;

  return (
    <>
      <Masthead payload={payload} />
      <SyntheticBanner payload={payload} />

      <WeekNav weeks={weeks} current={n} />

      <h3 className="section">
        Week {n} · {picks} of {games.length} picked · {best} best bet
        {best === 1 ? "" : "s"}
      </h3>

      {games.map((g) => (
        <GameCard key={g.game_id} game={g} />
      ))}

      {/* Footer, below the slate: reference material for anyone who wants it,
          rather than something to read past on the way to the picks. */}
      <div className="primer">
        <p>
          The write-ups often mention{" "}
          <strong>Pythagorean win expectation</strong> — the record a team&rsquo;s
          points scored and allowed say it <em>should</em> have. A side well
          above it has been winning in ways that rarely last. But the line
          already knows every team&rsquo;s point differential: over ten seasons,
          betting against the luckier team was a coin flip against the spread.
          It explains a record; on its own it is not a reason to bet.
        </p>
        <GlossaryLink />
      </div>
    </>
  );
}

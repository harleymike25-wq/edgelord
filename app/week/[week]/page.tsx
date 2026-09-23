import { notFound } from "next/navigation";

import { Masthead, SyntheticBanner, WeekNav } from "@/components/Chrome";
import { GameCard } from "@/components/GameCard";
import { GlossaryLink } from "@/components/Glossary";
import { EvidenceBadge, RecordRow } from "@/components/Stats";
import { gamesForWeek, loadSeason, predictedWeeks } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function WeekPage({
  params,
}: {
  params: Promise<{ week: string }>;
}) {
  const { week } = await params;
  const n = Number(week);
  if (!Number.isFinite(n)) notFound();

  const payload = await loadSeason();
  if (!payload) notFound();

  const games = gamesForWeek(payload.games, n);
  if (!games.length) notFound();

  const weeks = predictedWeeks(payload.games);
  const picks = games.filter((g) => g.prediction).length;
  const best = games.filter((g) => g.prediction?.conviction === "best_bet").length;

  return (
    <>
      <Masthead payload={payload} />
      <SyntheticBanner payload={payload} />

      {/* Season record above the slate, always rendered: 0-0 is still the
          record. Both records, because either alone invites the wrong
          conclusion. */}
      <RecordRow
        best={payload.record.best_bets ?? payload.record.overall}
        all={payload.record.overall}
        href="/record"
      />
      {payload.evidence && payload.evidence.plays_decided > 0 && (
        <EvidenceBadge e={payload.evidence} />
      )}

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

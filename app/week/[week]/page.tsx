import { notFound } from "next/navigation";

import { Masthead, SyntheticBanner, WeekNav } from "@/components/Chrome";
import { GameCard } from "@/components/GameCard";
import { GlossaryLink } from "@/components/Glossary";
import { EvidenceBadge, Strip } from "@/components/Stats";
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
  const plays = games.filter(
    (g) => g.prediction && g.prediction.pick_type !== "pass",
  ).length;
  const passes = games.filter((g) => g.prediction?.pick_type === "pass").length;

  return (
    <>
      <Masthead payload={payload} />
      <SyntheticBanner payload={payload} />

      {/* Season record sits above the slate -- it is the thing worth seeing
          first, and it does not warrant its own tab. */}
      {/* Always rendered. A record of 0-0 with four passes is still the
          record, and hiding it until the first play makes the dashboard look
          broken rather than empty. */}
      {/* Both records, side by side. Best bets are what would actually have
          been staked; the total includes every lean. Showing only one invites
          the wrong conclusion in either direction. */}
      <Strip
        s={payload.record.best_bets ?? payload.record.overall}
        href="/record"
        label="Best bets"
      />
      <Strip s={payload.record.overall} href="/record" label="All picks" compact />
      {payload.evidence && payload.evidence.plays_decided > 0 && (
        <EvidenceBadge e={payload.evidence} />
      )}

      <WeekNav weeks={weeks} current={n} />

      <h3 className="section">
        Week {n} — {plays} play{plays === 1 ? "" : "s"}, {passes} pass
        {passes === 1 ? "" : "es"}, {games.length} games
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

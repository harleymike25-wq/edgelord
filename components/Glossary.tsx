"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Explains the terms the write-ups lean on.
 *
 * Uses the native <dialog> element rather than a hand-rolled overlay: it gets
 * focus trapping, Escape-to-close and inertness on the rest of the page for
 * free, which a div-with-a-backdrop does not.
 */

interface Term {
  term: string;
  short: string;
  body: string[];
}

const TERMS: Term[] = [
  {
    term: "Pythagorean win expectation",
    short: "the record a team's points say it should have",
    body: [
      "Takes points scored and points allowed and works out what record that scoring actually supports. The name comes from the original baseball formula, which had the shape of the Pythagorean theorem — scored² / (scored² + allowed²). The NFL version uses an exponent of 2.37 rather than 2.",
      "A team at 11-6 with a Pythagorean of 8-9 has been winning games its scoring does not justify — usually by going unbeaten in one-score finishes. That is the least repeatable way to win, so the following season, or the second half of the same one, tends to look worse.",
      "The pack reports pythagorean_delta: actual win rate minus Pythagorean win rate. Positive means the record flatters the team. Anything past +0.10 is a loud regression flag, and the market is often still pricing the record.",
    ],
  },
  {
    term: "Closing line value (CLV)",
    short: "did you get a better number than the market settled on",
    body: [
      "The gap between the line you took and where it closed. Take a team at +3.5 and watch it close at +2.5, and you held a better number than everyone who bet it later — that is +1 point of CLV.",
      "It matters because it converges far faster than win rate. Whether a bettor is genuinely good takes something like two thousand plays to establish; CLV is measured on every single bet, resolved or not, and shows up within a season.",
      "If average CLV sits at or below zero over a decent sample, the model is describing the market rather than beating it — regardless of what the win-loss record happens to say.",
    ],
  },
  {
    term: "EPA per play",
    short: "expected points added, the standard efficiency measure",
    body: [
      "Every situation on a field — down, distance, field position, time — has an expected point value based on what historically happens next. EPA is how much a play changed that value. A 4-yard gain on 3rd-and-2 is a good play; the same 4 yards on 3rd-and-12 is not, and EPA reflects the difference where raw yardage does not.",
      "Figures here are opponent-adjusted, because a team that has faced four bottom-five defences will look better than it is. Offensive EPA above zero is above average; for a defence, below zero is better, since it is measuring what they allow.",
    ],
  },
  {
    term: "Success rate",
    short: "how often a play keeps the offence on schedule",
    body: [
      "A play counts as successful if it gains 40% of the yards needed on first down, 60% on second, or converts on third and fourth. It measures consistency rather than explosiveness.",
      "Read it alongside EPA. High success with low EPA is an offence that moves the chains without ever breaking one; the reverse is a team living on a few big plays, which is a less stable way to score.",
    ],
  },
  {
    term: "One-score record",
    short: "record in games decided by 8 points or fewer",
    body: [
      "Games inside a single score are close to coin flips — the winner is often decided by a bounce, a spot, or a kick. Nobody sustains a 7-1 record in them.",
      "So a team whose season rests on one-score wins is a regression candidate, and one that lost several is often better than its record. Both get priced slowly by a market that starts from the standings.",
    ],
  },
  {
    term: "Explosive rate",
    short: "share of plays gaining 15+ passing or 10+ rushing",
    body: [
      "Big plays drive scoring more than sustained drives do, and explosive rate is reasonably sticky year to year for offences — less so for defences, where preventing them is harder to repeat.",
    ],
  },
  {
    term: "Best bet vs lean",
    short: "how much the pick is worth acting on",
    body: [
      "Every game gets a side, because even a coin flip leans fractionally one way and that view is worth recording. What varies is conviction.",
      "A best bet clears the edge bar: the projection differs from the market by at least 2 points, or 3 when the numbers lean on prior-season data, or the number itself sits wrong against a key value. A lean is an opinion inside the noise — recorded, tracked, but not a recommendation to bet.",
      "The two records are kept separately. Best bets are what would actually have been staked; folding leans into the same number would measure picks nobody made.",
    ],
  },
  {
    term: "Key numbers",
    short: "3 and 7, where NFL margins pile up",
    body: [
      "NFL games are scored in 3s and 7s, so final margins cluster: roughly one game in seven lands on exactly 3, and one in seventeen on exactly 7.",
      "That makes half a point around those values worth far more than half a point anywhere else. Getting +3.5 instead of +2.5 buys the entire field-goal outcome; moving from 6.5 to 7.5 is a much smaller gain.",
    ],
  },
  {
    term: "Roster continuity",
    short: "how much of last season's team actually returned",
    body: [
      "Measured by snaps rather than headcount, because losing a 1,100-snap quarterback and losing a backup guard are not the same event.",
      "It matters most early in a season, when the efficiency figures still lean on prior-season data. A team returning 85% of its snaps is broadly the same team; one at 50% is not, and its old numbers describe a side that no longer exists.",
    ],
  },
];

export function GlossaryLink() {
  const ref = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <>
      <button className="glossary-link" onClick={() => setOpen(true)}>
        What do these numbers mean?
      </button>

      <dialog ref={ref} className="glossary" onClose={() => setOpen(false)}>
        <div className="glossary-head">
          <h2>Reading the numbers</h2>
          <button
            className="glossary-close"
            onClick={() => setOpen(false)}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="glossary-body">
          {TERMS.map((t) => (
            <section key={t.term}>
              <h3>
                {t.term}
                <span className="glossary-short">{t.short}</span>
              </h3>
              {t.body.map((p, i) => (
                <p key={i}>{p}</p>
              ))}
            </section>
          ))}
        </div>
      </dialog>
    </>
  );
}

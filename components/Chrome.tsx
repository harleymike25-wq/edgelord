import Link from "next/link";

import type { SeasonPayload } from "@/lib/types";

/** Neon wordmark on a black plate, with the tagline underneath. */
export function Logo() {
  return (
    <Link href="/" className="logo" aria-label="Edgelord — Beat the Edge, home">
      <h1 className="logo-word">Edgelord</h1>
      <p className="logo-tag">Beat the Edge</p>
    </Link>
  );
}

export function Masthead({ payload }: { payload: SeasonPayload }) {
  const when = new Date(payload.generated_at);
  return (
    <>
      <div className="masthead">
        <Logo />
        <nav className="masthead-nav">
          <Link href="/">Picks</Link>
          <Link href="/record">Record</Link>
          <Link href="/ratings">Ratings</Link>
        </nav>
      </div>
      <p className="generated">
        {payload.season} season · updated{" "}
        {when.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
      </p>
    </>
  );
}

/**
 * The dev snapshot contains placeholder paragraphs, not model output. Saying so
 * loudly is the whole point -- a fabricated write-up that reads like a real
 * prediction is worse than no dashboard at all.
 */
export function SyntheticBanner({ payload }: { payload: SeasonPayload }) {
  if (!payload.synthetic) return null;
  return (
    <div className="banner">
      <strong>Placeholder data.</strong> These picks and paragraphs are synthetic
      output from <code>scripts/seed_dev_snapshot.py</code>, generated so the layout
      could be built before any real predictions existed. Nothing here is a read on
      a game. Run <code>edgelord predict</code> then <code>edgelord sync</code> to
      replace it.
    </div>
  );
}

export function WeekNav({
  weeks,
  current,
}: {
  weeks: number[];
  current: number;
}) {
  if (weeks.length < 2) return null;
  return (
    <nav className="tabs">
      {weeks.map((w) => (
        <Link key={w} href={`/week/${w}`} className={w === current ? "on" : ""}>
          Wk {w}
        </Link>
      ))}
    </nav>
  );
}

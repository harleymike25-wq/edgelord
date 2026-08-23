import Link from "next/link";

import type { SeasonPayload } from "@/lib/types";

export function Masthead({ payload }: { payload: SeasonPayload }) {
  const when = new Date(payload.generated_at);
  return (
    <>
      <div className="masthead">
        <h1>
          <Link href="/">Edgelord</Link>
        </h1>
        <span className="season">{payload.season} season</span>
      </div>
      <p className="generated">
        Updated {when.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}
        {payload.source === "snapshot" ? " · local snapshot" : " · firestore"}
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

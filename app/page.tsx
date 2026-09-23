import { redirect } from "next/navigation";

import { Masthead, SyntheticBanner } from "@/components/Chrome";
import { lastLoadError, loadSeason, predictedWeeks } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function Home() {
  const payload = await loadSeason();
  if (!payload) return <NoData />;

  // The newest week that actually has picks, deliberately ignoring the
  // calendar. Resolving the live week by date was tried first and is worse in
  // the ordinary case: between Monday night and the next prediction run it
  // lands on a slate with no picks, an empty record strip and sixteen "not
  // picked yet" cards, which reads as a broken dashboard rather than as a
  // pending job. `predictedWeeks` is newest-first, so [0] is the latest.
  const week = predictedWeeks(payload.games)[0];
  if (week) redirect(`/week/${week}`);

  return (
    <>
      <Masthead payload={payload} />
      <SyntheticBanner payload={payload} />
      <div className="empty">
        <p>
          {payload.games.length} games loaded for {payload.season}, but no
          predictions stored yet.
        </p>
        <p>
          Run <code>edgelord predict --week 1</code> then <code>edgelord sync</code>.
        </p>
      </div>
    </>
  );
}

/**
 * Shows the actual reason, not just "no data".
 *
 * The cause is always an environment variable you cannot inspect from a
 * browser, so a blank page is close to undebuggable on a deployed site.
 */
function NoData() {
  return (
    <>
      <div className="masthead">
        <h1>Edgelord</h1>
      </div>
      <div className="empty">
        <p>No data loaded.</p>
        {lastLoadError && <p className="reason">{lastLoadError}</p>}
        <p className="hint">
          This site reads Firestore server-side. The only variable it needs is{" "}
          <code>FIREBASE_SERVICE_ACCOUNT</code>, set to the entire contents of
          your service-account JSON on one line — not a file path.
        </p>
      </div>
    </>
  );
}

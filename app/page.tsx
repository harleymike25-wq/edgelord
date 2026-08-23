import { redirect } from "next/navigation";

import { Masthead, SyntheticBanner } from "@/components/Chrome";
import { loadSeason, predictedWeeks } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function Home() {
  const payload = await loadSeason();
  if (!payload) return <NoData />;

  const weeks = predictedWeeks(payload.games);
  if (weeks.length) redirect(`/week/${weeks[0]}`);

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

function NoData() {
  return (
    <>
      <div className="masthead">
        <h1>Edgelord</h1>
      </div>
      <div className="empty">
        <p>No data available.</p>
        <p>
          Run <code>edgelord sync</code> to write a snapshot, or set{" "}
          <code>FIREBASE_SERVICE_ACCOUNT</code> to read from Firestore.
        </p>
      </div>
    </>
  );
}

import Link from "next/link";

import { Masthead, SyntheticBanner } from "@/components/Chrome";
import {
  ConfidenceTracking,
  EvidenceBadge,
  Strip,
  SummaryTable,
  UnitsTrend,
} from "@/components/Stats";
import { loadSeason } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function RecordPage() {
  const payload = await loadSeason();
  if (!payload) {
    return (
      <div className="empty">
        <p>No data available.</p>
      </div>
    );
  }

  const { record, weekly } = payload;
  const graded = record.overall.plays > 0;

  return (
    <>
      <Masthead payload={payload} />
      <Link href="/" className="back">
        ← Slate
      </Link>
      <SyntheticBanner payload={payload} />

      {/* Two records, deliberately separate. Best bets are what would actually
          have been staked; leans are recorded opinions. Averaging them into one
          number would flatter or punish the model for picks nobody made. */}
      <h3 className="section">Best bets — what it would have staked</h3>
      <Strip s={record.best_bets ?? record.overall} label="Best bets" />
      {payload.evidence && payload.evidence.plays_decided > 0 && (
        <EvidenceBadge e={payload.evidence} />
      )}

      <h3 className="section">Every pick, including leans</h3>
      <Strip s={record.overall} label="All picks" />

      {!graded && (
        <div className="empty">
          <p>Nothing graded yet.</p>
          <p>
            Picks appear in the record as soon as they are made; win-loss
            figures fill in once games finish and <code>edgelord grade</code>{" "}
            runs.
          </p>
        </div>
      )}

      {graded && (
        <>
          {weekly.length > 1 && (
            <>
              <h3 className="section">Cumulative units</h3>
              <UnitsTrend weekly={weekly} />
            </>
          )}

          <h3 className="section">By conviction</h3>
          <SummaryTable rows={record.by_conviction ?? {}} label="Conviction" />

          <h3 className="section">By market</h3>
          <SummaryTable rows={record.by_market} label="Market" />
        </>
      )}

      <h3 className="section">Confidence tracking</h3>
      <ConfidenceTracking
        buckets={record.by_confidence}
        discrimination={payload.evidence?.discrimination}
      />

      {graded && (
        <>
          <h3 className="section">On closing line value</h3>
          <p className="note">
            CLV is the gap between the number we took and where the market
            settled. Positive means we were consistently on the better side of the
            number, which is the most reliable early evidence of an edge — win
            rate over a 17-week sample is mostly noise. If average CLV sits at or
            below zero, the model is describing the market rather than beating it.
          </p>
        </>
      )}
    </>
  );
}

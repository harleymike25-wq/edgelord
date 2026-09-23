import { Masthead, SyntheticBanner } from "@/components/Chrome";
import {
  ConfidenceTracking,
  EvidenceBadge,
  RecordRow,
  SpreadRecord,
  SummaryTable,
  WeeklyRecord,
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

  const { record } = payload;
  const graded = record.overall.plays > 0;

  return (
    <>
      <Masthead payload={payload} />
      <SyntheticBanner payload={payload} />

      <RecordRow best={record.best_bets ?? record.overall} all={record.overall} />
      {payload.evidence && payload.evidence.plays_decided > 0 && (
        <EvidenceBadge e={payload.evidence} />
      )}

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
          <h3 className="section">By week</h3>
          <WeeklyRecord games={payload.games} />

          <h3 className="section">Spreads vs over/unders</h3>
          <SummaryTable rows={record.by_market} label="Bet type" />

          <h3 className="section">By spread</h3>
          <SpreadRecord games={payload.games} />

          <h3 className="section">Best bets vs leans</h3>
          <SummaryTable rows={record.by_conviction ?? {}} label="Conviction" />
        </>
      )}

      <h3 className="section">Confidence tracking</h3>
      <ConfidenceTracking
        buckets={record.by_confidence}
        discrimination={payload.evidence?.discrimination}
      />


    </>
  );
}

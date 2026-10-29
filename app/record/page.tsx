import { Masthead, SyntheticBanner } from "@/components/Chrome";
import {
  ConfidenceTracking,
  EdgeRecord,
  EvidenceBadge,
  FactorCorrections,
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

      <RecordRow tiers={record.by_conviction ?? {}} all={record.overall} />
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

          <h3 className="section">By edge</h3>
          <p className="note">
            How far the projection beat the line. A real edge should win more as
            it grows; a coin flip is the model saying the line is about right.
          </p>
          <EdgeRecord games={payload.games} />

          <h3 className="section">Spreads vs over/unders</h3>
          <SummaryTable rows={record.by_market} label="Bet type" />

          <h3 className="section">By spread</h3>
          <SpreadRecord games={payload.games} />

          <h3 className="section">Best bets, leans and coin flips</h3>
          <SummaryTable rows={record.by_conviction ?? {}} label="Conviction" />
        </>
      )}

      <h3 className="section">Confidence tracking</h3>
      <ConfidenceTracking
        buckets={record.by_confidence}
        discrimination={payload.evidence?.discrimination}
      />

      {payload.calibration && payload.calibration.n_games > 0 && (
        <>
          <h3 className="section">What the model has learned</h3>
          <p className="note">
            The model scores each factor in points and the points are added up into
            its margin. After each graded game, every factor gets a correction for how
            its points have actually tracked the final score. The corrections stay
            close to ×1 until there are enough games to back them.
          </p>
          <FactorCorrections c={payload.calibration} />
        </>
      )}


    </>
  );
}

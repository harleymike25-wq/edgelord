import { notFound } from "next/navigation";

import { WeekView } from "@/components/WeekView";
import { gamesForWeek, loadSeason } from "@/lib/data";

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
  if (!gamesForWeek(payload.games, n).length) notFound();

  return <WeekView payload={payload} week={n} />;
}

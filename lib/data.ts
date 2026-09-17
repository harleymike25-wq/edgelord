import "server-only";

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

import type {
  Evidence,
  Game,
  RecordBlock,
  SeasonPayload,
  WeeklyPoint,
} from "./types";

const SNAPSHOT_DIR = path.join(process.cwd(), "public", "data");

/**
 * Firestore is the production backend, the local JSON snapshot is the
 * development one. The snapshot is what `edgelord sync` writes, so the two
 * always carry the same shape and the UI never branches on which is in use.
 */
function firestoreConfigured(): boolean {
  return Boolean(process.env.FIREBASE_SERVICE_ACCOUNT);
}

async function firestore() {
  const admin = await import("firebase-admin");
  if (!admin.apps.length) {
    admin.initializeApp({
      credential: admin.credential.cert(
        JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT as string),
      ),
    });
  }
  return admin.firestore();
}

async function loadFromFirestore(season: number): Promise<SeasonPayload> {
  const dbc = await firestore();

  const [gameSnap, metaSnap] = await Promise.all([
    dbc.collection("games").where("season", "==", season).get(),
    dbc.collection("meta").doc(`record-${season}`).get(),
  ]);

  const games = gameSnap.docs.map((d: { data: () => unknown }) => d.data() as Game);
  games.sort(
    (a, b) =>
      a.week - b.week ||
      a.gameday.localeCompare(b.gameday) ||
      (a.gametime_et ?? "").localeCompare(b.gametime_et ?? ""),
  );

  const meta = metaSnap.data() as
    | {
        record: RecordBlock;
        weekly: WeeklyPoint[];
        generated_at: string;
        evidence?: Evidence;
      }
    | undefined;

  return {
    season,
    generated_at: meta?.generated_at ?? new Date().toISOString(),
    games,
    record: meta?.record ?? emptyRecord(),
    weekly: meta?.weekly ?? [],
    // Travels with the record: a win rate shown without its verdict is the one
    // combination this project exists to avoid.
    evidence: meta?.evidence,
    synthetic: false,
    source: "firestore",
  };
}

function emptyRecord(): RecordBlock {
  return {
    overall: {
      plays: 0, passes: 0, record: "0-0", win_pct: null,
      units: 0, roi: null, avg_clv: null, clv_positive_pct: null,
    },
    by_market: {},
    by_confidence: {},
  };
}

async function snapshotSeasons(): Promise<number[]> {
  try {
    const files = await readdir(SNAPSHOT_DIR);
    return files
      .filter((f) => /^season-\d+\.json$/.test(f))
      .map((f) => Number(f.replace(/\D/g, "")))
      .sort((a, b) => a - b);
  } catch {
    return [];
  }
}

async function loadFromSnapshot(season: number): Promise<SeasonPayload> {
  const raw = await readFile(path.join(SNAPSHOT_DIR, `season-${season}.json`), "utf-8");
  return { ...(JSON.parse(raw) as SeasonPayload), source: "snapshot" };
}

/**
 * Why the last load failed, for display.
 *
 * A deployed dashboard that renders "no data" without saying why is close to
 * useless to debug -- the cause is always in an environment variable you
 * cannot see from the browser. This carries the reason to the page.
 */
export let lastLoadError: string | null = null;

function describe(e: unknown): string {
  const msg = e instanceof Error ? e.message : String(e);
  if (/JSON|Unexpected token/i.test(msg)) {
    return `FIREBASE_SERVICE_ACCOUNT is set but is not valid JSON. Paste the whole service-account file contents on one line. (${msg})`;
  }
  if (/PERMISSION_DENIED|permission/i.test(msg)) {
    return `Firestore refused the credential. Check the service account belongs to this project and has Firestore access. (${msg})`;
  }
  if (/UNAUTHENTICATED|invalid_grant|credential/i.test(msg)) {
    return `Firestore rejected the credential -- it may be from a different project, or revoked. (${msg})`;
  }
  if (/Cannot find module|firebase-admin/i.test(msg)) {
    return `firebase-admin is not installed in the deploy. (${msg})`;
  }
  return msg;
}

export async function availableSeasons(): Promise<number[]> {
  if (firestoreConfigured()) {
    try {
      const dbc = await firestore();
      const snap = await dbc.collection("meta").get();
      const seasons = snap.docs
        .map((d: { id: string }) => Number(d.id.replace("record-", "")))
        .filter((n: number) => Number.isFinite(n))
        .sort((a: number, b: number) => a - b);
      if (seasons.length) return seasons;
      lastLoadError =
        "Connected to Firestore but the meta collection is empty. Run `edgelord sync`.";
    } catch (e) {
      lastLoadError = describe(e);
      return [];
    }
  } else {
    lastLoadError =
      "FIREBASE_SERVICE_ACCOUNT is not set, so the site fell back to the local JSON snapshot -- which is gitignored and therefore absent from this deploy. Set it in Site configuration > Environment variables to the contents of your service-account JSON.";
  }
  return snapshotSeasons();
}

export async function loadSeason(season?: number): Promise<SeasonPayload | null> {
  const seasons = await availableSeasons();
  if (!seasons.length) return null;

  const target = season && seasons.includes(season) ? season : seasons[seasons.length - 1];
  try {
    const payload = firestoreConfigured()
      ? await loadFromFirestore(target)
      : await loadFromSnapshot(target);
    lastLoadError = null;
    return payload;
  } catch (e) {
    lastLoadError = describe(e);
    return null;
  }
}

/** Weeks that actually have a stored prediction, newest first. */
export function predictedWeeks(games: Game[]): number[] {
  const weeks = new Set<number>();
  for (const g of games) if (g.prediction) weeks.add(g.week);
  return [...weeks].sort((a, b) => b - a);
}

/**
 * The live week, resolved from the schedule rather than the calendar: bye
 * structure and flexed games make date arithmetic unreliable.
 *
 * The two-day grace period matches `run_task.ps1`, and is what keeps Monday and
 * Tuesday on the week that just finished rather than jumping ahead to a slate
 * nobody has picked yet. Returns null once the season has no games left.
 */
export function currentWeek(games: Game[]): number | null {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 2);
  const since = cutoff.toISOString().slice(0, 10);

  let earliest: Game | null = null;
  for (const g of games) {
    if (g.gameday < since) continue;
    if (
      earliest === null ||
      g.gameday < earliest.gameday ||
      (g.gameday === earliest.gameday &&
        (g.gametime_et ?? "").localeCompare(earliest.gametime_et ?? "") < 0)
    ) {
      earliest = g;
    }
  }
  return earliest?.week ?? null;
}

export function gamesForWeek(games: Game[], week: number): Game[] {
  return games.filter((g) => g.week === week);
}

export function findGame(games: Game[], gameId: string): Game | undefined {
  return games.find((g) => g.game_id === gameId);
}

import type { Game, Prediction } from "./types";

/**
 * Render a spread in the notation a bettor reads.
 *
 * `line_at_pick` is stored as "this side is favoured by N", but sportsbooks
 * display the inverse: laying 7 shows as -7, getting 7 shows as +7. This
 * mirrors `_describe_pick` in edgelord/report.py -- the two must agree, or the
 * dashboard and the generated report will contradict each other.
 */
export function describePick(game: Game, p: Prediction | null): string {
  // "No play" is a decision the model made. A game it has not been asked about
  // yet has to say so instead, or an unpicked slate reads as sixteen passes.
  if (!p) return "Not picked yet";
  if (p.pick_type === "pass") return "No play";

  if (p.pick_type === "total") {
    const line = p.line_at_pick ?? game.closing_total;
    return line === null ? p.pick_side : `${titleCase(p.pick_side)} ${fmt(line)}`;
  }

  let line = p.line_at_pick;
  if (line === null && game.closing_spread_home !== null) {
    line =
      p.pick_side === game.home_team
        ? game.closing_spread_home
        : -game.closing_spread_home;
  }
  if (line === null) return p.pick_side;

  // Normalise -0 on a pick'em.
  const shown = line === 0 ? 0 : -line;
  return `${p.pick_side} ${signed(shown)}`;
}

export function signed(n: number): string {
  return `${n > 0 ? "+" : n < 0 ? "-" : "+"}${fmt(Math.abs(n))}`;
}

export function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : String(n);
}

export function titleCase(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function pct(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `${(n * 100).toFixed(1)}%`;
}

export function units(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}u`;
}

export function clv(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}`;
}

export function kickoff(game: Game): string {
  const day = game.weekday ?? "";
  const date = new Date(`${game.gameday}T12:00:00`);
  const nice = date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return [day, nice, game.gametime_et ? `${game.gametime_et} ET` : null]
    .filter(Boolean)
    .join(" · ");
}

export function finalScore(game: Game): string | null {
  if (!game.final) return null;
  return `${game.away_team} ${game.final.away} – ${game.home_team} ${game.final.home}`;
}

/** Confidence above this is rare and worth flagging in the UI. */
export const HIGH_CONFIDENCE = 65;

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

/**
 * The projection as a game result: who wins, by how much, and the score that
 * margin and total imply.
 *
 * `projected_margin` is the HOME margin (positive = home wins), the opposite
 * sign of a betting line. Printed as "PIT -3" beside the current line it read
 * as Pittsburgh laying 3 when it meant Pittsburgh losing by 3.
 */
export function projectedResult(game: Game, p: Prediction): string {
  const margin = p.projected_margin;
  const total = p.projected_total;
  const home = (total + margin) / 2;
  const away = (total - margin) / 2;
  const score =
    home >= away
      ? `${game.home_team} ${home.toFixed(1)}, ${game.away_team} ${away.toFixed(1)}`
      : `${game.away_team} ${away.toFixed(1)}, ${game.home_team} ${home.toFixed(1)}`;
  if (margin === 0) return `Pick'em · ${score}`;
  const winner = margin > 0 ? game.home_team : game.away_team;
  return `${winner} by ${fmt(Math.abs(margin))} · ${score}`;
}

/**
 * What the market itself predicts: who wins, by how much, and how likely, from
 * the spread and the moneylines with the vig taken out. Once the final is in,
 * `winner` and `outcome` say whether the market's favourite actually won --
 * a straight-up call, separate from whether it covered.
 *
 * `closing_spread_home` is positive when the home team is favoured. A zero
 * spread falls back to the moneyline to name a favourite.
 */
export function marketCall(game: Game): {
  favourite: string | null;
  margin: number;
  winProb: number | null;
  winner: string | null;
  outcome: "win" | "loss" | "push" | null;
} | null {
  const s = game.closing_spread_home;
  if (s === null || s === undefined) return null;
  const hp = impliedProb(game.home_moneyline);
  const ap = impliedProb(game.away_moneyline);
  const homeProb = hp !== null && ap !== null ? hp / (hp + ap) : null;

  const homeFav = s > 0 || (s === 0 && homeProb !== null && homeProb > 0.5);
  const awayFav = s < 0 || (s === 0 && homeProb !== null && homeProb < 0.5);
  const favourite = homeFav ? game.home_team : awayFav ? game.away_team : null;
  const winProb =
    homeProb === null || favourite === null ? null : homeFav ? homeProb : 1 - homeProb;

  let winner: string | null = null;
  let outcome: "win" | "loss" | "push" | null = null;
  if (game.final) {
    const margin = game.final.home - game.final.away;
    winner = margin > 0 ? game.home_team : margin < 0 ? game.away_team : null;
    if (favourite) outcome = winner === null ? "push" : winner === favourite ? "win" : "loss";
  }
  return { favourite, margin: Math.abs(s), winProb, winner, outcome };
}

function impliedProb(ml: number | null | undefined): number | null {
  if (ml === null || ml === undefined || ml === 0) return null;
  return ml < 0 ? -ml / (-ml + 100) : 100 / (ml + 100);
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

/**
 * Under a point off the line is a coin flip: the model is saying the line is
 * right and picking a side because every game gets one. Mirrors COIN_FLIP_EDGE
 * in bot/edgelord/predict.py, which sets the stored tier from 2026 Week 5.
 */
export const COIN_FLIP_EDGE = 1;

export function edge(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)} pts`;
}

/**
 * The edge with the side it belongs to: "+0.5 pts on LA", "+2.0 pts on the
 * under". The edge is always measured toward the pick, so a bare "+0.5" left
 * readers asking which team it was for.
 */
export function edgeOn(p: { edge?: number | null; pick_type: string; pick_side: string | null }): string {
  if (p.edge === null || p.edge === undefined || !p.pick_side) return "—";
  const side = p.pick_type === "total" ? `the ${p.pick_side}` : p.pick_side;
  return `${edge(p.edge)} on ${side}`;
}

export function isCoinFlip(n: number | null | undefined): boolean {
  return n !== null && n !== undefined && n < COIN_FLIP_EDGE;
}

/**
 * The over/under the projected total implies, alongside a spread pick.
 *
 * Display only: worked out here from the model's own total against the
 * current line, never stored, graded or counted in the record. Null when the
 * pick already is the total, or there is no line to compare against.
 */
export function totalLean(
  game: Game,
  p: Prediction | null,
): {
  side: "over" | "under" | null;
  line: number;
  projected: number;
  edge: number;
  /** Graded against the final score once there is one; null before then. */
  outcome: "win" | "loss" | "push" | null;
} | null {
  if (!p || p.pick_type === "total" || p.pick_type === "pass") return null;
  if (game.closing_total === null || p.projected_total === null || p.projected_total === undefined) {
    return null;
  }
  const diff = p.projected_total - game.closing_total;
  const side = diff > 0 ? "over" : diff < 0 ? "under" : null;
  return {
    side,
    line: game.closing_total,
    projected: p.projected_total,
    edge: Math.abs(diff),
    outcome: side && game.final ? gradeTotal(side, game.final.home + game.final.away, game.closing_total) : null,
  };
}

function gradeTotal(side: "over" | "under", actual: number, line: number): "win" | "loss" | "push" {
  if (actual === line) return "push";
  return (actual > line) === (side === "over") ? "win" : "loss";
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


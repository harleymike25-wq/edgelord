export type PickType = "spread" | "total" | "pass";
export type PickResult = "win" | "loss" | "push";

/** How much a pick is worth acting on. Every game gets a side. */
export type Conviction = "best_bet" | "lean" | "pass";

export interface Prediction {
  id: number;
  model: string;
  created_at: string;
  run_label: string;
  pick_type: PickType;
  pick_side: string;
  conviction: Conviction;
  /** Stored as "the picked side is favoured by N". Books display the inverse. */
  line_at_pick: number | null;
  price_at_pick: number | null;
  confidence: number;
  projected_margin: number;
  projected_total: number;
  /** One line, no statistics -- for scanning a slate. */
  headline?: string | null;
  /** Two or three short paragraphs separated by a blank line. */
  paragraph: string;
  key_factors: string[];
  data_gaps: string[];
}

export interface Result {
  pick_result: PickResult;
  profit_units: number;
  /** Positive means we held a better number than the market closed at. */
  clv_points: number | null;
  closing_line: number | null;
  closing_total: number | null;
}

export interface Game {
  game_id: string;
  season: number;
  week: number;
  game_type: string;
  gameday: string;
  weekday: string | null;
  gametime_et: string | null;
  home_team: string;
  away_team: string;
  stadium: string | null;
  roof: string | null;
  referee: string | null;
  divisional: boolean;
  home_coach: string | null;
  away_coach: string | null;
  closing_spread_home: number | null;
  closing_total: number | null;
  final: { home: number; away: number } | null;
  prediction: Prediction | null;
  result: Result | null;
}

export interface Summary {
  plays: number;
  passes: number;
  /** Live picks made but not yet graded. Only present on the overall summary. */
  pending?: number;
  record: string;
  win_pct: number | null;
  units: number;
  roi: number | null;
  avg_clv: number | null;
  clv_positive_pct: number | null;
}

export interface RecordBlock {
  /** The headline: only picks the model would actually have staked. */
  best_bets?: Summary;
  overall: Summary;
  by_conviction?: Record<string, Summary>;
  by_market: Record<string, Summary>;
  by_confidence: Record<string, Summary>;
}

export interface WeeklyPoint {
  week: number;
  avg_clv: number | null;
  units: number;
  plays: number;
}

export type Verdict =
  | "no signal yet"
  | "early, unproven"
  | "promising"
  | "established";

/** How much the record itself should be believed. */
export interface Evidence {
  verdict: Verdict;
  /** 0-100, dominated by sample size and closing line value. */
  score: number;
  plays_decided: number;
  record: string;
  win_pct: number | null;
  breakeven_pct: number;
  win_pct_95_interval: [number, number];
  p_value_vs_breakeven: number;
  plays_needed_for_confidence: number;
  units: number;
  clv: {
    plays: number;
    mean: number | null;
    positive_rate?: number;
    significant: boolean;
    z?: number;
  };
  discrimination: {
    measurable: boolean;
    informative?: boolean;
    low_half_win_pct?: number;
    high_half_win_pct?: number;
  };
  reasons: string[];
}

export interface SeasonPayload {
  season: number;
  generated_at: string;
  games: Game[];
  record: RecordBlock;
  weekly: WeeklyPoint[];
  evidence?: Evidence;
  /** True when the data is placeholder output from scripts/seed_dev_snapshot.py. */
  synthetic: boolean;
  /** Which backend served this payload. */
  source?: "firestore" | "snapshot";
}

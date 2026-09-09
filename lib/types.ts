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
  /** The model's own ledger of what it weighed, including what argued against it. */
  decision_table?: DecisionRow[];
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

/** One paired metric: an offence against what that defence allows. */
export interface UnitMetric {
  offense: number;
  defense_allows: number;
  league_avg: number;
  /** What this offence projects to do against this defence. */
  projected: number;
  /** Relative to league average. Positive favours the offence. */
  edge: number;
}

export interface UnitPairing {
  matchup: string;
  verdict?: string;
  epa_per_play?: UnitMetric;
  success_rate?: UnitMetric;
  explosive_rate?: UnitMetric;
  red_zone_td_pct?: UnitMetric;
  third_down_rate?: UnitMetric;
  pressure?: {
    defense_generates: number;
    offense_allows: number;
    /** Positive means the pass rush beats the protection. */
    edge_to_defense: number;
  };
  plays_per_game?: { offense: number; defense_faces: number };
}

export interface UnitRatings {
  units: UnitPairing[];
  biggest_mismatch: string | null;
  note?: string;
}

export interface H2HMeeting {
  season: number;
  week: number;
  at: string;
  score: string;
  spread_line: number | null;
  winner: string;
  covered: string;
  total: number | null;
  total_line: number | null;
}

export interface HeadToHead {
  meetings: number;
  recent: H2HMeeting[];
  [key: string]: unknown;
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
  /** Unit-vs-unit ratings lifted from the feature pack the pick was built on. */
  unit_ratings?: UnitRatings | null;
  head_to_head?: HeadToHead | null;
  /** Every input that moved the number, not just the ones the prose named. */
  factors?: Factors | null;
}

export interface DecisionRow {
  factor: string;
  reading: string;
  /** Team abbreviation this factor points to, or "neither". */
  favors: string;
  weight: "decisive" | "strong" | "moderate" | "slight" | "none";
}

export interface RosterMove {
  player: string;
  position: string | null;
  snap_pct_2025: number | null;
  side: "offense" | "defense";
  /** Departures carry where they went; arrivals carry where they came from. */
  now?: string | null;
  from?: string | null;
}

export interface RosterTurnover {
  offense_continuity: number | null;
  defense_continuity: number | null;
  overall_continuity: number | null;
  departures: RosterMove[];
  arrivals: RosterMove[];
  reading?: string | null;
}

export interface PriorSeasonRecord {
  wins: number;
  losses: number;
  ties: number;
  points_for: number;
  points_against: number;
  point_diff_per_game: number | null;
  win_pct: number | null;
  pythagorean_win_pct: number | null;
  pythagorean_delta: number | null;
  one_score_wins: number;
  one_score_losses: number;
  turnover_margin: number | null;
  own_fg_pct: number | null;
  opp_fg_pct: number | null;
}

export interface Weather {
  roof: string | null;
  indoor: boolean;
  source?: string | null;
  note?: string | null;
  temp_f?: number | null;
  wind_mph?: number | null;
  wind_gust_mph?: number | null;
  precip_probability_pct?: number | null;
  precip_inches?: number | null;
  humidity_pct?: number | null;
}

export interface SituationSide {
  rest_days: number | null;
  off_bye: boolean;
  short_week: boolean;
  travel_miles: number | null;
  timezone_shift_hours: number | null;
  altitude_change_ft: number | null;
  consecutive_road_games: number | null;
}

export interface Situation {
  kickoff_slot: string | null;
  is_primetime: boolean;
  neutral_site: boolean;
  divisional: boolean;
  venue: string | null;
  home: SituationSide;
  away: SituationSide;
}

export interface Factors {
  weather?: Weather | null;
  situation?: Situation | null;
  home?: {
    roster_turnover?: RosterTurnover | null;
    prior_season_record?: PriorSeasonRecord | null;
  } | null;
  away?: {
    roster_turnover?: RosterTurnover | null;
    prior_season_record?: PriorSeasonRecord | null;
  } | null;
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

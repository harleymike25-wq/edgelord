# What has actually been run

Everything in this repo was written by an AI agent across one session. The bot
grades its own picks; this file grades the build. It exists because "I wrote it
and it typechecks" is not the same claim as "I ran it and watched it work,"
and only one of those is worth anything at 11am on a Sunday.

Keep it honest. Move a row up only after the thing has actually executed.

Last updated: 2026-09-17

---

## Verified — executed and output inspected

| Thing | Evidence |
|---|---|
| nflverse backfill | 570 games, 98,263 pbp rows, 2 seasons, 0 nulls on referee/spread |
| Efficiency engine | 32 teams, 0 nulls, values in plausible ranges (EPA, success, explosive, pressure) |
| Regression indicators | League-wide wins summed to 271 across 272 games + 1 tie |
| Feature pack build | 11.7 KB pack for a real game, all blocks populated, 2 expected data gaps |
| Result-leak fix | `final_score` and `home_score` confirmed absent from the default pack |
| Grading maths | Unit tests: spread/total/push/CLV in both directions |
| Spend guard logic | Unit-tested: ceiling blocks, month rollover, unknown model bills at Opus not free |
| Key-number re-predict filter | Unit-tested against a synthetic snapshot series |
| Preseason isolation | Unit-tested: orphan snapshots cannot reach the record |
| Evidence / confidence scoring | Unit-tested; a 59.5% record over 74 plays correctly scores 1.3/100 |
| Dashboard render | Server returns 200, record strip at top, verdict badge below, 0 console errors |
| Firestore sync (local path) | Writes `public/data/season-2025.json`, correct shape |
| **Fable 5 request path** | 2026-08-17: live calls on `claude-fable-5` via `beta.messages.create` with `fallbacks`. Well-formed structured responses; returned both a `pass` and a `spread` pick. |
| **Spend recording** | 2 calls: 15,943 in / 2,013 out / $0.26 written to `api_usage`; `edgelord spend` reports 1% of ceiling. |
| **Backtest isolation** | 2026-09-17: was overstated — see "Backtests were reaching the record" below. Now genuinely verified: `record` and `_clv_series` both exclude `run_label = 'backtest'`, pinned by regression tests. All-seasons record reads 6-9-1, the same as 2026 alone. |
| **Dedicated API key + workspace** | 2026-08-17: key distinct from the sibling project's (SHA differs), scoped to `wrkspc_01JXFyJAfmMGrAQPPpd7zM1u` rather than Default, so a console spend cap is available. |
| **2026 schedule loaded** | 272 games, Week 1 spreads present, 112 games with a line. |
| **Free line snapshots** | 2026-08-18: `snapshot-lines` wrote 112 rows, then correctly wrote 0 on re-run (dedup). `poll-odds` falls back to it cleanly with no key. Market block reports `available: True` with opener, current and key-number context. |
| **Firestore push and read-back** | 2026-08-18: project `edgelord-4c9ec`, 285 game docs + meta written, read back by document id with correct scores. Dashboard reports source `firestore`, zero console errors. |
| **Pick quality spot-check** | NYJ +14 vs BAL: projected a 10-point Baltimore win, actual was 13 (BAL 23-10), so the pick covered by half a point. Reasoning cited the 5-5 record and +1 point differential behind a two-touchdown price. |
| **`.env` BOM handling** | PowerShell `-Encoding utf8` writes a BOM; dotenv then reads the first key as `﻿NAME`. Fixed by writing without BOM. Bit only when the key was line 1. |
| **Refresh → grade on real results** | 2026-09-17: `refresh` took 2026 from 2 scored games to 16, then `grade` wrote 79 results. First time the chain has run on games that actually finished rather than on fixtures. |
| **A real running record** | 2026-09-17: **6-9-1, -3.55 units, ROI -0.236, avg CLV +0.09** over Week 1. Best bets 1-1. Before the refresh the dashboard read 0-1-1 off a single graded game, which looked like no data rather than a losing week. |
| **Post-mortem arithmetic** | 30 unit tests: both spread directions, over and under, severity bands at every boundary, the decision-table split, and `contradicted_own_projection` including the zero-edge case. Full suite 200 passing. |
| **Post-mortem model pass** | 2026-09-17: 10 live `postmortem` calls on Fable 5, $0.60 total, all 9 losses carry a narrative. 2 calls failed transiently and succeeded on re-run; the arithmetic had already stored, so nothing was lost. |
| **Post-mortem verdict calibration** | 8 `thesis_wrong`, 1 `thesis_right_variance`. The variance verdict went to the 2.5-point near-miss; the blowouts all read as reasoning failures. Spot-checked against the misses rather than taken on trust. |
| **Post-mortem on the dashboard** | 2026-09-17: panel renders on `/game/2026_01_DAL_NYG` with the no-edge warning, and on `/game/2026_01_TB_CIN` in the neutral grey variance treatment. `tsc --noEmit` clean, 0 console errors. |
| **Landing on the live week** | 2026-09-17: `/` resolves Week 2 by date and redirects there on both the Firestore and snapshot backends; nav reads `Wk 2` (current) then `Wk 1`. `_live_week` unit-tested at the two-day boundary, on a same-day kickoff tie, at season end and across seasons — it has to agree with `run_task.ps1` or the two disagree about which week is live on a Monday. |
| **An unpicked week reads as unpicked** | 2026-09-17: Week 3 renders 16 cards saying "Not picked yet" on a dashed badge, under "Week 3 — 0 plays, 0 passes, 16 games". Every one previously said "No play", which is the model's word for a deliberate pass, so an unrun job looked like sixteen decisions. Full suite 206 passing. |

## Ran exactly once, on a model we are no longer using

| Thing | Caveat |
|---|---|
| Live Claude call on Opus 4.8 | Superseded — the Fable 5 path is now the verified one. Kept as a note that Opus also works if the model is switched back. |

## Measured cost (recalibrated 2026-08-17)

Two real Fable 5 calls at `effort=medium`: **15,943 input / 2,013 output = $0.26**,
averaging **$0.13 per game**. Earlier estimates assumed ~4k input; the real pack
plus system prompt is closer to 8k, so per-game cost is roughly double what was
originally projected.

- Sunday slate, 16 games: **~$2.27**
- Midweek with `--only-moved` (~4 games, twice): **~$1.13**
- Per week **~$3.40**, per month **~$15**, regular season **~$61**

That sits inside the $25/month ceiling with headroom, but not by much. If
`--only-moved` were removed and all three weekly runs did the full slate, the
month would be ~$29 and the guard would start cutting runs short.

## NOT VERIFIED — written, typechecks, never executed

These are where a Sunday morning failure will come from.

| Thing | Why it is unverified | First command that would prove it |
|---|---|---|
| **Refusal fallback** | Requires an actual classifier refusal to exercise; the one live call was not refused. May never fire. | (opportunistic — look for a two-model row in `api_usage`) |
| **`usage.iterations` parsing** | Written defensively against the fallback billing shape. The one live call had no fallback, so the branch that sums iterations is still unexercised. | a live `predict` that actually gets refused |
| **The Odds API** | Deliberately not used — the free nflverse line is the source instead. The client, sign convention and team mapping remain unexercised against the live API and should be treated as unverified if a key is ever added. | `edgelord poll-odds --dry-run` |
| **Netlify deploy** | `netlify.toml` written, never deployed. `FIREBASE_SERVICE_ACCOUNT` must be set in the Netlify UI or the site falls back to a gitignored snapshot and renders blank. | push to git, connect the repo in Netlify |
| **Scheduled tasks** | Never registered, never fired. | `register_tasks.ps1` then `Start-ScheduledTask` |
| **Weather forecast API** | Open-Meteo needs a game within 16 days; the 2026 season had not started. | any Week 1 feature build |
| **Line movement across a real week** | 112 snapshots stored, but all from one moment. The movement path is unit-tested; it has not yet watched a number actually move. | wait for nflverse to update a 2026 line, then `snapshot-lines` again |

## Bugs found and fixed

**Backtests were reaching the record (2026-09-17).**
The isolation that was verified in August was the *superseding* rule: a backtest
never replaces a live prediction. But `grade` scores backtests deliberately —
that is how a replay gets evaluated — and `track.record` filtered only on
`superseded_by IS NULL`, so every graded replay was counted as money at risk.
`sync._clv_series` had the same gap, which meant the trend chart was drawn from
the same contaminated set. The all-seasons record read 3-2-1 off four backtest
predictions of games that had already finished; it now reads 6-9-1, matching
2026 alone, and 2025 correctly reads 0-0. No error was ever raised — a backtest
that happened to pick well would simply have inflated the published record.
Both queries now exclude `run_label = 'backtest'`, pinned by regression tests in
`tests/test_postmortem.py`.

**The live week would have 404'd the deployed dashboard (2026-09-17).**
The Firestore mirror skips games with neither a prediction nor a result, so the
schedule beyond the last predicted week is simply absent — 32 documents out of a
272-game season. That was fine while the homepage redirected to the newest
*predicted* week, and broke the moment it started landing on the live week by
date: every Tuesday, once Week N finished and before the Sunday job predicted
Week N+1, `/` would have redirected to a week Firestore had never heard of and
the site would have 404'd. Locally it was invisible, because the JSON snapshot
carries all 272 games and is what development reads. `sync` now mirrors the live
week even when nothing has been picked in it — the one exception to the filter,
at a cost of at most 16 documents.

**A blank environment variable shadowed a valid key (2026-09-17).**
`ANTHROPIC_API_KEY` was present and correct in `bot/.env`, and the bot still
reported it missing. The surrounding shell exported it as an empty string, and
`load_dotenv` will not override a variable that already exists — so the blank
ambient value won and the file was never consulted. Same family as the BOM bug
below: the key was right there and the loader could not see it. `config.py` now
drops blank values for the three secret variables before loading `.env`, so the
file can fill them while a genuinely set variable still takes precedence.

**Roster continuity join was wrong three separate ways (2026-08-23).**
All three produced plausible-looking numbers rather than errors, which is the
dangerous kind. (1) Rosters spell Arizona `AZ` and snap counts spell it `ARI`,
so the team was silently dropped and reported 0.0 continuity with no
departures. (2) The join used roster `pfr_id`, which is ~34% null, so any
returning player without a Pro Football Reference page counted as departed and
every team's continuity was understated -- now routed through the players
crosswalk to `gsis_id`, which is fully populated. (3) A player's "notable"
threshold was measured against the *sum* of all roster snaps (~12,000), where a
full-time starter scores 0.08 and never crosses a 0.35 bar -- Miami showed no
departures despite having the most turnover in the league. Now uses
`offense_pct`, the player's share of team plays. Regression tests in
`tests/test_roster.py` pin all three.

**Depth charts silently returned empty (2026-08-23).**
`load_depth_charts` has no `season` column, but the shared cache loader filters
every dataset by one. The exception was swallowed by a defensive `except` and
the feature degraded to no depth chart at all. Given its own loader.

**Neutral-site venues resolved to the wrong stadium (2026-08-17).**
nflverse gives international games the *nominal home team's* `stadium_id` and
`roof`, not the actual venue's. The 2026 Melbourne game carries `LAX01` (SoFi
Stadium, Los Angeles) and the Rio game carries `DAL00` (AT&T Stadium, Texas).
Resolving by id produced a ~350-mile intra-California trip with zero time-zone
change for a flight to Australia, and skipped the weather forecast on three
open-air stadiums because the home team's roof said "dome". Eight games in 2026
were affected, and they are precisely the games where travel is the largest
factor in the pack. No error was raised — the numbers were simply wrong.

Fixed by resolving neutral sites on stadium *name* (accent- and
punctuation-folded) with an explicit per-venue `roof`. Verified: SF→Melbourne
now reads 7,873 miles and a 17-hour shift; all eight venues resolve; roof
overrides correct on all eight. Regression tests in
`tests/test_neutral_site_venues.py`.

**Backfill crashed on a future season (2026-08-17).**
`load_pbp([2024, 2025, 2026])` raised because 2026 play-by-play does not exist
yet, taking down the whole pull including the datasets that *were* available.
Now falls back to per-season fetches and reports what was skipped.

**Evidence block dropped on the way to Firestore (2026-08-18).**
`build_payload` included the verdict, but the Firestore meta document was
written with only `season`, `generated_at`, `record` and `weekly`. The local
snapshot therefore showed the verdict badge and the deployed site would not --
a win rate displayed with no sample-size caveat, which is the one combination
this project exists to avoid. Caught by reading the document back rather than
trusting the write. Fixed in `sync.py` and `lib/data.ts`; re-verified by
round-trip.

**`.env` UTF-8 BOM (2026-08-17).**
PowerShell `-Encoding utf8` writes a BOM; dotenv then reads the first key as
`﻿NAME` and reports it missing. Only bites when the key is on line 1.

## Known-wrong things the agent said during the build

Kept as a calibration record, not as self-flagellation.

- Claimed the record-at-top UI change was half-finished and had broken the
  build. It was complete. The failure was asserted without checking.
- Built the feature pack with `final_score` included — a result leak that would
  have invalidated every backtest. Caught, but only after it was written.
- Asserted an output/input cost ratio of >4x in a test; the real figure is 3.4x.
- Copied an API key from a sibling project, then raised the "you may want
  separate keys" caveat afterwards rather than before.
- Reviewed the DAL/NYG loss, read a stored line of `3.0` as "getting the field
  goal", and returned `thesis_right_variance` for a pick whose own projected
  edge was **-3.5**. It repeated the write-up's sign error instead of catching
  it, which is the one job a post-mortem has. Fixed by computing
  `contradicted_own_projection` rather than leaving the signs to be read, and by
  making that verdict unavailable when the flag is true — the check now does not
  depend on the reviewer getting the arithmetic right.

## What the losses actually showed (2026-09-17, Week 1)

Recorded here because it is the substance of the post-mortems, and a pattern
across nine losses is worth more than any single one of them.

Eight of the nine were the same shape: take the underdog and the points, argued
from prior-season efficiency and regression indicators, with a thin claimed edge
of +1.5 to +5.0. The projections were then off by 12 to 25 points. That is not
nine independent misses — it is one thesis applied nine times, and the sample is
far too small to tell a broken thesis from a bad week.

Two specific failures are not variance and do not need a larger sample:

- **DAL/NYG** — the write-up argued for a side "plus the field goal" that was
  laying three. The pick had a -3.5 edge by its own projection and could not
  have been correct even had it cashed.
- **Week 1 priors** — every loss leaned on 2025 efficiency for games played
  with substantially changed rosters, while the market had already priced the
  change. Several decision tables say so explicitly in the row that got
  outvoted.

Per the brief, none of this is fed back into the prediction prompt. Nine losses
teach noise far more readily than signal, and the system prompt already warns
that a single game carries roughly 13 points of standard error. The post-mortems
are stored and displayed so a human can see the pattern; they do not steer the
next pick.

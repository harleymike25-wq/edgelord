# What has actually been run

Everything in this repo was written by an AI agent across one session. The bot
grades its own picks; this file grades the build. It exists because "I wrote it
and it typechecks" is not the same claim as "I ran it and watched it work,"
and only one of those is worth anything at 11am on a Sunday.

Keep it honest. Move a row up only after the thing has actually executed.

Last updated: 2026-10-01

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
| **Week 2 graded, the first anchored week** | 2026-09-23: `refresh` took 2026 to 32 final scores, `grade` wrote 48 rows. Week 2 **10-6-0, +3.09 units** against Week 1's 6-9-1, -3.55. Season 16-15-1, -0.45 units. The first total pick of the year (LV/LAC under 43.5) won. Sixteen games, so the record is not evidence — the loss arithmetic below is. |
| **Week 2 post-mortems** | 2026-09-23: 6 losses, 6 explained, 0 failed, $0.37. Verdicts went 4 `thesis_right_variance` / 1 `bad_input` / 1 `thesis_wrong`, near-inverting Week 1's 8 `thesis_wrong` / 1 variance — and the computed misses moved with them (mean 16.3 → 9.3, median 17.5 → 8.2), so the softer verdicts are backed by arithmetic rather than self-flattery. |
| **Week 3 graded** | 2026-10-01: `refresh` took 2026 to 48 final scores, `grade` scored Week 3 at **9-7-0, +1.18 units**. Season **25-22-1, +0.73 units, ROI +0.015, avg CLV -0.04**; spreads 24-22-1, totals 1-0. Synced to Firestore (64 game docs + record). Miss arithmetic computed for all 7 losses with `--no-model` ($0); every one carried a claimed edge of about +0.5 points, so they were leans, not convictions. **Narratives not yet written** -- the model pass is pending. |
| **Week 4 graded, Week 5 picked** | 2026-10-08: `refresh` took 2026 to 64 final scores; season now **35-26-3, +5.82 units, ROI +0.095, avg CLV -0.05**, so Week 4 went **10-4-2, +5.09 units**. Week 5: 15 picks (14 spreads, 1 total, MIN/NO under 41.5), 2 computed best bets (LV +3.5, TEN +7.5), $1.69 on Opus 5.5. Report rendered, 79 game docs synced to Firestore. Week 4 post-mortems not yet run. |
| **Officiating cut from the pack (from 2026 Week 3)** | 2026-09-23: the `officiating` block was **null in all 32 live packs** (the crew is announced after picks are made), yet 29 decision tables spent a row on it at weight "none". Removed from the pack and the prompt; the referee gap line goes with it. Saves close to nothing on input, since the block was already empty; the gain is a cleaner decision table. Suite passing. |
| **Pre-registered signal search** | 2026-09-23: `scripts/signal_search.py`, 25 rules committed (3eeac57) before any was scored. Discovery 2016–2021: 3 through the gate, about the 2.5 expected from 25 tries by chance alone. Holdout 2022–2025, looked at once: **all 3 failed**. No model calls. |
| **Regression demoted in the prompt (from 2026 Week 3)** | 2026-09-23: the system prompt no longer calls the regression indicators "the most reliable edge in the pack". It now says the line prices them, caps them at "slight" unless the write-up can say why this line has not, and forbids fading a team on last season's luck alone. The worked example of a strong thesis was itself a turnover-luck fade and is replaced with an injury-driven one. Principle only, no statistic, per the no-feedback rule. Suite 253 passing. **Not yet run on a live slate** -- Sunday's Week 3 job is the first. |
| **The luck/regression thesis, backtested** | 2026-09-23: `scripts/backtest_regression_thesis.py`, the bot's own `regression.records` definitions, 2,576 regular-season games 2016–2025 against closing lines, pre-kickoff data only. Fading the Pythagorean overachiever went **1258-1253 (50.1%)** with no threshold; no gap threshold clears 50%, let alone the 52.4% break-even. No model calls. |
| **Power ratings, replayed over 2022–2025** | 2026-09-23: `edgelord ratings` fits a margin-based rating from nflverse final scores, walk-forward, no model calls. Tuned on 2017–2021 (optimum inside the grid), judged on 1,087 untouched games: **RMSE 12.90 vs the closing line's 12.36**, weight earned next to the line **−0.18 ± 0.12**, ATS taking its side **508-547-29, −85.2u**. It does not beat the market. 10 unit tests pin the sign convention and that no projection is fitted on its own result; full suite 253 passing. `/ratings` renders at desktop and 375px with 0 console errors. |
| **Best bets computed, not self-rated (from 2026 Week 3)** | 2026-09-23: `conviction` is now set by `predict.computed_conviction` from the move off the line: 2+ points, 3+ while the prior season carries half the efficiency weight or continuity is under 0.7, or 1+ point that carries the number through 3 or 7. The model's own rating is kept in `model_conviction`. Weeks 1–2 are untouched. The prompt is unchanged, so the picks themselves are not affected. 16 unit tests on sign and key numbers; full suite 243 passing. Not yet run on a live slate. |
| **Anchored projection, A/B'd on Week 1** | 2026-09-17: 16 live backtest calls, $4.11. The model is now asked for a move off the line rather than a margin from scratch. Winner agreement with the market went 69% → **100%**, mean move off the line **2.03 → 1.16**. Measured against the live pre-change picks on the same 16 games, not asserted — see "The underdog tilt" below for what it did *not* fix. Full suite 228 passing. |

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

## The underdog tilt: measured, half-fixed (2026-09-17)

Across all 32 live 2026 spread picks the bot took the points **25 times (78%)**
and never laid more than 6.5. The cause was not a preference for dogs. It was
the output format: the model was asked for a margin from scratch, a from-scratch
margin regresses toward a pick'em, and a projection nearer zero than the spread
argues for the underdog in *every* game it touches — so the side was being
chosen by the shrinkage rather than by the factors. The projection sat closer to
zero than the spread in **27 of 32** picks, and claimed edge split **+2.40 on
dogs vs +0.29 on favourites**, which is the shrinkage showing up as "value".

The fix asks for `market_adjustment` — how far the model moves the number —
instead of the margin. Week 1 was then re-run under the new format and compared
against the live pre-change picks on the same 16 games:

| | free-floating | anchored | market |
|---|---|---|---|
| agrees with the market on the winner | 11/16 | **16/16** | — |
| mean move off the line | 2.03 | **1.16** | — |
| projection nearer zero than the spread | 13/16 | 11/16 | — |
| took the dog | 11/16 | 11/16 | — |
| MAE vs actual | 11.75 | 11.25 | 11.28 |
| RMSE vs actual | 14.28 | 13.69 | 13.47 |

What actually improved is the top two rows, and only those should be believed.
They are properties of the format on a fixed set of games: the projection no
longer wanders across zero from the market's favourite, and the average claimed
edge halved. The accuracy rows moved the right way but by well under a point on
sixteen games, which is noise — the same standard error the system prompt warns
the model about applies to the agent evaluating it.

Graded head to head on the same sixteen games, the anchored picks go **8-7-1,
+0.27 units** against the live **6-9-1, -3.55 units**. That number should be
treated as almost meaningless: **14 of the 16 picks are identical**, and the
entire difference is two flips (DAL/NYG and DEN/KC) that both happened to land.
Had they gone the other way the identical change would read 4-11-1. Quoted here
only because it will otherwise be misremembered as "the fix turned a losing week
around".

The one non-random piece of it: DAL/NYG is the pick whose write-up argued for a
side "plus the field goal" while laying three, with a -3.5 edge by its own
projection. Anchoring flipped it — not by predicting the Giants, but because a
move stated off the line cannot silently contradict the side it names. That
failure mode is now structurally unavailable.

**On Week 2 the dog rate did move, a lot.** The live slate was re-predicted
under the anchored format on 2026-09-17, replacing 16 free-floating picks made
by that morning's scheduled job:

| | free-floating | anchored |
|---|---|---|
| took the points | **14/16 (88%)** | **7/15 (47%)** |
| projection nearer zero than the spread | 14/16 | 7/15 |
| mean move off the line | 2.25 | 1.20 |

Seven of sixteen picks changed side and one left the spread market entirely
(LV/LAC became a total, the first total pick of 2026). Same games, same feature
packs, same day — the output format is the only variable, which makes this a
paired measurement of the change rather than an outcome that two lucky games
could flip. It says nothing about whether the picks are *better*.

**On the Week 1 backtest the dog rate did not move at all.** Eleven of sixteen adjustments still point
away from the favourite, and the model returned an adjustment of **0 exactly
zero times** despite the prompt saying 0 should be common. Anchoring made the
tilt smaller and made it something the write-up has to argue for; it did not
remove it on that slate. The next lever, if the tilt returns over more weeks, is
a computed guardrail that refuses conviction to edge which exists only because
`|projection| < |spread|`.

Across both weeks — 31 anchored spread picks — the model has returned an
adjustment of exactly **0 zero times**, despite the prompt saying 0 should be a
common answer. Whatever else anchoring fixed, it did not buy the ability to
agree with the market outright.

### What Week 2 actually settled, and what it did not

Graded on 2026-09-23. Week 2 went **10-6, +3.09 units** — the first winning week,
and also the first fully anchored one. That pairing is exactly the coincidence
this file exists to resist: it is sixteen games, and a 10-6 is one bounce away
from a 6-10. It is not evidence.

What *is* evidence, because it is measured rather than won:

- **Losing projections are landing half as far off.** Mean miss on a losing
  spread pick went 16.3 → 9.3, median 17.5 → 8.2. The post-mortem verdicts
  flipped from 8-of-9 `thesis_wrong` to 4-of-6 `thesis_right_variance`, and that
  shift is backed by the arithmetic rather than by the model being kinder to
  itself.
- **The dog tilt corrected** (88% → 47%, above).

And the number that got worse, or at least did not get better:

- **CLV is unmeasured, not bad.** *(Corrected 2026-09-23; this row previously
  read "CLV is bad… only 15.6% of picks beat the closing line".)* The 15.6% is
  5 of 32, but **24 of the 32 have CLV of exactly 0** and only 3 are negative:
  among the eight picks where the number moved at all, 5 beat the close and 3
  did not. The "close" is nflverse's `spread_line`, the same source as the line
  at pick, updated sporadically; Week 1 picks were made at 11:40 on the Sunday
  and had no time to see a move. `price_at_pick` is null on every row, so every
  result assumes -110. Until a second line source exists, CLV here says almost
  nothing in either direction and should not be quoted as a signal.

None of this reached the prompt as a statistic. The argument in the system
prompt is that shrinkage manufactures dog edge, which is true a priori; the
Week 1 numbers are the test of the change, not an input to it.

## Best bets move out of the model's hands (2026-09-23)

The prompt already set the best-bet bar at a 2-point move (3 on thin
evidence). The model did not apply it: Week 2 had seven picks moving the number
2+ points and rated none of them best_bet, so every game on the card was a
"lean" and the headline record had nothing to count. Rating a pick is
arithmetic on numbers the model has already committed to, so it is now done in
code; the model still picks every game.

Replayed on the 32 stored live picks before the change, the move off the line
said **nothing** about results: moves under 1 point went 4-0, 1 to 1.5 went
3-4-1, 1.5 to 2.5 went 6-7, 2.5+ went 2-3. That is noise on 32 games in both
directions, and it is why the computed tier is a test rather than a claim. If
the best bets do not beat the leans over the season, the moves are not edges.

## A computed rating does not beat the line either (2026-09-23)

The LLM's number was measured slightly worse than the market, so the obvious
next question was whether a plain arithmetic rating does better. It does not,
and on a sample large enough to mean it.

`edgelord/ratings.py` fits team ratings from final margins (capped, last season
at reduced weight, pulled toward average) and projects each week only from the
weeks before it. Settings were chosen on 2017–2021 by accuracy against the
final margin, not by ATS record, and then left alone. On 2022–2025, 1,087
regular-season games it had never seen:

| | rating | closing line |
|---|---|---|
| RMSE vs final margin | 12.90 | **12.36** |
| MAE vs final margin | 9.98 | **9.49** |

Regressing the line's miss on the rating's disagreement gives a weight of
**−0.18 (se 0.12)**: the rating carries nothing the line has not already
priced. Betting its side every week went 508-547-29 (48.1%), and restricting
to bigger disagreements does not help: 2+ points 47.9%, 3+ 46.6%, 4+ 49.2%.
None clears the 52.4% break-even.

One by-product answers an earlier question. The rating took the **underdog in
67%** of games where it disagreed with the line, with no LLM anywhere in it.
Any rating pulled toward average projects closer to a pick'em than the market
does, and a projection closer to zero than the spread always points at the dog.
So the dog lean on big spreads is what shrinkage looks like, not a read on
those games, and the market being right to be more extreme is exactly why
fading it loses.

What this does not rule out is an edge from information the scores do not
carry: better prices across books, late injury news, weather, totals. It does
rule out "compute a better number from public results" as the source.

## The bot's main argument does not cover (2026-09-23)

Luck/regression is the heaviest-weighted factor in the model's own decision
tables (average 2.27 of 4) and the most one-sided: it pointed at the picked
side 22 times to 8. "This team's record outruns its points, fade it" is the
thesis behind most picks, including eight of Week 1's nine losses. So it was
tested on its own, with the bot's own definitions, on every regular-season
game from 2016 to 2025 against the closing line:

| Fade the luckier side when the Pythagorean gap is at least | games | record | win % |
|---|---|---|---|
| any | 2,511 | 1258-1253 | 50.1% |
| 0.10 | 1,350 | 661-689 | 49.0% |
| 0.20 | 519 | 243-276 | 46.8% |
| 0.30 | 163 | 78-85 | 47.9% |

Fading the better one-score record is no better (49.2% overall, 45.3% at the
widest gap), and the picture is the same in 2016–2020 and 2021–2025 separately.
The market prices regression. A bigger gap does not make a better bet; if
anything the fade gets slightly worse, though no row except the one below is
more than 1.7 standard errors from a coin flip.

The one row that stands out is the Week 1 situation exactly: in Weeks 1–4,
fading on **last season's** luck at a gap of 0.20 or more went **25-47
(34.7%, z −2.6)**, and the win rate falls steadily as the gap widens (49.5,
47.5, 47.4, 42.9, 34.7). That is 72 games and one of about twenty rows tested,
so it is suggestive rather than proven. But it points the same way as the Week 1
post-mortems: leaning on last year's luck early in the season has actively
cost money, probably because the line has already regressed those teams and
then some.

Per the no-feedback rule this is not written into the prompt as a statistic.
Whether to weight the factor down is a design decision, like anchoring was.

## Nothing computable survives a holdout (2026-09-23)

Asked whether the weights could be tuned until the record reached 60%: any search
wide enough will find 60% in-sample, so the search was run the way that can be
believed. Twenty-five rules (situational spots, rest, travel, key numbers,
streaks, the power rating, weather and totals) were written down and committed
before any was scored, with a fixed gate and a single look at held-out seasons.

Discovery, 2016–2021 — three rules through the gate (50+ bets, at or above
52.4%, one-sided p < 0.10):

| rule | discovery | holdout 2022–2025 |
|---|---|---|
| back a team that lost its last game by 20+ | 129-101, 56.1% | **82-84, 49.4%** |
| underdogs in Weeks 1–4 | 208-167, 55.5% | **130-117, 52.6%** (p 0.20) |
| under at 32°F or below | 32-21, 60.4% | **21-26, 44.7%** |

Three passes from twenty-five tries at p < 0.10 is what chance alone produces
(about 2.5), and not one survived the Holm correction even in discovery. All
three failed the holdout. The early-season underdog rule came nearest — 54.3%
over the decade — but it missed its pre-set bar and cannot be claimed; it is
also the one spot where the bot's own 2026 Week 1 dog-heavy card went 6-9-1.

The temptation this file exists to resist is visible in the table: road teams
that crossed two or more time zones covered 54.4% in discovery, which looks
like a finding. It was registered in the other direction, and flipping it after
seeing the result is exactly the move that produces a 60% backtest and a 50%
season.

Across this session four independent tests — the LLM's number, a computed
rating, the regression thesis, and this search — agree: public results and
schedule context are priced into the closing line. An edge, if there is one,
has to come from price (a better number than the close) or from information the
line has not yet absorbed.

**A manual predict priced a game off a week-old line (2026-09-24).**
Run by hand as `refresh` then `predict`, the Week 3 Thursday pick (ATL/GB) was
built on the last line snapshot, taken 9/17: GB −6.5, total 46.5. The real
number was GB −4.5, total 42.5. `refresh` updates `games.spread_line`, but the
market block reads `line_snapshots`, which only the scheduled jobs refresh; 31
of 32 upcoming lines had moved in the gap. The model moved the stale 6.5 two
points to GB −4.5, which is exactly where the market already was, so at the real
number the pick has no edge by its own projection, and grading it at +6.5 would
credit two points that were never available. `predict` now snapshots lines
itself before building any pack. Dry-run confirmed the pack reads 4.5/42.5.

**The pack described injured quarterbacks as the starter (2026-10-04).**
`quarterback` came from depth-chart QB1, which keeps an injured starter listed,
and `player_form` reports whoever has thrown most. The Week 4 NYJ/CHI pack named
Caleb Williams (Out) with only his numbers; Keenum's start and Bagent's place at
QB2 were invisible, so the write-up assumed a backup drop-off it never measured.
TB (Mayfield) and WAS (Jayden Daniels) had the same gap. Packs now carry
`quarterback_situation` when QB1 is Out/Doubtful/Questionable, practised less
than fully, or did not start the last game: the expected starter (first QB on the
depth chart not ruled out), each candidate's own line this season and last, and
a flag when the last game's starter disagrees with the chart. Rebuilt all Week 4
packs with no model calls: exactly CHI, TB and WAS are flagged. Not yet run
through a live prediction.

Also tested, free, on 2017–2025 (927 games, weeks 2–8): giving the current
season more weight early makes the EPA blend predict margins *worse*; the
present 6-game prior (33% current at Week 4) beats 50% and 60%. Left unchanged.
Big favourites (7+) against teams at −7/game or worse covered 141-141; no edge.

**A max-effort post-mortem run billed $1.23 and wrote nothing (2026-10-12).**
`EDGELORD_EFFORT=max postmortem --regenerate` on Weeks 4-5 hit the flat
`max_tokens` 8000 on every call: adaptive thinking spent the whole allowance and
no text block came back. Seven calls at $0.176 each before it was stopped, and
the run summary printed `cost_usd 0.0` because a failed call's cost was never
counted. Worse, `--regenerate` stored a null narrative over the three existing
Week 4 reviews; they were restored from the 14:27 `public/data` snapshot. Now
`max_tokens` scales with effort (32000 at xhigh/max), a `max_tokens` stop is
reported as such, failed calls count toward the printed cost, and a failed
review never overwrites a stored one (tested).

**Picks are now rechecked against late injury news and line moves (2026-10-12).**
Week 5 was picked on Thursday 10/8 and nothing looked again: the scheduled
tasks had never been registered, and even registered, the Sunday job re-predicted
every game at 10:00, before inactives, while the midweek job watched lines only.
Two Week 5 losses (CLE, LAC) went to kickoff after a quarterback's status changed.
`edgelord recheck --week N` now compares each live pick's pack with a fresh one
and flags a key-number line move, an expected-QB change, any QB status change,
or a starter moving into or out of Out/Doubtful; flags show on the site. Run
free on Weeks 5-6: flagged exactly BUF/LA (3 -> 3.5, Ed Oliver Out) and the 14
unpicked Week 6 games. `--run` reruns flagged games within
EDGELORD_RECHECK_WEEKLY_USD, default 0 (flag only); that path is tested with a
stubbed model but has not made a live call. The scheduler scripts now run one
`recheck` job after each report and wave of inactives; the tasks are still not
registered.

**The model no longer sees luck measures (2026-10-12).** About half of 2026's
bigger-edge picks (1+ point) leaned on record-vs-points, close-game record or
turnover margin rated "strong", against a prompt that said "slight" at most, and
18 of those 20 picks were underdogs. Those measures were already shown priced
in on 2017-2025. `build_prompt` now sends `season_record` (record and point
differential) in place of `regression_indicators`, and drops
`prior_season_record`; the stored pack and the site keep both. The prompt's
"dog at +3.5" best-bet example is replaced by the key-number rule the code
applies. Applies from the next live pick; not yet run through one.

*Flagged by the owner as a drastic change -- review it, do not assume it worked.*
What was removed: last season's record block and this season's luck measures.
What was NOT removed: last season's efficiency, still blended in (55% at Week
6), and this season's record and point differential. Judge it from Week 6 on,
against Weeks 1-5, by: the share of underdog picks among edges of 1+ point
(was 18 of 20), how often "regression" or "luck" still drives a pick, and the
record and CLV by edge on the site. Undo is one function: drop the
`model_view(pack)` line in `build_prompt` (bot/edgelord/predict.py), commit
14e1e7c. Same day, also first applied from Week 6: coin-flip tier (9dfe3dd,
bf23998), picks switched to the side their own number favours (905f023), and
key-number best bets held to the thin-evidence bar (a454e0a).

**Week 5 relabelled into coin flips (2026-10-12).** At the owner's request the
coin-flip tier was applied to Week 5 after the fact: 7 leans with an edge under
a point (PHI, IND, TEN, NYG, LAC, SF, LA) are now `coin_flip`; best bets were
not touched. Weeks 1-4 stay as recorded (all leans). Every card now shows its
tier (BEST BET, LEAN or COIN FLIP).

**Prompt asks for conviction (2026-10-18).** The Week 6 Sunday rerun came back
11 coin flips of 14, every edge exactly 0.5 or 1.0: the prompt called 0 "a
good answer" that "should be a common one", and the model took the smallest
move that named a side. That paragraph in `SYSTEM_PROMPT` (bot/edgelord/
predict.py) now asks it to size the move to the evidence and commit, keeping
coin flips for games where the pack shows nothing. Tier thresholds and the
anti-hedging paragraph are unchanged. Applies from the next run; Week 6 live
picks were made under the old wording. Judge it on: spread of edges, share of
best bets per slate, and whether underdog share among 1+ point edges climbs
back toward the old 18 of 20.

## An EPA rating does not beat the line either (2026-10-18)

Asked for more conviction, the obvious source was a number of the bot's own to
disagree with. A score-based rating had already failed (2026-09-23), so this
tried play-level efficiency instead: the bot's own blended, opponent-adjusted
EPA per play, net of defence, turned into points by two numbers fit on
2017-2021 margins. Rules were committed before the run (8445829,
`bot/scripts/epa_rating_test.py`): pass only if the line's miss regresses
positively on the rating's disagreement at 2+ standard errors AND bets 2+
points off the line win 52.4% at p < 0.05. One look at 2022-2025, 1,087 games:

| | EPA rating | closing line |
|---|---|---|
| RMSE vs final margin | 12.97 | **12.36** |
| MAE vs final margin | 10.01 | **9.49** |

Market weight **-0.20 (se 0.11)**: negative, like the score rating's -0.18.
ATS was 48.8% betting every disagreement, 48.6% at 2+ points, 47.6% at 3+,
48.4% at 4+. It took the underdog in 70% of its disagreements. **FAIL** on
both tests; it does not go into the prediction pack.

That makes five independent tests -- the LLM's number, a score rating, the
regression thesis, the pre-registered signal search, and now EPA -- all saying
public data is priced into the closing line. The prompt change asking the
model for conviction (fa994a7) will produce bigger moves; nothing here says
bigger moves will cover more often. Grade the best bets it produces against
the leans before trusting them.

**Post-mortems no longer default to variance (2026-10-18).** All six Week 6
losses came back "thesis_right_variance": the prompt only counted a loss as
broken past a three-touchdown miss or a 20-point projection error, so nothing
smaller could be anything else. PHI +3 was the clearest case: it argued Tanner
McKee was "not clearly worse" than Hurts on 46 dropbacks and rated the
Barkley/Dickerson/Shipley absences "slight", then lost by 11. The prompt now
judges the argument rather than the miss size, and adds two rules: a factor
played down that looks like it decided the game, and a pick resting on a small
sample, are "thesis_wrong". Regenerated, all six flipped to thesis_wrong --
the other extreme, so watch whether it ever returns variance again. Post-mortems
stay display-only and never reach the prediction prompt.

**Post-mortems judged on a box score (2026-10-21).** The 2026-10-18 rules
could force thesis_wrong four ways and nothing could earn variance. Each loss
now carries a box score computed from the play-by-play (0042a30): EPA per play
with and without giveaways, success rate, turnover margin and special teams,
picked side against opponent. Out-played on clean snaps is thesis_wrong; won
the snaps and lost on turnovers or kicks is variance; a thin sample only
counts against a pick when the game showed the claim failing. Week 6 box
scores before any rerun: SEA (+0.19 EPA/play clean, -3 turnovers) and IND
(+0.14, -2, -12 special teams) won the football; ATL, PHI and LAC were
out-played by 0.29-0.32 a play. Not yet regenerated.

## Elo and a quarterback-adjusted Elo do not beat the line (2026-10-21)

First two of a planned set of computed models (Elo, QB-adjusted, efficiency,
matchup, machine learning, simulation) meant to give the bot its own view of
who wins before it looks at the spread. Both tuned on 2017-2021 only; rules
committed before the run (8149569, `bot/scripts/model_holdout.py`). Two tests
per model: WINNER (straight-up accuracy within 2.0 points of the line's
favourite AND Brier within 0.010 of the line's) and SPREAD (the EPA test's
bar: market weight 2+ se above zero AND 2+ point disagreements winning 52.4%
at p < 0.05). One look at 2022-2025, 1,084 games:

| | straight-up | Brier | RMSE vs margin | market weight | ATS 2+ off |
|---|---|---|---|---|---|
| closing line | **67.5%** | **0.2105** | **12.36** | -- | -- |
| QB-adjusted Elo | 65.2% | 0.2191 | 12.72 | -0.04 (se 0.13) | 254-252, 50.2% |
| Elo | 64.4% | 0.2227 | 12.90 | -0.11 (se 0.11) | 273-280, 49.4% |
| least-squares rating | 63.9% | 0.2250 | 12.90 | -0.18 (se 0.12) | 248-270, 47.9% |

All three **FAIL** both tests. The QB model missed the winner bar by 0.3
points (2.3 behind the line) and passed its Brier half. When it named a
different winner from the line it was right 42% of the time (65 of 154).

What it does show: the quarterback adjustment is real. It took a third of the
distance between Elo and the line off the margin error (12.90 to 12.72) and
cut wrong-winner disagreements from 182 to 154, out of sample. It is the
first computed number here that is plainly better than the score ratings,
though still not as good as the market.

2026 to date, 92 games, a live look graded by nothing: QB-adjusted Elo 64.1%
straight-up to the line's 62.0%, 39-27 ATS at 1+ point. Eleven weeks of that
would still be noise against four seasons saying otherwise.

Six computed numbers now say public data is priced into the closing line.
None of these goes into the prediction pack as a source of edge. Next in the
set: efficiency and matchup models, then a learned blend of all of them --
graded on the same card, with the same pre-registration.

## Shadow test: who wins first, the line last (pre-registered 2026-10-21)

The live predictor starts from the market spread and says how far to move it,
so every pick is a nudge to the line. The shadow predictor (`bot/edgelord/
shadow.py`) runs beside it on the same games and reverses the order: the model
sees the pack with the line removed, scores a fixed checklist of ten factors in
points (team strength from Elo, quarterback, availability, pass, run, pressure,
form, rest/travel, weather, home field), code sums them into the margin, and
only then compares to the line. Tier: best bet when the sum is 2+ points past
the line AND the QB-adjusted Elo is 1+ past it on the same side; lean at 1+
with the Elo on the same side; otherwise coin flip. Shadow picks sit in their
own table and never reach the record or the site.

Context it starts from: the live record's profit is an underdog run. Live dogs
33-26-2 (+4.0u), favourites 13-15-2 (-3.2u); league-wide dogs covered 48 of 87
in Weeks 1-6, so taking every dog would have matched the live dogs.

RULES, fixed before the first shadow pick:
1. From 2026 Week 7, every slate the live predictor runs, the shadow runs too,
   before kickoff. Graded by `edgelord shadow-report` on finished games.
2. No verdict before 8 weeks of shadow picks (about 110 games). Weekly numbers
   are reported, not acted on.
3. The shadow replaces the live predictor only if, over those weeks, it beats
   the live picks on BOTH spread record and average closing-line value, and
   names winners no worse than 2 points below the market favourite. Otherwise
   it stays a shadow or is dropped.
4. Every report splits underdog and favourite picks, so an underdog run is
   visible for what it is.

**Write-ups for fans (2026-10-21).** From Week 7 the headline and paragraph,
live and shadow, are written for a football fan: players, matchups, stakes, no
analytics terms and at most one plain number per paragraph. Figures stay in
the factor tags and decision table. Only the prose instructions changed; the
reasoning and tier rules did not. If Week 7's edges or tiers look different
from Weeks 5-6, this is the first suspect.

**Week 7 made official instead of shadowed (2026-10-21).** At the owner's call
the blind predictor makes the official Week 7 picks (`edgelord shadow --week 7
--official`, run label `blind`) rather than running beside the live one. Its
picks go in `predictions` with its own tier, so they count in the record and
show on the site. Each write-up opens with one plain line tying the blind call
to the line ("Our number: CHI by 1. The market: CHI by 1.5. The pick: NE
+1.5."). One week of picks says nothing on its own; the old predictor is
untouched and can be run again next week. Note that a recheck rerun would use
the old predictor for that game.

**Blind best-bet bar raised to 4 points (2026-10-25).** The blind predictor
carried over the live predictor's 2-point best-bet bar, but its edges are not
nudges off the line: Week 7's sums landed 2.5-3.75 points off it, and 9 of 14
picks were best bets (5 of them underdogs, NYG +10 among them). At the owner's
call `BEST_BET_EDGE` in bot/edgelord/shadow.py is now 4.0; the Elo-agreement
and lean rules are unchanged. Applied before any affected game kicked off: the
8 unplayed Week 7 best bets were re-tiered to lean, then the 12 unplayed games
were rerun on the blind predictor with fresh lines and injuries. NE @ CHI
(played Thursday) keeps its best_bet; PIT @ NO (underway in London) was not
touched. The two scored rating tests (2026-09-23, 2026-10-18) lost at 2-4
points off the line, so a 4-point bar is about frequency, not proof of an edge.

## Learned factor corrections (2026-10-29)

At the owner's call, results now feed back into the blind predictor: as numbers
applied when the factor points are added up, not as lessons in the prompt.
Post-mortem prose still never reaches a prompt. `edgelord/calibration.py` fits
one multiplier per factor on graded blind picks (ridge toward ×1, prior ±0.25,
SIGMA 13.5, bounded ×0.5–×1.5) and `edgelord shadow` applies it from Week 8.

| What | Evidence |
|---|---|
| **Week 7 graded** | 2026-10-29: `refresh` took 2026 to 107 final scores. The official blind picks went **5-9, -4.45 units**. Season 53-50-4, -1.82 units. Post-mortem miss arithmetic stored for all 9 losses (`--no-model`, $0). Narratives not run. |
| **Factor points backfilled** | Week 7 picks stored only the top five factors' points (in `key_factors`), so `calibrate --backfill` rebuilt the rest from the margin. Every factor outside the top five was "slight". 26 rows, superseded ones included. The 14 standing picks re-sum to their stored margin, with one 0.05 rounding gap (CLE/TEN). From now on raw points are stored in `predictions.factor_points`. |
| **First corrections** | 14 games: team_strength ×0.897, home_field ×0.967, everything else within ±0.012 of ×1. In-sample margin error 14.42 → 14.24. Team strength averaged 3.4 points a game and the finals did not follow it in Week 7. One week is noise, and the prior is what keeps this at a 10% trim. |
| **Tests** | `tests/test_calibration.py`, 9 tests: no data = no change, 14 games of a factor really worth half stays above ×0.8, 3000 games moves it below ×0.75, unused factors stay at exactly ×1, the floor holds, raw points survive storage, reconstruction is exact for a single remainder. Full suite 343 passing. |
| **Dashboard** | "What the model has learned" panel on `/record`, from the synced Firestore record doc. `tsc --noEmit` clean, 0 console errors, rows in checklist order. |

Watch: whether team_strength keeps falling as weeks are added. If it settles
near ×1 the Week 7 trim was noise. If it goes below ×0.8, the model is
over-scoring the Elo baseline.

**Week 7 post-mortems (2026-10-29).** 9 losses, 9 explained, 0 failed, $0.38.
Verdicts 5 `thesis_wrong` / 4 `thesis_right_variance`. The variance calls are
all games the picked side won on clean snaps: SF (+0.26 EPA/play, -4 turnovers),
NYJ, DET (+18.5 success rate, lost the cover by 0.5), NE (+0.10, -5.2 special
teams). The wrong calls include both of the week's biggest misses, CAR (by 33) and
SEA (by 14). Two themes repeat: an early-season Elo or record that outruns per-play
efficiency (CAR, MIN), and protection or availability gaps rated "slight" (SEA,
PHI, LV). The first is the same thing the team_strength ×0.90 correction picked up
independently. Display only, as before.

**Week 8 picked, partly (2026-10-29).** First slate on the factor corrections
(team_strength ×0.897, home_field ×0.967, from 14 games). 10 of 14 official blind
picks stored, $1.22: best bets BUF -3 and MIN +3; leans GB -3.5, LV +1.5 and
ATL +2.5; coin flips CIN -11.5, ARI +7, JAX -10, PIT -3.5 and LAC +6.5. KC @ DEN,
NE @ MIA, PHI @ WAS and CHI @ SEA failed with "credit balance too low" (HTTP 400,
not billed) and have no pick yet. Synced to Firestore.

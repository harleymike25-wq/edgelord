# What has actually been run

Everything in this repo was written by an AI agent across one session. The bot
grades its own picks; this file grades the build. It exists because "I wrote it
and it typechecks" is not the same claim as "I ran it and watched it work,"
and only one of those is worth anything at 11am on a Sunday.

Keep it honest. Move a row up only after the thing has actually executed.

Last updated: 2026-09-23

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

# Edgelord

NFL betting prediction bot. Assembles a pack of ~30 quantitative factors per game,
hands it to Claude one game at a time, and stores the pick plus a written paragraph
so performance can be graded across the season.

## Layout

The repository root **is** the Next.js app, so it deploys to Vercel with no root
directory setting. The Python bot lives in `bot/`.

```
app/  components/  lib/  public/     Next.js dashboard (repo root)
bot/
  edgelord/        the bot: sources, features, predict, track, postmortem, sync
  scripts/         scheduled-task runner and registration
  tests/           grading, odds parsing, notation, post-mortem arithmetic
  data/            SQLite database and the parquet cache
firestore.rules    denies all client access; the app reads server-side
```

## Setup

```powershell
# --- Python bot ---
cd bot
winget install Python.Python.3.12          # if not already installed
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
copy .env.example .env                     # fill in ANTHROPIC_API_KEY, ODDS_API_KEY

# --- dashboard ---
cd ..
npm install
```

## Where the lines come from

By default there is **no odds API and no key**. nflverse carries a live
spread, total and moneyline on upcoming games and updates it through the week,
so `edgelord snapshot-lines` records it on every run. That reconstructs the
opening number, the movement path, key-number crossings and **closing line
value** for free.

The trade-off is breadth, not existence: one consensus line instead of thirty
books, so there is no best-number shopping and no cross-book divergence signal.
Public betting percentages are unavailable either way — no free source
publishes them — so the model is told they are null rather than asked to guess.

If you later want multiple books, set `ODDS_API_KEY` (free Starter tier at
<https://the-odds-api.com/>, 500 credits/month) and `poll-odds` switches to it
automatically. Note that client has never run against the live API — see
[VERIFIED.md](VERIFIED.md).

## Commands

Run these from `bot/`.

```powershell
$py = ".venv\Scripts\python.exe"

& $py -m edgelord.cli backfill                      # pull 2024-25 nflverse data
& $py -m edgelord.cli status                        # what's in the database
& $py -m edgelord.cli poll-odds                     # snapshot current lines
& $py -m edgelord.cli features --game 2025_12_PIT_CHI          # inspect one pack
& $py -m edgelord.cli predict --game <id> --dry-run            # prompt, no API call
& $py -m edgelord.cli predict --week 1 --label sunday          # whole slate
& $py -m edgelord.cli grade                         # grade finished games
& $py -m edgelord.cli postmortem --week 1           # work out why the losses lost
& $py -m edgelord.cli report --week 1 --open        # render the slate
& $py -m edgelord.cli sync                          # mirror to Firestore + snapshot
```

## Dashboard

The Next.js app at the repository root displays the slate, each game's write-up,
and the running record.

```powershell
npm run dev          # http://localhost:3000
```

**Storage model:** SQLite stays the source of truth. `edgelord sync` pushes a
denormalised read-only mirror to Firestore — one document per game carrying the
game, its current prediction and its result — so the dashboard renders a week
from a single query. Nothing in the bot depends on the sync succeeding; with no
credentials it no-ops and only writes the local snapshot.

The dashboard reads Firestore **server-side via the Admin SDK**, so no browser
ever connects to Firestore and `firestore.rules` denies all client access. With
no `FIREBASE_SERVICE_ACCOUNT` set it falls back to the JSON snapshot in
`public/data/` — that is the intended local development mode and needs no
Firebase project at all.

### Putting it on your phone

1. Create a Firebase project, enable Firestore, and download a service account key
   (Project settings → Service accounts → Generate new private key).
2. Point the sync at it and push:
   ```powershell
   $env:FIREBASE_CREDENTIALS = "C:\path\to\serviceAccount.json"
   .venv\Scripts\python.exe -m pip install -e ".[firebase]"
   .venv\Scripts\python.exe -m edgelord.cli sync
   ```
   Add `FIREBASE_CREDENTIALS` to `.env` to make it stick for the scheduled jobs.
3. Deploy the rules: `firebase deploy --only firestore`
4. Deploy the app (`npx vercel` from the repo root), setting `FIREBASE_SERVICE_ACCOUNT`
   to the **contents** of that JSON key as an environment variable.

The Sunday, Midweek and Grade scheduled jobs all call `sync` after they run, so
the dashboard updates itself.

### Placeholder data

Before any real predictions exist, generate a synthetic snapshot so the UI has
something to render:

```powershell
.venv\Scripts\python.exe scripts\seed_dev_snapshot.py
```

The paragraphs are obvious placeholder text, the snapshot is flagged
`synthetic: true`, and the dashboard shows a warning banner. It refuses to run
once real predictions exist, and it rolls back its transaction so the database is
left untouched.

## Scheduling

Once `bot\.env` has both keys, from `bot/`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
```

Registers four per-user tasks (no elevation needed):

| Task | When | Does |
|---|---|---|
| `Edgelord\PollOdds` | every 6 hours | snapshots lines — this is what builds the open→close curve |
| `Edgelord\Sunday` | Sunday 10:00 | poll, grade, predict the slate, render the report |
| `Edgelord\Midweek` | Thu + Mon 18:00 | re-poll, re-predict, re-render |
| `Edgelord\Grade` | Tuesday 09:00 | grade the completed week |

Sunday runs at 10:00 so a sixteen-game slate is finished by 11:00. Logs land in
`logs\YYYY-MM.log`. Remove with `register_tasks.ps1 -Unregister`.

## What's stored

`data\edgelord.db` (SQLite):

- **`games`** — nflverse schedule, upserted
- **`line_snapshots`** — one row per poll per book per market; the entire
  open-vs-close and movement picture is reconstructed from this
- **`features`** — the exact JSON pack sent to the model, so any prediction can be replayed
- **`predictions`** — pick, confidence, paragraph, `line_at_pick`, `run_label`,
  `superseded_by` (re-predictions chain rather than overwrite)
- **`results`** — score, win/loss/push, `profit_units`, `clv_points`
- **`odds_api_usage`** — credit accounting; the poller hard-stops before overrunning

## Data sources and their limits

| Factor group | Source | Caveat |
|---|---|---|
| Closing lines, rest, roof/temp/wind, referee, div game | nflverse `games.csv` | complete back to 1999 |
| Opening line, movement, key-number crossings | our own `line_snapshots` | **2026 forward only** — no free source has history |
| Public betting % | none | no free source exists; the pack reports it as null and the model is told so |
| EPA, success, explosive, red zone, pace, PROE | nflverse pbp | opponent-adjusted first-order |
| Pressure rate | pbp sacks + QB hits per dropback | a proxy; true pressure is PFF/charting |
| Blitz rate | FTN charting `n_pass_rushers >= 5` | 2022+ only |
| Weather forecast | Open-Meteo | no key; 16-day horizon; skipped for domes |
| Injuries | nflverse | practice reports only — final actives drop 90 min pre-kick and are not in nflverse |
| Referee crew | nflverse officials | 2015+; effects are small and noisy |

Every gap is written into the pack's `data_gaps` array, and the system prompt
instructs the model to reason around gaps rather than fill them in.

## Post-mortems

Every losing pick gets a row in `post_mortems`, in two layers.

The **miss** is computed from what is already stored: how far the projection was
off, how many points short of the number the pick finished, which rows of the
model's own decision table argued for the side that lost, and whether the pick
had any edge by its own arithmetic. It costs nothing, is unit-tested, and can be
regenerated at any time. `--no-model` stops there.

The **narrative** is a second model call that reads those figures and says
whether the reasoning was wrong or the game simply went the other way. It is
allowed — encouraged — to return `thesis_right_variance` and change nothing. A
-1.00 unit loss is the same number for a half-point miss and a three-touchdown
one, and only the second is evidence.

One verdict is not available to it. When `contradicted_own_projection` is true
the pick needed a result its own projection did not forecast, so it had no edge
whatever the game then did; that cannot be excused as variance. The flag is
computed rather than inferred from the signs, because that inference has already
gone wrong once — see VERIFIED.md.

**These do not feed back into the prediction prompt, by design.** A week of
football is nine losses; injecting them would teach the model to overfit noise
it cannot distinguish from signal. They are stored and displayed so a human can
look for a pattern across a season.

## Sign conventions

Getting these backwards silently corrupts everything downstream, so they are
fixed and tested:

- `spread_home` / `spread_line`: **positive means the home team is favoured**.
  The Odds API quotes the favourite as negative, so `sources/odds.py` flips it on
  ingest (`tests/test_odds_parse.py`).
- `line_at_pick`: **the side we picked is favoured by this many points**. Reports
  display the inverse, because a team laying 7 shows as `-7`
  (`tests/test_report_notation.py`).
- `clv_points`: **positive means we held a better number than the close**
  (`tests/test_grading.py`).

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Covers the odds sign flip, spread/total grading, payout maths, CLV direction,
report notation, post-mortem miss arithmetic, and the exclusion of backtests
from the record — the places where a silent error would produce plausible but
wrong numbers.

## A caveat worth stating plainly

Closing lines are the sharpest public forecast of an NFL game that exists, and a
factor-pack model should not be expected to beat them consistently. Treat this as
a tracking-and-analysis instrument: it makes reasoning explicit, stores it, and
grades it honestly.

Watch the CLV column. If average CLV sits at or below zero after a few weeks, the
model is describing the market rather than beating it — and that will be visible
long before win-loss record says anything meaningful.

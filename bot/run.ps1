<#
.SYNOPSIS
  Run one Edgelord job by name.

.DESCRIPTION
  A short front door for running jobs by hand while the scheduler is not
  registered. Each verb maps to the same code path Task Scheduler uses, so
  what you run here is what will run automatically later.

  Every job prints what it is about to do and an estimated model cost before
  it touches the API, and stops for confirmation on anything that spends more
  than a slate's worth. Use -Force to skip the prompt.

.EXAMPLE
  .\run.ps1 sunday            # the full slate: refresh, poll, grade, predict, report, sync
  .\run.ps1 thursday          # standalone game: only re-predicts numbers that moved
  .\run.ps1 monday
  .\run.ps1 grade             # score finished games, no model calls
  .\run.ps1 lines             # snapshot the current line, no model calls
  .\run.ps1 status            # what is in the database, no model calls

.EXAMPLE
  .\run.ps1 sunday -Week 1 -Season 2026 -Force
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('recheck', 'rerun', 'slate', 'grade', 'lines', 'status', 'spend')]
    [string]$Job,

    [int]$Week,
    [int]$Season,

    # Skip the cost confirmation on jobs that make model calls.
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$runner = Join-Path $root 'scripts\run_task.ps1'
$python = Join-Path $root '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    throw "venv not found at $python -- run: python -m venv .venv; .venv\Scripts\python.exe -m pip install -e ."
}

# Roughly $0.17 a game at current pack size and effort=medium.
$COST_PER_GAME = 0.17

function Invoke-Cli {
    param([string[]]$CliArgs)
    $env:PYTHONIOENCODING = 'utf-8'
    & $python -m edgelord.cli @CliArgs
}

# The current NFL week from the schedule, as the scheduled runner resolves it.
function Get-Week {
    $env:PYTHONIOENCODING = 'utf-8'
    # First week with an unplayed game. "Within the last two days" alone kept
    # returning last week until Wednesday, because Monday night is in range.
    (& $python -c "import datetime as d; from edgelord import db; db.init(); c=db.connect(); y=(d.date.today()-d.timedelta(days=1)).isoformat(); r=c.execute('SELECT week FROM games WHERE home_score IS NULL AND gameday >= ? ORDER BY gameday, gametime LIMIT 1', (y,)).fetchone(); print(r[0] if r else 1)").Trim()
}

# Jobs that only read, and the description shown before running.
$readOnly = @{
    'grade'  = 'Refresh final scores and grade any finished games. No model calls.'
    'lines'  = 'Snapshot the current nflverse line. No model calls.'
    'status' = 'Show what is in the database. No model calls.'
    'spend'  = 'Show model spend by month. No model calls.'
    'recheck' = 'Flag picks whose line or key injuries changed since they were made. No model calls.'
}

if ($readOnly.ContainsKey($Job)) {
    Write-Host $readOnly[$Job] -ForegroundColor Cyan
    switch ($Job) {
        'grade'  { & powershell -NoProfile -ExecutionPolicy Bypass -File $runner -Job grade }
        'lines'  { Invoke-Cli @('poll-odds') }
        'status' { Invoke-Cli @('status') }
        'spend'  { Invoke-Cli @('spend') }
        'recheck' {
            $wk = if ($Week) { @('--week', $Week) } else { @('--week', (Get-Week)) }
            $sn = if ($Season) { @('--season', $Season) } else { @() }
            Invoke-Cli (@('recheck') + $wk + $sn)
        }
    }
    exit $LASTEXITCODE
}

# --- jobs that spend money -------------------------------------------------

$wk = if ($Week) { $Week } else { Get-Week }
$sn = if ($Season) { @('--season', $Season) } else { @() }
if ($Job -eq 'slate') {
    $estimate = 16 * $COST_PER_GAME
    $description = "Full slate for week $wk. Predict every unplayed game (replaces existing picks)."
    $cliArgs = @('predict', '--week', $wk, '--label', 'manual') + $sn
} else {
    Invoke-Cli (@('recheck', '--week', $wk) + $sn)
    $seasonExpr = if ($Season) { "$Season" } else { 'config.current_season()' }
    $flagged = @(& $python -c "from edgelord import db; db.init(); c=db.connect(); from edgelord import config; print(c.execute('SELECT COUNT(*) FROM recheck_flags f JOIN games g ON g.game_id=f.game_id WHERE g.week=? AND g.season=?', ($wk, $seasonExpr)).fetchone()[0])")[0]
    if ([int]$flagged -eq 0) { exit 0 }
    $estimate = [int]$flagged * $COST_PER_GAME
    $description = "Re-predict the $flagged flagged game(s) above."
    # The cap is on top of whatever the scheduler already spent this week.
    $cliArgs = @('recheck', '--week', $wk, '--run', '--allow', ('{0:N2}' -f ($estimate + 0.5))) + $sn
}

Write-Host ""
Write-Host "  $description" -ForegroundColor Cyan
Write-Host ("  estimated model cost: ~`${0:N2} USD" -f $estimate) -ForegroundColor Yellow
Write-Host ""

Invoke-Cli @('spend') | Select-Object -Last 2 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
Write-Host ""

if (-not $Force) {
    $answer = Read-Host "  Proceed? (y/N)"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host "  cancelled - nothing spent" -ForegroundColor DarkGray
        exit 0
    }
}

Invoke-Cli $cliArgs
$code = $LASTEXITCODE
Invoke-Cli (@('report', '--week', $wk) + $sn) | Out-Null
Invoke-Cli (@('sync') + $sn) | Select-Object -First 1

Write-Host ""
Invoke-Cli @('spend') | Select-Object -Last 2 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
exit $code

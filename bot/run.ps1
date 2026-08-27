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
    [ValidateSet('sunday', 'wednesday', 'thursday', 'monday', 'grade', 'lines', 'status', 'spend')]
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

# Jobs that only read, and the description shown before running.
$readOnly = @{
    'grade'  = 'Refresh final scores and grade any finished games. No model calls.'
    'lines'  = 'Snapshot the current nflverse line. No model calls.'
    'status' = 'Show what is in the database. No model calls.'
    'spend'  = 'Show model spend by month. No model calls.'
}

if ($readOnly.ContainsKey($Job)) {
    Write-Host $readOnly[$Job] -ForegroundColor Cyan
    switch ($Job) {
        'grade'  { & powershell -NoProfile -ExecutionPolicy Bypass -File $runner -Job grade }
        'lines'  { Invoke-Cli @('poll-odds') }
        'status' { Invoke-Cli @('status') }
        'spend'  { Invoke-Cli @('spend') }
    }
    exit $LASTEXITCODE
}

# --- jobs that spend money -------------------------------------------------

# Sunday predicts the whole slate; the weekday jobs only re-predict games whose
# number has crossed a key value since the last run, which is usually a handful.
$isFullSlate = $Job -eq 'sunday'
$estimate = if ($isFullSlate) { 16 * $COST_PER_GAME } else { 3 * $COST_PER_GAME }

$description = if ($isFullSlate) {
    "Full slate. Refresh scores, snapshot lines, grade finished games, predict every game, render the report, sync to Firestore."
} else {
    "Midweek pass for $Job. Refresh, snapshot lines, grade, then re-predict only games whose number crossed a key value since the last run."
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

# Sunday is its own job; the three weekday runs share the midweek path, which
# derives its run label from the actual day of the week.
$taskJob = if ($isFullSlate) { 'sunday' } else { 'midweek' }
$taskArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $runner, '-Job', $taskJob)
if ($Week)   { $taskArgs += @('-Week', $Week) }
if ($Season) { $taskArgs += @('-Season', $Season) }
# Label by the job you asked for, not by today's date -- running `thursday`
# on a Tuesday should still be recorded as the Thursday pass.
if (-not $isFullSlate) { $taskArgs += @('-Label', $Job) }

& powershell @taskArgs
$code = $LASTEXITCODE

Write-Host ""
Invoke-Cli @('spend') | Select-Object -Last 2 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
Write-Host ""
Write-Host "  log: bot\logs\$(Get-Date -Format 'yyyy-MM').log" -ForegroundColor DarkGray
exit $code

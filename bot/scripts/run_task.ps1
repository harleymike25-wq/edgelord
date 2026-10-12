<#
.SYNOPSIS
  Entry point for every scheduled Edgelord job.

.DESCRIPTION
  Task Scheduler gets one script and a verb. Everything runs through the venv
  python so the tasks do not depend on PATH, and all output is appended to a
  dated log -- a scheduled task that fails silently is worse than one that
  never ran.
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('poll', 'recheck', 'grade')]
    [string]$Job,

    [int]$Week,
    [int]$Season,

    # Overrides the run label, which otherwise comes from the current weekday.
    # Task Scheduler fires on the right day so the default is correct there;
    # a manual `run.ps1 thursday` on a Tuesday needs to say so explicitly.
    [string]$Label
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$log = Join-Path $logDir ("{0}.log" -f (Get-Date -Format 'yyyy-MM'))

$env:PYTHONIOENCODING = 'utf-8'

function Write-Log($msg) {
    $line = "{0}  [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Job, $msg
    Add-Content -Path $log -Value $line -Encoding utf8
    Write-Output $line
}

function Invoke-Edgelord {
    param([string[]]$EdgelordArgs)
    Write-Log ("edgelord " + ($EdgelordArgs -join ' '))
    $output = & $python -m edgelord.cli @EdgelordArgs 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $output) { Add-Content -Path $log -Value "    $line" -Encoding utf8 }
    if ($code -ne 0) { Write-Log "exit code $code" }
    return $code
}

# Resolve the current NFL week from the schedule rather than the calendar --
# bye structure and flexed games make date arithmetic unreliable.
function Get-CurrentWeek {
    $resolved = & $python -c @"
from edgelord import config, db
db.init()
season = config.current_season()
with db.session() as conn:
    row = conn.execute(
        'SELECT season, week FROM games WHERE home_score IS NULL '
        'AND gameday >= date(\"now\", \"-1 day\") ORDER BY gameday, gametime LIMIT 1'
    ).fetchone()
print(f'{row[\"season\"]} {row[\"week\"]}' if row else f'{season} 1')
"@
    return $resolved.Trim() -split ' '
}

Set-Location $root

switch ($Job) {
    'poll' {
        Invoke-Edgelord @('poll-odds') | Out-Null
    }
    'recheck' {
        # One job for the whole week, fired after each injury report and each
        # wave of inactives. It picks games that have no pick yet and reruns
        # picks whose line or key injuries changed -- but only within
        # EDGELORD_RECHECK_WEEKLY_USD. At the default of 0 it calls no model at
        # all: changed picks are flagged on the site and in this log instead.
        #
        # This replaced a Sunday 10:00 full-slate re-predict (before any
        # inactives, and paying for every game whether or not anything changed)
        # and a midweek pass that watched lines but not injuries.
        #
        # `refresh` must precede `grade`: it is the only thing that writes final
        # scores into the games table, and grade skips any game whose score is
        # still null.
        Invoke-Edgelord @('refresh') | Out-Null
        if (-not $Week) { $s, $w = Get-CurrentWeek } else { $s, $w = $Season, $Week }
        Invoke-Edgelord @('grade') | Out-Null
        Invoke-Edgelord @('recheck', '--season', $s, '--week', $w, '--run') | Out-Null
        Invoke-Edgelord @('report', '--season', $s, '--week', $w) | Out-Null
        Invoke-Edgelord @('sync', '--season', $s) | Out-Null
    }
    'grade' {
        Invoke-Edgelord @('refresh') | Out-Null
        Invoke-Edgelord @('grade') | Out-Null
        Invoke-Edgelord @('sync') | Out-Null
    }
}

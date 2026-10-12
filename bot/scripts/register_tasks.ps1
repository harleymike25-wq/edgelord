<#
.SYNOPSIS
  Register (or re-register) the Edgelord scheduled tasks for the current user.

.DESCRIPTION
  Registers three tasks under the \Edgelord\ folder. No elevation is required.

    Edgelord\PollLines  every 6 hours          snapshot lines (builds open->close)
    Edgelord\Recheck    after each injury report and wave of inactives (below):
                        pick unpicked games, flag or rerun picks whose line or
                        key injuries changed -- model spend capped per week by
                        EDGELORD_RECHECK_WEEKLY_USD (default 0: flag only)
    Edgelord\Grade      Tuesdays 09:00         grade the completed week

  Registering also removes tasks left under the old names (Sunday, Midweek),
  which ran jobs the runner no longer accepts.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1
  powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1 -Unregister
#>
param([switch]$Unregister)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$runner = Join-Path $root 'scripts\run_task.ps1'
$folder = '\Edgelord\'

$tasks = @(
    @{ Name = 'PollLines'; Job = 'poll' },
    @{ Name = 'Recheck';   Job = 'recheck' },
    @{ Name = 'Grade';     Job = 'grade' }
)

# The pre-recheck task names. Always removed, so an old registration cannot keep
# firing 'sunday' or 'midweek', which run_task.ps1 now rejects.
$retired = @('Sunday', 'Midweek')
foreach ($name in $retired) {
    if (Get-ScheduledTask -TaskName $name -TaskPath $folder -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -TaskPath $folder -Confirm:$false
        Write-Output "removed retired $folder$name"
    }
}

if ($Unregister) {
    foreach ($t in $tasks) {
        $full = "$folder$($t.Name)"
        if (Get-ScheduledTask -TaskName $t.Name -TaskPath $folder -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t.Name -TaskPath $folder -Confirm:$false
            Write-Output "removed $full"
        }
    }
    return
}

if (-not (Test-Path $runner)) { throw "runner not found at $runner" }

function New-EdgelordAction($job) {
    New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$runner`" -Job $job" `
        -WorkingDirectory $root
}

# -WakeToRun brings the machine out of sleep for a run; -StartWhenAvailable
# catches up a trigger that was missed entirely (machine off). Together with the
# S4U principal below, a run needs the PC powered on but not logged in, not
# awake, and not unlocked.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 10)

# S4U ("service for user") runs the task whether or not anyone is logged on,
# without storing a password. The job is headless -- it writes to a log file and
# never touches a window -- so having no desktop session is fine.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType S4U -RunLevel Limited

$triggers = @{
    # Every 6 hours, indefinitely. Snapshots the free nflverse line, which is
    # what reconstructs the opening number, the movement path and CLV.
    PollLines = @(
        $t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours(2) `
            -RepetitionInterval (New-TimeSpan -Hours 6)
        $t
    )

    # Timed to land just after new information, Eastern (this machine's zone):
    #   Wed 17:00  first practice report; the week's initial picks
    #   Thu 18:50  Thursday inactives (~90 min before the 20:15 kickoff)
    #   Fri 17:00  final game statuses (Out / Doubtful / Questionable)
    #   Sat 17:00  Saturday designations and late-week news
    #   Sun 11:45, 14:50, 19:00  inactives for the 13:00, 16:05/16:25 and 20:20 games
    #   Mon 18:50  Monday night inactives
    # Games already kicked off are never touched, so the later Sunday runs only
    # see the games still to come. This replaced a Sunday 10:00 full re-predict
    # that ran before any inactives were out.
    Recheck  = @(
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At '17:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday  -At '18:50'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday    -At '17:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday  -At '17:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday    -At '11:45'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday    -At '14:50'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday    -At '19:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday    -At '18:50'
    )

    # Tuesday morning: grade everything the week just settled.
    Grade    = @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Tuesday -At '09:00')
}

foreach ($t in $tasks) {
    $existing = Get-ScheduledTask -TaskName $t.Name -TaskPath $folder -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $t.Name -TaskPath $folder -Confirm:$false
    }

    $common = @{
        TaskName    = $t.Name
        TaskPath    = $folder
        Action      = (New-EdgelordAction $t.Job)
        Trigger     = $triggers[$t.Name]
        Settings    = $settings
        Description = "Edgelord: $($t.Job)"
    }

    # S4U needs the "log on as a batch job" right, which some account types
    # lack. Fall back to an interactive principal rather than registering
    # nothing -- but say so, because the fallback only runs while logged in.
    try {
        Register-ScheduledTask @common -Principal $principal -ErrorAction Stop | Out-Null
        Write-Output "registered $folder$($t.Name)  (runs whether or not you are logged in)"
    } catch {
        Register-ScheduledTask @common -ErrorAction Stop | Out-Null
        Write-Warning "$($t.Name): background principal refused ($($_.Exception.Message.Trim()))."
        Write-Warning "  Registered to run only while $env:USERNAME is logged on."
    }
}

Write-Output ''
Write-Output 'Background behaviour:'
Write-Output '  logged out / locked  -> runs'
Write-Output '  asleep               -> wakes the machine and runs'
Write-Output '  powered off          -> runs at next boot (StartWhenAvailable)'
Write-Output ''
Write-Output 'Confirm with:  Get-ScheduledTask -TaskPath \Edgelord\ | Get-ScheduledTaskInfo'

Write-Output ''
Write-Output 'Verify with:  Get-ScheduledTask -TaskPath \Edgelord\'
Write-Output 'Test now:     Start-ScheduledTask -TaskName Recheck -TaskPath \Edgelord\'

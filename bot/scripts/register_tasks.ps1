<#
.SYNOPSIS
  Register (or re-register) the Edgelord scheduled tasks for the current user.

.DESCRIPTION
  Registers four tasks under the \Edgelord\ folder. No elevation is required --
  these run as the current user, only when logged on.

    Edgelord\PollOdds   every 6 hours          snapshot lines (builds open->close)
    Edgelord\Sunday     Sundays 10:00          full slate: poll, grade, predict, report
    Edgelord\Midweek    Thu + Mon 18:00        re-poll and re-predict
    Edgelord\Grade      Tuesdays 09:00         grade the completed week

  The Sunday job runs at 10:00 rather than 11:00 so a sixteen-game slate has
  time to finish before you want to read it.

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
    @{ Name = 'Sunday';    Job = 'sunday' },
    @{ Name = 'Midweek';   Job = 'midweek' },
    @{ Name = 'Grade';     Job = 'grade' }
)

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

    # The main slate build. 10:00 so a sixteen-game run is finished well before
    # the 13:00 ET kickoffs.
    Sunday   = @(New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At '10:00')

    # Wednesday and Thursday cover standalone games that kick off before the
    # Sunday job would ever see them. The 2026 season opens on a WEDNESDAY
    # (Sept 9, NE at SEA) with the Melbourne game the following night -- on a
    # Thursday/Sunday/Monday schedule alone, the opener would first be predicted
    # after it had already been played.
    Midweek  = @(
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At '11:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday -At '11:00'
        New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At '11:00'
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
Write-Output 'Test now:     Start-ScheduledTask -TaskName Sunday -TaskPath \Edgelord\'

# Brain Twin - Register Daily Backup (Windows Task Scheduler)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# Usage:
#   .\scripts\install_backup_task.ps1
#   .\scripts\install_backup_task.ps1 -Hour 4 -Minute 30
#
# To remove:
#   .\scripts\uninstall_backup_task.ps1
#
# - Validates Hour(0-23)/Minute(0-59) and exits before touching the task
#   scheduler if the values are invalid (validation logic lives in
#   scripts/lib/BackupTaskValidation.psm1 and is covered by Pester tests in
#   scripts/tests/BackupTaskValidation.Tests.ps1).
# - Works even if the username or repo path contains spaces or non-ASCII
#   characters.
# - Warns clearly (but still registers the task) if Docker Desktop does not
#   appear to be running.
# - Never touches any other, unrelated scheduled task (only the exact task
#   name used by Brain Twin is affected).

[CmdletBinding()]
param(
    [int]$Hour = 3,
    [int]$Minute = 0
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackupScript = Join-Path $RepoRoot "scripts\backup.ps1"
$TaskName = "BrainTwinDailyBackup"

Import-Module (Join-Path $PSScriptRoot "lib\BackupTaskValidation.psm1") -Force

# --- Validate input: if out of range, stop here without touching the task scheduler ---
$rangeCheck = Test-HourMinuteRange -Hour $Hour -Minute $Minute
if (-not $rangeCheck.IsValid) {
    Write-Host "[ERROR] $($rangeCheck.Message). No task was registered." -ForegroundColor Red
    exit 2
}

if (-not (Test-Path $BackupScript)) {
    Write-Host "[ERROR] $BackupScript was not found. Make sure you are running this from the repository root." -ForegroundColor Red
    exit 1
}

# --- Check whether Docker Desktop looks like it is running (registration continues either way) ---
if (-not (Test-DockerAvailable)) {
    Write-Host "[WARNING] Docker Desktop does not appear to be running. The task will still be registered," -ForegroundColor Yellow
    Write-Host "          but the backup will fail at run time unless Docker Desktop is running then." -ForegroundColor Yellow
}

# --- If a task with the same name already exists, remove it first, then re-register ---
# Get-ScheduledTask never affects any other, unrelated task (it is looked up by exact name).
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] An existing '$TaskName' task was found; removing it before re-registering."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Build the argument string via a helper function rather than raw string
# concatenation, so paths containing spaces or non-ASCII characters do not
# break anything.
$actionArgs = Get-BackupTaskActionArguments -BackupScriptPath $BackupScript
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours($Hour).AddMinutes($Minute))

# Registered with standard-user rights (no administrator elevation required),
# assuming Docker Desktop itself is running as the current user.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
    -Description "Automatically backs up the Brain Twin database every day (runs brain-twin/scripts/backup.ps1)." | Out-Null

Write-Host "[OK] Registered task '$TaskName'. It will run daily at $($Hour.ToString('00')):$($Minute.ToString('00'))."
Write-Host ""
Write-Host "Check registration: Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "Run it manually:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Check last result:  (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult  # non-zero means it failed"
Write-Host "Log file:           $RepoRoot\data\backups\backup.log"
Write-Host "To remove:          .\scripts\uninstall_backup_task.ps1"

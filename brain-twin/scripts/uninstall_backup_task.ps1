# Brain Twin - Remove Daily Backup Task (Windows Task Scheduler)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# Usage:
#   .\scripts\uninstall_backup_task.ps1

$ErrorActionPreference = "Stop"
$TaskName = "BrainTwinDailyBackup"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "[INFO] Task '$TaskName' is not registered. Nothing to do."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Removed task '$TaskName'."
Write-Host "(Existing backup files and logs are not deleted; they remain in data\backups\.)"

# Brain Twin Manual/Scheduled Backup (Windows PowerShell)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# Manual run:
#   .\scripts\backup.ps1
#
# To register a daily automatic run, use scripts\install_backup_task.ps1
# (no need to use the Task Scheduler GUI by hand).
#
# Log is appended to data\backups\backup.log.

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "data\backups"
$LogFile = Join-Path $LogDir "backup.log"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log($message) {
    $line = "[$(Get-Date -Format o)] $message"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

Write-Log "Starting backup"

$output = docker compose exec -T server python scripts/backup_cli.py 2>&1
$exitCode = $LASTEXITCODE
$output | ForEach-Object { Add-Content -Path $LogFile -Value $_; Write-Host $_ }

if ($exitCode -eq 0) {
    Write-Log "Backup finished successfully"
} else {
    Write-Log "[FAILED] Backup exited with an error (exit code: $exitCode)"
}

exit $exitCode

# Brain Twin Restore From Backup (Windows PowerShell)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# List available backups:
#   .\scripts\restore.ps1 --list
# Restore from the latest backup:
#   .\scripts\restore.ps1 --latest
# Restore from a specific file:
#   .\scripts\restore.ps1 --file brain_twin_20260730_030000_000000_abc123.sqlite3
#
# Restoring is a destructive operation. The current DB is safety-copied
# automatically before it is overwritten.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if ($args.Count -eq 0) {
    Write-Host "Usage: .\scripts\restore.ps1 [--list | --latest | --file <filename>]"
    docker compose exec -T server python scripts/restore_cli.py --list
    exit 0
}

if ($args[0] -eq "--list") {
    docker compose exec -T server python scripts/restore_cli.py --list
} else {
    docker compose exec server python scripts/restore_cli.py @args
}

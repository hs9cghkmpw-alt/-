# Brain Twin E2E Run Wrapper (Windows PowerShell)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why).
#
# Starts the Docker integration test environment, applies the Alembic
# migration, runs Playwright, and always tears the environment down
# (down -v) whether the run succeeded or failed.
#
# Usage:
#   .\scripts\run_e2e.ps1
#   .\scripts\run_e2e.ps1 pairing.spec.ts

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PlaywrightArgs
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$exitCode = 1
try {
    Write-Host "[run_e2e] Starting the Docker integration test environment..."
    docker compose -f docker-compose.test.yml up -d --build
    if ($LASTEXITCODE -ne 0) { throw "docker compose up failed" }

    Write-Host "[run_e2e] Applying the database schema..."
    $migrated = $false
    for ($i = 0; $i -lt 20; $i++) {
        docker compose -f docker-compose.test.yml exec -T server-test alembic upgrade head
        if ($LASTEXITCODE -eq 0) { $migrated = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $migrated) { throw "alembic upgrade head failed" }

    Write-Host "[run_e2e] Running Playwright E2E..."
    Push-Location apps\web
    npm run test:e2e -- @PlaywrightArgs
    $exitCode = $LASTEXITCODE
    Pop-Location
} catch {
    Write-Host "[run_e2e] Error: $($_.Exception.Message)" -ForegroundColor Red
    $exitCode = 1
} finally {
    Write-Host "[run_e2e] Cleanup: removing test containers and volumes"
    docker compose -f docker-compose.test.yml down -v --remove-orphans | Out-Null
}

exit $exitCode

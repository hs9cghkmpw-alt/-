# Brain Twin - Run-All Verification Script (Windows PowerShell)
#
# Runs everything that can be automated in one command, then prints a
# dashboard that is easy to read at a glance. Timestamp, environment info,
# and logs are saved to verification\latest\.
#
# NOTE: This file is intentionally ASCII-only. See scripts/setup.ps1 for why
# (Windows PowerShell 5.1 + non-ASCII text without a BOM is a known source of
# parser errors such as "UnexpectedToken" / "MissingEndParenthesisInExpression").
#
# Usage:
#   .\scripts\verify_all.ps1
#   .\scripts\verify_all.ps1 -SkipDocker -SkipE2E

param(
    [switch]$SkipDocker,
    [switch]$SkipE2E
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "data-test\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$LatestDir = Join-Path $RepoRoot "verification\latest"
if (Test-Path $LatestDir) { Remove-Item -Recurse -Force $LatestDir }
New-Item -ItemType Directory -Force -Path (Join-Path $LatestDir "logs") | Out-Null

$RunStartedAt = Get-Date -Format o

# ==================================================================
# IMPORTANT FIX: robust way to check whether an external .ps1 script
# actually completed successfully.
#
# Bug history: a previous version relied only on `$LASTEXITCODE -eq 0`
# after `& .\some-script.ps1`. If the invoked script fails to PARSE at all
# (for example due to a corrupted/garbled file), PowerShell throws a
# terminating parser error for the invocation itself - the called script
# never runs, so it never reaches its own "exit" statement, and
# $LASTEXITCODE is simply left at whatever value it happened to hold from
# an earlier, unrelated command. That earlier stale value could be 0,
# which made this stage look like a PASS even though nothing actually ran.
#
# Fix: reset $LASTEXITCODE (and $Error) before every external invocation,
# wrap the call in try/catch so a parser/terminating error is caught
# explicitly, and only report success when the exit code is verified to be
# exactly 0 AND no exception was thrown.
# ==================================================================
function Invoke-ExternalScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath
    )

    $Global:LASTEXITCODE = 1  # non-zero sentinel; a real success must overwrite this with 0
    $succeeded = $false
    $outputLines = @()

    try {
        $outputLines = & $ScriptPath 2>&1 | ForEach-Object { $_.ToString() }
        if ($LASTEXITCODE -eq 0) {
            $succeeded = $true
        } else {
            $outputLines += "[verify_all] Script exited with code $LASTEXITCODE"
        }
    } catch {
        $succeeded = $false
        $outputLines += "[verify_all] EXCEPTION while invoking ${ScriptPath}: $($_.Exception.Message)"
    }

    return [pscustomobject]@{
        Succeeded = $succeeded
        Output    = $outputLines
    }
}

# ==================================================================
# Environment check
# ==================================================================
$EnvDocker = if (Get-Command docker -ErrorAction SilentlyContinue) { "OK" } else { "NG" }
$EnvPython = if (Get-Command python -ErrorAction SilentlyContinue) { "OK" } else { "NG" }
$EnvNode = if (Get-Command node -ErrorAction SilentlyContinue) { "OK" } else { "NG" }
$EnvOllama = if (Get-Command ollama -ErrorAction SilentlyContinue) { "OK" } else { "NG" }
$EnvTailscale = if (Get-Command tailscale -ErrorAction SilentlyContinue) { "OK" } else { "NG" }

@"
Brain Twin Verification - environment info
Run started at: $RunStartedAt
OS: $([System.Environment]::OSVersion.VersionString)
Docker    : $EnvDocker
Python    : $EnvPython
Node.js   : $EnvNode
Ollama    : $EnvOllama
Tailscale : $EnvTailscale
"@ | Out-File -FilePath (Join-Path $LatestDir "environment.txt")

$Results = @()
function Add-Result($Name, $Status, $Log = "") {
    $script:Results += [pscustomobject]@{ Name = $Name; Status = $Status; Log = $Log }
}
function Write-Section($Title) {
    Write-Host ""; Write-Host "======================================================"
    Write-Host "  $Title"; Write-Host "======================================================"
}

$BackendOk = $true
$FrontendOk = $true
$NodeNpmAvailable = ($EnvNode -eq "OK") -and (Get-Command npm -ErrorAction SilentlyContinue)
$DepsReady = $false
$DockerRan = $false
$DockerOk = $true
$IntegrationStatus = "SKIP"
$PlaywrightStatus = "SKIP"

# ---------------------------------------------------------------
Write-Section "01/10 PowerShell script syntax check"
$log = Join-Path $LogDir "01-shell.log"
$syntaxOk = $true
$syntaxErrors = @()
Get-ChildItem "$RepoRoot\scripts\*.ps1" | ForEach-Object {
    $parseErrors = $null
    $tokens = $null
    [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count -gt 0) {
        $syntaxOk = $false
        foreach ($e in $parseErrors) { $syntaxErrors += "$($_.Name): $($e.Message)" }
    }
}
$syntaxErrors | Out-File -FilePath $log
if ($syntaxOk) { Add-Result "PowerShell script syntax" "OK" $log; Write-Host "[OK]" }
else { Add-Result "PowerShell script syntax" "NG" $log; $BackendOk = $false; Write-Host "[NG]" }

# ---------------------------------------------------------------
Write-Section "02/10 Python syntax check"
$log = Join-Path $LogDir "02-python-syntax.log"
if ($EnvPython -eq "OK") {
    $pyFiles = Get-ChildItem -Path "apps\server\app","apps\server\alembic\versions","apps\server\scripts" -Recurse -Filter "*.py"
    $pyOk = $true
    "" | Out-File -FilePath $log
    foreach ($f in $pyFiles) {
        $out = python -m py_compile $f.FullName 2>&1
        if ($LASTEXITCODE -ne 0) { $pyOk = $false; $out | Out-File -Append -FilePath $log }
    }
    if ($pyOk) { Add-Result "Python syntax" "OK" $log; Write-Host "[OK]" }
    else { Add-Result "Python syntax" "NG" $log; $BackendOk = $false; Write-Host "[NG]" }
} else {
    Add-Result "Python syntax" "SKIP" "(python not found)"; Write-Host "[SKIP]"
}

# ---------------------------------------------------------------
Write-Section "03/10 Python core logic tests"
$log = Join-Path $LogDir "03-python-tests.log"
if ($EnvPython -eq "OK") {
    Push-Location apps\server
    $out1 = python -m unittest discover -s tests -p "test_core_*.py" 2>&1; $ok1 = ($LASTEXITCODE -eq 0)
    $out2 = python -m unittest tests.test_cron_scripts_integration 2>&1; $ok2 = ($LASTEXITCODE -eq 0)
    Pop-Location
    Push-Location testing\fake_ollama
    $out3 = python -m unittest test_fake_ollama_server 2>&1; $ok3 = ($LASTEXITCODE -eq 0)
    Pop-Location
    $out4 = python verification\db_schema_check.py 2>&1; $ok4 = ($LASTEXITCODE -eq 0)
    ($out1 + $out2 + $out3 + $out4) | Out-File -FilePath $log
    if ($ok1 -and $ok2 -and $ok3 -and $ok4) { Add-Result "Python core logic tests" "OK" $log; Write-Host "[OK]" }
    else { Add-Result "Python core logic tests" "NG" $log; $BackendOk = $false; Write-Host "[NG]" }
} else {
    Add-Result "Python core logic tests" "SKIP" "(python not found)"; Write-Host "[SKIP]"
}

# ---------------------------------------------------------------
Write-Section "04/10 Backend API integration tests (pytest)"
$log = Join-Path $LogDir "04-pytest.log"
if ($EnvPython -eq "OK") {
    Push-Location apps\server
    $pytestAvailable = $false
    try { python -c "import pytest" 2>$null; if ($LASTEXITCODE -eq 0) { $pytestAvailable = $true } } catch {}
    if ($pytestAvailable) {
        $out = python -m pytest -q 2>&1; $out | Out-File -FilePath $log
        if ($LASTEXITCODE -eq 0) { Add-Result "pytest integration tests" "OK" $log; Write-Host "[OK]" }
        else { Add-Result "pytest integration tests" "NG" $log; $BackendOk = $false; Write-Host "[NG]" }
    } else {
        Add-Result "pytest integration tests" "SKIP" "(pytest not installed)"; Write-Host "[SKIP]"
    }
    Pop-Location
} else {
    Add-Result "pytest integration tests" "SKIP" "(python not found)"; Write-Host "[SKIP]"
}

# ---------------------------------------------------------------
Write-Section "05/10 Frontend dependency setup (npm ci / npm install)"
$log = Join-Path $LogDir "05-npm-install.log"
if (-not $NodeNpmAvailable) {
    Add-Result "Frontend dependency setup" "SKIP" "(Node.js/npm not found)"; Write-Host "[SKIP]"
} else {
    Push-Location apps\web
    if (Test-Path "package-lock.json") { $out = npm ci 2>&1 } else { $out = npm install 2>&1 }
    $out | Out-File -FilePath $log
    if (Test-Path "node_modules\react") {
        $DepsReady = $true
        Add-Result "Frontend dependency setup" "OK" $log; Write-Host "[OK]"
    } else {
        Add-Result "Frontend dependency setup" "NG" "$log (dependency install failed; frontend tests/build were NOT run)"
        $FrontendOk = $false
        Write-Host "[NG] Dependency setup failed (this is not a failure of the frontend test code itself)"
    }
    Pop-Location
}

# ---------------------------------------------------------------
Write-Section "06/10 Frontend unit tests (Vitest)"
$log = Join-Path $LogDir "06-frontend-test.log"
if (-not $DepsReady) { Add-Result "Frontend unit tests" "SKIP" "(dependencies not ready)"; Write-Host "[SKIP]" }
else {
    Push-Location apps\web
    $out = npm run test 2>&1; $out | Out-File -FilePath $log
    if ($LASTEXITCODE -eq 0) { Add-Result "Frontend unit tests" "OK" $log; Write-Host "[OK]" }
    else { Add-Result "Frontend unit tests" "NG" $log; $FrontendOk = $false; Write-Host "[NG]" }
    Pop-Location
}

# ---------------------------------------------------------------
Write-Section "07/10 Frontend build"
$log = Join-Path $LogDir "07-frontend-build.log"
if (-not $DepsReady) { Add-Result "Frontend build" "SKIP" "(dependencies not ready)"; Write-Host "[SKIP]" }
else {
    Push-Location apps\web
    $out = npm run build 2>&1; $out | Out-File -FilePath $log
    if ($LASTEXITCODE -eq 0) { Add-Result "Frontend build" "OK" $log; Write-Host "[OK]" }
    else { Add-Result "Frontend build" "NG" $log; $FrontendOk = $false; Write-Host "[NG]" }
    Pop-Location
}

# ---------------------------------------------------------------
Write-Section "08/10 Docker build check"
$log = Join-Path $LogDir "08-docker-build.log"
if ($SkipDocker) { Add-Result "Docker build" "SKIP" "(-SkipDocker specified)"; Write-Host "[SKIP]" }
elseif ($EnvDocker -ne "OK") { Add-Result "Docker build" "SKIP" "(docker not found)"; Write-Host "[SKIP]" }
else {
    $DockerRan = $true
    $Global:LASTEXITCODE = 1
    $out = docker compose build 2>&1; $out | Out-File -FilePath $log
    if ($LASTEXITCODE -eq 0) { Add-Result "Docker build" "OK" $log; Write-Host "[OK]" }
    else { Add-Result "Docker build" "NG" $log; $DockerOk = $false; Write-Host "[NG]" }
}

# ---------------------------------------------------------------
Write-Section "09/10 Docker integration test"
$log = Join-Path $LogDir "09-docker-integration.log"
if ($SkipDocker) { Add-Result "Docker integration test" "SKIP" "(-SkipDocker specified)"; Write-Host "[SKIP]" }
elseif ($EnvDocker -ne "OK") { Add-Result "Docker integration test" "SKIP" "(docker not found)"; Write-Host "[SKIP]" }
else {
    $result = Invoke-ExternalScript -ScriptPath ".\scripts\verify_integration.ps1"
    $result.Output | Out-File -FilePath $log
    if ($result.Succeeded) { Add-Result "Docker integration test" "OK" $log; $IntegrationStatus = "OK"; Write-Host "[OK]" }
    else { Add-Result "Docker integration test" "NG" $log; $IntegrationStatus = "NG"; Write-Host "[NG]" }
}

# ---------------------------------------------------------------
Write-Section "10/10 Playwright E2E"
$log = Join-Path $LogDir "10-playwright.log"
if ($SkipE2E) { Add-Result "Playwright E2E" "SKIP" "(-SkipE2E specified)"; Write-Host "[SKIP]" }
elseif ($SkipDocker -or $EnvDocker -ne "OK") { Add-Result "Playwright E2E" "SKIP" "(Docker not available)"; Write-Host "[SKIP]" }
elseif (-not $DepsReady -or -not (Test-Path "apps\web\node_modules\@playwright")) {
    Add-Result "Playwright E2E" "SKIP" "(frontend dependencies/Playwright not ready)"; Write-Host "[SKIP]"
} else {
    $result = Invoke-ExternalScript -ScriptPath ".\scripts\run_e2e.ps1"
    $result.Output | Out-File -FilePath $log
    if ($result.Succeeded) { Add-Result "Playwright E2E" "OK" $log; $PlaywrightStatus = "OK"; Write-Host "[OK]" }
    else { Add-Result "Playwright E2E" "NG" $log; $PlaywrightStatus = "NG"; Write-Host "[NG]" }
}

# ==================================================================
# Dashboard + save to verification\latest\
# ==================================================================
function Mark($status) { if ($status -eq "OK") { "PASS" } else { "FAIL" } }
function GroupLabel($status) {
    switch ($status) { "OK" { "PASS" } "NG" { "FAIL" } default { "SKIP" } }
}

$BackendLabel = if ($BackendOk) { "PASS" } else { "FAIL" }
$FrontendLabel = if (-not $NodeNpmAvailable) { "SKIP" } elseif ($FrontendOk) { "PASS" } else { "FAIL" }
$DockerLabel = if (-not $DockerRan) { "SKIP" } elseif ($DockerOk) { "PASS" } else { "FAIL" }
$IntegrationLabel = GroupLabel $IntegrationStatus
$PlaywrightLabel = GroupLabel $PlaywrightStatus

$Overall = "PASS"
if ((-not $BackendOk) -or (-not $FrontendOk) -or ($DockerRan -and -not $DockerOk) -or ($IntegrationStatus -eq "NG") -or ($PlaywrightStatus -eq "NG")) {
    $Overall = "FAIL"
}

$Dashboard = @"
==============================
Brain Twin Verification
Environment
$(Mark $EnvDocker) Docker
$(Mark $EnvPython) Python
$(Mark $EnvNode) Node
$(Mark $EnvOllama) Ollama
$(Mark $EnvTailscale) Tailscale
Backend
$BackendLabel
Frontend
$FrontendLabel
Docker
$DockerLabel
Integration
$IntegrationLabel
Playwright
$PlaywrightLabel
Overall
$Overall
==============================
"@

Write-Host ""
Write-Host $Dashboard

Write-Host ""
Write-Host "--- Details ---"
$Results | Format-Table -AutoSize

Write-Host ""
Write-Host "=== That is as far as automated checks go ==="
Write-Host "The following need to be checked on real hardware (out of scope for this script):"
Write-Host "  - Reachability of the real Ollama (both models): docker compose exec server python scripts/ollama_preflight.py"
Write-Host "  - iPhone access via Tailscale: docs\TAILSCALE_SETUP.md / docs\SETUP_IPHONE.md"

$Dashboard | Out-File -FilePath (Join-Path $LatestDir "summary.txt")
@"
Run started at: $RunStartedAt
Run finished at: $(Get-Date -Format o)

$Dashboard
"@ | Out-File -FilePath (Join-Path $LatestDir "run_info.txt")
Copy-Item "$LogDir\*.log" (Join-Path $LatestDir "logs") -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Saved run record to: $LatestDir\"

if ($Overall -eq "FAIL") { exit 1 } else { exit 0 }

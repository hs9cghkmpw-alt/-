# Brain Twin - Final Verification Script (Windows PowerShell)
#
# NOTE: ASCII-only by design. Windows PowerShell 5.1 can misread non-ASCII
# text in a BOM-less UTF-8 .ps1 file using the system code page, corrupting
# the file and breaking the parser. See docs/COMPLETE_GUIDE_JA.md for the
# Japanese explanation. All output messages in this script are in English
# for the same reason.
#
# PURPOSE
#   Run the entire verification pipeline (fresh checkout -> Docker no-cache
#   build -> startup -> health -> backend pytest -> cron -> frontend build ->
#   typecheck -> frontend unit test -> runtime smoke test -> pairing) in one
#   command, and produce exactly ONE log file (BrainTwin-Final-Verification.log)
#   that is sufficient, by itself, to diagnose any failure without a second
#   round trip.
#
# IMPORTANT DESIGN NOTE (fixes a real bug reported from a previous run)
#   A previous version of the verification workflow set
#   $ErrorActionPreference = "Stop" globally. When a native command such as
#   "docker compose down" writes a harmless warning to stderr (for example
#   "No resource found to remove" when there is nothing to clean up), some
#   PowerShell configurations wrap that stderr line as a non-terminating
#   ErrorRecord. Combined with $ErrorActionPreference = "Stop", that
#   non-terminating warning was escalated into a terminating error and ended
#   the entire verification run - even though nothing about the application
#   had actually failed.
#
#   This script never sets $ErrorActionPreference = "Stop" globally. Instead:
#     - $ErrorActionPreference is kept at "Continue" for the whole script.
#     - Every external/native command's success or failure is judged
#       exclusively by $LASTEXITCODE, which is reset to a non-zero sentinel
#       immediately before each call so a stale value from an earlier,
#       unrelated command can never be misread as success.
#     - "docker compose down" / "docker compose down -v" cleanup calls are
#       never treated as fatal, regardless of their exit code or any stderr
#       output, since cleanup failures (e.g. "no resource to remove") are not
#       application failures.
#
# USAGE
#   cd brain-twin
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#   .\scripts\BrainTwin-Final-Verification.ps1
#
# On success, prints a "BRAIN TWIN VERIFICATION PASSED" banner with counts.
# On failure, prints a "FAILURE SUMMARY" with everything needed to diagnose
# the problem (failing stage, command, exit code, failing test name if any,
# `docker compose ps` output, server/web container logs, and the full
# traceback), and stops.
#
# This script does not add, remove, or modify any application feature. It is
# verification tooling only.

param(
    [switch]$SkipDockerBuild,
    [switch]$KeepContainersOnSuccess
)

$ErrorActionPreference = "Continue"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$LogFile = Join-Path $RepoRoot "BrainTwin-Final-Verification.log"
if (Test-Path $LogFile) { Remove-Item $LogFile -Force }

$Script:StageStatus = New-Object System.Collections.ArrayList
$Script:Counts = @{
    BackendPassed  = $null
    CronPassed     = $null
    FrontendPassed = $null
}
$Script:FailureInfo = $null

# ------------------------------------------------------------------
# Logging helpers
# ------------------------------------------------------------------

function Write-Log {
    param([string]$Message)
    Write-Host $Message
    Add-Content -Path $LogFile -Value $Message -Encoding UTF8
}

function Write-LogBlock {
    param([string]$Title)
    Write-Log ""
    Write-Log ("=" * 70)
    Write-Log $Title
    Write-Log ("=" * 70)
}

function Write-LogLines {
    param($Lines)
    if ($null -eq $Lines) { return }
    foreach ($item in $Lines) {
        $text = ($item | Out-String).TrimEnd([Environment]::NewLine)
        if ($text -ne "") {
            Write-Host $text
            Add-Content -Path $LogFile -Value $text -Encoding UTF8
        }
    }
}

# ------------------------------------------------------------------
# Robust native-command invocation.
#
# Judges success/failure exclusively via $LASTEXITCODE (reset to a
# non-zero sentinel before every call). Never lets $ErrorActionPreference
# turn a stderr warning into a script-ending exception, and never treats
# PowerShell's own error-record wrapping of stderr output as a reason to
# stop.
# ------------------------------------------------------------------

function Invoke-Stage {
    param(
        [Parameter(Mandatory = $true)][string]$StageName,
        [Parameter(Mandatory = $true)][scriptblock]$ScriptBlock,
        [switch]$Optional  # if set, a non-zero exit does not count as a fatal failure (e.g. cleanup steps)
    )

    Write-LogBlock "STAGE: $StageName"
    $Global:LASTEXITCODE = 999
    $output = $null
    $threw = $false
    $exceptionMessage = $null
    try {
        $output = & $ScriptBlock 2>&1
    } catch {
        $threw = $true
        $exceptionMessage = $_.Exception.Message
    }
    Write-LogLines $output
    if ($threw) {
        Write-Log "EXCEPTION while running stage: $exceptionMessage"
    }

    $code = $LASTEXITCODE
    $success = ($code -eq 0) -and (-not $threw)

    if ($success) {
        Write-Log "RESULT: OK ($StageName, exit code $code)"
    } elseif ($Optional) {
        Write-Log "RESULT: NON-FATAL ($StageName, exit code $code) - continuing"
    } else {
        Write-Log "RESULT: FAILED ($StageName, exit code $code)"
    }

    [void]$Script:StageStatus.Add([pscustomobject]@{
        Stage   = $StageName
        Success = $success
        ExitCode = $code
        Optional = [bool]$Optional
    })

    return [pscustomobject]@{
        Success  = $success
        ExitCode = $code
        Output   = $output
    }
}

# ------------------------------------------------------------------
# Failure handling: collect full diagnostics and write the FAILURE SUMMARY,
# then stop the script (after best-effort cleanup).
# ------------------------------------------------------------------

function Enter-FailureMode {
    param(
        [string]$Stage,
        [string]$Command,
        [string]$ExitCode,
        [string]$FailingTest = "(see traceback below)",
        $Output = $null
    )

    $Script:FailureInfo = [pscustomobject]@{
        Stage       = $Stage
        Command     = $Command
        ExitCode    = $ExitCode
        FailingTest = $FailingTest
    }

    Write-LogBlock "FAILURE DETECTED - collecting full diagnostics"

    Write-Log ""
    Write-Log "========== FAILURE SUMMARY =========="
    Write-Log "Stage: $Stage"
    Write-Log "Command: $Command"
    Write-Log "ExitCode: $ExitCode"
    Write-Log "FailingTest: $FailingTest"

    Write-Log ""
    Write-Log "========== DOCKER PS =========="
    $Global:LASTEXITCODE = 0
    $psOut = docker compose ps 2>&1
    Write-LogLines $psOut

    Write-Log ""
    Write-Log "========== CONTAINER STATUS (docker ps -a) =========="
    $Global:LASTEXITCODE = 0
    $psaOut = docker ps -a 2>&1
    Write-LogLines $psaOut

    Write-Log ""
    Write-Log "========== SERVER LOG (last 300 lines) =========="
    $Global:LASTEXITCODE = 0
    $serverLog = docker compose logs --tail=300 server 2>&1
    Write-LogLines $serverLog

    Write-Log ""
    Write-Log "========== WEB LOG (last 300 lines) =========="
    $Global:LASTEXITCODE = 0
    $webLog = docker compose logs --tail=300 web 2>&1
    Write-LogLines $webLog

    Write-Log ""
    Write-Log "========== TRACEBACK =========="
    if ($Output) {
        Write-LogLines $Output
    } else {
        Write-Log "(no captured command output for this stage)"
    }

    Write-Log ""
    Write-Log "========== END OF FAILURE SUMMARY =========="
    Write-Log ""
    Write-Log "Full log saved to: $LogFile"
    Write-Log "Please send this single file for diagnosis."

    # Best-effort cleanup, never fatal.
    Invoke-Stage -StageName "Cleanup after failure (docker compose down -v)" -Optional -ScriptBlock {
        docker compose down -v --remove-orphans
    } | Out-Null

    exit 1
}

# ------------------------------------------------------------------
# Start of pipeline
# ------------------------------------------------------------------

Write-Log "Brain Twin Final Verification"
Write-Log "Started: $(Get-Date -Format o)"
Write-Log "Repo root: $RepoRoot"
Write-Log ""

# --- Stage 0: pre-cleanup (never fatal; a prior leftover environment is not an app failure) ---
Invoke-Stage -StageName "Pre-cleanup (docker compose down -v, any previous leftovers)" -Optional -ScriptBlock {
    docker compose down -v --remove-orphans
} | Out-Null

# --- Stage 1: Docker no-cache build (production images) ---
if (-not $SkipDockerBuild) {
    $buildResult = Invoke-Stage -StageName "Docker build --no-cache (production images)" -ScriptBlock {
        docker compose build --no-cache
    }
    if (-not $buildResult.Success) {
        Enter-FailureMode -Stage "Docker build" -Command "docker compose build --no-cache" `
            -ExitCode $buildResult.ExitCode -Output $buildResult.Output
    }
} else {
    Write-Log "Skipped Docker build (-SkipDockerBuild specified)."
}

# --- Stage 2: startup ---
$upResult = Invoke-Stage -StageName "Docker compose up -d" -ScriptBlock {
    docker compose up -d
}
if (-not $upResult.Success) {
    Enter-FailureMode -Stage "Docker up" -Command "docker compose up -d" `
        -ExitCode $upResult.ExitCode -Output $upResult.Output
}

# --- Stage 3: health check (poll, since containers may take a few seconds to become ready) ---
Write-LogBlock "STAGE: Health check"
$webPort = "8080"
$envFile = Join-Path $RepoRoot ".env"
if (Test-Path $envFile) {
    $portLine = Get-Content $envFile | Where-Object { $_ -match "^WEB_PORT=" }
    if ($portLine) { $webPort = ($portLine -split "=")[1].Trim() }
}
$healthUrl = "http://127.0.0.1:$webPort/api/health"
$healthy = $false
$lastHealthError = ""
for ($i = 0; $i -lt 30; $i++) {
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        $lastHealthError = $_.Exception.Message
    }
    Start-Sleep -Seconds 2
}
if ($healthy) {
    Write-Log "RESULT: OK (Health check, $healthUrl returned 200)"
    [void]$Script:StageStatus.Add([pscustomobject]@{ Stage = "Health check"; Success = $true; ExitCode = 0; Optional = $false })
} else {
    Write-Log "RESULT: FAILED (Health check never returned 200 within 60 seconds)"
    Write-Log "Last error: $lastHealthError"
    Enter-FailureMode -Stage "Health check" -Command "GET $healthUrl" -ExitCode "N/A" `
        -Output @("Health check did not return 200 within 60 seconds.", "Last error: $lastHealthError")
}

# --- Stage 4: backend pytest (all API/integration tests except the cron ones, counted separately) ---
$backendResult = Invoke-Stage -StageName "Backend pytest (excluding cron)" -ScriptBlock {
    docker compose exec -T server python -m pytest -x -vv --tb=long --ignore=tests/test_cron_scripts_integration.py
}
if (-not $backendResult.Success) {
    $failingTest = ($backendResult.Output | Select-String -Pattern "^(FAILED|ERROR)\s+\S+" | Select-Object -First 1)
    $failingTestText = if ($failingTest) { $failingTest.ToString() } else { "(see traceback below)" }
    Enter-FailureMode -Stage "Backend pytest" `
        -Command "docker compose exec -T server python -m pytest -x -vv --tb=long --ignore=tests/test_cron_scripts_integration.py" `
        -ExitCode $backendResult.ExitCode -FailingTest $failingTestText -Output $backendResult.Output
}
$backendPassedLine = ($backendResult.Output | Select-String -Pattern "^\d+ passed" | Select-Object -Last 1)
if ($backendPassedLine) {
    $Script:Counts.BackendPassed = ($backendPassedLine.ToString() -split "\s+")[0]
} else {
    $Script:Counts.BackendPassed = "unknown (see log)"
}

# --- Stage 5: cron script integration tests (counted separately, since they exercise real subprocess/crontab behavior) ---
$cronResult = Invoke-Stage -StageName "Cron script integration tests" -ScriptBlock {
    docker compose exec -T server python -m pytest -x -vv --tb=long tests/test_cron_scripts_integration.py
}
if (-not $cronResult.Success) {
    $failingTest = ($cronResult.Output | Select-String -Pattern "^(FAILED|ERROR)\s+\S+" | Select-Object -First 1)
    $failingTestText = if ($failingTest) { $failingTest.ToString() } else { "(see traceback below)" }
    Enter-FailureMode -Stage "Cron tests" `
        -Command "docker compose exec -T server python -m pytest -x -vv --tb=long tests/test_cron_scripts_integration.py" `
        -ExitCode $cronResult.ExitCode -FailingTest $failingTestText -Output $cronResult.Output
}
$cronPassedLine = ($cronResult.Output | Select-String -Pattern "^\d+ passed|^\d+ skipped" | Select-Object -Last 1)
if ($cronPassedLine) {
    $Script:Counts.CronPassed = $cronPassedLine.ToString().Trim()
} else {
    $Script:Counts.CronPassed = "unknown (see log)"
}

# --- Stage 6/7/8: frontend build, typecheck, unit test ---
# The production web image (docker-compose.yml) is a two-stage build whose final
# stage is nginx-only (no Node.js, no source, no node_modules) - see
# apps/web/Dockerfile. Frontend build success is therefore verified as part of
# Stage 1 (docker compose build --no-cache builds the "build" stage internally,
# and the whole build fails if `npm run build` fails). Typecheck and unit test
# need Node.js + source, so this script builds the intermediate "build" stage
# as its own temporary image (never touching the production images) and runs
# these checks against it.
Write-LogBlock "STAGE: Frontend verification image (intermediate build stage, for typecheck/unit test only)"
$feImageResult = Invoke-Stage -StageName "Build frontend verification image" -ScriptBlock {
    docker build --target build -f apps/web/Dockerfile -t brain-twin-web-verify:latest .
}
if (-not $feImageResult.Success) {
    Enter-FailureMode -Stage "Frontend verification image build" -Command "docker build --target build -f apps/web/Dockerfile -t brain-twin-web-verify:latest ." `
        -ExitCode $feImageResult.ExitCode -Output $feImageResult.Output
}
Write-Log "RESULT: OK (Frontend build) - confirmed via Stage 1's production image build and this intermediate image."

$typecheckResult = Invoke-Stage -StageName "Frontend typecheck (tsc -b, same as npm run build's type-check step)" -ScriptBlock {
    # NOTE: "tsc -b --noEmit" is intentionally NOT used here. TypeScript
    # rejects --noEmit when a composite project is involved (tsconfig.node.json
    # has "composite": true), failing with:
    #   error TS5053: Option 'noEmit' cannot be specified with option 'composite'.
    # This runs the exact same "tsc -b" invocation that apps/web/package.json's
    # own "build" script uses for its type-checking step. Since this container
    # is --rm (ephemeral) and separate from the production image, any emitted
    # output files are discarded and never affect production.
    docker run --rm brain-twin-web-verify:latest npx tsc -b
}
if (-not $typecheckResult.Success) {
    Enter-FailureMode -Stage "Frontend typecheck" -Command "docker run --rm brain-twin-web-verify:latest npx tsc -b" `
        -ExitCode $typecheckResult.ExitCode -Output $typecheckResult.Output
}

$feTestResult = Invoke-Stage -StageName "Frontend unit test (npm run test)" -ScriptBlock {
    docker run --rm brain-twin-web-verify:latest npm run test
}
if (-not $feTestResult.Success) {
    Enter-FailureMode -Stage "Frontend unit test" -Command "docker run --rm brain-twin-web-verify:latest npm run test" `
        -ExitCode $feTestResult.ExitCode -Output $feTestResult.Output
}
$fePassedLine = ($feTestResult.Output | Select-String -Pattern "Tests\s+\d+\s+passed|passed\s+\(\d+\)|\d+\s+passed" | Select-Object -Last 1)
if ($fePassedLine) {
    $Script:Counts.FrontendPassed = $fePassedLine.ToString().Trim()
} else {
    $Script:Counts.FrontendPassed = "see log (vitest summary line not auto-parsed)"
}

# --- Stage 9: runtime smoke test (confirms the running containers actually serve real content, not just /api/health) ---
Write-LogBlock "STAGE: Runtime smoke test"
$smokeChecks = @(
    @{ Name = "index.html";      Path = "/" },
    @{ Name = "manifest.json";   Path = "/manifest.webmanifest" },
    @{ Name = "service worker";  Path = "/sw.js" }
)
$smokeFailed = $false
$smokeOutput = New-Object System.Collections.ArrayList
foreach ($check in $smokeChecks) {
    $url = "http://127.0.0.1:$webPort$($check.Path)"
    try {
        $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
        $line = "$($check.Name) ($url): HTTP $($resp.StatusCode)"
        [void]$smokeOutput.Add($line)
        if ($resp.StatusCode -ne 200) { $smokeFailed = $true }
    } catch {
        $line = "$($check.Name) ($url): FAILED - $($_.Exception.Message)"
        [void]$smokeOutput.Add($line)
        # manifest/service worker file names can vary by PWA plugin config;
        # only index.html is treated as a hard requirement.
        if ($check.Name -eq "index.html") { $smokeFailed = $true }
    }
}
Write-LogLines $smokeOutput
if ($smokeFailed) {
    Enter-FailureMode -Stage "Runtime smoke test" -Command "GET / (and related static assets)" `
        -ExitCode "N/A" -Output $smokeOutput
} else {
    Write-Log "RESULT: OK (Runtime smoke test)"
    [void]$Script:StageStatus.Add([pscustomobject]@{ Stage = "Runtime smoke test"; Success = $true; ExitCode = 0; Optional = $false })
}

# --- Stage 10: pairing (issue a pairing code the same way a real setup would, via the PC-only internal endpoint) ---
$pairingResult = Invoke-Stage -StageName "Pairing (issue a code via the internal endpoint)" -ScriptBlock {
    docker compose exec -T server curl -sf -X POST http://localhost:8000/api/pairing/start
}
if (-not $pairingResult.Success) {
    Enter-FailureMode -Stage "Pairing" -Command "docker compose exec -T server curl -sf -X POST http://localhost:8000/api/pairing/start" `
        -ExitCode $pairingResult.ExitCode -Output $pairingResult.Output
}
$pairingText = ($pairingResult.Output | Out-String)
if ($pairingText -notmatch '"code"\s*:\s*"[A-Z0-9]+"') {
    Enter-FailureMode -Stage "Pairing" -Command "docker compose exec -T server curl -sf -X POST http://localhost:8000/api/pairing/start" `
        -ExitCode "0 (but response did not contain a valid code)" -Output $pairingResult.Output
} else {
    Write-Log "RESULT: OK (Pairing code issued successfully)"
}

# ------------------------------------------------------------------
# All stages passed. Print the success banner and clean up.
# ------------------------------------------------------------------

$tailscaleUrl = "(not detected - run 'tailscale serve status' manually, or see docs/TAILSCALE_SETUP.md)"
try {
    $Global:LASTEXITCODE = 0
    $tsStatus = tailscale serve status 2>&1
    if ($LASTEXITCODE -eq 0) {
        $urlLine = $tsStatus | Select-String -Pattern "https://\S+" | Select-Object -First 1
        if ($urlLine) {
            $match = [regex]::Match($urlLine.ToString(), "https://\S+")
            if ($match.Success) { $tailscaleUrl = $match.Value }
        }
    }
} catch {
    # tailscale not installed or not configured; keep the fallback message.
}

Write-Log ""
Write-Log "========== BRAIN TWIN VERIFICATION PASSED =========="
Write-Log ""
Write-Log "Backend:"
Write-Log "$($Script:Counts.BackendPassed) passed"
Write-Log ""
Write-Log "Cron:"
Write-Log "$($Script:Counts.CronPassed)"
Write-Log ""
Write-Log "Frontend:"
Write-Log "$($Script:Counts.FrontendPassed)"
Write-Log ""
Write-Log "Typecheck:"
Write-Log "PASS"
Write-Log ""
Write-Log "Health:"
Write-Log "PASS"
Write-Log ""
Write-Log "Runtime smoke:"
Write-Log "PASS"
Write-Log ""
Write-Log "Pairing:"
Write-Log "PASS"
Write-Log ""
Write-Log "PC:"
Write-Log "http://127.0.0.1:$webPort"
Write-Log ""
Write-Log "iPhone:"
Write-Log "$tailscaleUrl"
Write-Log ""
Write-Log "======================================================"
Write-Log ""
Write-Log "Full log saved to: $LogFile"

Write-Log ""
Write-Log "Stage summary:"
foreach ($s in $Script:StageStatus) {
    $mark = if ($s.Success) { "OK" } elseif ($s.Optional) { "SKIP/NON-FATAL" } else { "FAILED" }
    Write-Log ("  [{0}] {1} (exit code {2})" -f $mark, $s.Stage, $s.ExitCode)
}

if (-not $KeepContainersOnSuccess) {
    Invoke-Stage -StageName "Cleanup (docker compose down -v)" -Optional -ScriptBlock {
        docker compose down -v --remove-orphans
    } | Out-Null
} else {
    Write-Log ""
    Write-Log "Containers left running (-KeepContainersOnSuccess specified). Stop them later with: docker compose down"
}

# Also remove the temporary frontend verification image (never part of production).
Invoke-Stage -StageName "Remove temporary frontend verification image" -Optional -ScriptBlock {
    docker image rm brain-twin-web-verify:latest
} | Out-Null

exit 0

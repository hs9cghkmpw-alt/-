# Brain Twin Docker Integration Test (Windows PowerShell)
#
# NOTE: ASCII-only by design (see scripts/setup.ps1 for why: Windows
# PowerShell 5.1 can misread non-ASCII text in a BOM-less UTF-8 .ps1 file
# using the system code page, corrupting the file and breaking the parser).
#
# Uses docker-compose.test.yml and never touches production data
# (data\, docker-compose.yml). The exit code identifies which stage failed.
# Test containers/volumes are always removed at the end, whether the run
# succeeded or failed.
#
# Usage:
#   .\scripts\verify_integration.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$WebPort = if ($env:TEST_WEB_PORT) { $env:TEST_WEB_PORT } else { "18080" }
$OllamaPort = if ($env:TEST_OLLAMA_PORT) { $env:TEST_OLLAMA_PORT } else { "11435" }
$BaseUrl = "http://127.0.0.1:$WebPort"
$FakeOllamaUrl = "http://127.0.0.1:$OllamaPort"
$LogDir = Join-Path $RepoRoot "data-test"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "integration_test.log"

$StageCode = @{
    build = 10; up = 11; migrate = 12; nginx_syntax = 13; health = 14
    pairing_start_blocked = 15; pairing_start_internal = 16; pairing_complete = 17
    capture_sync = 18; idempotency = 19; search = 20; feedback = 21
    ollama_down = 22; ollama_recovery = 23; backup = 24; restore = 25
}
$Global:CurrentStage = "init"
$Global:PassedStages = @()

function Write-Log($msg) {
    $line = "[$(Get-Date -Format o)] $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Invoke-Compose {
    param([string[]]$Args)
    & docker compose -f docker-compose.test.yml @Args *>> $LogFile
    return $LASTEXITCODE
}

function Stop-WithFailure($Stage, $Message) {
    $Global:CurrentStage = $Stage
    Write-Log "[FAILED] stage '$Stage': $Message"
    Invoke-Cleanup
    exit $StageCode[$Stage]
}

function Pass-Stage($Stage) {
    $Global:PassedStages += $Stage
    Write-Log "[OK] stage '$Stage' passed"
}

function Invoke-Cleanup {
    Write-Log "Cleanup: removing test containers and volumes"
    & docker compose -f docker-compose.test.yml down -v --remove-orphans *>> $LogFile
}

function Get-JsonField($JsonText, $Path) {
    try {
        $obj = $JsonText | ConvertFrom-Json
        foreach ($key in $Path.Split('.')) {
            $obj = $obj.$key
        }
        return $obj
    } catch {
        return $null
    }
}

Write-Log "=== Brain Twin Docker integration test: starting ==="
Write-Log "Web (same-origin): $BaseUrl / Fake Ollama control: $FakeOllamaUrl"

try {
    # --- build ---
    $Global:CurrentStage = "build"
    if ((Invoke-Compose @("build")) -ne 0) { Stop-WithFailure "build" "docker compose build failed" }
    Pass-Stage "build"

    # --- up ---
    $Global:CurrentStage = "up"
    if ((Invoke-Compose @("up", "-d")) -ne 0) { Stop-WithFailure "up" "docker compose up failed" }
    Pass-Stage "up"

    # --- migrate ---
    $Global:CurrentStage = "migrate"
    $migrated = $false
    for ($i = 0; $i -lt 20; $i++) {
        if ((Invoke-Compose @("exec", "-T", "server-test", "alembic", "upgrade", "head")) -eq 0) { $migrated = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $migrated) { Stop-WithFailure "migrate" "alembic upgrade head failed" }
    Pass-Stage "migrate"

    # --- nginx_syntax ---
    $Global:CurrentStage = "nginx_syntax"
    if ((Invoke-Compose @("exec", "-T", "web-test", "nginx", "-t")) -ne 0) { Stop-WithFailure "nginx_syntax" "nginx -t failed" }
    Pass-Stage "nginx_syntax"

    # --- health ---
    $Global:CurrentStage = "health"
    $healthOk = $false
    $healthResp = $null
    for ($i = 0; $i -lt 20; $i++) {
        try {
            $healthResp = Invoke-WebRequest -Uri "$BaseUrl/api/health" -UseBasicParsing -TimeoutSec 3
            $healthOk = $true
            break
        } catch { Start-Sleep -Seconds 1 }
    }
    if (-not $healthOk) { Stop-WithFailure "health" "GET $BaseUrl/api/health failed" }
    if ($healthResp.Headers["Content-Type"] -notmatch "application/json") {
        Stop-WithFailure "health" "Content-Type is not JSON: $($healthResp.Headers['Content-Type'])"
    }
    $statusField = Get-JsonField $healthResp.Content "status"
    if ($statusField -ne "ok") { Stop-WithFailure "health" "health status is not 'ok': $($healthResp.Content)" }
    if ($healthResp.Content -match "<!doctype|<html") { Stop-WithFailure "health" "Got HTML instead of JSON" }
    Pass-Stage "health"

    # --- pairing_start_blocked ---
    $Global:CurrentStage = "pairing_start_blocked"
    try {
        $blockedResp = Invoke-WebRequest -Uri "$BaseUrl/api/pairing/start" -Method Post -UseBasicParsing -SkipHttpErrorCheck
        $blockedStatus = $blockedResp.StatusCode
    } catch {
        $blockedStatus = $_.Exception.Response.StatusCode.value__
    }
    if ($blockedStatus -ne 403) { Stop-WithFailure "pairing_start_blocked" "public route did not return 403 (actual: $blockedStatus)" }
    Pass-Stage "pairing_start_blocked"

    # --- pairing_start_internal ---
    $Global:CurrentStage = "pairing_start_internal"
    $pairingStartRaw = & docker compose -f docker-compose.test.yml exec -T server-test curl -sf -X POST http://localhost:8000/api/pairing/start
    if (-not $pairingStartRaw) { Stop-WithFailure "pairing_start_internal" "call from inside the container failed" }
    $pairingCode = Get-JsonField $pairingStartRaw "code"
    if (-not $pairingCode) { Stop-WithFailure "pairing_start_internal" "could not obtain a pairing code: $pairingStartRaw" }
    Write-Log "Issued pairing code: $pairingCode"
    Pass-Stage "pairing_start_internal"

    # --- pairing_complete ---
    $Global:CurrentStage = "pairing_complete"
    $completeBody = @{ code = $pairingCode; device_name = "integration-test" } | ConvertTo-Json
    $completeResp = Invoke-WebRequest -Uri "$BaseUrl/api/pairing/complete" -Method Post -Body $completeBody -ContentType "application/json" -UseBasicParsing
    $deviceToken = Get-JsonField $completeResp.Content "device_token"
    if (-not $deviceToken) { Stop-WithFailure "pairing_complete" "could not obtain a device token: $($completeResp.Content)" }

    try {
        $badResp = Invoke-WebRequest -Uri "$BaseUrl/api/pairing/complete" -Method Post `
            -Body (@{ code = "WRONGCODE"; device_name = "x" } | ConvertTo-Json) -ContentType "application/json" `
            -UseBasicParsing -SkipHttpErrorCheck
        $badStatus = $badResp.StatusCode
    } catch { $badStatus = $_.Exception.Response.StatusCode.value__ }
    if ($badStatus -lt 400) { Stop-WithFailure "pairing_complete" "an incorrect code was accepted (status: $badStatus)" }
    Pass-Stage "pairing_complete"

    $AuthHeaders = @{ Authorization = "Bearer $deviceToken" }

    # --- capture_sync ---
    $Global:CurrentStage = "capture_sync"
    $clientId = [guid]::NewGuid().ToString()
    $captureBody = @{ client_id = $clientId; raw_text = "Integration test thought"; input_type = "text"; captured_at = "2026-07-30T21:00:00Z" } | ConvertTo-Json
    $captureResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $captureBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $captureId = Get-JsonField $captureResp.Content "id"
    if (-not $captureId) { Stop-WithFailure "capture_sync" "failed to create a capture: $($captureResp.Content)" }
    Pass-Stage "capture_sync"

    # --- idempotency ---
    $Global:CurrentStage = "idempotency"
    $captureResp2 = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $captureBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $captureId2 = Get-JsonField $captureResp2.Content "id"
    if ($captureId -ne $captureId2) { Stop-WithFailure "idempotency" "resending the same client_id returned a different ID" }
    Pass-Stage "idempotency"

    # --- search (must be a real check, not just "did we get valid JSON") ---
    $Global:CurrentStage = "search"
    $searchUniqueText = "SearchUniquePhrase$(Get-Date -Format 'yyyyMMddHHmmss')"
    $chatConfigBody = @{ chat_content = (@{ thoughts = @(@{ content = $searchUniqueText; types = @("thought") }) } | ConvertTo-Json -Compress) } | ConvertTo-Json
    Invoke-WebRequest -Uri "$FakeOllamaUrl/_control/config" -Method Post -Body $chatConfigBody -ContentType "application/json" -UseBasicParsing | Out-Null

    $searchClientId = [guid]::NewGuid().ToString()
    $searchCaptureBody = @{ client_id = $searchClientId; raw_text = $searchUniqueText; input_type = "text"; captured_at = "2026-07-30T21:00:00Z" } | ConvertTo-Json
    $searchCaptureResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $searchCaptureBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $searchCaptureId = Get-JsonField $searchCaptureResp.Content "id"
    if (-not $searchCaptureId) { Stop-WithFailure "search" "failed to create the capture used for search" }

    $searchProcessed = $false
    for ($i = 0; $i -lt 15; $i++) {
        $st = Invoke-WebRequest -Uri "$BaseUrl/api/captures/$searchCaptureId" -Headers $AuthHeaders -UseBasicParsing
        if ((Get-JsonField $st.Content "processing_status") -eq "done") { $searchProcessed = $true; break }
        Start-Sleep -Seconds 2
    }
    if (-not $searchProcessed) { Stop-WithFailure "search" "the search test thought did not finish processing before the timeout" }

    $searchThoughtsResp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts?capture_id=$searchCaptureId" -Headers $AuthHeaders -UseBasicParsing
    $searchThoughtsObj = $searchThoughtsResp.Content | ConvertFrom-Json
    if ($searchThoughtsObj.items.Count -eq 0) { Stop-WithFailure "search" "no thought found even though processing said 'done'" }
    $searchThoughtId = $searchThoughtsObj.items[0].id

    $searchResp = Invoke-WebRequest -Uri "$BaseUrl/api/search?q=$([uri]::EscapeDataString($searchUniqueText))" -Headers $AuthHeaders -UseBasicParsing
    $searchObj = $searchResp.Content | ConvertFrom-Json
    $searchMatch = $searchObj.thoughts | Where-Object { $_.thought.id -eq $searchThoughtId -and $_.thought.content -eq $searchUniqueText }
    if (-not $searchMatch) { Stop-WithFailure "search" "searching for the unique phrase did not return the expected thought" }

    $unrelatedWord = "TotallyUnrelatedPhrase$(Get-Date -Format 'yyyyMMddHHmmss')XYZ"
    $unrelatedResp = Invoke-WebRequest -Uri "$BaseUrl/api/search?q=$([uri]::EscapeDataString($unrelatedWord))" -Headers $AuthHeaders -UseBasicParsing
    $unrelatedObj = $unrelatedResp.Content | ConvertFrom-Json
    $unrelatedMatch = $unrelatedObj.thoughts | Where-Object { $_.thought.id -eq $searchThoughtId }
    if ($unrelatedMatch) { Stop-WithFailure "search" "an unrelated search term incorrectly matched the target thought" }
    Pass-Stage "search"

    # --- feedback (must not report success by skipping when no thought exists) ---
    $Global:CurrentStage = "feedback"
    $fbTargetText = "FeedbackTarget$(Get-Date -Format 'yyyyMMddHHmmss')"
    $fbConfigBody = @{ chat_content = (@{ thoughts = @(@{ content = $fbTargetText; types = @("thought") }) } | ConvertTo-Json -Compress) } | ConvertTo-Json
    Invoke-WebRequest -Uri "$FakeOllamaUrl/_control/config" -Method Post -Body $fbConfigBody -ContentType "application/json" -UseBasicParsing | Out-Null
    $fbClientId = [guid]::NewGuid().ToString()
    $fbCaptureBody = @{ client_id = $fbClientId; raw_text = $fbTargetText; input_type = "text"; captured_at = "2026-07-30T21:00:00Z" } | ConvertTo-Json
    $fbCaptureResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $fbCaptureBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $fbCaptureId = Get-JsonField $fbCaptureResp.Content "id"

    $fbOtherText = "FeedbackNonTarget$(Get-Date -Format 'yyyyMMddHHmmss')"
    $fbOtherConfigBody = @{ chat_content = (@{ thoughts = @(@{ content = $fbOtherText; types = @("thought") }) } | ConvertTo-Json -Compress) } | ConvertTo-Json
    Invoke-WebRequest -Uri "$FakeOllamaUrl/_control/config" -Method Post -Body $fbOtherConfigBody -ContentType "application/json" -UseBasicParsing | Out-Null
    $fbOtherClientId = [guid]::NewGuid().ToString()
    $fbOtherCaptureBody = @{ client_id = $fbOtherClientId; raw_text = $fbOtherText; input_type = "text"; captured_at = "2026-07-30T21:00:00Z" } | ConvertTo-Json
    $fbOtherCaptureResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $fbOtherCaptureBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $fbOtherCaptureId = Get-JsonField $fbOtherCaptureResp.Content "id"

    $fbThoughtId = $null
    $fbOtherThoughtId = $null
    for ($i = 0; $i -lt 15; $i++) {
        $t1resp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts?capture_id=$fbCaptureId" -Headers $AuthHeaders -UseBasicParsing
        $t2resp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts?capture_id=$fbOtherCaptureId" -Headers $AuthHeaders -UseBasicParsing
        $t1obj = $t1resp.Content | ConvertFrom-Json
        $t2obj = $t2resp.Content | ConvertFrom-Json
        if ($t1obj.items.Count -gt 0 -and $t2obj.items.Count -gt 0) {
            $fbThoughtId = $t1obj.items[0].id
            $fbOtherThoughtId = $t2obj.items[0].id
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $fbThoughtId -or -not $fbOtherThoughtId) {
        Stop-WithFailure "feedback" "the thoughts needed for the feedback test were not created before the timeout (skip-as-success is forbidden)"
    }

    $fbResp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts/$fbThoughtId/feedback" -Method Post `
        -Body (@{ event_type = "marked_important" } | ConvertTo-Json) -ContentType "application/json" `
        -Headers $AuthHeaders -UseBasicParsing -SkipHttpErrorCheck
    if ($fbResp.StatusCode -ne 201) { Stop-WithFailure "feedback" "feedback API did not return the expected status (201)" }

    # Verify the row was actually written to feedback_events by querying the DB directly.
    $fbDbCountScript = "import sqlite3; con = sqlite3.connect('/app/data/database/brain_twin.sqlite3'); print(con.execute(`"SELECT COUNT(*) FROM feedback_events WHERE thought_id=? AND event_type='marked_important'`", ('$fbThoughtId',)).fetchone()[0])"
    $fbDbCount = docker compose -f docker-compose.test.yml exec -T server-test python3 -c $fbDbCountScript
    if ([int]$fbDbCount -lt 1) { Stop-WithFailure "feedback" "no row found in feedback_events" }

    # Make sure feedback was not mistakenly recorded against the other thought.
    $fbOtherCheckResp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts/$fbOtherThoughtId" -Headers $AuthHeaders -UseBasicParsing
    $fbOtherImportance = (Get-JsonField $fbOtherCheckResp.Content "importance")
    if ($null -ne $fbOtherImportance) { Stop-WithFailure "feedback" "the unrelated thought's importance was already set, which breaks the test's assumption" }
    $fbOtherDbCountScript = "import sqlite3; con = sqlite3.connect('/app/data/database/brain_twin.sqlite3'); print(con.execute('SELECT COUNT(*) FROM feedback_events WHERE thought_id=?', ('$fbOtherThoughtId',)).fetchone()[0])"
    $fbOtherDbCount = docker compose -f docker-compose.test.yml exec -T server-test python3 -c $fbOtherDbCountScript
    if ([int]$fbOtherDbCount -ne 0) { Stop-WithFailure "feedback" "feedback was incorrectly recorded against the unrelated thought" }

    # Sending the same feedback twice should behave per spec (2 history rows, consistent final state).
    Invoke-WebRequest -Uri "$BaseUrl/api/thoughts/$fbThoughtId/feedback" -Method Post `
        -Body (@{ event_type = "marked_important" } | ConvertTo-Json) -ContentType "application/json" `
        -Headers $AuthHeaders -UseBasicParsing | Out-Null
    $fbDbCountAfterDup = docker compose -f docker-compose.test.yml exec -T server-test python3 -c $fbDbCountScript
    if ([int]$fbDbCountAfterDup -ne 2) { Stop-WithFailure "feedback" "expected 2 history rows after a duplicate submission" }
    $fbFinalResp = Invoke-WebRequest -Uri "$BaseUrl/api/thoughts/$fbThoughtId" -Headers $AuthHeaders -UseBasicParsing
    $fbFinalImportance = Get-JsonField $fbFinalResp.Content "importance"
    if ($fbFinalImportance -ne 1) { Stop-WithFailure "feedback" "importance should remain 1.0 after the duplicate submission" }
    Pass-Stage "feedback"

    # --- ollama_down ---
    $Global:CurrentStage = "ollama_down"
    Invoke-Compose @("stop", "fake-ollama-test") | Out-Null
    Start-Sleep -Seconds 1
    $downClientId = [guid]::NewGuid().ToString()
    $downBody = @{ client_id = $downClientId; raw_text = "Thought captured while Ollama is down"; input_type = "text"; captured_at = "2026-07-30T21:00:00Z" } | ConvertTo-Json
    $downResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures" -Method Post -Body $downBody -ContentType "application/json" -Headers $AuthHeaders -UseBasicParsing
    $downCaptureId = Get-JsonField $downResp.Content "id"
    if (-not $downCaptureId) { Stop-WithFailure "ollama_down" "saving a capture failed while Ollama was down" }
    $downSearchResp = Invoke-WebRequest -Uri "$BaseUrl/api/search?q=OllamaDown" -Headers $AuthHeaders -UseBasicParsing
    if ($downSearchResp.Content -notmatch [regex]::Escape($downCaptureId)) {
        Stop-WithFailure "ollama_down" "the capture was not found in search results while Ollama was down"
    }
    Pass-Stage "ollama_down"

    # --- ollama_recovery ---
    $Global:CurrentStage = "ollama_recovery"
    Invoke-Compose @("start", "fake-ollama-test") | Out-Null
    Start-Sleep -Seconds 2
    try { Invoke-WebRequest -Uri "$FakeOllamaUrl/_control/reset" -Method Post -UseBasicParsing | Out-Null } catch {}
    $retryResp = Invoke-WebRequest -Uri "$BaseUrl/api/processing/$downCaptureId/retry" -Method Post -Headers $AuthHeaders -UseBasicParsing -SkipHttpErrorCheck
    if ($retryResp.StatusCode -ne 202) { Stop-WithFailure "ollama_recovery" "reprocessing request failed (status: $($retryResp.StatusCode))" }

    $recovered = $false
    $capStatusBody = $null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 2
        $capResp = Invoke-WebRequest -Uri "$BaseUrl/api/captures/$downCaptureId" -Headers $AuthHeaders -UseBasicParsing
        $capStatusBody = $capResp.Content
        if ((Get-JsonField $capStatusBody "processing_status") -eq "done") { $recovered = $true; break }
    }
    if (-not $recovered) { Stop-WithFailure "ollama_recovery" "processing_status never reached 'done' after Ollama recovered" }
    if ((Get-JsonField $capStatusBody "raw_text") -ne "Thought captured while Ollama is down") {
        Stop-WithFailure "ollama_recovery" "the original text was changed, which must never happen"
    }
    Pass-Stage "ollama_recovery"

    # --- backup ---
    $Global:CurrentStage = "backup"
    $backupResp = Invoke-WebRequest -Uri "$BaseUrl/api/backup" -Method Post -Headers $AuthHeaders -UseBasicParsing -SkipHttpErrorCheck
    if ($backupResp.StatusCode -ne 200) { Stop-WithFailure "backup" "backup API failed (status: $($backupResp.StatusCode))" }
    $backupFiles = Get-ChildItem -Path (Join-Path $RepoRoot "data-test\backups") -Filter "*.sqlite3" -ErrorAction SilentlyContinue
    if (-not $backupFiles -or $backupFiles.Count -lt 1) { Stop-WithFailure "backup" "no backup file was created" }
    Pass-Stage "backup"

    # --- restore ---
    $Global:CurrentStage = "restore"
    $latestBackup = $backupFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ((Invoke-Compose @("exec", "-T", "server-test", "python", "scripts/restore_cli.py", "--file", $latestBackup.Name, "--yes")) -ne 0) {
        Stop-WithFailure "restore" "the restore script failed"
    }
    Invoke-Compose @("restart", "server-test") | Out-Null
    Start-Sleep -Seconds 3
    try {
        Invoke-WebRequest -Uri "$BaseUrl/api/health" -UseBasicParsing | Out-Null
    } catch {
        Stop-WithFailure "restore" "the server did not restart cleanly after restore"
    }
    Pass-Stage "restore"

    Write-Log "=== all stages passed ==="
    Invoke-Cleanup
    exit 0
} catch {
    Write-Log "[UNEXPECTED ERROR] stage '$($Global:CurrentStage)': $($_.Exception.Message)"
    Invoke-Cleanup
    exit 99
}

[CmdletBinding()]
param(
    [switch]$SkipAcquire,
    [int]$SampleLimit = 0,
    [int]$DeterminismSamples = 8,
    [int]$DeterminismRepeats = 2
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

if ($env:OS -ne "Windows_NT") { throw "Organizer core evidence run is Windows-only." }
if ($SampleLimit -lt 0) { throw "SampleLimit must be 0 (full run) or a positive smoke size." }
if ($DeterminismSamples -lt 0) { throw "DeterminismSamples must be >= 0." }
if ($DeterminismRepeats -lt 1) { throw "DeterminismRepeats must be >= 1." }

$EvalPython = Join-Path $ProjectRoot ".venv-organizer\Scripts\python.exe"
if (-not (Test-Path $EvalPython)) {
    throw "Organizer evaluation venv is missing. Run .\scripts\setup_organizer_eval_windows.ps1 first."
}

& $EvalPython (Join-Path $PSScriptRoot "preflight_organizer_windows.py")
if ($LASTEXITCODE -ne 0) { throw "Organizer Windows preflight failed." }

$branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $branch -ne "brain-twin-dev") {
    throw "Expected git branch brain-twin-dev; got '$branch'."
}
$trackedChanges = @(git status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { throw "git status failed." }
if ($trackedChanges.Count -gt 0) {
    throw "Tracked working-tree changes detected. Commit/stash them before an evidence run."
}
$GitCommit = (git rev-parse HEAD).Trim().ToLowerInvariant()
if ($LASTEXITCODE -ne 0 -or $GitCommit.Length -ne 40) { throw "could not resolve git HEAD" }

if (-not $SkipAcquire) {
    Write-Host "== Acquire exact pinned core Organizer snapshots =="
    & $EvalPython (Join-Path $PSScriptRoot "acquire_organizer_models.py") `
        --candidate-id qwen3.5-0.8b `
        --candidate-id qwen3.5-2b
    if ($LASTEXITCODE -ne 0) { throw "Organizer core model acquisition failed." }
}

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is required for non-repository evidence storage."
}
$stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmssZ")
$RunRoot = Join-Path $env:LOCALAPPDATA "BrainTwin\evaluation\organizer-core\$($GitCommit.Substring(0,8))-$stamp"
if (Test-Path $RunRoot) { throw "Refusing existing Organizer core evidence directory: $RunRoot" }
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null

$CandidateIds = @("qwen3.5-0.8b", "qwen3.5-2b")
$Summaries = @()

foreach ($CandidateId in $CandidateIds) {
    Write-Host ""
    Write-Host "== Isolated candidate process: $CandidateId =="
    $CandidateRoot = Join-Path $RunRoot $CandidateId
    New-Item -ItemType Directory -Force -Path $CandidateRoot | Out-Null

    $runnerArgs = @(
        (Join-Path $PSScriptRoot "run_organizer_open_matrix.py"),
        "--candidate-id", $CandidateId,
        "--results-root", $CandidateRoot,
        "--determinism-samples", $DeterminismSamples,
        "--determinism-repeats", $DeterminismRepeats
    )
    if ($SampleLimit -gt 0) {
        $runnerArgs += @("--sample-limit", $SampleLimit)
    }

    # Each candidate is a fresh Python process. This avoids carrying Torch/model
    # allocations and process peak-RSS history from one model into the next.
    & $EvalPython @runnerArgs
    if ($LASTEXITCODE -ne 0) { throw "Organizer candidate run failed: $CandidateId" }

    $summaryFiles = @(Get-ChildItem -LiteralPath $CandidateRoot -Recurse -Filter "matrix_summary.json" -File)
    if ($summaryFiles.Count -ne 1) {
        throw "Expected exactly one matrix_summary.json for $CandidateId; found $($summaryFiles.Count)."
    }
    $summary = Get-Content -LiteralPath $summaryFiles[0].FullName -Raw | ConvertFrom-Json
    if ($summary.git_commit -ne $GitCommit) { throw "Git evidence mismatch for $CandidateId." }
    if ($summary.candidates.Count -ne 1 -or $summary.candidates[0].candidate_id -ne $CandidateId) {
        throw "Candidate summary identity mismatch for $CandidateId."
    }
    $Summaries += $summary
}

$DatasetSha = $Summaries[0].dataset_sha256
$DatasetVersion = $Summaries[0].dataset_version
$SampleCount = $Summaries[0].sample_count
$SmokeOnly = $Summaries[0].smoke_only
foreach ($summary in $Summaries) {
    if ($summary.git_commit -ne $GitCommit) { throw "Mixed Git identities in Organizer core evidence." }
    if ($summary.dataset_sha256 -ne $DatasetSha -or $summary.dataset_version -ne $DatasetVersion) {
        throw "Mixed Organizer dataset identities in core evidence."
    }
    if ($summary.sample_count -ne $SampleCount -or $summary.smoke_only -ne $SmokeOnly) {
        throw "Mixed Organizer sample protocols in core evidence."
    }
}

$CandidateRows = @()
foreach ($summary in $Summaries) { $CandidateRows += $summary.candidates[0] }
$Combined = [ordered]@{
    schema = 1
    scope = "open-development-only"
    git_commit = $GitCommit
    dataset_version = $DatasetVersion
    dataset_sha256 = $DatasetSha
    sample_count = $SampleCount
    smoke_only = $SmokeOnly
    process_isolation = $true
    candidates = $CandidateRows
    selection_note = "No automatic winner. Review quality, hallucination, determinism, latency, model-load cost, RSS, disk and artifact integrity before any profile freeze."
    formal_blind_acceptance = $false
    production_activation = $false
}
$CombinedPath = Join-Path $RunRoot "combined_core_summary.json"
$Combined | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $CombinedPath

$Handoff = [ordered]@{
    schema = 1
    git_commit = $GitCommit
    evidence_root = $RunRoot
    combined_summary = $CombinedPath
    process_isolation = $true
    formal_blind_acceptance = $false
    production_activation = $false
}
$Handoff | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $RunRoot "run_handoff.json")

Write-Host ""
Write-Host "[OK] Organizer core evidence run complete."
Write-Host "Combined summary: $CombinedPath"
Write-Host "NOTE: open-development evidence only. Do not infer formal acceptance or production activation."
